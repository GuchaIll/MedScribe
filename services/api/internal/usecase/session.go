package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/repo"
	"github.com/medscribe/services/api/pkg/cache"
	"github.com/redis/go-redis/v9"
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
	if err = writeActiveSessionState(ctx, uc.redis, &activeSessionState{
		SessionID:        created.ID,
		DoctorID:         created.DoctorID,
		Status:           string(created.Status),
		StartedAtMs:      created.StartedAt.UnixMilli(),
		SpeakerRoleCheck: defaultSpeakerRoleCheckState(),
	}); err != nil {
		uc.log.Warn("failed to initialize active session state",
			zap.String("session_id", created.ID),
			zap.Error(err),
		)
	}
	return &SessionStartResponse{
		SessionID:        created.ID,
		Status:           string(created.Status),
		SpeakerRoleCheck: buildSpeakerRoleCheckResponse(created.ID, defaultSpeakerRoleCheckState()),
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

	flushedTurns, workflowState, err := uc.flushTranscriptBuffer(ctx, s)
	if err != nil {
		return nil, fmt.Errorf("end session: flush transcript buffer: %w", err)
	}
	if workflowState != "" {
		s.WorkflowState = &workflowState
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
	if flushedTurns > 0 {
		if err = uc.redis.Del(ctx, transcriptBufferKey(sessionID)).Err(); err != nil {
			uc.log.Warn("failed to clear transcript buffer after session end",
				zap.String("session_id", sessionID),
				zap.Int("flushed_turns", flushedTurns),
				zap.Error(err),
			)
		}
	}
	if err = updateActiveSessionState(ctx, uc.redis, sessionID, func(state *activeSessionState) {
		completedAtMs := now.UnixMilli()
		state.Status = string(entity.SessionStatusCompleted)
		state.CompletedAtMs = &completedAtMs
		state.TranscriptTurnsBuffered = 0
	}); err != nil {
		uc.log.Warn("failed to finalize active session state",
			zap.String("session_id", sessionID),
			zap.Error(err),
		)
	}
	return &SessionEndResponse{
		SessionID: updated.ID,
		Status:    string(updated.Status),
		Duration:  updated.DurationSeconds,
	}, nil
}

func (uc *sessionUseCase) flushTranscriptBuffer(
	ctx context.Context,
	session *entity.Session,
) (int, string, error) {
	rawTurns, err := uc.redis.LRange(ctx, transcriptBufferKey(session.ID), 0, -1).Result()
	if err != nil {
		return 0, "", err
	}
	if len(rawTurns) == 0 {
		return 0, "", nil
	}

	bufferedTurns := make([]entity.TranscriptTurn, 0, len(rawTurns))
	for _, raw := range rawTurns {
		var turn entity.TranscriptTurn
		if err = json.Unmarshal([]byte(raw), &turn); err != nil {
			return 0, "", fmt.Errorf("decode transcript turn: %w", err)
		}
		bufferedTurns = append(bufferedTurns, turn)
	}

	state := map[string]any{}
	if session.WorkflowState != nil && *session.WorkflowState != "" {
		if err = json.Unmarshal([]byte(*session.WorkflowState), &state); err != nil {
			return 0, "", fmt.Errorf("decode workflow state: %w", err)
		}
	}

	var existing []entity.TranscriptTurn
	if rawExisting, ok := state["transcript_turns"]; ok {
		b, marshalErr := json.Marshal(rawExisting)
		if marshalErr != nil {
			return 0, "", fmt.Errorf("encode existing transcript turns: %w", marshalErr)
		}
		if err = json.Unmarshal(b, &existing); err != nil {
			return 0, "", fmt.Errorf("decode existing transcript turns: %w", err)
		}
	}

	existing = append(existing, bufferedTurns...)
	state["transcript_turns"] = existing
	state["transcript_turn_count"] = len(existing)
	state["transcript_buffer_flushed_at"] = time.Now().UTC().Format(time.RFC3339Nano)

	encoded, err := json.Marshal(state)
	if err != nil {
		return 0, "", fmt.Errorf("encode workflow state: %w", err)
	}
	return len(bufferedTurns), string(encoded), nil
}
