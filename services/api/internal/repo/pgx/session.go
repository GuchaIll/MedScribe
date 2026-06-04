// Package pgxrepo contains pgx/v5 implementations of the repo interfaces.
package pgxrepo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/medscribe/services/api/internal/entity"
)

// SessionRepo implements repo.SessionRepository using pgxpool.
type SessionRepo struct {
	db *pgxpool.Pool
}

// NewSessionRepo creates a SessionRepo backed by the given pool.
func NewSessionRepo(db *pgxpool.Pool) *SessionRepo {
	return &SessionRepo{db: db}
}

func (r *SessionRepo) Create(ctx context.Context, s *entity.Session) (*entity.Session, error) {
	const q = `
		INSERT INTO sessions
			(id, patient_id, doctor_id, status, visit_type, started_at, created_at, updated_at)
		VALUES
			($1, $2, $3, $4, $5, $6, $7, $7)
		RETURNING id, patient_id, doctor_id, status, visit_type, started_at, completed_at,
		          duration_seconds, created_at, updated_at`

	now := time.Now().UTC()
	// patient_id may be nil (NULL) when session is started before patient is identified.
	var patientID any
	if s.PatientID != nil {
		patientID = *s.PatientID
	}
	row := r.db.QueryRow(ctx, q,
		s.ID, patientID, s.DoctorID,
		string(s.Status), s.VisitType,
		s.StartedAt, now,
	)
	return scanSession(row)
}

func (r *SessionRepo) GetByID(ctx context.Context, id string) (*entity.Session, error) {
	const q = `
		SELECT id, patient_id, doctor_id, status, visit_type,
		       workflow_state, checkpoint_id, audio_file_path, duration_seconds,
		       started_at, completed_at, created_at, updated_at
		FROM sessions
		WHERE id = $1`

	row := r.db.QueryRow(ctx, q, id)
	return scanSessionFull(row)
}

func (r *SessionRepo) Update(ctx context.Context, s *entity.Session) (*entity.Session, error) {
	const q = `
		UPDATE sessions
		SET status = $2, workflow_state = $3, checkpoint_id = $4,
		    completed_at = $5, duration_seconds = $6, updated_at = NOW()
		WHERE id = $1
		RETURNING id, patient_id, doctor_id, status, visit_type,
		          workflow_state, checkpoint_id, audio_file_path, duration_seconds,
		          started_at, completed_at, created_at, updated_at`

	row := r.db.QueryRow(ctx, q,
		s.ID, string(s.Status), s.WorkflowState, s.CheckpointID,
		s.CompletedAt, s.DurationSeconds,
	)
	return scanSessionFull(row)
}

func (r *SessionRepo) ListByDoctor(ctx context.Context, doctorID string, limit, offset int) ([]*entity.Session, error) {
	const q = `
		SELECT id, patient_id, doctor_id, status, visit_type,
		       started_at, completed_at, created_at, updated_at
		FROM sessions
		WHERE doctor_id = $1
		ORDER BY started_at DESC
		LIMIT $2 OFFSET $3`

	rows, err := r.db.Query(ctx, q, doctorID, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("session: list by doctor: %w", err)
	}
	defer rows.Close()

	var result []*entity.Session
	for rows.Next() {
		var s entity.Session
		if err = rows.Scan(
			&s.ID, &s.PatientID, &s.DoctorID, &s.Status, &s.VisitType,
			&s.StartedAt, &s.CompletedAt, &s.CreatedAt, &s.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("session: scan row: %w", err)
		}
		result = append(result, &s)
	}
	return result, rows.Err()
}

func (r *SessionRepo) GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error) {
	const q = `
		SELECT id, session_id, original_filename, stored_path, COALESCE(file_type, ''),
		       COALESCE(extracted_text, ''), ocr_status::text, COALESCE(document_type, ''),
		       COALESCE(classification_confidence, 0), COALESCE(overall_confidence, 0),
		       COALESCE(field_count, 0), COALESCE(conflict_count, 0),
		       COALESCE(processing_errors, '[]'::json), COALESCE(structured_fields, '[]'::json),
		       COALESCE(conflicts, '[]'::json), processed_at, created_at
		FROM documents
		WHERE session_id = $1
		ORDER BY created_at ASC`

	rows, err := r.db.Query(ctx, q, sessionID)
	if err != nil {
		return nil, fmt.Errorf("session: get documents: %w", err)
	}
	defer rows.Close()

	var docs []*entity.Document
	for rows.Next() {
		var (
			d                    entity.Document
			ocrStatus            string
			processingErrorsJSON []byte
			fieldChangesJSON     []byte
			conflictDetailsJSON  []byte
		)
		if err = rows.Scan(
			&d.ID, &d.SessionID, &d.OriginalName, &d.StoragePath, &d.MimeType,
			&d.ExtractedText, &ocrStatus, &d.DocumentType,
			&d.ClassificationConfidence, &d.OverallConfidence,
			&d.FieldsExtracted, &d.ConflictsDetected,
			&processingErrorsJSON, &fieldChangesJSON, &conflictDetailsJSON,
			&d.ProcessedAt, &d.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("session: scan document: %w", err)
		}
		if err = json.Unmarshal(processingErrorsJSON, &d.ProcessingErrors); err != nil {
			return nil, fmt.Errorf("session: decode document processing errors: %w", err)
		}
		if err = json.Unmarshal(fieldChangesJSON, &d.FieldChanges); err != nil {
			return nil, fmt.Errorf("session: decode document field changes: %w", err)
		}
		if err = json.Unmarshal(conflictDetailsJSON, &d.ConflictDetails); err != nil {
			return nil, fmt.Errorf("session: decode document conflict details: %w", err)
		}
		d.Status = normalizeDocumentStatus(ocrStatus, d.ConflictsDetected, len(d.ProcessingErrors))
		docs = append(docs, &d)
	}
	return docs, rows.Err()
}

func normalizeDocumentStatus(ocrStatus string, conflicts, processingErrors int) string {
	switch ocrStatus {
	case "failed":
		return "failed"
	case "processing":
		return "processing"
	case "completed":
		if processingErrors > 0 {
			return "failed"
		}
		if conflicts > 0 {
			return "conflicts"
		}
		return "processed"
	case "pending":
		return "pending_ocr"
	default:
		if processingErrors > 0 {
			return "failed"
		}
		if conflicts > 0 {
			return "conflicts"
		}
		return ocrStatus
	}
}

func (r *SessionRepo) GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error) {
	const q = `
		SELECT id, session_id, field_path, old_value, new_value, reason, status,
		       created_at, reviewed_at
		FROM modification_queue
		WHERE session_id = $1
		ORDER BY created_at ASC`

	rows, err := r.db.Query(ctx, q, sessionID)
	if err != nil {
		return nil, fmt.Errorf("session: get queue: %w", err)
	}
	defer rows.Close()

	var items []*entity.QueueItem
	for rows.Next() {
		var it entity.QueueItem
		if err = rows.Scan(
			&it.ID, &it.SessionID, &it.FieldPath, &it.OldValue, &it.NewValue,
			&it.Reason, &it.Status, &it.CreatedAt, &it.ReviewedAt,
		); err != nil {
			return nil, fmt.Errorf("session: scan queue item: %w", err)
		}
		items = append(items, &it)
	}
	return items, rows.Err()
}

func (r *SessionRepo) UpdateQueueItem(
	ctx context.Context, sessionID, itemID, status string,
) (*entity.QueueItem, error) {
	const q = `
		UPDATE modification_queue
		SET status = $3, reviewed_at = NOW(), updated_at = NOW()
		WHERE id = $2 AND session_id = $1
		RETURNING id, session_id, field_path, old_value, new_value, reason, status,
		          created_at, reviewed_at`

	var it entity.QueueItem
	err := r.db.QueryRow(ctx, q, sessionID, itemID, status).Scan(
		&it.ID, &it.SessionID, &it.FieldPath, &it.OldValue, &it.NewValue,
		&it.Reason, &it.Status, &it.CreatedAt, &it.ReviewedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("session: update queue item: %w", err)
	}
	return &it, nil
}

func (r *SessionRepo) GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error) {
	const q = `
		SELECT id, patient_id, session_id,
		       COALESCE(template_used, record_type, 'SOAP') AS template_type,
		       structured_data,
		       COALESCE(soap_note, '') AS clinical_note,
		       is_final AS is_finalized,
		       version, created_at, finalized_at
		FROM medical_records
		WHERE session_id = $1
		ORDER BY version DESC
		LIMIT 1`

	var mr entity.MedicalRecord
	err := r.db.QueryRow(ctx, q, sessionID).Scan(
		&mr.ID, &mr.PatientID, &mr.SessionID, &mr.TemplateType,
		&mr.StructuredData, &mr.ClinicalNote, &mr.IsFinalized, &mr.Version,
		&mr.CreatedAt, &mr.FinalizedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("session: get record: %w", err)
	}
	return &mr, nil
}

// ─── scan helpers ─────────────────────────────────────────────────────────────

func scanSession(row pgx.Row) (*entity.Session, error) {
	var s entity.Session
	var status string
	err := row.Scan(
		&s.ID, &s.PatientID, &s.DoctorID, &status, &s.VisitType,
		&s.StartedAt, &s.CompletedAt, &s.DurationSeconds,
		&s.CreatedAt, &s.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("session: scan: %w", err)
	}
	s.Status = entity.SessionStatus(status)
	return &s, nil
}

func scanSessionFull(row pgx.Row) (*entity.Session, error) {
	var s entity.Session
	var status string
	err := row.Scan(
		&s.ID, &s.PatientID, &s.DoctorID, &status, &s.VisitType,
		&s.WorkflowState, &s.CheckpointID, &s.AudioFilePath, &s.DurationSeconds,
		&s.StartedAt, &s.CompletedAt, &s.CreatedAt, &s.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("session: scan full: %w", err)
	}
	s.Status = entity.SessionStatus(status)
	return &s, nil
}
