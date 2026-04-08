package entity

import "time"

// UserRole mirrors the UserRole enum in server/app/database/models.py.
type UserRole string

const (
	UserRoleDoctor           UserRole = "doctor"
	UserRoleNurse            UserRole = "nurse"
	UserRoleAdmin            UserRole = "admin"
	UserRoleMedicalAssistant UserRole = "medical_assistant"
)

// User represents an authenticated clinical user.
type User struct {
	ID             string
	Username       string
	Email          string
	HashedPassword string
	FullName       string
	Role           UserRole
	Permissions    []string // additional permissions beyond role
	IsActive       bool
	LastLogin      *time.Time
	CreatedAt      time.Time
	UpdatedAt      time.Time
}

// Patient holds core demographics.
// Sensitive fields (full_name, dob) are stored AES-256-GCM encrypted in
// encrypted_demographics when at rest in PostgreSQL.
type Patient struct {
	ID                    string
	MRN                   string // Medical Record Number — unique
	FullName              string
	DOB                   time.Time
	Age                   *int
	Sex                   *string
	EncryptedDemographics *string // AES-256-GCM encrypted JSON blob
	CreatedBy             *string
	IsActive              bool
	CreatedAt             time.Time
	UpdatedAt             time.Time
}

// LabTrend is a serialized trend analysis from the patient model.
type LabTrend struct {
	TestName   string    `json:"test_name"`
	Values     []float64 `json:"values"`
	Timestamps []int64   `json:"timestamps_ms"`
	Trend      string    `json:"trend"` // improving | stable | worsening
	Min        float64   `json:"min"`
	Max        float64   `json:"max"`
	Latest     float64   `json:"latest"`
}

// RiskScore is the composite clinical risk score for a patient.
type RiskScore struct {
	PatientID  string             `json:"patient_id"`
	Score      float64            `json:"score"`
	Level      string             `json:"level"` // low | moderate | high | critical
	Factors    []string           `json:"factors"`
	Components map[string]float64 `json:"components"`
	ComputedAt time.Time          `json:"computed_at"`
}
