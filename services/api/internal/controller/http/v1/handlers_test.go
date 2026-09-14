package v1

import (
	"bytes"
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
	processFn          func(context.Context, usecase.TranscribeRequest) (*usecase.TranscribeResponse, error)
	uploadAudioFn      func(context.Context, string, usecase.UploadAudioSegmentRequest, *multipart.FileHeader, multipart.File) (*usecase.UploadAudioSegmentResponse, error)
	uploadRoleSampleFn func(context.Context, string, usecase.UploadSpeakerRoleSampleRequest, *multipart.FileHeader, multipart.File) (*usecase.SpeakerRoleCheckResponse, error)
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
	return &usecase.TranscribeResponse{SessionID: req.SessionID, TurnsStored: 1, Speaker: req.Speaker, Source: "gateway"}, nil
}
func (s *stubSessionUC) UploadAudioSegment(
	ctx context.Context,
	sessionID string,
	req usecase.UploadAudioSegmentRequest,
	fh *multipart.FileHeader,
	file multipart.File,
) (*usecase.UploadAudioSegmentResponse, error) {
	if s.uploadAudioFn != nil {
		return s.uploadAudioFn(ctx, sessionID, req, fh, file)
	}
	return &usecase.UploadAudioSegmentResponse{
		SessionID: sessionID,
		SegmentID: req.SegmentID,
		Accepted:  true,
		Status:    "queued",
	}, nil
}
func (s *stubSessionUC) UploadSpeakerRoleSample(
	ctx context.Context,
	sessionID string,
	req usecase.UploadSpeakerRoleSampleRequest,
	fh *multipart.FileHeader,
	file multipart.File,
) (*usecase.SpeakerRoleCheckResponse, error) {
	if s.uploadRoleSampleFn != nil {
		return s.uploadRoleSampleFn(ctx, sessionID, req, fh, file)
	}
	return &usecase.SpeakerRoleCheckResponse{
		SessionID:        sessionID,
		Required:         true,
		Status:           "collecting",
		Method:           "reference_voice_samples",
		ExpectedSpeakers: 2,
		TargetRoles:      []string{"Clinician", "Patient"},
	}, nil
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
func (s *stubSessionUC) GetLiveTranscript(context.Context, string) (*usecase.LiveTranscriptResponse, error) {
	return &usecase.LiveTranscriptResponse{}, nil
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
			return &usecase.TranscribeResponse{SessionID: req.SessionID, Speaker: req.Speaker, TurnsStored: 1, Source: "gateway"}, nil
		},
	}, zap.NewNop(), false)

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

func TestSessionUploadAudioSegmentUsesMultipartMetadata(t *testing.T) {
	var (
		seenSessionID string
		seenReq       usecase.UploadAudioSegmentRequest
		seenFilename  string
	)
	h := NewSessionHandler(&stubSessionUC{
		uploadAudioFn: func(
			_ context.Context,
			sessionID string,
			req usecase.UploadAudioSegmentRequest,
			fh *multipart.FileHeader,
			_ multipart.File,
		) (*usecase.UploadAudioSegmentResponse, error) {
			seenSessionID = sessionID
			seenReq = req
			if fh != nil {
				seenFilename = fh.Filename
			}
			return &usecase.UploadAudioSegmentResponse{
				SessionID: sessionID,
				SegmentID: req.SegmentID,
				Accepted:  true,
				Status:    "queued",
			}, nil
		},
	}, zap.NewNop(), false)

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	if err := writer.WriteField("segment_id", "seg-1"); err != nil {
		t.Fatalf("write segment_id: %v", err)
	}
	if err := writer.WriteField("started_at_ms", "100"); err != nil {
		t.Fatalf("write started_at_ms: %v", err)
	}
	if err := writer.WriteField("ended_at_ms", "250"); err != nil {
		t.Fatalf("write ended_at_ms: %v", err)
	}
	if err := writer.WriteField("sample_rate_hz", "16000"); err != nil {
		t.Fatalf("write sample_rate_hz: %v", err)
	}
	if err := writer.WriteField("mime_type", "audio/wav"); err != nil {
		t.Fatalf("write mime_type: %v", err)
	}
	if err := writer.WriteField("optimistic_text", "hello there"); err != nil {
		t.Fatalf("write optimistic_text: %v", err)
	}
	if err := writer.WriteField("optimistic_speaker", "Patient"); err != nil {
		t.Fatalf("write optimistic_speaker: %v", err)
	}
	part, err := writer.CreateFormFile("file", "segment.wav")
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	if _, err = part.Write([]byte("wav-bytes")); err != nil {
		t.Fatalf("write form file: %v", err)
	}
	if err = writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/api/session/s123/audio-segment", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req = withURLParam(req, "sessionID", "s123")
	rec := httptest.NewRecorder()

	h.UploadAudioSegment(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rec.Code, rec.Body.String())
	}
	if seenSessionID != "s123" || seenReq.SegmentID != "seg-1" || seenReq.SampleRateHz != 16000 || seenReq.OptimisticSpeaker != "Patient" || seenFilename != "segment.wav" {
		t.Fatalf("unexpected upload request: session=%q req=%+v file=%q", seenSessionID, seenReq, seenFilename)
	}
}

func TestSessionUploadSpeakerRoleSampleUsesURLParamAndMultipartRole(t *testing.T) {
	var (
		seenSessionID string
		seenReq       usecase.UploadSpeakerRoleSampleRequest
		seenFilename  string
	)
	h := NewSessionHandler(&stubSessionUC{
		uploadRoleSampleFn: func(
			_ context.Context,
			sessionID string,
			req usecase.UploadSpeakerRoleSampleRequest,
			fh *multipart.FileHeader,
			_ multipart.File,
		) (*usecase.SpeakerRoleCheckResponse, error) {
			seenSessionID = sessionID
			seenReq = req
			if fh != nil {
				seenFilename = fh.Filename
			}
			return &usecase.SpeakerRoleCheckResponse{
				SessionID:        sessionID,
				Required:         true,
				Status:           "collecting",
				Method:           "reference_voice_samples",
				ExpectedSpeakers: 2,
				TargetRoles:      []string{"Clinician", "Patient"},
			}, nil
		},
	}, zap.NewNop(), false)

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	if err := writer.WriteField("role", "clinician"); err != nil {
		t.Fatalf("write field: %v", err)
	}
	part, err := writer.CreateFormFile("file", "sample.webm")
	if err != nil {
		t.Fatalf("create form file: %v", err)
	}
	if _, err = part.Write([]byte("audio-bytes")); err != nil {
		t.Fatalf("write form file: %v", err)
	}
	if err = writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}

	req := httptest.NewRequest(http.MethodPost, "/api/session/s123/speaker-role-check", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req = withURLParam(req, "sessionID", "s123")
	rec := httptest.NewRecorder()

	h.UploadSpeakerRoleSample(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rec.Code, rec.Body.String())
	}
	if seenSessionID != "s123" || seenReq.Role != "clinician" || seenFilename != "sample.webm" {
		t.Fatalf("unexpected request forwarded: session=%q req=%+v file=%q", seenSessionID, seenReq, seenFilename)
	}
}

func TestSessionTriggerPipelineAcceptsNumericConfidence(t *testing.T) {
	var seenReq usecase.TriggerPipelineRequest
	h := NewSessionHandler(&stubSessionUC{
		processFn: nil,
	}, zap.NewNop(), false)
	h.sessions = &stubSessionUCWithPipeline{
		triggerFn: func(_ context.Context, req usecase.TriggerPipelineRequest) (*usecase.TriggerPipelineResponse, error) {
			seenReq = req
			return &usecase.TriggerPipelineResponse{Accepted: true, PipelineID: "p1"}, nil
		},
	}

	req := httptest.NewRequest(http.MethodPost, "/api/session/s123/pipeline", strings.NewReader(`{
		"session_id":"s123",
		"patient_id":"p1",
		"doctor_id":"d1",
		"segments":[{"start":0,"end":1.2,"speaker":"Clinician","raw_text":"hello","confidence":0.91}]
	}`))
	req = withURLParam(req, "sessionID", "s123")
	rec := httptest.NewRecorder()

	h.TriggerPipeline(rec, req)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d body=%s", rec.Code, rec.Body.String())
	}
	if len(seenReq.Segments) != 1 || seenReq.Segments[0].Confidence != usecase.SegmentConfidence("0.91") {
		t.Fatalf("unexpected request forwarded to usecase: %+v", seenReq)
	}
}

type stubSessionUCWithPipeline struct {
	stubSessionUC
	triggerFn func(context.Context, usecase.TriggerPipelineRequest) (*usecase.TriggerPipelineResponse, error)
}

func (s *stubSessionUCWithPipeline) TriggerPipeline(ctx context.Context, req usecase.TriggerPipelineRequest) (*usecase.TriggerPipelineResponse, error) {
	if s.triggerFn != nil {
		return s.triggerFn(ctx, req)
	}
	return s.stubSessionUC.TriggerPipeline(ctx, req)
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
