// Package entity contains the core domain types for the MedScribe API gateway.
// These types are independent of any persistence or transport layer.
package entity

import "time"

// SessionStatus mirrors the SessionStatus enum in server/app/database/models.py.
type SessionStatus string

const (
	SessionStatusActive        SessionStatus = "active"
	SessionStatusCompleted     SessionStatus = "completed"
	SessionStatusError         SessionStatus = "error"
	SessionStatusReviewPending SessionStatus = "review_pending"
)

// Session represents a single clinical encounter / transcription session.
type Session struct {
	ID              string
	PatientID       *string // nullable — set during pipeline trigger, not session start
	DoctorID        string
	Status          SessionStatus
	VisitType       string
	WorkflowState   *string // JSON blob — Go orchestrator checkpoint
	CheckpointID    *string
	AudioFilePath   *string
	DurationSeconds *int
	StartedAt       time.Time
	CompletedAt     *time.Time
	CreatedAt       time.Time
	UpdatedAt       time.Time
}

// Document is an uploaded file that has been through the OCR pipeline.
type Document struct {
	ID                       string           `json:"document_id"`
	SessionID                string           `json:"session_id,omitempty"`
	OriginalName             string           `json:"original_name"`
	StoragePath              string           `json:"path,omitempty"`
	MimeType                 string           `json:"content_type,omitempty"`
	ExtractedText            string           `json:"extracted_text,omitempty"`
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

// QueueItem is a proposed modification awaiting physician review.
type QueueItem struct {
	ID         string
	SessionID  string
	FieldPath  string
	OldValue   string
	NewValue   string
	Reason     string
	Status     string // pending | approved | rejected
	CreatedAt  time.Time
	ReviewedAt *time.Time
}

// PipelineStatus is the runtime state of the 16-node clinical pipeline,
// read from Redis hash pipeline:{sessionID}.
type PipelineStatus struct {
	SessionID           string         `json:"session_id"`
	PipelineID          string         `json:"pipeline_id"`
	Status              string         `json:"status"` // pending | running | completed | failed
	CurrentNode         string         `json:"current_node,omitempty"`
	StartedAtMs         int64          `json:"started_at_ms"`
	CompletedAtMs       *int64         `json:"completed_at_ms,omitempty"`
	Error               string         `json:"error,omitempty"`
	Message             string         `json:"message,omitempty"`
	ClinicalNote        string         `json:"clinical_note,omitempty"`
	StructuredRecord    map[string]any `json:"structured_record,omitempty"`
	ClinicalSuggestions map[string]any `json:"clinical_suggestions,omitempty"`
	ValidationReport    map[string]any `json:"validation_report,omitempty"`
	Nodes               []NodeProgress `json:"nodes,omitempty"`
}

// NodeProgress is a single node's execution summary within a pipeline run.
type NodeProgress struct {
	Name          string  `json:"name"`
	Label         string  `json:"label,omitempty"`
	Phase         string  `json:"phase,omitempty"`
	Status        string  `json:"status"`
	StartedAtMs   int64   `json:"started_at_ms"`
	CompletedAtMs *int64  `json:"completed_at_ms,omitempty"`
	DurationMs    float64 `json:"duration_ms"`
	Detail        string  `json:"detail,omitempty"`
}

// MedicalRecord is the structured output of a completed pipeline run.
type MedicalRecord struct {
	ID             string
	PatientID      string
	SessionID      string
	TemplateType   string
	StructuredData map[string]any
	ClinicalNote   string
	IsFinalized    bool
	Version        int
	CreatedAt      time.Time
	FinalizedAt    *time.Time
}

// TranscriptTurn is a single incremental transcription event stored in-session.
// Stored in the sessions.workflow_state JSON or a dedicated transcript table.
type TranscriptTurn struct {
	SessionID string
	Speaker   string
	Text      string
	Timestamp time.Time
}
