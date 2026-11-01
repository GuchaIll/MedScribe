package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

const pipelineProgressKeyPrefix = "pipeline:progress:"

// pythonPipelineProgress mirrors the Redis record written by Python's
// PipelineProgressStore. It intentionally accepts the Python timestamp shape
// (ISO-8601 strings) before adapting it to the gateway's millisecond contract.
type pythonPipelineProgress struct {
	CurrentNode string               `json:"current_node"`
	Nodes       []pythonNodeProgress `json:"nodes"`
}

type pythonNodeProgress struct {
	Name        string   `json:"name"`
	Label       string   `json:"label"`
	Phase       string   `json:"phase"`
	Status      string   `json:"status"`
	StartedAt   string   `json:"started_at"`
	CompletedAt string   `json:"completed_at"`
	DurationMs  *float64 `json:"duration_ms"`
	Detail      string   `json:"detail"`
}

// pipelineTriggerMsg is the Kafka message schema for the pipeline.trigger topic.
// Consumed by the Rust Kafka consumer which forwards to the Go orchestrator.
type pipelineTriggerMsg struct {
	PipelineID   string                   `json:"pipeline_id"`
	SessionID    string                   `json:"session_id"`
	PatientID    string                   `json:"patient_id"`
	DoctorID     string                   `json:"doctor_id"`
	IsNewPatient bool                     `json:"is_new_patient"`
	Segments     []TranscriptSegmentInput `json:"segments"`
	EnqueuedAtMs int64                    `json:"enqueued_at_ms"`
}

// TriggerPipeline publishes a trigger message to Kafka and seeds a pending
// status entry in Redis so callers can poll immediately without receiving 404.
func (uc *sessionUseCase) TriggerPipeline(ctx context.Context, req TriggerPipelineRequest) (*TriggerPipelineResponse, error) {
	// Fast path: check local cache before hitting PostgreSQL.
	var s *entity.Session
	if cached, ok := uc.sessionCache.Get(req.SessionID); ok {
		s = cached.(*entity.Session)
	} else {
		var err error
		s, err = uc.sessions.GetByID(ctx, req.SessionID)
		if err != nil {
			return nil, err
		}
		uc.sessionCache.Set(req.SessionID, s)
	}
	if s.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}
	if err := updateActiveSessionState(ctx, uc.redis, req.SessionID, func(state *activeSessionState) {
		state.Status = string(s.Status)
		state.PatientID = req.PatientID
		state.DoctorID = req.DoctorID
	}); err != nil {
		uc.log.Warn("failed to refresh active session metadata before pipeline",
			zap.String("session_id", req.SessionID),
			zap.Error(err),
		)
	}

	pipelineID := uuid.NewString()
	msg := pipelineTriggerMsg{
		PipelineID:   pipelineID,
		SessionID:    req.SessionID,
		PatientID:    req.PatientID,
		DoctorID:     req.DoctorID,
		IsNewPatient: req.IsNewPatient,
		Segments:     req.Segments,
		EnqueuedAtMs: time.Now().UnixMilli(),
	}

	if err := uc.producer.PublishJSON(ctx, uc.topic, req.SessionID, msg); err != nil {
		return nil, fmt.Errorf("trigger pipeline: publish to Kafka: %w", err)
	}

	// Seed the Redis status synchronously so an immediate follow-up poll
	// never races a background write and returns a transient 404.
	statusKey := fmt.Sprintf("pipeline:%s", req.SessionID)
	initial := entity.PipelineStatus{
		SessionID:   req.SessionID,
		PipelineID:  pipelineID,
		Status:      "pending",
		StartedAtMs: time.Now().UnixMilli(),
	}
	if b, err := json.Marshal(initial); err == nil {
		if err = uc.redis.Set(ctx, statusKey, b, 24*time.Hour).Err(); err != nil {
			return nil, fmt.Errorf("trigger pipeline: seed redis status: %w", err)
		}
	} else {
		return nil, fmt.Errorf("trigger pipeline: marshal status: %w", err)
	}

	uc.log.Info("pipeline trigger published",
		zap.String("session_id", req.SessionID),
		zap.String("pipeline_id", pipelineID),
		zap.String("topic", uc.topic),
	)
	return &TriggerPipelineResponse{
		Accepted:   true,
		PipelineID: pipelineID,
		Message:    "pipeline queued",
	}, nil
}

// GetPipelineStatus retrieves the current pipeline execution status from Redis.
func (uc *sessionUseCase) GetPipelineStatus(ctx context.Context, sessionID string) (*entity.PipelineStatus, error) {
	key := fmt.Sprintf("pipeline:%s", sessionID)
	data, err := uc.redis.Get(ctx, key).Bytes()
	if err != nil {
		if err == redis.Nil {
			return nil, entity.ErrNotFound
		}
		return nil, fmt.Errorf("get pipeline status: redis: %w", err)
	}
	var status entity.PipelineStatus
	if err = json.Unmarshal(data, &status); err != nil {
		return nil, fmt.Errorf("get pipeline status: unmarshal: %w", err)
	}
	if err = uc.mergePipelineProgress(ctx, sessionID, &status); err != nil {
		// Top-level status is the gateway's lifecycle authority. Detailed
		// progress improves the response but must not make a completed or failed
		// run unreadable when the Python writer is unavailable or emitted bad data.
		uc.log.Warn("failed to merge pipeline progress; returning top-level status",
			zap.String("session_id", sessionID),
			zap.Error(err),
		)
	}
	return &status, nil
}

func (uc *sessionUseCase) mergePipelineProgress(
	ctx context.Context,
	sessionID string,
	status *entity.PipelineStatus,
) error {
	if status == nil {
		return fmt.Errorf("merge pipeline progress: status is required")
	}

	data, err := uc.redis.Get(ctx, pipelineProgressKey(sessionID)).Bytes()
	if err != nil {
		if err == redis.Nil {
			return nil
		}
		return fmt.Errorf("read progress: %w", err)
	}

	var progress pythonPipelineProgress
	if err = json.Unmarshal(data, &progress); err != nil {
		return fmt.Errorf("decode progress: %w", err)
	}

	if progress.CurrentNode != "" && status.Status != "completed" && status.Status != "failed" {
		status.CurrentNode = progress.CurrentNode
	}
	if len(progress.Nodes) == 0 {
		return nil
	}

	nodes := make([]entity.NodeProgress, 0, len(progress.Nodes))
	for _, node := range progress.Nodes {
		if node.Name == "" || node.Status == "" {
			return fmt.Errorf("decode progress: node requires name and status")
		}
		next := entity.NodeProgress{
			Name:   node.Name,
			Label:  node.Label,
			Phase:  node.Phase,
			Status: node.Status,
			Detail: node.Detail,
		}
		if node.DurationMs != nil {
			next.DurationMs = *node.DurationMs
		}
		if node.StartedAt != "" {
			startedAtMs, parseErr := parsePipelineProgressTimestamp(node.StartedAt)
			if parseErr != nil {
				return fmt.Errorf("decode progress: node %q started_at: %w", node.Name, parseErr)
			}
			next.StartedAtMs = startedAtMs
		}
		if node.CompletedAt != "" {
			completedAtMs, parseErr := parsePipelineProgressTimestamp(node.CompletedAt)
			if parseErr != nil {
				return fmt.Errorf("decode progress: node %q completed_at: %w", node.Name, parseErr)
			}
			next.CompletedAtMs = &completedAtMs
		}
		nodes = append(nodes, next)
	}
	status.Nodes = nodes
	return nil
}

func parsePipelineProgressTimestamp(value string) (int64, error) {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil {
		// datetime.isoformat() on Python's naive datetime omits the timezone.
		parsed, err = time.Parse("2006-01-02T15:04:05.999999999", value)
		if err != nil {
			return 0, fmt.Errorf("timestamp %q is not ISO-8601: %w", value, err)
		}
	}
	return parsed.UnixMilli(), nil
}
