package v1

import (
	"net/http"

	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

// AuthHandler handles /api/auth/* routes.
type AuthHandler struct {
	auth usecase.AuthUseCase
	log  *zap.Logger
}

// NewAuthHandler creates a new AuthHandler.
func NewAuthHandler(auth usecase.AuthUseCase, log *zap.Logger) *AuthHandler {
	return &AuthHandler{auth: auth, log: log}
}

func (h *AuthHandler) Register(w http.ResponseWriter, r *http.Request) {
	var req usecase.RegisterRequest
	if !bindJSON(w, r, &req) {
		return
	}
	user, err := h.auth.Register(r.Context(), req)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"user_id": user.ID,
		"message": "registered successfully",
	})
}

func (h *AuthHandler) Login(w http.ResponseWriter, r *http.Request) {
	var req usecase.LoginRequest
	if !bindJSON(w, r, &req) {
		return
	}
	resp, err := h.auth.Login(r.Context(), req)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (h *AuthHandler) GetProfile(w http.ResponseWriter, r *http.Request) {
	// JWTAuth middleware has already validated the token; use the subject claim
	// directly to prevent IDOR (insecure direct object reference).
	// TODO: allow ADMIN role to fetch any user's profile.
	user, err := h.auth.GetProfile(r.Context(), claimUserID(r))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, user)
}
