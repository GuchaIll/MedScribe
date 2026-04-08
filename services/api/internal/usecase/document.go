package usecase

import (
	"context"
	"fmt"
	"mime/multipart"

	"github.com/medscribe/services/api/internal/entity"
)

// UploadDocument stores a clinical document attachment for the session.
// Phase 1 defers to the Python storage layer via the shared database;
// Phase 4 will wire the Go S3 storage backend.
func (uc *sessionUseCase) UploadDocument(
	ctx context.Context, sessionID string,
	fh *multipart.FileHeader, _ multipart.File,
) (*entity.Document, error) {
	return nil, fmt.Errorf("upload document: not yet implemented — Phase 4")
}

// GetRecord returns the most recent MedicalRecord produced for the session.
func (uc *sessionUseCase) GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error) {
	return uc.sessions.GetRecord(ctx, sessionID)
}

// GetDocuments returns all documents attached to the session.
func (uc *sessionUseCase) GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error) {
	return uc.sessions.GetDocuments(ctx, sessionID)
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
