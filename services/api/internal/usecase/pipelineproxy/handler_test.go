package pipelineproxy

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	miniredis "github.com/alicebob/miniredis/v2"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

func TestHandleMarksDeclaredPythonFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/internal/pipeline" {
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"session_id":"s1","status":"failed","message":"internal graph error"}`))
	}))
	defer server.Close()

	mr := miniredis.RunT(t)
	defer mr.Close()
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	handler := NewHandler(Config{PythonBaseURL: server.URL, RequestTimeout: time.Second}, rdb, zap.NewNop())
	message := []byte(`{"pipeline_id":"p1","session_id":"s1","patient_id":"patient-1","doctor_id":"doctor-1","segments":[]}`)
	err := handler.Handle(context.Background(), nil, message)
	if err == nil || !strings.Contains(err.Error(), "declared failure") {
		t.Fatalf("expected declared failure error, got %v", err)
	}

	raw, err := rdb.Get(context.Background(), "pipeline:s1").Bytes()
	if err != nil {
		t.Fatalf("read top-level pipeline status: %v", err)
	}
	var status entity.PipelineStatus
	if err = json.Unmarshal(raw, &status); err != nil {
		t.Fatalf("decode top-level pipeline status: %v", err)
	}
	if status.Status != "failed" || status.Error != "python pipeline declared failure" {
		t.Fatalf("expected safe failed status, got %+v", status)
	}
}
