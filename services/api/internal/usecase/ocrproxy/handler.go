package ocrproxy

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

type Config struct {
	PythonBaseURL  string
	RequestTimeout time.Duration
}

type jobMsg struct {
	JobID        string `json:"job_id"`
	DocumentID   string `json:"document_id"`
	SessionID    string `json:"session_id"`
	OriginalName string `json:"original_name"`
	StoragePath  string `json:"storage_path"`
	MimeType     string `json:"mime_type"`
}

type pythonUploadResponse struct {
	SessionID        string                 `json:"session_id"`
	Uploaded         int                    `json:"uploaded"`
	Files            []pythonUploadDocument `json:"files"`
	StructuredRecord map[string]any         `json:"structured_record"`
}

type pythonUploadDocument struct {
	DocumentID               string           `json:"document_id"`
	OriginalName             string           `json:"original_name"`
	Path                     string           `json:"path"`
	ContentType              string           `json:"content_type"`
	DocumentType             string           `json:"document_type"`
	ClassificationConfidence float64          `json:"classification_confidence"`
	OverallConfidence        float64          `json:"overall_confidence"`
	FieldsExtracted          int              `json:"fields_extracted"`
	ConflictsDetected        int              `json:"conflicts_detected"`
	QueueItemsCreated        int              `json:"queue_items_created"`
	ProcessingErrors         []string         `json:"processing_errors"`
	FieldChanges             []map[string]any `json:"field_changes"`
	ConflictDetails          []map[string]any `json:"conflict_details"`
	AgentSummary             string           `json:"agent_summary"`
	Error                    string           `json:"error"`
}

type activeSessionState struct {
	SessionID        string          `json:"session_id"`
	PendingDocuments []documentState `json:"pending_documents,omitempty"`
	OCRJobs          []ocrJobState   `json:"ocr_jobs,omitempty"`
}

type documentState struct {
	DocumentID               string           `json:"document_id"`
	SessionID                string           `json:"session_id,omitempty"`
	OriginalName             string           `json:"original_name"`
	Path                     string           `json:"path,omitempty"`
	ContentType              string           `json:"content_type,omitempty"`
	Status                   string           `json:"status,omitempty"`
	DocumentType             string           `json:"document_type,omitempty"`
	ClassificationConfidence float64          `json:"classification_confidence,omitempty"`
	OverallConfidence        float64          `json:"overall_confidence,omitempty"`
	FieldsExtracted          int              `json:"fields_extracted,omitempty"`
	ConflictsDetected        int              `json:"conflicts_detected,omitempty"`
	QueueItemsCreated        int              `json:"queue_items_created,omitempty"`
	ProcessingErrors         []string         `json:"processing_errors,omitempty"`
	FieldChanges             []map[string]any `json:"field_changes,omitempty"`
	ConflictDetails          []map[string]any `json:"conflict_details,omitempty"`
	AgentSummary             string           `json:"agent_summary,omitempty"`
	StructuredRecord         map[string]any   `json:"structured_record,omitempty"`
	ProcessedAt              *time.Time       `json:"processed_at,omitempty"`
	CreatedAt                time.Time        `json:"created_at,omitempty"`
}

type ocrJobState struct {
	JobID      string `json:"job_id"`
	DocumentID string `json:"document_id"`
	Status     string `json:"status"`
	QueuedAtMs int64  `json:"queued_at_ms"`
}

type Handler struct {
	cfg    Config
	client *http.Client
	redis  *redis.Client
	log    *zap.Logger
}

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

func (h *Handler) Handle(ctx context.Context, key, value []byte) error {
	var job jobMsg
	if err := json.Unmarshal(value, &job); err != nil {
		return fmt.Errorf("ocrproxy: unmarshal job: %w", err)
	}

	if err := h.setJobStatus(ctx, job, "processing", nil, nil, ""); err != nil {
		h.log.Warn("ocrproxy: failed to mark processing", zap.Error(err))
	}

	resp, err := h.submitToPython(ctx, job)
	if err != nil {
		_ = h.setJobStatus(ctx, job, "failed", nil, nil, err.Error())
		return err
	}
	if len(resp.Files) == 0 {
		err = fmt.Errorf("ocrproxy: python upload returned no files")
		_ = h.setJobStatus(ctx, job, "failed", nil, nil, err.Error())
		return err
	}

	doc := resp.Files[0]
	status := "processed"
	if doc.Error != "" || len(doc.ProcessingErrors) > 0 {
		status = "failed"
	} else if doc.ConflictsDetected > 0 {
		status = "conflicts"
	}

	if err = h.setJobStatus(ctx, job, status, &doc, resp.StructuredRecord, ""); err != nil {
		return fmt.Errorf("ocrproxy: write completion state: %w", err)
	}
	return nil
}

func (h *Handler) submitToPython(ctx context.Context, job jobMsg) (*pythonUploadResponse, error) {
	f, err := os.Open(job.StoragePath)
	if err != nil {
		return nil, fmt.Errorf("ocrproxy: open spool file: %w", err)
	}
	defer f.Close()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreateFormFile("files", job.OriginalName)
	if err != nil {
		return nil, fmt.Errorf("ocrproxy: create multipart file: %w", err)
	}
	if _, err = io.Copy(part, f); err != nil {
		return nil, fmt.Errorf("ocrproxy: copy file body: %w", err)
	}
	if err = writer.Close(); err != nil {
		return nil, fmt.Errorf("ocrproxy: close multipart writer: %w", err)
	}

	url := fmt.Sprintf("%s/api/session/%s/upload", h.cfg.PythonBaseURL, job.SessionID)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, &body)
	if err != nil {
		return nil, fmt.Errorf("ocrproxy: create request: %w", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())

	resp, err := h.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("ocrproxy: python request: %w", err)
	}
	defer resp.Body.Close()

	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("ocrproxy: python returned %d: %s", resp.StatusCode, string(raw))
	}

	var parsed pythonUploadResponse
	if err = json.Unmarshal(raw, &parsed); err != nil {
		return nil, fmt.Errorf("ocrproxy: decode python response: %w", err)
	}
	return &parsed, nil
}

func (h *Handler) setJobStatus(
	ctx context.Context,
	job jobMsg,
	status string,
	doc *pythonUploadDocument,
	structuredRecord map[string]any,
	errorMsg string,
) error {
	state, err := h.readActiveSessionState(ctx, job.SessionID)
	if err != nil {
		return err
	}
	if state == nil {
		state = &activeSessionState{SessionID: job.SessionID}
	}

	now := time.Now().UTC()
	for i := range state.OCRJobs {
		if state.OCRJobs[i].JobID == job.JobID {
			state.OCRJobs[i].Status = status
		}
	}

	foundDoc := false
	for i := range state.PendingDocuments {
		d := &state.PendingDocuments[i]
		if d.DocumentID != job.DocumentID && d.OriginalName != job.OriginalName {
			continue
		}
		foundDoc = true
		d.DocumentID = job.DocumentID
		d.SessionID = job.SessionID
		d.OriginalName = firstNonEmpty(d.OriginalName, job.OriginalName)
		d.Path = firstNonEmpty(d.Path, job.StoragePath)
		d.ContentType = firstNonEmpty(d.ContentType, job.MimeType)
		d.Status = status
		if doc != nil {
			d.OriginalName = firstNonEmpty(doc.OriginalName, d.OriginalName)
			d.Path = firstNonEmpty(doc.Path, d.Path)
			d.ContentType = firstNonEmpty(doc.ContentType, d.ContentType)
			d.DocumentType = doc.DocumentType
			d.ClassificationConfidence = doc.ClassificationConfidence
			d.OverallConfidence = doc.OverallConfidence
			d.FieldsExtracted = doc.FieldsExtracted
			d.ConflictsDetected = doc.ConflictsDetected
			d.QueueItemsCreated = doc.QueueItemsCreated
			d.ProcessingErrors = doc.ProcessingErrors
			d.FieldChanges = doc.FieldChanges
			d.ConflictDetails = doc.ConflictDetails
			d.AgentSummary = doc.AgentSummary
			d.StructuredRecord = structuredRecord
		}
		if errorMsg != "" {
			d.ProcessingErrors = appendUnique(d.ProcessingErrors, errorMsg)
		}
		processedAt := now
		d.ProcessedAt = &processedAt
	}

	if !foundDoc {
		entry := documentState{
			DocumentID:   job.DocumentID,
			SessionID:    job.SessionID,
			OriginalName: job.OriginalName,
			Path:         job.StoragePath,
			ContentType:  job.MimeType,
			Status:       status,
			CreatedAt:    now,
		}
		if doc != nil {
			entry.DocumentType = doc.DocumentType
			entry.ClassificationConfidence = doc.ClassificationConfidence
			entry.OverallConfidence = doc.OverallConfidence
			entry.FieldsExtracted = doc.FieldsExtracted
			entry.ConflictsDetected = doc.ConflictsDetected
			entry.QueueItemsCreated = doc.QueueItemsCreated
			entry.ProcessingErrors = doc.ProcessingErrors
			entry.FieldChanges = doc.FieldChanges
			entry.ConflictDetails = doc.ConflictDetails
			entry.AgentSummary = doc.AgentSummary
			entry.StructuredRecord = structuredRecord
			entry.Path = firstNonEmpty(doc.Path, entry.Path)
			entry.ContentType = firstNonEmpty(doc.ContentType, entry.ContentType)
			entry.OriginalName = firstNonEmpty(doc.OriginalName, entry.OriginalName)
		}
		if errorMsg != "" {
			entry.ProcessingErrors = []string{errorMsg}
		}
		processedAt := now
		entry.ProcessedAt = &processedAt
		state.PendingDocuments = append(state.PendingDocuments, entry)
	}

	jobState := map[string]any{
		"job_id":        job.JobID,
		"document_id":   job.DocumentID,
		"session_id":    job.SessionID,
		"original_name": job.OriginalName,
		"storage_path":  job.StoragePath,
		"mime_type":     job.MimeType,
		"status":        status,
	}
	if errorMsg != "" {
		jobState["error"] = errorMsg
	}
	if doc != nil {
		jobState["ocr_result"] = doc
	}
	if structuredRecord != nil {
		jobState["structured_record"] = structuredRecord
	}
	if err = h.writeActiveSessionState(ctx, state); err != nil {
		return err
	}
	if b, marshalErr := json.Marshal(jobState); marshalErr == nil {
		_ = h.redis.Set(ctx, fmt.Sprintf("ocr:job:%s", job.JobID), b, 24*time.Hour).Err()
	}
	return nil
}

func (h *Handler) readActiveSessionState(ctx context.Context, sessionID string) (*activeSessionState, error) {
	data, err := h.redis.Get(ctx, fmt.Sprintf("session:%s:active", sessionID)).Bytes()
	if err != nil {
		if err == redis.Nil {
			return nil, nil
		}
		return nil, fmt.Errorf("ocrproxy: read active session: %w", err)
	}
	var state activeSessionState
	if err = json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("ocrproxy: decode active session: %w", err)
	}
	return &state, nil
}

func (h *Handler) writeActiveSessionState(ctx context.Context, state *activeSessionState) error {
	payload, err := json.Marshal(state)
	if err != nil {
		return fmt.Errorf("ocrproxy: encode active session: %w", err)
	}
	if err = h.redis.Set(ctx, fmt.Sprintf("session:%s:active", state.SessionID), payload, 24*time.Hour).Err(); err != nil {
		return fmt.Errorf("ocrproxy: write active session: %w", err)
	}
	return nil
}

func firstNonEmpty(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

func appendUnique(existing []string, value string) []string {
	if value == "" {
		return existing
	}
	for _, item := range existing {
		if item == value {
			return existing
		}
	}
	return append(existing, value)
}
