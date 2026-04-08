package httpcontroller

import (
	"context"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/medscribe/services/api/config"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/usecase"
	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"
)

type authUCStub struct{}

func (a *authUCStub) Register(context.Context, usecase.RegisterRequest) (*entity.User, error) {
	return &entity.User{ID: "u1"}, nil
}
func (a *authUCStub) Login(context.Context, usecase.LoginRequest) (*usecase.LoginResponse, error) {
	return &usecase.LoginResponse{AccessToken: "token"}, nil
}
func (a *authUCStub) GetProfile(context.Context, string) (*entity.User, error) {
	return &entity.User{ID: "u1"}, nil
}
func (a *authUCStub) ValidateToken(context.Context, string) (*usecase.Claims, error) {
	return &usecase.Claims{UserID: "u1", Role: "doctor"}, nil
}

type sessionUCStub struct{}

func (s *sessionUCStub) StartSession(_ context.Context, _ string) (*usecase.SessionStartResponse, error) {
	return &usecase.SessionStartResponse{SessionID: "s1", Status: "active"}, nil
}
func (s *sessionUCStub) EndSession(context.Context, string) (*usecase.SessionEndResponse, error) {
	return &usecase.SessionEndResponse{SessionID: "s1", Status: "completed"}, nil
}
func (s *sessionUCStub) ProcessTranscription(context.Context, usecase.TranscribeRequest) (*usecase.TranscribeResponse, error) {
	return &usecase.TranscribeResponse{SessionID: "s1", Speaker: "doctor", TurnsStored: 1}, nil
}
func (s *sessionUCStub) TriggerPipeline(context.Context, usecase.TriggerPipelineRequest) (*usecase.TriggerPipelineResponse, error) {
	return &usecase.TriggerPipelineResponse{Accepted: true, PipelineID: "p1"}, nil
}
func (s *sessionUCStub) GetPipelineStatus(context.Context, string) (*entity.PipelineStatus, error) {
	return &entity.PipelineStatus{Status: "pending"}, nil
}
func (s *sessionUCStub) UploadDocument(context.Context, string, *multipart.FileHeader, multipart.File) (*entity.Document, error) {
	return &entity.Document{ID: "d1"}, nil
}
func (s *sessionUCStub) GetRecord(context.Context, string) (*entity.MedicalRecord, error) {
	return &entity.MedicalRecord{ID: "r1"}, nil
}
func (s *sessionUCStub) GetDocuments(context.Context, string) ([]*entity.Document, error) {
	return nil, nil
}
func (s *sessionUCStub) GetQueue(context.Context, string) ([]*entity.QueueItem, error) {
	return nil, nil
}
func (s *sessionUCStub) UpdateQueueItem(context.Context, string, string, string) (*entity.QueueItem, error) {
	return &entity.QueueItem{ID: "q1"}, nil
}

type patientUCStub struct{}

func (p *patientUCStub) GetProfile(context.Context, string) (*usecase.PatientProfileResponse, error) {
	return &usecase.PatientProfileResponse{}, nil
}
func (p *patientUCStub) GetLabTrends(context.Context, string, *string) ([]entity.LabTrend, error) {
	return nil, nil
}
func (p *patientUCStub) GetRiskScore(context.Context, string) (*entity.RiskScore, error) {
	return &entity.RiskScore{}, nil
}
func (p *patientUCStub) GetHistoryRecords(context.Context, string, int, int) ([]*entity.MedicalRecord, error) {
	return nil, nil
}

type assistantUCStub struct{}

func (a *assistantUCStub) Query(context.Context, string, string, string) (*usecase.AssistantResponse, error) {
	return &usecase.AssistantResponse{Answer: "ok"}, nil
}

func TestRouterHealthAndProtectedRoute(t *testing.T) {
	cfg := &config.Config{
		CORS: config.CORSConfig{AllowedOrigins: []string{"http://localhost:3000"}},
	}
	h := Router(
		cfg,
		zap.NewNop(),
		prometheus.NewRegistry(),
		&authUCStub{},
		&sessionUCStub{},
		&patientUCStub{},
		&assistantUCStub{},
	)

	healthReq := httptest.NewRequest(http.MethodGet, "/health", nil)
	healthRec := httptest.NewRecorder()
	h.ServeHTTP(healthRec, healthReq)
	if healthRec.Code != http.StatusOK {
		t.Fatalf("expected /health 200, got %d", healthRec.Code)
	}

	protectedReq := httptest.NewRequest(http.MethodPost, "/api/session/start", nil)
	protectedRec := httptest.NewRecorder()
	h.ServeHTTP(protectedRec, protectedReq)
	if protectedRec.Code != http.StatusUnauthorized {
		t.Fatalf("expected protected route without auth to return 401, got %d", protectedRec.Code)
	}
}
