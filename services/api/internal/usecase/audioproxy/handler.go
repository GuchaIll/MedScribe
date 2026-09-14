package audioproxy

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

const transcriptSegmentsTopic = "transcript.segments"

type messagePublisher interface {
	PublishJSON(ctx context.Context, topic, key string, v any) error
}

type Config struct {
	SpeechWorkerBaseURL string
	RequestTimeout      time.Duration
	ResultsTopic        string
}

type jobMsg struct {
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

type speechWorkerResponse struct {
	SessionID               string  `json:"session_id"`
	SegmentID               string  `json:"segment_id"`
	Status                  string  `json:"status"`
	Text                    string  `json:"text"`
	SpeakerID               string  `json:"speaker_id,omitempty"`
	SpeakerRole             string  `json:"speaker_role,omitempty"`
	RoleConfidence          float64 `json:"role_confidence,omitempty"`
	TranscriptionConfidence float64 `json:"transcription_confidence,omitempty"`
	StartMs                 int64   `json:"start_ms"`
	EndMs                   int64   `json:"end_ms"`
	Source                  string  `json:"source,omitempty"`
	Error                   string  `json:"error,omitempty"`
}

type activeSessionState struct {
	SessionID             string                 `json:"session_id"`
	Status                string                 `json:"status"`
	TranscriptJobs        []transcriptJobState   `json:"transcript_jobs,omitempty"`
	AuthoritativeSegments []authoritativeSegment `json:"authoritative_segments,omitempty"`
	SpeakerRoleAssignments map[string]string     `json:"speaker_role_assignments,omitempty"`
	SpeakerRoleCheck      speakerRoleCheckState  `json:"speaker_role_check,omitempty"`
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
	Samples []speakerRoleSampleState `json:"samples,omitempty"`
}

type speakerRoleSampleState struct {
	Role        string `json:"role"`
	Status      string `json:"status"`
	FileName    string `json:"file_name,omitempty"`
	MimeType    string `json:"mime_type,omitempty"`
	StoragePath string `json:"storage_path,omitempty"`
}

type referenceSampleAttachment struct {
	FieldName   string
	FileName    string
	MimeType    string
	StoragePath string
}

type Handler struct {
	cfg      Config
	client   *http.Client
	producer messagePublisher
	redis    *redis.Client
	log      *zap.Logger
}

func NewHandler(cfg Config, producer messagePublisher, redisClient *redis.Client, log *zap.Logger) *Handler {
	if cfg.ResultsTopic == "" {
		cfg.ResultsTopic = transcriptSegmentsTopic
	}
	return &Handler{
		cfg: cfg,
		client: &http.Client{
			Timeout: cfg.RequestTimeout,
		},
		producer: producer,
		redis:    redisClient,
		log:      log,
	}
}

func (h *Handler) Handle(ctx context.Context, key, value []byte) error {
	var job jobMsg
	if err := json.Unmarshal(value, &job); err != nil {
		return fmt.Errorf("audioproxy: unmarshal job: %w", err)
	}

	startedAtMs := time.Now().UnixMilli()
	if err := h.setJobStatus(ctx, job, "processing", &startedAtMs, nil, ""); err != nil {
		h.log.Warn("audioproxy: failed to mark processing", zap.Error(err))
	}

	resp, err := h.submitToSpeechWorker(ctx, job)
	if err != nil {
		_ = h.setJobStatus(ctx, job, "failed", &startedAtMs, nil, err.Error())
		return err
	}
	if resp.Status == "" {
		resp.Status = "completed"
	}
	if resp.Status != "completed" {
		_ = h.setJobStatus(ctx, job, "failed", &startedAtMs, nil, firstNonEmpty(resp.Error, "speech worker failed"))
		return fmt.Errorf("audioproxy: speech worker returned status=%s error=%s", resp.Status, resp.Error)
	}

	completedAtMs := time.Now().UnixMilli()
	if err = h.setJobStatus(ctx, job, "completed", &startedAtMs, &completedAtMs, ""); err != nil {
		return fmt.Errorf("audioproxy: write completion status: %w", err)
	}
	if err = h.recordAuthoritativeSegment(ctx, job, resp, completedAtMs); err != nil {
		return fmt.Errorf("audioproxy: record authoritative segment: %w", err)
	}
	if h.producer != nil {
		if err = h.producer.PublishJSON(ctx, h.cfg.ResultsTopic, job.SessionID, resp); err != nil {
			h.log.Warn("audioproxy: failed to publish transcript segment result",
				zap.String("session_id", job.SessionID),
				zap.String("segment_id", job.SegmentID),
				zap.Error(err),
			)
		}
	}
	return nil
}

func (h *Handler) submitToSpeechWorker(ctx context.Context, job jobMsg) (*speechWorkerResponse, error) {
	f, err := os.Open(job.StoragePath)
	if err != nil {
		return nil, fmt.Errorf("audioproxy: open spool file: %w", err)
	}
	defer f.Close()

	referenceSamples, err := h.loadReferenceSamples(ctx, job.SessionID)
	if err != nil {
		h.log.Warn("audioproxy: failed to load speaker reference samples",
			zap.String("session_id", job.SessionID),
			zap.Error(err),
		)
	}

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	fields := map[string]string{
		"session_id":         job.SessionID,
		"segment_id":         job.SegmentID,
		"started_at_ms":      fmt.Sprintf("%d", job.StartedAtMs),
		"ended_at_ms":        fmt.Sprintf("%d", job.EndedAtMs),
		"sample_rate_hz":     fmt.Sprintf("%d", job.SampleRateHz),
		"mime_type":          job.MimeType,
		"optimistic_text":    job.OptimisticText,
		"optimistic_speaker": job.OptimisticSpeaker,
	}
	for key, value := range fields {
		if value == "" || value == "0" {
			continue
		}
		if err = writer.WriteField(key, value); err != nil {
			return nil, fmt.Errorf("audioproxy: write field %s: %w", key, err)
		}
	}
	part, err := writer.CreateFormFile("file", job.OriginalName)
	if err != nil {
		return nil, fmt.Errorf("audioproxy: create multipart file: %w", err)
	}
	if _, err = io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("audioproxy: copy file body: %w", err)
	}
	for _, sample := range referenceSamples {
		if sample.StoragePath == "" {
			continue
		}
		refFile, openErr := os.Open(sample.StoragePath)
		if openErr != nil {
			h.log.Warn("audioproxy: failed to open speaker reference sample",
				zap.String("session_id", job.SessionID),
				zap.String("role", sample.FieldName),
				zap.String("path", sample.StoragePath),
				zap.Error(openErr),
			)
			continue
		}
		part, createErr := writer.CreateFormFile(sample.FieldName, sample.FileName)
		if createErr != nil {
			refFile.Close()
			return nil, fmt.Errorf("audioproxy: create reference multipart file: %w", createErr)
		}
		if _, copyErr := io.Copy(part, refFile); copyErr != nil {
			refFile.Close()
			return nil, fmt.Errorf("audioproxy: copy reference file body: %w", copyErr)
		}
		if closeErr := refFile.Close(); closeErr != nil {
			return nil, fmt.Errorf("audioproxy: close reference file: %w", closeErr)
		}
	}
	if err = writer.Close(); err != nil {
		return nil, fmt.Errorf("audioproxy: close multipart writer: %w", err)
	}

	url := fmt.Sprintf("%s/internal/audio-segment", h.cfg.SpeechWorkerBaseURL)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, &body)
	if err != nil {
		return nil, fmt.Errorf("audioproxy: create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := h.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("audioproxy: speech worker request: %w", err)
	}
	defer resp.Body.Close()

	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("audioproxy: speech worker returned %d: %s", resp.StatusCode, string(raw))
	}

	var parsed speechWorkerResponse
	if err = json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("audioproxy: decode speech worker response: %w", err)
	}
	return &parsed, nil
}

func (h *Handler) setJobStatus(
	ctx context.Context,
	job jobMsg,
	status string,
	startedAtMs *int64,
	completedAtMs *int64,
	errorMsg string,
) error {
	jobState := transcriptJobState{
		SegmentID:         job.SegmentID,
		Status:            status,
		MimeType:          job.MimeType,
		OptimisticText:    job.OptimisticText,
		OptimisticSpeaker: job.OptimisticSpeaker,
		QueuedAtMs:        job.EnqueuedAtMs,
		StartedAtMs:       startedAtMs,
		CompletedAtMs:     completedAtMs,
		Error:             errorMsg,
	}
	payload, err := json.Marshal(jobState)
	if err != nil {
		return fmt.Errorf("marshal transcript job state: %w", err)
	}
	if err = h.redis.Set(ctx, audioSegmentJobKey(job.SegmentID), payload, 24*time.Hour).Err(); err != nil {
		return fmt.Errorf("write transcript job key: %w", err)
	}

	state, err := h.readActiveSessionState(ctx, job.SessionID)
	if err != nil {
		return err
	}
	if state == nil {
		state = &activeSessionState{SessionID: job.SessionID}
	}
	state.TranscriptJobs = upsertTranscriptJob(state.TranscriptJobs, jobState)
	return h.writeActiveSessionState(ctx, state)
}

func (h *Handler) recordAuthoritativeSegment(
	ctx context.Context,
	job jobMsg,
	resp *speechWorkerResponse,
	receivedAtMs int64,
) error {
	state, err := h.readActiveSessionState(ctx, job.SessionID)
	if err != nil {
		return err
	}
	if state == nil {
		state = &activeSessionState{SessionID: job.SessionID}
	}
	state.AuthoritativeSegments = appendAuthoritativeSegment(state.AuthoritativeSegments, authoritativeSegment{
		SegmentID:               job.SegmentID,
		StartMs:                 resp.StartMs,
		EndMs:                   resp.EndMs,
		Text:                    resp.Text,
		SpeakerID:               resp.SpeakerID,
		SpeakerRole:             resp.SpeakerRole,
		RoleConfidence:          resp.RoleConfidence,
		TranscriptionConfidence: resp.TranscriptionConfidence,
		Source:                  resp.Source,
		ReceivedAtMs:            receivedAtMs,
	})
	return h.writeActiveSessionState(ctx, state)
}

func (h *Handler) readActiveSessionState(ctx context.Context, sessionID string) (*activeSessionState, error) {
	data, err := h.redis.Get(ctx, activeSessionKey(sessionID)).Bytes()
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

func (h *Handler) writeActiveSessionState(ctx context.Context, state *activeSessionState) error {
	payload, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("encode active session state: %w", err)
	}
	if err = h.redis.Set(ctx, activeSessionKey(state.SessionID), payload, 24*time.Hour).Err(); err != nil {
		return fmt.Errorf("write active session state: %w", err)
	}
	return nil
}

func upsertTranscriptJob(jobs []transcriptJobState, next transcriptJobState) []transcriptJobState {
	for idx := range jobs {
		if jobs[idx].SegmentID == next.SegmentID {
			jobs[idx] = next
			return jobs
		}
	}
	return append(jobs, next)
}

func appendAuthoritativeSegment(segments []authoritativeSegment, next authoritativeSegment) []authoritativeSegment {
	segments = append(segments, next)
	if len(segments) > 50 {
		return append([]authoritativeSegment(nil), segments[len(segments)-50:]...)
	}
	return segments
}

func (h *Handler) loadReferenceSamples(ctx context.Context, sessionID string) ([]referenceSampleAttachment, error) {
	state, err := h.readActiveSessionState(ctx, sessionID)
	if err != nil || state == nil {
		return nil, err
	}

	var attachments []referenceSampleAttachment
	for _, sample := range state.SpeakerRoleCheck.Samples {
		if sample.Status != "captured" || sample.StoragePath == "" {
			continue
		}
		fieldName := ""
		switch sample.Role {
		case "Clinician":
			fieldName = "reference_clinician"
		case "Patient":
			fieldName = "reference_patient"
		default:
			continue
		}
		fileName := sample.FileName
		if fileName == "" {
			fileName = fieldName + ".wav"
		}
		attachments = append(attachments, referenceSampleAttachment{
			FieldName:   fieldName,
			FileName:    fileName,
			MimeType:    sample.MimeType,
			StoragePath: sample.StoragePath,
		})
	}
	return attachments, nil
}

func audioSegmentJobKey(segmentID string) string {
	return fmt.Sprintf("transcript:segment:%s", segmentID)
}

func activeSessionKey(sessionID string) string {
	return fmt.Sprintf("session:%s:active", sessionID)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}
