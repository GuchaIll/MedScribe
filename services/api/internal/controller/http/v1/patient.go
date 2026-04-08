package v1

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

// PatientHandler handles /api/patient/* routes.
type PatientHandler struct {
	patients usecase.PatientUseCase
	log      *zap.Logger
}

func NewPatientHandler(patients usecase.PatientUseCase, log *zap.Logger) *PatientHandler {
	return &PatientHandler{patients: patients, log: log}
}

func (h *PatientHandler) GetProfile(w http.ResponseWriter, r *http.Request) {
	profile, err := h.patients.GetProfile(r.Context(), chi.URLParam(r, "patientID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, profile)
}

func (h *PatientHandler) GetLabTrends(w http.ResponseWriter, r *http.Request) {
	var testName *string
	if tn := r.URL.Query().Get("test_name"); tn != "" {
		testName = &tn
	}
	trends, err := h.patients.GetLabTrends(r.Context(), chi.URLParam(r, "patientID"), testName)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"patient_id": chi.URLParam(r, "patientID"),
		"trends":     trends,
	})
}

func (h *PatientHandler) GetRiskScore(w http.ResponseWriter, r *http.Request) {
	score, err := h.patients.GetRiskScore(r.Context(), chi.URLParam(r, "patientID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, score)
}
