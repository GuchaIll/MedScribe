package pgxrepo

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/medscribe/services/api/internal/entity"
)

// PatientRepo implements repo.PatientRepository using pgxpool.
type PatientRepo struct {
	db *pgxpool.Pool
}

func NewPatientRepo(db *pgxpool.Pool) *PatientRepo {
	return &PatientRepo{db: db}
}

func (r *PatientRepo) Create(ctx context.Context, p *entity.Patient) (*entity.Patient, error) {
	const q = `
		INSERT INTO patients
			(id, mrn, full_name, dob, age, sex, encrypted_demographics,
			 created_by, is_active, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9,$9)
		RETURNING id, mrn, full_name, dob, age, sex, encrypted_demographics,
		          created_by, is_active, created_at, updated_at`

	now := time.Now().UTC()
	row := r.db.QueryRow(ctx, q,
		p.ID, p.MRN, p.FullName, p.DOB, p.Age, p.Sex,
		p.EncryptedDemographics, p.CreatedBy, now,
	)
	return scanPatient(row)
}

func (r *PatientRepo) GetByID(ctx context.Context, id string) (*entity.Patient, error) {
	const q = `
		SELECT id, mrn, full_name, dob, age, sex, encrypted_demographics,
		       created_by, is_active, created_at, updated_at
		FROM patients WHERE id = $1 AND is_active = true`
	return scanPatient(r.db.QueryRow(ctx, q, id))
}

func (r *PatientRepo) GetByMRN(ctx context.Context, mrn string) (*entity.Patient, error) {
	const q = `
		SELECT id, mrn, full_name, dob, age, sex, encrypted_demographics,
		       created_by, is_active, created_at, updated_at
		FROM patients WHERE mrn = $1 AND is_active = true`
	return scanPatient(r.db.QueryRow(ctx, q, mrn))
}

func (r *PatientRepo) Update(ctx context.Context, p *entity.Patient) (*entity.Patient, error) {
	const q = `
		UPDATE patients
		SET full_name = $2, dob = $3, age = $4, sex = $5,
		    encrypted_demographics = $6, updated_at = NOW()
		WHERE id = $1
		RETURNING id, mrn, full_name, dob, age, sex, encrypted_demographics,
		          created_by, is_active, created_at, updated_at`
	return scanPatient(r.db.QueryRow(ctx, q,
		p.ID, p.FullName, p.DOB, p.Age, p.Sex, p.EncryptedDemographics,
	))
}

func (r *PatientRepo) List(ctx context.Context, limit, offset int) ([]*entity.Patient, error) {
	const q = `
		SELECT id, mrn, full_name, dob, age, sex, encrypted_demographics,
		       created_by, is_active, created_at, updated_at
		FROM patients WHERE is_active = true
		ORDER BY full_name ASC LIMIT $1 OFFSET $2`

	return queryPatients(ctx, r.db, q, limit, offset)
}

func (r *PatientRepo) Search(ctx context.Context, query string, limit int) ([]*entity.Patient, error) {
	const q = `
		SELECT id, mrn, full_name, dob, age, sex, encrypted_demographics,
		       created_by, is_active, created_at, updated_at
		FROM patients
		WHERE is_active = true
		  AND (full_name ILIKE '%' || $1 || '%' OR mrn ILIKE '%' || $1 || '%')
		ORDER BY full_name ASC LIMIT $2`
	return queryPatients(ctx, r.db, q, query, limit)
}

func (r *PatientRepo) HistoryRecords(
	ctx context.Context, patientID string, limit, offset int,
) ([]*entity.MedicalRecord, error) {
	const q = `
		SELECT id, patient_id, session_id, template_type,
		       structured_data, clinical_note, is_finalized, version, created_at, finalized_at
		FROM medical_records
		WHERE patient_id = $1
		ORDER BY created_at DESC
		LIMIT $2 OFFSET $3`

	rows, err := r.db.Query(ctx, q, patientID, limit, offset)
	if err != nil {
		return nil, fmt.Errorf("patient: history records query: %w", err)
	}
	defer rows.Close()

	var result []*entity.MedicalRecord
	for rows.Next() {
		var mr entity.MedicalRecord
		if err = rows.Scan(
			&mr.ID, &mr.PatientID, &mr.SessionID, &mr.TemplateType,
			&mr.StructuredData, &mr.ClinicalNote, &mr.IsFinalized, &mr.Version,
			&mr.CreatedAt, &mr.FinalizedAt,
		); err != nil {
			return nil, fmt.Errorf("patient: scan record: %w", err)
		}
		result = append(result, &mr)
	}
	return result, rows.Err()
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func scanPatient(row pgx.Row) (*entity.Patient, error) {
	var p entity.Patient
	err := row.Scan(
		&p.ID, &p.MRN, &p.FullName, &p.DOB, &p.Age, &p.Sex,
		&p.EncryptedDemographics, &p.CreatedBy, &p.IsActive,
		&p.CreatedAt, &p.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("patient: scan: %w", err)
	}
	return &p, nil
}

func queryPatients(ctx context.Context, db *pgxpool.Pool, q string, args ...any) ([]*entity.Patient, error) {
	rows, err := db.Query(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("patient: query: %w", err)
	}
	defer rows.Close()

	var result []*entity.Patient
	for rows.Next() {
		var p entity.Patient
		if err = rows.Scan(
			&p.ID, &p.MRN, &p.FullName, &p.DOB, &p.Age, &p.Sex,
			&p.EncryptedDemographics, &p.CreatedBy, &p.IsActive,
			&p.CreatedAt, &p.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("patient: scan row: %w", err)
		}
		result = append(result, &p)
	}
	return result, rows.Err()
}
