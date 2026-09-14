package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/medscribe/services/api/internal/entity"
	"github.com/redis/go-redis/v9"
)

const (
	activeSessionTTL       = 24 * time.Hour
	completedSessionTTL    = 2 * time.Hour
	assistantResponseTTL   = 30 * time.Minute
	maxRecentTranscriptLen = 50
)

type activeSessionState struct {
	SessionID               string                  `json:"session_id"`
	PatientID               string                  `json:"patient_id,omitempty"`
	DoctorID                string                  `json:"doctor_id,omitempty"`
	Status                  string                  `json:"status"`
	StartedAtMs             int64                   `json:"started_at_ms,omitempty"`
	CompletedAtMs           *int64                  `json:"completed_at_ms,omitempty"`
	LastUpdatedAtMs         int64                   `json:"last_updated_at_ms"`
	TranscriptTurnsBuffered int                     `json:"transcript_turns_buffered,omitempty"`
	RecentTranscript        []entity.TranscriptTurn `json:"recent_transcript,omitempty"`
	TranscriptJobs          []transcriptJobState    `json:"transcript_jobs,omitempty"`
	AuthoritativeSegments   []authoritativeSegment  `json:"authoritative_segments,omitempty"`
	SpeakerRoleAssignments  map[string]string       `json:"speaker_role_assignments,omitempty"`
	SpeakerRoleCheck        speakerRoleCheckState   `json:"speaker_role_check,omitempty"`
	PendingDocuments        []entity.Document       `json:"pending_documents,omitempty"`
	OCRJobs                 []ocrJobState           `json:"ocr_jobs,omitempty"`
}

type ocrJobState struct {
	JobID      string `json:"job_id"`
	DocumentID string `json:"document_id"`
	Status     string `json:"status"`
	QueuedAtMs int64  `json:"queued_at_ms"`
}

type transcriptJobState struct {
	SegmentID         string `json:"segment_id"`
	Status            string `json:"status"`
	MimeType          string `json:"mime_type,omitempty"`
	OptimisticText    string `json:"optimistic_text,omitempty"`
	OptimisticSpeaker string `json:"optimistic_speaker,omitempty"`
	QueuedAtMs        int64  `json:"queued_at_ms"`
	StartedAtMs       *int64 `json:"started_at_ms,omitempty"`
	CompletedAtMs     *int64 `json:"completed_at_ms,omitempty"`
	Error             string `json:"error,omitempty"`
}

type authoritativeSegment struct {
	SegmentID               string  `json:"segment_id"`
	StartMs                 int64   `json:"start_ms"`
	EndMs                   int64   `json:"end_ms"`
	Text                    string  `json:"text"`
	SpeakerID               string  `json:"speaker_id,omitempty"`
	SpeakerRole             string  `json:"speaker_role,omitempty"`
	RoleConfidence          float64 `json:"role_confidence,omitempty"`
	TranscriptionConfidence float64 `json:"transcription_confidence,omitempty"`
	Source                  string  `json:"source,omitempty"`
	ReceivedAtMs            int64   `json:"received_at_ms"`
}

type speakerRoleCheckState struct {
	Required         bool                     `json:"required"`
	Status           string                   `json:"status,omitempty"`
	Method           string                   `json:"method,omitempty"`
	ExpectedSpeakers int                      `json:"expected_speakers,omitempty"`
	TargetRoles      []string                 `json:"target_roles,omitempty"`
	Instructions     []string                 `json:"instructions,omitempty"`
	Samples          []speakerRoleSampleState `json:"samples,omitempty"`
}

type speakerRoleSampleState struct {
	Role         string `json:"role"`
	Status       string `json:"status"`
	FileName     string `json:"file_name,omitempty"`
	MimeType     string `json:"mime_type,omitempty"`
	StoragePath  string `json:"storage_path,omitempty"`
	UploadedAtMs int64  `json:"uploaded_at_ms,omitempty"`
}

func readActiveSessionState(
	ctx context.Context,
	rdb redis.Cmdable,
	sessionID string,
) (*activeSessionState, error) {
	data, err := rdb.Get(ctx, activeSessionKey(sessionID)).Bytes()
	if err != nil {
		if err == redis.Nil {
			return nil, nil
		}
		return nil, fmt.Errorf("read active session state: %w", err)
	}

	var state activeSessionState
	if err = json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("decode active session state: %w", err)
	}
	return &state, nil
}

func writeActiveSessionState(
	ctx context.Context,
	rdb redis.Cmdable,
	state *activeSessionState,
) error {
	if state == nil {
		return nil
	}
	if state.Status == "" {
		state.Status = string(entity.SessionStatusActive)
	}
	state.LastUpdatedAtMs = time.Now().UnixMilli()

	payload, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("encode active session state: %w", err)
	}

	ttl := activeSessionTTL
	if state.Status == string(entity.SessionStatusCompleted) {
		ttl = completedSessionTTL
	}
	if err = rdb.Set(ctx, activeSessionKey(state.SessionID), payload, ttl).Err(); err != nil {
		return fmt.Errorf("write active session state: %w", err)
	}
	return nil
}

func updateActiveSessionState(
	ctx context.Context,
	rdb redis.Cmdable,
	sessionID string,
	mutate func(*activeSessionState),
) error {
	state, err := readActiveSessionState(ctx, rdb, sessionID)
	if err != nil {
		return err
	}
	if state == nil {
		state = &activeSessionState{
			SessionID: sessionID,
			Status:    string(entity.SessionStatusActive),
		}
	}
	mutate(state)
	return writeActiveSessionState(ctx, rdb, state)
}

func appendRecentTranscript(state *activeSessionState, turn entity.TranscriptTurn) {
	state.RecentTranscript = append(state.RecentTranscript, turn)
	if len(state.RecentTranscript) > maxRecentTranscriptLen {
		state.RecentTranscript = append([]entity.TranscriptTurn(nil), state.RecentTranscript[len(state.RecentTranscript)-maxRecentTranscriptLen:]...)
	}
	state.TranscriptTurnsBuffered++
}

func upsertTranscriptJob(state *activeSessionState, job transcriptJobState) {
	for idx := range state.TranscriptJobs {
		if state.TranscriptJobs[idx].SegmentID == job.SegmentID {
			state.TranscriptJobs[idx] = job
			return
		}
	}
	state.TranscriptJobs = append(state.TranscriptJobs, job)
}

func appendAuthoritativeSegment(state *activeSessionState, seg authoritativeSegment) {
	state.AuthoritativeSegments = append(state.AuthoritativeSegments, seg)
	if len(state.AuthoritativeSegments) > maxRecentTranscriptLen {
		state.AuthoritativeSegments = append(
			[]authoritativeSegment(nil),
			state.AuthoritativeSegments[len(state.AuthoritativeSegments)-maxRecentTranscriptLen:]...,
		)
	}
}
