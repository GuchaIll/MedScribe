// Package repo declares the repository interfaces that bound the persistence
// layer. UseCases depend only on these interfaces; concrete implementations
// (pgx) are injected in internal/app/app.go.
package repo

import (
	"context"

	"github.com/medscribe/services/api/internal/entity"
)

// SessionRepository is the data-access contract for sessions.
type SessionRepository interface {
	Create(ctx context.Context, s *entity.Session) (*entity.Session, error)
	GetByID(ctx context.Context, id string) (*entity.Session, error)
	Update(ctx context.Context, s *entity.Session) (*entity.Session, error)
	ListByDoctor(ctx context.Context, doctorID string, limit, offset int) ([]*entity.Session, error)
	GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error)
	GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error)
	UpdateQueueItem(ctx context.Context, sessionID, itemID, status string) (*entity.QueueItem, error)
	// GetRecord returns the most recent MedicalRecord built for a session.
	GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error)
}

// PatientRepository is the data-access contract for patients.
type PatientRepository interface {
	Create(ctx context.Context, p *entity.Patient) (*entity.Patient, error)
	GetByID(ctx context.Context, id string) (*entity.Patient, error)
	GetByMRN(ctx context.Context, mrn string) (*entity.Patient, error)
	Update(ctx context.Context, p *entity.Patient) (*entity.Patient, error)
	List(ctx context.Context, limit, offset int) ([]*entity.Patient, error)
	Search(ctx context.Context, query string, limit int) ([]*entity.Patient, error)
	// HistoryRecords returns finalized MedicalRecords for the patient, newest first.
	HistoryRecords(ctx context.Context, patientID string, limit, offset int) ([]*entity.MedicalRecord, error)
}

// UserRepository is the data-access contract for authentication.
type UserRepository interface {
	Create(ctx context.Context, u *entity.User) (*entity.User, error)
	GetByID(ctx context.Context, id string) (*entity.User, error)
	GetByEmail(ctx context.Context, email string) (*entity.User, error)
	GetByUsername(ctx context.Context, username string) (*entity.User, error)
	UpdateLastLogin(ctx context.Context, userID string) error
}
