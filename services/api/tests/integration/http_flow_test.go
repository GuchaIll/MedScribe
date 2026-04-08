package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	miniredis "github.com/alicebob/miniredis/v2"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/medscribe/services/api/config"
	httpcontroller "github.com/medscribe/services/api/internal/controller/http"
	"github.com/medscribe/services/api/internal/entity"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
	"github.com/medscribe/services/api/internal/usecase"
	"github.com/medscribe/services/api/pkg/cache"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

type publisherOK struct{}

func (p *publisherOK) PublishJSON(context.Context, string, string, any) error { return nil }

type assistantStub struct{}

func (a *assistantStub) Query(context.Context, string, string, string) (*usecase.AssistantResponse, error) {
	return &usecase.AssistantResponse{Answer: "ok"}, nil
}

func setupRouter(t *testing.T, pool *pgxpool.Pool) (http.Handler, *redis.Client) {
	t.Helper()

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() {
		_ = rdb.Close()
		mr.Close()
	})

	userRepo := pgxrepo.NewUserRepo(pool)
	sessionRepo := pgxrepo.NewSessionRepo(pool)
	patientRepo := pgxrepo.NewPatientRepo(pool)

	authUC := usecase.NewAuthUseCase(userRepo, "integration-secret", time.Hour, zap.NewNop())
	sessionUC := usecase.NewSessionUseCase(sessionRepo, &publisherOK{}, rdb, cache.New(5*time.Second), "pipeline.trigger", zap.NewNop())
	patientUC := usecase.NewPatientUseCase(patientRepo, zap.NewNop())
	assistantUC := &assistantStub{}

	cfg := &config.Config{
		CORS: config.CORSConfig{AllowedOrigins: []string{"*"}},
	}

	router := httpcontroller.Router(
		cfg,
		zap.NewNop(),
		prometheus.NewRegistry(),
		authUC,
		sessionUC,
		patientUC,
		assistantUC,
	)
	return router, rdb
}

func doJSON(t *testing.T, srv *httptest.Server, method, path string, body any, token string) *http.Response {
	t.Helper()
	var payload []byte
	if body != nil {
		var err error
		payload, err = json.Marshal(body)
		if err != nil {
			t.Fatalf("marshal request body: %v", err)
		}
	}
	req, err := http.NewRequest(method, srv.URL+path, bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request %s %s: %v", method, path, err)
	}
	return resp
}

func decodeMap(t *testing.T, resp *http.Response) map[string]any {
	t.Helper()
	defer resp.Body.Close()
	var m map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&m); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return m
}

func TestHTTPAuthSessionPatientAndPipelineFlows(t *testing.T) {
	pool, ctx := setupPostgres(t)
	if pool == nil {
		return
	}

	// Sanity-check schema/repo compatibility before exercising HTTP flows.
	if _, err := pgxrepo.NewSessionRepo(pool).Create(ctx, &entity.Session{
		ID:        "sanity-session",
		Status:    entity.SessionStatusActive,
		StartedAt: time.Now().UTC(),
	}); err != nil {
		t.Fatalf("session repo sanity create failed: %v", err)
	}

	router, rdb := setupRouter(t, pool)
	srv := httptest.NewServer(router)
	defer srv.Close()

	registerResp := doJSON(t, srv, http.MethodPost, "/api/auth/register", map[string]any{
		"email":     "doctor@example.com",
		"password":  "Pass123!",
		"full_name": "Doctor One",
		"role":      "doctor",
	}, "")
	if registerResp.StatusCode != http.StatusCreated {
		t.Fatalf("expected register 201, got %d", registerResp.StatusCode)
	}

	loginResp := doJSON(t, srv, http.MethodPost, "/api/auth/login", map[string]any{
		"email": "doctor@example.com", "password": "Pass123!",
	}, "")
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("expected login 200, got %d", loginResp.StatusCode)
	}
	loginBody := decodeMap(t, loginResp)
	token, _ := loginBody["access_token"].(string)
	if token == "" {
		t.Fatalf("expected access token in login response")
	}

	profileNoAuth := doJSON(t, srv, http.MethodGet, "/api/auth/profile", nil, "")
	if profileNoAuth.StatusCode != http.StatusUnauthorized {
		t.Fatalf("expected profile without token 401, got %d", profileNoAuth.StatusCode)
	}
	_ = profileNoAuth.Body.Close()

	profileResp := doJSON(t, srv, http.MethodGet, "/api/auth/profile", nil, token)
	if profileResp.StatusCode != http.StatusOK {
		t.Fatalf("expected profile with token 200, got %d", profileResp.StatusCode)
	}
	_ = profileResp.Body.Close()

	startResp := doJSON(t, srv, http.MethodPost, "/api/session/start", nil, token)
	if startResp.StatusCode != http.StatusCreated {
		b, _ := io.ReadAll(startResp.Body)
		startResp.Body.Close()
		t.Fatalf("expected start session 201, got %d body=%s", startResp.StatusCode, string(b))
	}
	startBody := decodeMap(t, startResp)
	sessionID, _ := startBody["session_id"].(string)
	if sessionID == "" {
		t.Fatalf("expected session_id in start response")
	}

	transcribeResp := doJSON(t, srv, http.MethodPost, "/api/session/"+sessionID+"/transcribe", map[string]any{
		"text": "Patient has headache",
		"speaker": "doctor",
	}, token)
	if transcribeResp.StatusCode != http.StatusOK {
		t.Fatalf("expected transcribe 200, got %d", transcribeResp.StatusCode)
	}
	_ = transcribeResp.Body.Close()

	endResp := doJSON(t, srv, http.MethodPost, "/api/session/"+sessionID+"/end", nil, token)
	if endResp.StatusCode != http.StatusOK {
		t.Fatalf("expected first end 200, got %d", endResp.StatusCode)
	}
	_ = endResp.Body.Close()
	endAgainResp := doJSON(t, srv, http.MethodPost, "/api/session/"+sessionID+"/end", nil, token)
	if endAgainResp.StatusCode != http.StatusConflict {
		t.Fatalf("expected second end 409, got %d", endAgainResp.StatusCode)
	}
	_ = endAgainResp.Body.Close()

	_, err := pool.Exec(ctx, `
		INSERT INTO patients (id, mrn, full_name, dob, age)
		VALUES ('p1', 'MRN-100', 'Patient One', NOW(), 67)
	`)
	if err != nil {
		t.Fatalf("insert patient: %v", err)
	}
	_, err = pool.Exec(ctx, `
		INSERT INTO medical_records (id, patient_id, session_id, template_type, structured_data, clinical_note, is_finalized, version)
		VALUES ('r1', 'p1', $1, 'soap', '{"labs":[{"test_name":"A1c","value":8.2}]}'::jsonb, '', true, 1)
	`, sessionID)
	if err != nil {
		t.Fatalf("insert medical record: %v", err)
	}

	patientProfileResp := doJSON(t, srv, http.MethodGet, "/api/patient/p1/profile", nil, token)
	if patientProfileResp.StatusCode != http.StatusOK {
		t.Fatalf("expected patient profile 200, got %d", patientProfileResp.StatusCode)
	}
	_ = patientProfileResp.Body.Close()

	patientTrendsResp := doJSON(t, srv, http.MethodGet, "/api/patient/p1/lab-trends?test_name=A1c", nil, token)
	if patientTrendsResp.StatusCode != http.StatusOK {
		t.Fatalf("expected patient lab trends 200, got %d", patientTrendsResp.StatusCode)
	}
	_ = patientTrendsResp.Body.Close()

	status := entity.PipelineStatus{
		SessionID:  sessionID,
		PipelineID: "pipe1",
		Status:     "running",
	}
	b, _ := json.Marshal(status)
	if err = rdb.Set(ctx, "pipeline:"+sessionID, b, time.Hour).Err(); err != nil {
		t.Fatalf("seed redis status: %v", err)
	}
	pipelineStatusResp := doJSON(t, srv, http.MethodGet, "/api/session/"+sessionID+"/pipeline/status", nil, token)
	if pipelineStatusResp.StatusCode != http.StatusOK {
		t.Fatalf("expected pipeline status 200, got %d", pipelineStatusResp.StatusCode)
	}
	statusBody := decodeMap(t, pipelineStatusResp)
	gotStatus, _ := statusBody["status"].(string)
	if gotStatus == "" {
		gotStatus, _ = statusBody["Status"].(string)
	}
	if gotStatus != "running" {
		t.Fatalf("expected running status, got %+v", statusBody)
	}
}
