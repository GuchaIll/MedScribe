package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

const audioIngestTopic = "audio.ingest"

type audioSegmentIngestMsg struct {
	SessionID         string `json:"session_id"`
	SegmentID         string `json:"segment_id"`
	StartedAtMs       int64  `json:"started_at_ms"`
	EndedAtMs         int64  `json:"ended_at_ms"`
	SampleRateHz      int    `json:"sample_rate_hz,omitempty"`
	MimeType          string `json:"mime_type,omitempty"`
	StoragePath       string `json:"storage_path"`
	OriginalName      string `json:"original_name"`
	OptimisticText    string `json:"optimistic_text,omitempty"`
	OptimisticSpeaker string `json:"optimistic_speaker,omitempty"`
	EnqueuedAtMs      int64  `json:"enqueued_at_ms"`
}

func (uc *sessionUseCase) UploadAudioSegment(
	ctx context.Context,
	sessionID string,
	req UploadAudioSegmentRequest,
	fh *multipart.FileHeader,
	file multipart.File,
) (*UploadAudioSegmentResponse, error) {
	session, err := uc.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if session.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}
	if fh == nil || file == nil {
		return nil, entity.ErrInvalidInput
	}
	if req.StartedAtMs > 0 && req.EndedAtMs > 0 && req.EndedAtMs < req.StartedAtMs {
		return nil, entity.ErrInvalidInput
	}

	segmentID := req.SegmentID
	if segmentID == "" {
		segmentID = uuid.NewString()
	}
	storagePath, err := spoolUpload(sessionID, segmentID, fh.Filename, file)
	if err != nil {
		return nil, fmt.Errorf("upload audio segment: spool file: %w", err)
	}

	now := time.Now().UTC()
	msg := audioSegmentIngestMsg{
		SessionID:         sessionID,
		SegmentID:         segmentID,
		StartedAtMs:       req.StartedAtMs,
		EndedAtMs:         req.EndedAtMs,
		SampleRateHz:      req.SampleRateHz,
		MimeType:          firstNonEmpty(req.MimeType, fh.Header.Get("Content-Type")),
		StoragePath:       storagePath,
		OriginalName:      fh.Filename,
		OptimisticText:    req.OptimisticText,
		OptimisticSpeaker: req.OptimisticSpeaker,
		EnqueuedAtMs:      now.UnixMilli(),
	}

	if err = uc.producer.PublishJSON(ctx, audioIngestTopic, sessionID, msg); err != nil {
		return nil, fmt.Errorf("upload audio segment: publish audio job: %w", err)
	}

	job := transcriptJobState{
		SegmentID:         segmentID,
		Status:            "queued",
		MimeType:          msg.MimeType,
		OptimisticText:    req.OptimisticText,
		OptimisticSpeaker: req.OptimisticSpeaker,
		QueuedAtMs:        msg.EnqueuedAtMs,
	}
	if payload, marshalErr := json.Marshal(job); marshalErr == nil {
		if err = uc.redis.Set(ctx, audioSegmentJobKey(segmentID), payload, activeSessionTTL).Err(); err != nil {
			return nil, fmt.Errorf("upload audio segment: store job status: %w", err)
		}
	} else {
		return nil, fmt.Errorf("upload audio segment: marshal job status: %w", marshalErr)
	}

	if err = updateActiveSessionState(ctx, uc.redis, sessionID, func(state *activeSessionState) {
		state.Status = string(session.Status)
		upsertTranscriptJob(state, job)
	}); err != nil {
		uc.log.Warn("audio job queued but active session state update failed",
			zap.String("session_id", sessionID),
			zap.String("segment_id", segmentID),
			zap.Error(err),
		)
	}

	uc.log.Info("audio segment queued",
		zap.String("session_id", sessionID),
		zap.String("segment_id", segmentID),
		zap.String("topic", audioIngestTopic),
	)

	return &UploadAudioSegmentResponse{
		SessionID: sessionID,
		SegmentID: segmentID,
		Accepted:  true,
		Status:    "queued",
		Message:   "audio segment queued for whisper/pyannote processing",
	}, nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
