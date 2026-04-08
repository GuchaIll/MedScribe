package usecase

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/repo"
	"github.com/medscribe/services/api/pkg/cache"
	"go.uber.org/zap"
)

type messagePublisher interface {
	PublishJSON(ctx context.Context, topic, key string, v any) error
}

// sessionUseCase implements SessionUseCase. Methods are split across four
// files, each owning a single concern:
//   - session.go        — session lifecycle (Start, End)
//   - transcription.go  — transcript turn ingestion
//   - pipeline.go       — pipeline trigger and status polling
//   - document.go       — documents, queue, and medical records
type sessionUseCase struct {
	sessions     repo.SessionRepository
	producer     messagePublisher
	redis        redis.Cmdable
	sessionCache *cache.TTLCache
	topic        string
	log          *zap.Logger
}

// NewSessionUseCase wires the session use-case with its dependencies.
func NewSessionUseCase(
	sessions repo.SessionRepository,
	producer messagePublisher,
	redisClient redis.Cmdable,
	sessionCache *cache.TTLCache,
	kafkaTopic string,
	log *zap.Logger,
) SessionUseCase {
	return &sessionUseCase{
		sessions:     sessions,
		producer:     producer,
		redis:        redisClient,
		sessionCache: sessionCache,
		topic:        kafkaTopic,
		log:          log,
	}
}

// StartSession opens a new active session and returns its generated ID.
// The authenticated user (from JWT) is recorded as the session doctor.
func (uc *sessionUseCase) StartSession(ctx context.Context, userID string) (*SessionStartResponse, error) {
	s := &entity.Session{
		ID:        uuid.NewString(),
		DoctorID:  userID,
		Status:    entity.SessionStatusActive,
		StartedAt: time.Now().UTC(),
	}
	created, err := uc.sessions.Create(ctx, s)
	if err != nil {
		return nil, fmt.Errorf("start session: %w", err)
	}
	return &SessionStartResponse{
		SessionID: created.ID,
		Status:    string(created.Status),
	}, nil
}

// EndSession marks an active session as completed and records its duration.
func (uc *sessionUseCase) EndSession(ctx context.Context, sessionID string) (*SessionEndResponse, error) {
	s, err := uc.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if s.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}

	now := time.Now().UTC()
	s.Status = entity.SessionStatusCompleted
	s.CompletedAt = &now
	dur := int(now.Sub(s.StartedAt).Seconds())
	s.DurationSeconds = &dur

	updated, err := uc.sessions.Update(ctx, s)
	if err != nil {
		return nil, fmt.Errorf("end session: %w", err)
	}
	return &SessionEndResponse{
		SessionID: updated.ID,
		Status:    string(updated.Status),
		Duration:  updated.DurationSeconds,
	}, nil
}
