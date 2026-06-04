package usecase

import (
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"strings"

	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/repo"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

type assistantUseCase struct {
	redis    redis.Cmdable
	sessions repo.SessionRepository
	patients repo.PatientRepository
	log      *zap.Logger
}

func NewAssistantUseCase(
	redisClient redis.Cmdable,
	sessions repo.SessionRepository,
	patients repo.PatientRepository,
	log *zap.Logger,
) AssistantUseCase {
	return &assistantUseCase{
		redis:    redisClient,
		sessions: sessions,
		patients: patients,
		log:      log,
	}
}

func (uc *assistantUseCase) Query(
	ctx context.Context,
	sessionID, patientID, question string,
) (*AssistantResponse, error) {
	question = strings.TrimSpace(question)
	if len(question) < 3 {
		return nil, entity.ErrInvalidInput
	}

	if sessionID != "" {
		if cached, err := uc.getCachedAssistantResponse(ctx, sessionID, question); err == nil && cached != nil {
			return cached, nil
		}
	}

	activeState, err := readActiveSessionState(ctx, uc.redis, sessionID)
	if err != nil {
		return nil, err
	}

	var patient *entity.Patient
	if patientID != "" {
		patient, err = uc.patients.GetByID(ctx, patientID)
		if err != nil && err != entity.ErrNotFound {
			return nil, err
		}
	}

	resp := uc.buildAssistantResponse(ctx, sessionID, question, activeState, patient)
	if sessionID != "" {
		if err = uc.cacheAssistantResponse(ctx, sessionID, question, resp); err != nil {
			uc.log.Warn("assistant cache write failed",
				zap.String("session_id", sessionID),
				zap.Error(err),
			)
		}
	}
	return resp, nil
}

func (uc *assistantUseCase) buildAssistantResponse(
	ctx context.Context,
	sessionID, question string,
	activeState *activeSessionState,
	patient *entity.Patient,
) *AssistantResponse {
	lowerQuestion := strings.ToLower(question)
	sources := make([]map[string]any, 0, 4)

	if resp := answerFromActiveTranscript(lowerQuestion, activeState, &sources); resp != nil {
		return resp
	}
	if resp := answerFromPendingDocuments(lowerQuestion, activeState, &sources); resp != nil {
		return resp
	}
	if resp := answerFromPatientFacts(lowerQuestion, patient, &sources); resp != nil {
		return resp
	}

	recordSummary := ""
	if sessionID != "" {
		if rec, err := uc.sessions.GetRecord(ctx, sessionID); err == nil && rec != nil {
			recordSummary = summarizeRecord(rec)
			sources = append(sources, map[string]any{
				"type":       "session_record",
				"session_id": sessionID,
				"record_id":  rec.ID,
			})
		}
	}

	parts := make([]string, 0, 4)
	if patient != nil {
		parts = append(parts, fmt.Sprintf("Patient: %s", patient.FullName))
	}
	if activeState != nil && len(activeState.RecentTranscript) > 0 {
		parts = append(parts, fmt.Sprintf("Recent session context: %s", summarizeTranscript(activeState.RecentTranscript, 4)))
		sources = append(sources, map[string]any{
			"type":       "redis_active_session",
			"session_id": activeState.SessionID,
			"turn_count": len(activeState.RecentTranscript),
			"buffered":   activeState.TranscriptTurnsBuffered,
			"status":     activeState.Status,
		})
	}
	if activeState != nil && len(activeState.PendingDocuments) > 0 {
		parts = append(parts, fmt.Sprintf("Pending uploads: %d", len(activeState.PendingDocuments)))
		sources = append(sources, map[string]any{
			"type":           "redis_pending_documents",
			"session_id":     activeState.SessionID,
			"document_count": len(activeState.PendingDocuments),
		})
	}
	if recordSummary != "" {
		parts = append(parts, fmt.Sprintf("Latest record: %s", recordSummary))
	}

	answer := "I could not find direct structured support for that question yet."
	lowConfidence := true
	if len(parts) > 0 {
		answer = strings.Join(parts, " ")
	}
	disclaimer := "Response is built from active session cache and available structured data; confirm against the final chart before sign-off."

	return &AssistantResponse{
		Answer:        answer,
		Confidence:    0.52,
		LowConfidence: lowConfidence,
		Disclaimer:    &disclaimer,
		Sources:       sources,
	}
}

func answerFromActiveTranscript(
	lowerQuestion string,
	activeState *activeSessionState,
	sources *[]map[string]any,
) *AssistantResponse {
	if activeState == nil || len(activeState.RecentTranscript) == 0 {
		return nil
	}
	if !containsAny(lowerQuestion, "transcript", "said", "discuss", "talk", "session", "what happened") {
		return nil
	}
	*sources = append(*sources, map[string]any{
		"type":       "redis_active_session",
		"session_id": activeState.SessionID,
		"turn_count": len(activeState.RecentTranscript),
	})
	return &AssistantResponse{
		Answer:        summarizeTranscript(activeState.RecentTranscript, 6),
		Confidence:    0.86,
		LowConfidence: false,
		Sources:       *sources,
	}
}

func answerFromPendingDocuments(
	lowerQuestion string,
	activeState *activeSessionState,
	sources *[]map[string]any,
) *AssistantResponse {
	if activeState == nil || len(activeState.PendingDocuments) == 0 {
		return nil
	}
	if !containsAny(lowerQuestion, "document", "upload", "ocr", "scan", "pdf") {
		return nil
	}

	names := make([]string, 0, len(activeState.PendingDocuments))
	for _, doc := range activeState.PendingDocuments {
		names = append(names, doc.OriginalName)
	}
	*sources = append(*sources, map[string]any{
		"type":          "redis_pending_documents",
		"session_id":    activeState.SessionID,
		"pending_count": len(activeState.PendingDocuments),
		"ocr_job_count": len(activeState.OCRJobs),
	})
	return &AssistantResponse{
		Answer:        fmt.Sprintf("%d document(s) are queued or pending OCR review: %s.", len(names), strings.Join(names, ", ")),
		Confidence:    0.89,
		LowConfidence: false,
		Sources:       *sources,
	}
}

func answerFromPatientFacts(
	lowerQuestion string,
	patient *entity.Patient,
	sources *[]map[string]any,
) *AssistantResponse {
	if patient == nil {
		return nil
	}
	var answer string
	switch {
	case containsAny(lowerQuestion, "name", "patient name"):
		answer = fmt.Sprintf("The patient is %s.", patient.FullName)
	case containsAny(lowerQuestion, "mrn", "medical record number"):
		answer = fmt.Sprintf("The patient's MRN is %s.", patient.MRN)
	case containsAny(lowerQuestion, "age", "old"):
		if patient.Age == nil {
			answer = fmt.Sprintf("The patient date of birth is %s.", patient.DOB.Format("2006-01-02"))
		} else {
			answer = fmt.Sprintf("The patient is %d years old.", *patient.Age)
		}
	case containsAny(lowerQuestion, "dob", "date of birth", "born"):
		answer = fmt.Sprintf("The patient's date of birth is %s.", patient.DOB.Format("2006-01-02"))
	case containsAny(lowerQuestion, "sex", "gender"):
		if patient.Sex != nil {
			answer = fmt.Sprintf("The recorded sex is %s.", *patient.Sex)
		}
	}
	if answer == "" {
		return nil
	}
	*sources = append(*sources, map[string]any{
		"type":       "patient_db",
		"patient_id": patient.ID,
	})
	return &AssistantResponse{
		Answer:        answer,
		Confidence:    0.97,
		LowConfidence: false,
		Sources:       *sources,
	}
}

func summarizeTranscript(turns []entity.TranscriptTurn, limit int) string {
	if len(turns) == 0 {
		return "No recent transcript is available."
	}
	if limit <= 0 || limit > len(turns) {
		limit = len(turns)
	}
	selected := turns[len(turns)-limit:]
	parts := make([]string, 0, len(selected))
	for _, turn := range selected {
		text := strings.TrimSpace(turn.Text)
		if len(text) > 120 {
			text = text[:117] + "..."
		}
		parts = append(parts, fmt.Sprintf("%s: %s", turn.Speaker, text))
	}
	return strings.Join(parts, " | ")
}

func summarizeRecord(record *entity.MedicalRecord) string {
	if record == nil {
		return ""
	}
	note := strings.TrimSpace(record.ClinicalNote)
	if note == "" {
		return fmt.Sprintf("%s record v%d", record.TemplateType, record.Version)
	}
	if len(note) > 160 {
		note = note[:157] + "..."
	}
	return note
}

func containsAny(question string, terms ...string) bool {
	for _, term := range terms {
		if strings.Contains(question, term) {
			return true
		}
	}
	return false
}

func (uc *assistantUseCase) getCachedAssistantResponse(
	ctx context.Context,
	sessionID, question string,
) (*AssistantResponse, error) {
	data, err := uc.redis.Get(ctx, assistantResponseKey(sessionID, question)).Bytes()
	if err != nil {
		if err == redis.Nil {
			return nil, nil
		}
		return nil, err
	}
	var resp AssistantResponse
	if err = json.Unmarshal(data, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (uc *assistantUseCase) cacheAssistantResponse(
	ctx context.Context,
	sessionID, question string,
	resp *AssistantResponse,
) error {
	payload, err := json.Marshal(resp)
	if err != nil {
		return err
	}
	return uc.redis.Set(ctx, assistantResponseKey(sessionID, question), payload, assistantResponseTTL).Err()
}

func assistantResponseKey(sessionID, question string) string {
	hash := fnv.New32a()
	_, _ = hash.Write([]byte(strings.ToLower(strings.TrimSpace(question))))
	return fmt.Sprintf("%s:%08x", assistantCachePrefix(sessionID), hash.Sum32())
}
