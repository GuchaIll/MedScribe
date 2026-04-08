// Package usecase declares the UseCase interfaces consumed by the HTTP
// controller layer. Concrete implementations live alongside in this package.
package usecase

import (
	"context"
	"errors"
	"mime/multipart"

	"github.com/medscribe/services/api/internal/entity"
)

// ErrNotImplemented is returned by stub UseCases for features not yet built.
var ErrNotImplemented = errors.New("not yet implemented")

// ─── Session ─────────────────────────────────────────────────────────────────

// SessionUseCase is the full contract for session business logic.
type SessionUseCase interface {
	StartSession(ctx context.Context, userID string) (*SessionStartResponse, error)
	EndSession(ctx context.Context, sessionID string) (*SessionEndResponse, error)
	ProcessTranscription(ctx context.Context, req TranscribeRequest) (*TranscribeResponse, error)
	TriggerPipeline(ctx context.Context, req TriggerPipelineRequest) (*TriggerPipelineResponse, error)
	GetPipelineStatus(ctx context.Context, sessionID string) (*entity.PipelineStatus, error)
	UploadDocument(ctx context.Context, sessionID string, fh *multipart.FileHeader, file multipart.File) (*entity.Document, error)
	GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error)
	GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error)
	GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error)
	UpdateQueueItem(ctx context.Context, sessionID, itemID, status string) (*entity.QueueItem, error)
}

type SessionStartResponse struct {
	SessionID string `json:"session_id"`
	Status    string `json:"status"`
}

type SessionEndResponse struct {
	SessionID string `json:"session_id"`
	Status    string `json:"status"`
	Duration  *int   `json:"duration_seconds,omitempty"`
}

type TranscribeRequest struct {
	SessionID string `json:"session_id"`
	Text      string `json:"text"`
	Speaker   string `json:"speaker"`
}

type TranscribeResponse struct {
	SessionID    string `json:"session_id"`
	TurnsStored  int    `json:"turns_stored"`
	Speaker      string `json:"speaker"`
}

// TriggerPipelineRequest mirrors RunPipelineRequest from the Python route.
type TriggerPipelineRequest struct {
	SessionID    string                          `json:"session_id"`
	PatientID    string                          `json:"patient_id"`
	DoctorID     string                          `json:"doctor_id"`
	IsNewPatient bool                            `json:"is_new_patient"`
	Segments     []TranscriptSegmentInput        `json:"segments"`
}

type TranscriptSegmentInput struct {
	Start      float64  `json:"start"`
	End        float64  `json:"end"`
	Speaker    string   `json:"speaker"`
	RawText    string   `json:"raw_text"`
	CleanedText string  `json:"cleaned_text,omitempty"`
	Confidence string   `json:"confidence,omitempty"`
}

type TriggerPipelineResponse struct {
	Accepted   bool   `json:"accepted"`
	PipelineID string `json:"pipeline_id"`
	Message    string `json:"message"`
}

// ─── Patient ──────────────────────────────────────────────────────────────────

// PatientUseCase is the contract for patient business logic.
type PatientUseCase interface {
	GetProfile(ctx context.Context, patientID string) (*PatientProfileResponse, error)
	GetLabTrends(ctx context.Context, patientID string, testName *string) ([]entity.LabTrend, error)
	GetRiskScore(ctx context.Context, patientID string) (*entity.RiskScore, error)
	GetHistoryRecords(ctx context.Context, patientID string, limit, offset int) ([]*entity.MedicalRecord, error)
}

// PatientProfileResponse aggregates all patient data for the /profile endpoint.
type PatientProfileResponse struct {
	Patient    *entity.Patient      `json:"patient"`
	LabTrends  []entity.LabTrend    `json:"lab_trends"`
	RiskScore  *entity.RiskScore    `json:"risk_score"`
	RecordCount int                 `json:"record_count"`
}

// ─── Auth ─────────────────────────────────────────────────────────────────────

// AuthUseCase is the contract for authentication business logic.
type AuthUseCase interface {
	Register(ctx context.Context, req RegisterRequest) (*entity.User, error)
	Login(ctx context.Context, req LoginRequest) (*LoginResponse, error)
	GetProfile(ctx context.Context, userID string) (*entity.User, error)
	ValidateToken(ctx context.Context, token string) (*Claims, error)
}

type RegisterRequest struct {
	Email      string `json:"email"`
	Password   string `json:"password"`
	FullName   string `json:"full_name"`
	Role       string `json:"role"`
	Occupation string `json:"occupation"`
}

type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type LoginResponse struct {
	AccessToken string       `json:"access_token"`
	TokenType   string       `json:"token_type"`
	ExpiresAtMs int64        `json:"expires_at_ms"`
	Profile     *entity.User `json:"profile"`
}

// Claims holds the validated JWT payload, stored in request context.
type Claims struct {
	UserID      string   `json:"user_id"`
	Role        string   `json:"role"`
	Permissions []string `json:"permissions"`
	ExpiresAtMs int64    `json:"expires_at_ms"`
}

// ─── Assistant ────────────────────────────────────────────────────────────────

// AssistantUseCase is the contract for the RAG-based clinical Q&A.
type AssistantUseCase interface {
	Query(ctx context.Context, sessionID, patientID, question string) (*AssistantResponse, error)
}

type AssistantResponse struct {
	Answer        string         `json:"answer"`
	Confidence    float64        `json:"confidence"`
	LowConfidence bool           `json:"low_confidence"`
	Disclaimer    *string        `json:"disclaimer,omitempty"`
	Sources       []map[string]any `json:"sources"`
}
