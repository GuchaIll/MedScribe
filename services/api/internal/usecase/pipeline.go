package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

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

	// Seed the Redis progress hash so the status endpoint returns pending
	// immediately instead of 404. Fire-and-forget: the status endpoint
	// handles the brief window before this completes by retrying.
	statusKey := fmt.Sprintf("pipeline:%s", req.SessionID)
	initial := entity.PipelineStatus{
		SessionID:   req.SessionID,
		PipelineID:  pipelineID,
		Status:      "pending",
		StartedAtMs: time.Now().UnixMilli(),
	}
	go func() {
		if b, merr := json.Marshal(initial); merr == nil {
			_ = uc.redis.Set(context.Background(), statusKey, b, 24*time.Hour).Err()
		}
	}()

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
	return &status, nil
}
