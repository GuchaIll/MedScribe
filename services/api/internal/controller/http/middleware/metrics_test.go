package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/testutil"
)

func TestPrometheusMiddlewareRecordsMetrics(t *testing.T) {
	reg := prometheus.NewRegistry()
	m := NewMetrics(reg)
	h := PrometheusMiddleware(m)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusCreated)
	}))

	req := httptest.NewRequest(http.MethodPost, "/x", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusCreated {
		t.Fatalf("expected status 201, got %d", rec.Code)
	}

	counter := m.requestsTotal.WithLabelValues(http.MethodPost, "/x", "201")
	if got := testutil.ToFloat64(counter); got != 1 {
		t.Fatalf("expected counter=1 got=%v", got)
	}
	if got := testutil.ToFloat64(m.requestsInFlight); got != 0 {
		t.Fatalf("expected in-flight gauge reset to 0 got=%v", got)
	}
}
