package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/textproto"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/usecase"
	"github.com/redis/go-redis/v9"
)

type authenticatedSessionEnv struct {
	ctx   context.Context
	pool  *pgxpool.Pool
	rdb   *redis.Client
	srv   *httptest.Server
	token string
}

type activeSessionSnapshot struct {
	Status                  string                  `json:"status"`
	CompletedAtMs           *int64                  `json:"completed_at_ms,omitempty"`
	TranscriptTurnsBuffered int                     `json:"transcript_turns_buffered,omitempty"`
	RecentTranscript        []entity.TranscriptTurn `json:"recent_transcript,omitempty"`
	PendingDocuments        []entity.Document       `json:"pending_documents,omitempty"`
	OCRJobs                 []ocrJobSnapshot        `json:"ocr_jobs,omitempty"`
}

type ocrJobSnapshot struct {
	JobID      string `json:"job_id"`
	DocumentID string `json:"document_id"`
	Status     string `json:"status"`
	QueuedAtMs int64  `json:"queued_at_ms"`
}

type ocrQueuedJob struct {
	JobID       string `json:"job_id"`
	JobType     string `json:"job_type"`
	Status      string `json:"status"`
	DocumentID  string `json:"document_id"`
	SessionID   string `json:"session_id"`
	StoragePath string `json:"storage_path"`
	MimeType    string `json:"mime_type"`
}

type workflowStateSnapshot struct {
	TranscriptTurns           []entity.TranscriptTurn `json:"transcript_turns"`
	TranscriptTurnCount       int                     `json:"transcript_turn_count"`
	TranscriptBufferFlushedAt string                  `json:"transcript_buffer_flushed_at"`
}

type documentListResponse struct {
	Documents []entity.Document `json:"documents"`
}

func newAuthenticatedSessionEnv(t *testing.T) *authenticatedSessionEnv {
	t.Helper()

	pool, ctx := setupPostgres(t)
	if pool == nil {
		return nil
	}

	router, rdb := setupRouter(t, pool)
	srv := httptest.NewServer(router)
	t.Cleanup(srv.Close)

	return &authenticatedSessionEnv{
		ctx:   ctx,
		pool:  pool,
		rdb:   rdb,
		srv:   srv,
		token: registerAndLoginDoctor(t, srv),
	}
}

func registerAndLoginDoctor(t *testing.T, srv *httptest.Server) string {
	t.Helper()

	email := fmt.Sprintf("doctor-%d@example.com", time.Now().UnixNano())
	password := "Pass123!"

	registerResp := doJSON(t, srv, http.MethodPost, "/api/auth/register", map[string]any{
		"email":     email,
		"password":  password,
		"full_name": "Doctor Integration",
		"role":      "doctor",
	}, "")
	if registerResp.StatusCode != http.StatusCreated {
		t.Fatalf("expected register 201, got %d body=%s", registerResp.StatusCode, readAndCloseBody(t, registerResp))
	}
	_ = registerResp.Body.Close()

	loginResp := doJSON(t, srv, http.MethodPost, "/api/auth/login", map[string]any{
		"email": email, "password": password,
	}, "")
	if loginResp.StatusCode != http.StatusOK {
		t.Fatalf("expected login 200, got %d body=%s", loginResp.StatusCode, readAndCloseBody(t, loginResp))
	}
	login := decodeJSON[usecase.LoginResponse](t, loginResp)
	if login.AccessToken == "" {
		t.Fatalf("expected access token in login response")
	}
	return login.AccessToken
}

func (env *authenticatedSessionEnv) startSession(t *testing.T) string {
	t.Helper()

	resp := doJSON(t, env.srv, http.MethodPost, "/api/session/start", nil, env.token)
	if resp.StatusCode != http.StatusCreated {
		t.Fatalf("expected start session 201, got %d body=%s", resp.StatusCode, readAndCloseBody(t, resp))
	}
	start := decodeJSON[usecase.SessionStartResponse](t, resp)
	if start.SessionID == "" {
		t.Fatalf("expected session_id in start response")
	}
	return start.SessionID
}

func doMultipartFile(
	t *testing.T,
	srv *httptest.Server,
	method, path, fieldName, fileName string,
	data []byte,
	contentType, token string,
) *http.Response {
	t.Helper()

	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	header := textproto.MIMEHeader{}
	header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="%s"; filename="%s"`, fieldName, fileName))
	if contentType != "" {
		header.Set("Content-Type", contentType)
	}

	part, err := writer.CreatePart(header)
	if err != nil {
		t.Fatalf("create multipart part: %v", err)
	}
	if _, err = part.Write(data); err != nil {
		t.Fatalf("write multipart part: %v", err)
	}
	if err = writer.Close(); err != nil {
		t.Fatalf("close multipart writer: %v", err)
	}

	req, err := http.NewRequest(method, srv.URL+path, &body)
	if err != nil {
		t.Fatalf("new multipart request: %v", err)
	}
	req.Header.Set("Content-Type", writer.FormDataContentType())
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("request %s %s: %v", method, path, err)
	}
	return resp
}

func decodeJSON[T any](t *testing.T, resp *http.Response) T {
	t.Helper()
	defer resp.Body.Close()

	var out T
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return out
}

func readAndCloseBody(t *testing.T, resp *http.Response) string {
	t.Helper()
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("read response body: %v", err)
	}
	return string(body)
}

func mustReadRedisJSON[T any](t *testing.T, env *authenticatedSessionEnv, key string) T {
	t.Helper()

	payload, err := env.rdb.Get(env.ctx, key).Bytes()
	if err != nil {
		t.Fatalf("redis get %q: %v", key, err)
	}

	var out T
	if err = json.Unmarshal(payload, &out); err != nil {
		t.Fatalf("decode redis payload %q: %v", key, err)
	}
	return out
}

func transcriptBufferRedisKey(sessionID string) string {
	return fmt.Sprintf("session:%s:transcript:pending", sessionID)
}

func activeSessionRedisKey(sessionID string) string {
	return fmt.Sprintf("session:%s:active", sessionID)
}
