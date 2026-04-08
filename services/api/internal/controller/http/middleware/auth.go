// Package middleware provides chi-compatible HTTP middleware for the MedScribe
// API gateway: JWT authentication, structured request logging, and Prometheus metrics.
package middleware

import (
	"context"
	"net/http"

	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

// contextKey is an unexported type for request-context keys to prevent collisions.
type contextKey int

const (
	claimsKey contextKey = iota
)

// ClaimsFromContext retrieves the validated JWT claims stored by JWTAuth.
func ClaimsFromContext(ctx context.Context) *usecase.Claims {
	v, _ := ctx.Value(claimsKey).(*usecase.Claims)
	return v
}

// JWTAuth returns a middleware that validates Bearer tokens using authUC.
// On success it stores the Claims in the request context.
// On failure it writes 401 JSON and aborts the chain.
func JWTAuth(authUC usecase.AuthUseCase, log *zap.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			const prefix = "Bearer "
			authHeader := r.Header.Get("Authorization")
			if len(authHeader) <= len(prefix) || authHeader[:len(prefix)] != prefix {
				writeUnauthorized(w, "missing or malformed Authorization header")
				return
			}
			tokenStr := authHeader[len(prefix):]

			claims, err := authUC.ValidateToken(r.Context(), tokenStr)
			if err != nil {
				log.Debug("JWT validation failed", zap.Error(err))
				writeUnauthorized(w, "invalid or expired token")
				return
			}

			ctx := context.WithValue(r.Context(), claimsKey, claims)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// RequireRole returns a middleware that enforces a minimum role on a route.
// Call after JWTAuth so claims are guaranteed to be present.
func RequireRole(role string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			claims := ClaimsFromContext(r.Context())
			if claims == nil {
				writeUnauthorized(w, "no auth context")
				return
			}
			if !hasRole(claims.Role, role) {
				writeForbidden(w)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// hasRole checks whether claimedRole satisfies the required role.
// Hierarchy: admin > doctor > nurse > medical_assistant.
func hasRole(claimedRole, required string) bool {
	rank := map[string]int{
		"admin":             4,
		"doctor":            3,
		"nurse":             2,
		"medical_assistant": 1,
	}
	return rank[claimedRole] >= rank[required]
}

// ─── response helpers ─────────────────────────────────────────────────────────

func writeUnauthorized(w http.ResponseWriter, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	_, _ = w.Write([]byte(`{"error":"` + msg + `"}`))
}

func writeForbidden(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusForbidden)
	_, _ = w.Write([]byte(`{"error":"forbidden"}`))
}
