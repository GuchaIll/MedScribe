package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

// ProcessTranscription records a single transcript turn for the session.
// Phase 1 protects the hot path by appending turns to Redis immediately.
// Session end later flushes the buffer into durable session metadata until a
// dedicated transcript ledger/persister is introduced.
func (uc *sessionUseCase) ProcessTranscription(ctx context.Context, req TranscribeRequest) (*TranscribeResponse, error) {
	session, err := uc.sessions.GetByID(ctx, req.SessionID)
	if err != nil {
		return nil, err
	}
	if session.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}

	turn := entity.TranscriptTurn{
		SessionID: req.SessionID,
		Speaker:   req.Speaker,
		Text:      req.Text,
		Timestamp: time.Now().UTC(),
	}
	payload, err := json.Marshal(turn)
	if err != nil {
		return nil, fmt.Errorf("transcription: marshal turn: %w", err)
	}

	if err = uc.redis.RPush(ctx, transcriptBufferKey(req.SessionID), payload).Err(); err != nil {
		return nil, fmt.Errorf("transcription: store turn: %w", err)
	}
	if err = uc.redis.Expire(ctx, transcriptBufferKey(req.SessionID), transcriptBufferTTL).Err(); err != nil {
		uc.log.Warn("failed to refresh transcript buffer TTL",
			zap.String("session_id", req.SessionID),
			zap.Error(err),
		)
	}

	turnsStored, err := uc.redis.LLen(ctx, transcriptBufferKey(req.SessionID)).Result()
	if err != nil {
		uc.log.Warn("failed to read transcript buffer length",
			zap.String("session_id", req.SessionID),
			zap.Error(err),
		)
		turnsStored = 1
	}
	if err = updateActiveSessionState(ctx, uc.redis, req.SessionID, func(state *activeSessionState) {
		state.Status = string(session.Status)
		if state.DoctorID == "" {
			state.DoctorID = session.DoctorID
		}
		appendRecentTranscript(state, turn)
		state.TranscriptTurnsBuffered = int(turnsStored)
	}); err != nil {
		uc.log.Warn("failed to update active session transcript state",
			zap.String("session_id", req.SessionID),
			zap.Error(err),
		)
	}
	uc.log.Info("transcription turn received",
		zap.String("session_id", req.SessionID),
		zap.String("speaker", req.Speaker),
		zap.Int("text_len", len(req.Text)),
		zap.Int64("buffered_turns", turnsStored),
	)
	return &TranscribeResponse{
		SessionID:    req.SessionID,
		TurnsStored:  int(turnsStored),
		Speaker:      req.Speaker,
		Source:       "gateway",
		AgentMessage: "Captured for background processing",
	}, nil
}
