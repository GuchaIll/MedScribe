// Package usecase declares the UseCase interfaces consumed by the HTTP
// controller layer. Concrete implementations live alongside in this package.
package usecase

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"mime/multipart"
	"strconv"

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
	UploadAudioSegment(
		ctx context.Context,
		sessionID string,
		req UploadAudioSegmentRequest,
		fh *multipart.FileHeader,
		file multipart.File,
	) (*UploadAudioSegmentResponse, error)
	UploadSpeakerRoleSample(
		ctx context.Context,
		sessionID string,
		req UploadSpeakerRoleSampleRequest,
		fh *multipart.FileHeader,
		file multipart.File,
	) (*SpeakerRoleCheckResponse, error)
	TriggerPipeline(ctx context.Context, req TriggerPipelineRequest) (*TriggerPipelineResponse, error)
	GetPipelineStatus(ctx context.Context, sessionID string) (*entity.PipelineStatus, error)
	UploadDocument(ctx context.Context, sessionID string, fh *multipart.FileHeader, file multipart.File) (*entity.Document, error)
	GetRecord(ctx context.Context, sessionID string) (*entity.MedicalRecord, error)
	GetLiveTranscript(ctx context.Context, sessionID string) (*LiveTranscriptResponse, error)
	GetDocuments(ctx context.Context, sessionID string) ([]*entity.Document, error)
	GetQueue(ctx context.Context, sessionID string) ([]*entity.QueueItem, error)
	UpdateQueueItem(ctx context.Context, sessionID, itemID, status string) (*entity.QueueItem, error)
}

type SessionStartResponse struct {
	SessionID        string                    `json:"session_id"`
	Status           string                    `json:"status"`
	SpeakerRoleCheck *SpeakerRoleCheckResponse `json:"speaker_role_check,omitempty"`
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
	Source       string `json:"source,omitempty"`
	AgentMessage string `json:"agent_message,omitempty"`
}

type UploadAudioSegmentRequest struct {
	SegmentID         string `json:"segment_id"`
	StartedAtMs       int64  `json:"started_at_ms"`
	EndedAtMs         int64  `json:"ended_at_ms"`
	SampleRateHz      int    `json:"sample_rate_hz,omitempty"`
	MimeType          string `json:"mime_type,omitempty"`
	OptimisticText    string `json:"optimistic_text,omitempty"`
	OptimisticSpeaker string `json:"optimistic_speaker,omitempty"`
}

type UploadAudioSegmentResponse struct {
	SessionID string `json:"session_id"`
	SegmentID string `json:"segment_id"`
	Accepted  bool   `json:"accepted"`
	Status    string `json:"status"`
	Message   string `json:"message,omitempty"`
}

type UploadSpeakerRoleSampleRequest struct {
	Role string `json:"role"`
}

type LiveTranscriptResponse struct {
	SessionID             string                     `json:"session_id"`
	TranscriptJobs        []LiveTranscriptJob        `json:"transcript_jobs,omitempty"`
	AuthoritativeSegments []LiveAuthoritativeSegment `json:"authoritative_segments,omitempty"`
}

type LiveTranscriptJob struct {
	SegmentID         string `json:"segment_id"`
	Status            string `json:"status"`
	OptimisticText    string `json:"optimistic_text,omitempty"`
	OptimisticSpeaker string `json:"optimistic_speaker,omitempty"`
	Error             string `json:"error,omitempty"`
}

type LiveAuthoritativeSegment struct {
	SegmentID               string  `json:"segment_id"`
	Text                    string  `json:"text"`
	SpeakerID               string  `json:"speaker_id,omitempty"`
	SpeakerRole             string  `json:"speaker_role,omitempty"`
	RoleConfidence          float64 `json:"role_confidence,omitempty"`
	TranscriptionConfidence float64 `json:"transcription_confidence,omitempty"`
	Source                  string  `json:"source,omitempty"`
}

type SpeakerRoleCheckResponse struct {
	SessionID        string                  `json:"session_id"`
	Required         bool                    `json:"required"`
	Status           string                  `json:"status"`
	Method           string                  `json:"method"`
	ExpectedSpeakers int                     `json:"expected_speakers"`
	TargetRoles      []string                `json:"target_roles"`
	Instructions     []string                `json:"instructions,omitempty"`
	Samples          []SpeakerRoleSampleInfo `json:"samples,omitempty"`
}

type SpeakerRoleSampleInfo struct {
	Role         string `json:"role"`
	Status       string `json:"status"`
	FileName     string `json:"file_name,omitempty"`
	MimeType     string `json:"mime_type,omitempty"`
	UploadedAtMs int64  `json:"uploaded_at_ms,omitempty"`
}

// TriggerPipelineRequest mirrors RunPipelineRequest from the Python route.
type TriggerPipelineRequest struct {
	SessionID    string                   `json:"session_id"`
	PatientID    string                   `json:"patient_id"`
	DoctorID     string                   `json:"doctor_id"`
	IsNewPatient bool                     `json:"is_new_patient"`
	Segments     []TranscriptSegmentInput `json:"segments"`
}

type TranscriptSegmentInput struct {
	Start       float64           `json:"start"`
	End         float64           `json:"end"`
	Speaker     string            `json:"speaker"`
	RawText     string            `json:"raw_text"`
	CleanedText string            `json:"cleaned_text,omitempty"`
	Confidence  SegmentConfidence `json:"confidence,omitempty"`
}

// SegmentConfidence accepts either a JSON string or number and normalizes it
// to the string representation expected by the downstream Python pipeline.
type SegmentConfidence string

func (c *SegmentConfidence) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		*c = ""
		return nil
	}

	var asString string
	if err := json.Unmarshal(data, &asString); err == nil {
		*c = SegmentConfidence(asString)
		return nil
	}

	var asNumber float64
	if err := json.Unmarshal(data, &asNumber); err == nil {
		*c = SegmentConfidence(strconv.FormatFloat(asNumber, 'f', -1, 64))
		return nil
	}

	return fmt.Errorf("invalid confidence value: %s", string(data))
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
	Patient     *entity.Patient   `json:"patient"`
	LabTrends   []entity.LabTrend `json:"lab_trends"`
	RiskScore   *entity.RiskScore `json:"risk_score"`
	RecordCount int               `json:"record_count"`
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
	Answer        string           `json:"answer"`
	Confidence    float64          `json:"confidence"`
	LowConfidence bool             `json:"low_confidence"`
	Disclaimer    *string          `json:"disclaimer,omitempty"`
	Sources       []map[string]any `json:"sources"`
}
