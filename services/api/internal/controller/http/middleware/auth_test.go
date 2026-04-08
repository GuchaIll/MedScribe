package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

type stubAuthUseCase struct {
	validateFn func(context.Context, string) (*usecase.Claims, error)
}

func (s *stubAuthUseCase) Register(context.Context, usecase.RegisterRequest) (*entity.User, error) {
	return nil, nil
}
func (s *stubAuthUseCase) Login(context.Context, usecase.LoginRequest) (*usecase.LoginResponse, error) {
	return nil, nil
}
func (s *stubAuthUseCase) GetProfile(context.Context, string) (*entity.User, error) {
	return nil, nil
}
func (s *stubAuthUseCase) ValidateToken(ctx context.Context, token string) (*usecase.Claims, error) {
	if s.validateFn != nil {
		return s.validateFn(ctx, token)
	}
	return &usecase.Claims{UserID: "u1", Role: "doctor"}, nil
}

func TestJWTAuth(t *testing.T) {
	t.Parallel()

	nextOK := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		claims := ClaimsFromContext(r.Context())
		if claims == nil || claims.UserID != "u1" {
			t.Fatalf("missing claims in context")
		}
		w.WriteHeader(http.StatusNoContent)
	})

	t.Run("missing bearer header", func(t *testing.T) {
		h := JWTAuth(&stubAuthUseCase{}, zap.NewNop())(nextOK)
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401, got %d", rec.Code)
		}
	})

	t.Run("invalid token", func(t *testing.T) {
		h := JWTAuth(&stubAuthUseCase{
			validateFn: func(context.Context, string) (*usecase.Claims, error) {
				return nil, entity.ErrUnauthorized
			},
		}, zap.NewNop())(nextOK)
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("Authorization", "Bearer bad")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401, got %d", rec.Code)
		}
	})

	t.Run("valid token", func(t *testing.T) {
		h := JWTAuth(&stubAuthUseCase{}, zap.NewNop())(nextOK)
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("Authorization", "Bearer good")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusNoContent {
			t.Fatalf("expected next handler to run, got %d", rec.Code)
		}
	})
}

func TestRequireRoleMiddleware(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name       string
		claims     *usecase.Claims
		required   string
		wantStatus int
	}{
		{
			name:       "no claims",
			claims:     nil,
			required:   "doctor",
			wantStatus: http.StatusUnauthorized,
		},
		{
			name:       "insufficient role",
			claims:     &usecase.Claims{Role: "nurse"},
			required:   "doctor",
			wantStatus: http.StatusForbidden,
		},
		{
			name:       "sufficient role",
			claims:     &usecase.Claims{Role: "admin"},
			required:   "doctor",
			wantStatus: http.StatusNoContent,
		},
	}

	for _, tc := range tests {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()

			next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(http.StatusNoContent)
			})
			h := RequireRole(tc.required)(next)

			req := httptest.NewRequest(http.MethodGet, "/", nil)
			if tc.claims != nil {
				req = req.WithContext(context.WithValue(req.Context(), claimsKey, tc.claims))
			}

			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			if rec.Code != tc.wantStatus {
				t.Fatalf("expected status %d, got %d", tc.wantStatus, rec.Code)
			}
		})
	}
}
