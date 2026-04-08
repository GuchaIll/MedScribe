package v1

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

// AssistantHandler handles POST /api/session/{sessionID}/assistant.
type AssistantHandler struct {
	assistant usecase.AssistantUseCase
	log       *zap.Logger
}

func NewAssistantHandler(assistant usecase.AssistantUseCase, log *zap.Logger) *AssistantHandler {
	return &AssistantHandler{assistant: assistant, log: log}
}

func (h *AssistantHandler) Query(w http.ResponseWriter, r *http.Request) {
	var req struct {
		PatientID string `json:"patient_id"`
		Question  string `json:"question"`
	}
	if !bindJSON(w, r, &req) {
		return
	}
	if len(req.Question) < 3 {
		writeJSONError(w, http.StatusBadRequest, "question must be at least 3 characters")
		return
	}

	sessionID := claimSessionID(r)
	resp, err := h.assistant.Query(r.Context(), sessionID, req.PatientID, req.Question)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// claimSessionID reads the sessionID URL param set by chi.
func claimSessionID(r *http.Request) string {
	return chi.URLParam(r, "sessionID")
}
