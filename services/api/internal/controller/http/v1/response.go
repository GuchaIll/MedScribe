package v1

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/medscribe/services/api/internal/controller/http/middleware"
	"github.com/medscribe/services/api/internal/entity"
)

// bindJSON decodes the JSON request body into dst. Writes HTTP 400 and returns
// false on any decode error. Strict mode (DisallowUnknownFields) is enabled to
// surface API contract mismatches early.
func bindJSON(w http.ResponseWriter, r *http.Request, dst any) bool {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		writeJSONError(w, http.StatusBadRequest, "invalid request body: "+err.Error())
		return false
	}
	return true
}

// writeJSON serializes v to JSON and sends it with the given HTTP status.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// writeJSONError sends a JSON error body with the given HTTP status and message.
func writeJSONError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

// writeError maps domain error sentinels from internal/entity to HTTP status
// codes. Unrecognised errors produce a 500 with a generic message so that
// internal details are not leaked to callers.
func writeError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, entity.ErrNotFound):
		writeJSONError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, entity.ErrAlreadyExists):
		writeJSONError(w, http.StatusConflict, err.Error())
	case errors.Is(err, entity.ErrUnauthorized):
		writeJSONError(w, http.StatusUnauthorized, err.Error())
	case errors.Is(err, entity.ErrForbidden):
		writeJSONError(w, http.StatusForbidden, err.Error())
	case errors.Is(err, entity.ErrSessionClosed):
		writeJSONError(w, http.StatusConflict, err.Error())
	case errors.Is(err, entity.ErrPipelineBusy):
		writeJSONError(w, http.StatusConflict, err.Error())
	case errors.Is(err, entity.ErrInvalidInput):
		writeJSONError(w, http.StatusBadRequest, err.Error())
	default:
		writeJSONError(w, http.StatusInternalServerError, "internal server error")
	}
}

// claimUserID extracts the subject (user_id) from the JWT claims placed in
// context by the JWTAuth middleware.
func claimUserID(r *http.Request) string {
	claims := middleware.ClaimsFromContext(r.Context())
	if claims == nil {
		return ""
	}
	return claims.UserID
}
