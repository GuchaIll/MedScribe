package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

const ocrJobsTopic = "ocr.jobs"

// UploadDocument stores a clinical document attachment for the session.
// Phase 2 captures the original file quickly, queues OCR asynchronously, and
// returns a pending document immediately. A later phase can swap the local
// spool path for object storage without changing the request semantics.
func (uc *sessionUseCase) UploadDocument(
	ctx context.Context, sessionID string,
	fh *multipart.FileHeader, file multipart.File,
) (*entity.Document, error) {
	session, err := uc.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if session.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}
	if fh == nil || file == nil {
		return nil, fmt.Errorf("upload document: file is required")
	}

	now := time.Now().UTC()
	docID := uuid.NewString()
	jobID := uuid.NewString()
	storagePath, err := spoolUpload(sessionID, docID, fh.Filename, file)
	if err != nil {
		return nil, fmt.Errorf("upload document: spool file: %w", err)
	}

	doc := &entity.Document{
		ID:           docID,
		SessionID:    sessionID,
		OriginalName: fh.Filename,
		StoragePath:  storagePath,
		MimeType:     fh.Header.Get("Content-Type"),
		Status:       "pending_ocr",
		DocumentType: "pending_ocr",
		CreatedAt:    now,
	}

	job := map[string]any{
		"job_id":        jobID,
		"job_type":      "ocr",
		"status":        "queued",
		"document_id":   doc.ID,
		"session_id":    doc.SessionID,
		"original_name": doc.OriginalName,
		"storage_path":  doc.StoragePath,
		"mime_type":     doc.MimeType,
		"uploaded_at":   now.Format(time.RFC3339Nano),
	}
	if err = uc.enqueueOCRJob(ctx, doc, jobID, job); err != nil {
		return nil, err
	}

	uc.log.Info("document queued for OCR",
		zap.String("session_id", sessionID),
		zap.String("document_id", doc.ID),
		zap.String("path", doc.StoragePath),
	)
	return doc, nil
}

// GetRecord returns the most recent MedicalRecord produced for the session.
func (uc *sessionUseCase) GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error) {
	return uc.sessions.GetRecord(ctx, sessionID)
}

// GetDocuments returns all documents attached to the session.
func (uc *sessionUseCase) GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error) {
	docs, err := uc.sessions.GetDocuments(ctx, sessionID)
	if err != nil {
		uc.log.Warn("failed to load persisted documents; falling back to active session state",
			zap.String("session_id", sessionID),
			zap.Error(err),
		)
		docs = nil
	}
	pendingDocs, err := uc.pendingDocuments(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	return mergeSessionDocuments(docs, pendingDocs), nil
}

// GetQueue returns the processing queue for the session.
func (uc *sessionUseCase) GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error) {
	return uc.sessions.GetQueue(ctx, sessionID)
}

// UpdateQueueItem advances the status of a single queue item.
func (uc *sessionUseCase) UpdateQueueItem(
	ctx context.Context, sessionID, itemID, status string,
) (*entity.QueueItem, error) {
	return uc.sessions.UpdateQueueItem(ctx, sessionID, itemID, status)
}

func spoolUpload(sessionID, documentID, fileName string, src multipart.File) (string, error) {
	baseDir := filepath.Join(os.TempDir(), "medscribe", "ocr-spool", sessionID)
	if err := os.MkdirAll(baseDir, 0o755); err != nil {
		return "", err
	}

	safeName := sanitizeFileName(fileName)
	if safeName == "" {
		safeName = "upload.bin"
	}
	targetPath := filepath.Join(baseDir, fmt.Sprintf("%s-%s", documentID, safeName))

	dst, err := os.Create(targetPath)
	if err != nil {
		return "", err
	}
	defer dst.Close()

	if _, err = io.Copy(dst, src); err != nil {
		return "", err
	}
	return targetPath, nil
}

func (uc *sessionUseCase) enqueueOCRJob(
	ctx context.Context,
	doc *entity.Document,
	jobID string,
	job map[string]any,
) error {
	jobPayload, err := json.Marshal(job)
	if err != nil {
		return fmt.Errorf("upload document: marshal OCR job: %w", err)
	}
	if err = uc.producer.PublishJSON(ctx, ocrJobsTopic, doc.SessionID, job); err != nil {
		return fmt.Errorf("upload document: publish OCR job: %w", err)
	}
	if err = uc.redis.Set(ctx, ocrJobStatusKey(jobID), jobPayload, activeSessionTTL).Err(); err != nil {
		return fmt.Errorf("upload document: store OCR job status: %w", err)
	}
	if err = updateActiveSessionState(ctx, uc.redis, doc.SessionID, func(state *activeSessionState) {
		state.PendingDocuments = append(state.PendingDocuments, *doc)
		state.OCRJobs = append(state.OCRJobs, ocrJobState{
			JobID:      jobID,
			DocumentID: doc.ID,
			Status:     "queued",
			QueuedAtMs: time.Now().UnixMilli(),
		})
	}); err != nil {
		uc.log.Warn("ocr job queued but active session mirror failed",
			zap.String("session_id", doc.SessionID),
			zap.String("job_id", jobID),
			zap.Error(err),
		)
	}
	return nil
}

func (uc *sessionUseCase) pendingDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error) {
	state, err := readActiveSessionState(ctx, uc.redis, sessionID)
	if err != nil {
		return nil, fmt.Errorf("get pending documents: %w", err)
	}
	if state == nil || len(state.PendingDocuments) == 0 {
		return nil, nil
	}

	docs := make([]*entity.Document, 0, len(state.PendingDocuments))
	for i := range state.PendingDocuments {
		doc := state.PendingDocuments[i]
		docs = append(docs, &doc)
	}
	return docs, nil
}

func sanitizeFileName(name string) string {
	name = filepath.Base(strings.TrimSpace(name))
	var b strings.Builder
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z':
			b.WriteRune(r)
		case r >= 'A' && r <= 'Z':
			b.WriteRune(r)
		case r >= '0' && r <= '9':
			b.WriteRune(r)
		case r == '.', r == '-', r == '_':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	return b.String()
}

func mergeSessionDocuments(primary []*entity.Document, overlay []*entity.Document) []*entity.Document {
	if len(primary) == 0 {
		return overlay
	}
	if len(overlay) == 0 {
		return primary
	}

	merged := make([]*entity.Document, 0, len(primary)+len(overlay))
	indexByKey := make(map[string]int, len(primary)+len(overlay))
	appendDoc := func(doc *entity.Document) {
		key := documentMergeKey(doc)
		if idx, ok := indexByKey[key]; ok {
			merged[idx] = doc
			return
		}
		indexByKey[key] = len(merged)
		merged = append(merged, doc)
	}

	for _, doc := range primary {
		appendDoc(doc)
	}
	for _, doc := range overlay {
		appendDoc(doc)
	}
	return merged
}

func documentMergeKey(doc *entity.Document) string {
	if doc == nil {
		return ""
	}
	if doc.ID != "" {
		return "id:" + doc.ID
	}
	return "name:" + doc.OriginalName
}
