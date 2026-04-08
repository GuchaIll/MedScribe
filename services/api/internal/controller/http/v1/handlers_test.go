package v1

import (
	"context"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/usecase"
	"go.uber.org/zap"
)

type stubAuthUC struct {
	loginFn      func(context.Context, usecase.LoginRequest) (*usecase.LoginResponse, error)
	registerFn   func(context.Context, usecase.RegisterRequest) (*entity.User, error)
	getProfileFn func(context.Context, string) (*entity.User, error)
	validateFn   func(context.Context, string) (*usecase.Claims, error)
}

func (s *stubAuthUC) Register(ctx context.Context, req usecase.RegisterRequest) (*entity.User, error) {
	if s.registerFn != nil {
		return s.registerFn(ctx, req)
	}
	return &entity.User{ID: "u1"}, nil
}
func (s *stubAuthUC) Login(ctx context.Context, req usecase.LoginRequest) (*usecase.LoginResponse, error) {
	if s.loginFn != nil {
		return s.loginFn(ctx, req)
	}
	return &usecase.LoginResponse{AccessToken: "t"}, nil
}
func (s *stubAuthUC) GetProfile(ctx context.Context, userID string) (*entity.User, error) {
	if s.getProfileFn != nil {
		return s.getProfileFn(ctx, userID)
	}
	return &entity.User{ID: userID}, nil
}
func (s *stubAuthUC) ValidateToken(ctx context.Context, token string) (*usecase.Claims, error) {
	if s.validateFn != nil {
		return s.validateFn(ctx, token)
	}
	return &usecase.Claims{UserID: "u1"}, nil
}

type stubSessionUC struct {
	processFn func(context.Context, usecase.TranscribeRequest) (*usecase.TranscribeResponse, error)
}

func (s *stubSessionUC) StartSession(_ context.Context, _ string) (*usecase.SessionStartResponse, error) {
	return &usecase.SessionStartResponse{SessionID: "s1", Status: "active"}, nil
}
func (s *stubSessionUC) EndSession(context.Context, string) (*usecase.SessionEndResponse, error) {
	return &usecase.SessionEndResponse{SessionID: "s1", Status: "completed"}, nil
}
func (s *stubSessionUC) ProcessTranscription(ctx context.Context, req usecase.TranscribeRequest) (*usecase.TranscribeResponse, error) {
	if s.processFn != nil {
		return s.processFn(ctx, req)
	}
	return &usecase.TranscribeResponse{SessionID: req.SessionID, TurnsStored: 1, Speaker: req.Speaker}, nil
}
func (s *stubSessionUC) TriggerPipeline(context.Context, usecase.TriggerPipelineRequest) (*usecase.TriggerPipelineResponse, error) {
	return &usecase.TriggerPipelineResponse{Accepted: true, PipelineID: "p1"}, nil
}
func (s *stubSessionUC) GetPipelineStatus(context.Context, string) (*entity.PipelineStatus, error) {
	return &entity.PipelineStatus{Status: "pending"}, nil
}
func (s *stubSessionUC) UploadDocument(context.Context, string, *multipart.FileHeader, multipart.File) (*entity.Document, error) {
	return &entity.Document{ID: "d1"}, nil
}
func (s *stubSessionUC) GetRecord(context.Context, string) (*entity.MedicalRecord, error) {
	return &entity.MedicalRecord{ID: "r1"}, nil
}
func (s *stubSessionUC) GetDocuments(context.Context, string) ([]*entity.Document, error) {
	return []*entity.Document{}, nil
}
func (s *stubSessionUC) GetQueue(context.Context, string) ([]*entity.QueueItem, error) {
	return []*entity.QueueItem{}, nil
}
func (s *stubSessionUC) UpdateQueueItem(context.Context, string, string, string) (*entity.QueueItem, error) {
	return &entity.QueueItem{ID: "q1"}, nil
}

func withURLParam(r *http.Request, key, value string) *http.Request {
	ctx := chi.NewRouteContext()
	ctx.URLParams.Add(key, value)
	return r.WithContext(context.WithValue(r.Context(), chi.RouteCtxKey, ctx))
}

func TestAuthLoginStrictJSONAndErrorMapping(t *testing.T) {
	h := NewAuthHandler(&stubAuthUC{
		loginFn: func(_ context.Context, _ usecase.LoginRequest) (*usecase.LoginResponse, error) {
			return nil, entity.ErrUnauthorized
		},
	}, zap.NewNop())

	req := httptest.NewRequest(http.MethodPost, "/api/auth/login", strings.NewReader(`{"email":"a@b.c","password":"x","unknown":1}`))
	rec := httptest.NewRecorder()
	h.Login(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for unknown JSON field, got %d", rec.Code)
	}

	req = httptest.NewRequest(http.MethodPost, "/api/auth/login", strings.NewReader(`{"email":"a@b.c","password":"x"}`))
	rec = httptest.NewRecorder()
	h.Login(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 from mapped domain error, got %d", rec.Code)
	}
}

func TestSessionTranscribeUsesURLParam(t *testing.T) {
	var seenReq usecase.TranscribeRequest
	h := NewSessionHandler(&stubSessionUC{
		processFn: func(_ context.Context, req usecase.TranscribeRequest) (*usecase.TranscribeResponse, error) {
			seenReq = req
			return &usecase.TranscribeResponse{SessionID: req.SessionID, Speaker: req.Speaker, TurnsStored: 1}, nil
		},
	}, zap.NewNop())

	req := httptest.NewRequest(http.MethodPost, "/api/session/s123/transcribe", strings.NewReader(`{"text":"hello","speaker":"doctor"}`))
	req = withURLParam(req, "sessionID", "s123")
	rec := httptest.NewRecorder()

	h.Transcribe(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if seenReq.SessionID != "s123" || seenReq.Speaker != "doctor" {
		t.Fatalf("unexpected request forwarded to usecase: %+v", seenReq)
	}

	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	if out["session_id"] != "s123" {
		t.Fatalf("unexpected response body: %s", rec.Body.String())
	}
}

func TestWriteErrorMappings(t *testing.T) {
	cases := []struct {
		err  error
		want int
	}{
		{entity.ErrNotFound, http.StatusNotFound},
		{entity.ErrAlreadyExists, http.StatusConflict},
		{entity.ErrUnauthorized, http.StatusUnauthorized},
		{entity.ErrForbidden, http.StatusForbidden},
		{entity.ErrSessionClosed, http.StatusConflict},
		{entity.ErrInvalidInput, http.StatusBadRequest},
	}
	for _, tc := range cases {
		rec := httptest.NewRecorder()
		writeError(rec, tc.err)
		if rec.Code != tc.want {
			t.Fatalf("err=%v want=%d got=%d", tc.err, tc.want, rec.Code)
		}
	}
}
