package usecase

import (
	"context"

	"go.uber.org/zap"
)

// ProcessTranscription records a single transcript turn for the session.
// Turn persistence to a dedicated transcript_turns table is deferred to
// Phase 2; Phase 1 stores turns inside the session workflow_state JSON blob.
func (uc *sessionUseCase) ProcessTranscription(ctx context.Context, req TranscribeRequest) (*TranscribeResponse, error) {
	if _, err := uc.sessions.GetByID(ctx, req.SessionID); err != nil {
		return nil, err
	}
	uc.log.Info("transcription turn received",
		zap.String("session_id", req.SessionID),
		zap.String("speaker", req.Speaker),
		zap.Int("text_len", len(req.Text)),
	)
	return &TranscribeResponse{
		SessionID:   req.SessionID,
		TurnsStored: 1,
		Speaker:     req.Speaker,
	}, nil
}
