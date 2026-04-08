// Package pipelineproxy consumes pipeline.trigger messages from Kafka and
// forwards them as HTTP POST requests to the internal Python FastAPI server.
//
// This is the strangler-fig bridge: the Go API gateway handles ingress (auth,
// rate limiting, request validation, Kafka queueing) while the Python backend
// continues to execute the 18-node LangGraph clinical pipeline. As individual
// pipeline nodes are ported to Go/Rust, this proxy shrinks until it is removed.
//
// Flow:
//
//	Client → Go Gateway (POST /session/{id}/pipeline)
//	       → Kafka (pipeline.trigger topic)
//	       → pipelineproxy.Consumer (this package)
//	       → HTTP POST to Python FastAPI (/internal/pipeline)
//	       → Python WorkflowEngine.execute_async()
//	       → Progress written to Redis by Python
//	       → Go reads Redis for GET /session/{id}/pipeline/status
package pipelineproxy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"

	"github.com/medscribe/services/api/internal/entity"
)

// Config holds the Python backend connection settings.
type Config struct {
	// PythonBaseURL is the internal URL of the Python FastAPI server,
	// e.g. "http://python-backend:8000".
	PythonBaseURL string

	// RequestTimeout is the maximum time to wait for the Python pipeline to
	// complete a single run. The 18-node pipeline typically finishes in 10-60s
	// depending on LLM latency; 5 minutes gives headroom for cold-start and
	// large transcripts.
	RequestTimeout time.Duration
}

// triggerMsg mirrors the pipelineTriggerMsg published by the Go gateway's
// TriggerPipeline usecase. Both must stay in sync.
type triggerMsg struct {
	PipelineID   string          `json:"pipeline_id"`
	SessionID    string          `json:"session_id"`
	PatientID    string          `json:"patient_id"`
	DoctorID     string          `json:"doctor_id"`
	IsNewPatient bool            `json:"is_new_patient"`
	Segments     json.RawMessage `json:"segments"`
	EnqueuedAtMs int64           `json:"enqueued_at_ms"`
}

// pythonPipelineRequest is the JSON body sent to the Python
// POST /internal/pipeline endpoint, matching RunPipelineRequest schema.
type pythonPipelineRequest struct {
	SessionID    string          `json:"session_id"`
	PatientID    string          `json:"patient_id"`
	DoctorID     string          `json:"doctor_id"`
	IsNewPatient bool            `json:"is_new_patient"`
	Segments     json.RawMessage `json:"segments"`
}

// Handler processes consumed Kafka messages by forwarding them to Python.
type Handler struct {
	cfg    Config
	client *http.Client
	redis  *redis.Client
	log    *zap.Logger
}

// NewHandler creates a pipeline proxy handler.
func NewHandler(cfg Config, redisClient *redis.Client, log *zap.Logger) *Handler {
	return &Handler{
		cfg: cfg,
		client: &http.Client{
			Timeout: cfg.RequestTimeout,
		},
		redis: redisClient,
		log:   log,
	}
}

// Handle is the kafka.MessageHandler callback. It deserialises the trigger
// message, forwards it to the Python backend, and updates Redis with the
// terminal status (completed/failed). Intermediate progress is written by
// the Python process itself.
func (h *Handler) Handle(ctx context.Context, key, value []byte) error {
	var msg triggerMsg
	if err := json.Unmarshal(value, &msg); err != nil {
		return fmt.Errorf("pipelineproxy: unmarshal trigger: %w", err)
	}

	h.log.Info("pipeline proxy: forwarding to python",
		zap.String("session_id", msg.SessionID),
		zap.String("pipeline_id", msg.PipelineID),
	)

	// Mark pipeline as "running" in Redis.
	h.updateRedisStatus(ctx, msg.SessionID, msg.PipelineID, "running", "")

	// Build the request body matching Python's RunPipelineRequest schema.
	reqBody := pythonPipelineRequest{
		SessionID:    msg.SessionID,
		PatientID:    msg.PatientID,
		DoctorID:     msg.DoctorID,
		IsNewPatient: msg.IsNewPatient,
		Segments:     msg.Segments,
	}

	payload, err := json.Marshal(reqBody)
	if err != nil {
		h.markFailed(ctx, msg.SessionID, msg.PipelineID, "marshal request body: "+err.Error())
		return fmt.Errorf("pipelineproxy: marshal request: %w", err)
	}

	url := fmt.Sprintf("%s/internal/pipeline", h.cfg.PythonBaseURL)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		h.markFailed(ctx, msg.SessionID, msg.PipelineID, "create request: "+err.Error())
		return fmt.Errorf("pipelineproxy: create request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := h.client.Do(httpReq)
	if err != nil {
		h.markFailed(ctx, msg.SessionID, msg.PipelineID, "python unreachable: "+err.Error())
		return fmt.Errorf("pipelineproxy: python request: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20)) // cap at 1 MB

	if resp.StatusCode >= 400 {
		errMsg := fmt.Sprintf("python returned %d: %s", resp.StatusCode, string(body))
		h.markFailed(ctx, msg.SessionID, msg.PipelineID, errMsg)
		return fmt.Errorf("pipelineproxy: %s", errMsg)
	}

	// Python's PipelineProgressStore (now Redis-backed) writes per-node
	// progress. On success we ensure the top-level key reflects completion.
	h.updateRedisStatus(ctx, msg.SessionID, msg.PipelineID, "completed", "")

	h.log.Info("pipeline proxy: python completed",
		zap.String("session_id", msg.SessionID),
		zap.String("pipeline_id", msg.PipelineID),
		zap.Int("status_code", resp.StatusCode),
	)
	return nil
}

// ─── Redis helpers ────────────────────────────────────────────────────────────

func (h *Handler) markFailed(ctx context.Context, sessionID, pipelineID, errMsg string) {
	h.log.Error("pipeline proxy: pipeline failed",
		zap.String("session_id", sessionID),
		zap.String("pipeline_id", pipelineID),
		zap.String("error", errMsg),
	)
	h.updateRedisStatus(ctx, sessionID, pipelineID, "failed", errMsg)
}

func (h *Handler) updateRedisStatus(ctx context.Context, sessionID, pipelineID, status, errMsg string) {
	now := time.Now().UnixMilli()
	ps := entity.PipelineStatus{
		SessionID:   sessionID,
		PipelineID:  pipelineID,
		Status:      status,
		StartedAtMs: now,
		Error:       errMsg,
	}
	if status == "completed" || status == "failed" {
		ps.CompletedAtMs = &now
	}

	// Read existing status to preserve StartedAtMs from the original seed.
	existingKey := fmt.Sprintf("pipeline:%s", sessionID)
	if existing, err := h.redis.Get(ctx, existingKey).Bytes(); err == nil {
		var prev entity.PipelineStatus
		if json.Unmarshal(existing, &prev) == nil && prev.StartedAtMs > 0 {
			ps.StartedAtMs = prev.StartedAtMs
		}
	}

	b, err := json.Marshal(ps)
	if err != nil {
		h.log.Warn("pipeline proxy: failed to marshal status", zap.Error(err))
		return
	}
	if err = h.redis.Set(ctx, existingKey, b, 24*time.Hour).Err(); err != nil {
		h.log.Warn("pipeline proxy: failed to write status to redis", zap.Error(err))
	}
}
