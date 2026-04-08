package v1

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"
)

// RecordsHandler handles /api/records/* routes.
//
// Phase 1: These are thin stubs — full record generation logic lives in the
// Go orchestrator (services/orchestrator/). The API gateway proxies requests
// to the orchestrator via gRPC once Phase 2 is complete.
type RecordsHandler struct {
	log *zap.Logger
}

func NewRecordsHandler(log *zap.Logger) *RecordsHandler {
	return &RecordsHandler{log: log}
}

var availableTemplates = []map[string]any{
	{"name": "soap", "description": "SOAP Note", "formats": []string{"html", "pdf", "text"}},
	{"name": "discharge", "description": "Discharge Summary", "formats": []string{"html", "pdf", "text"}},
	{"name": "consultation", "description": "Consultation Note", "formats": []string{"html", "pdf", "text"}},
	{"name": "progress", "description": "Progress Note", "formats": []string{"html", "pdf", "text"}},
}

func (h *RecordsHandler) Generate(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Record              map[string]any `json:"record"`
		Template            string         `json:"template"`
		ClinicalSuggestions map[string]any `json:"clinical_suggestions"`
		Format              string         `json:"format"`
	}
	req.Template = "soap"
	req.Format = "html"
	if !bindJSON(w, r, &req) {
		return
	}
	// TODO Phase 2: proxy to orchestrator gRPC GenerateRecord RPC.
	writeJSONError(w, http.StatusNotImplemented, "record generation not yet available — Phase 2")
}

func (h *RecordsHandler) Preview(w http.ResponseWriter, r *http.Request) {
	writeJSONError(w, http.StatusNotImplemented, "not yet implemented — Phase 2")
}

func (h *RecordsHandler) Regenerate(w http.ResponseWriter, r *http.Request) {
	writeJSONError(w, http.StatusNotImplemented, "not yet implemented — Phase 2")
}

func (h *RecordsHandler) Commit(w http.ResponseWriter, r *http.Request) {
	writeJSONError(w, http.StatusNotImplemented, "not yet implemented — Phase 2")
}

func (h *RecordsHandler) History(w http.ResponseWriter, r *http.Request) {
	// TODO Phase 2: call patient usecase GetHistoryRecords once wired.
	_ = chi.URLParam(r, "patientID")
	writeJSONError(w, http.StatusNotImplemented, "not yet implemented — Phase 2")
}

func (h *RecordsHandler) ListTemplates(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"templates": availableTemplates})
}
