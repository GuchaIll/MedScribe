// Package v1 contains the HTTP handler implementations for API version 1.
// Each handler translates HTTP primitives into UseCase calls and JSON responses.
// No business logic lives here; all decisions belong in the UseCase layer.
package v1

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

// SessionHandler handles /api/session/* routes.
type SessionHandler struct {
	sessions usecase.SessionUseCase
	log      *zap.Logger
}

// NewSessionHandler creates a new SessionHandler.
func NewSessionHandler(sessions usecase.SessionUseCase, log *zap.Logger) *SessionHandler {
	return &SessionHandler{sessions: sessions, log: log}
}

func (h *SessionHandler) Start(w http.ResponseWriter, r *http.Request) {
	userID := claimUserID(r)
	if userID == "" {
		writeJSONError(w, http.StatusUnauthorized, "missing user identity")
		return
	}
	resp, err := h.sessions.StartSession(r.Context(), userID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, resp)
}

func (h *SessionHandler) End(w http.ResponseWriter, r *http.Request) {
	resp, err := h.sessions.EndSession(r.Context(), chi.URLParam(r, "sessionID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *SessionHandler) Transcribe(w http.ResponseWriter, r *http.Request) {
	var req usecase.TranscribeRequest
	if !bindJSON(w, r, &req) {
		return
	}
	req.SessionID = chi.URLParam(r, "sessionID")
	resp, err := h.sessions.ProcessTranscription(r.Context(), req)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *SessionHandler) TriggerPipeline(w http.ResponseWriter, r *http.Request) {
	var req usecase.TriggerPipelineRequest
	if !bindJSON(w, r, &req) {
		return
	}
	req.SessionID = chi.URLParam(r, "sessionID")
	resp, err := h.sessions.TriggerPipeline(r.Context(), req)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, resp)
}

func (h *SessionHandler) PipelineStatus(w http.ResponseWriter, r *http.Request) {
	status, err := h.sessions.GetPipelineStatus(r.Context(), chi.URLParam(r, "sessionID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, status)
}

func (h *SessionHandler) UploadDocument(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(64 << 20); err != nil { // 64 MB limit
		writeJSONError(w, http.StatusBadRequest, "request body too large or not multipart")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "field 'file' is missing")
		return
	}
	defer file.Close()

	doc, err := h.sessions.UploadDocument(r.Context(), chi.URLParam(r, "sessionID"), header, file)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, doc)
}

func (h *SessionHandler) GetRecord(w http.ResponseWriter, r *http.Request) {
	rec, err := h.sessions.GetRecord(r.Context(), chi.URLParam(r, "sessionID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rec)
}

func (h *SessionHandler) GetDocuments(w http.ResponseWriter, r *http.Request) {
	docs, err := h.sessions.GetDocuments(r.Context(), chi.URLParam(r, "sessionID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"documents": docs})
}

func (h *SessionHandler) GetQueue(w http.ResponseWriter, r *http.Request) {
	items, err := h.sessions.GetQueue(r.Context(), chi.URLParam(r, "sessionID"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"queue": items})
}

func (h *SessionHandler) UpdateQueueItem(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Status string `json:"status"`
	}
	if !bindJSON(w, r, &body) {
		return
	}
	item, err := h.sessions.UpdateQueueItem(
		r.Context(),
		chi.URLParam(r, "sessionID"),
		chi.URLParam(r, "itemID"),
		body.Status,
	)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, item)
}
