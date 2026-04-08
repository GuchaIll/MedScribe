package middleware

import (
	"net/http"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics holds the Prometheus instruments registered by this middleware.
// Exposed publicly so the telemetry layer can register additional metrics
// on the same registry.
type Metrics struct {
	requestsTotal   *prometheus.CounterVec
	requestDuration *prometheus.HistogramVec
	requestsInFlight prometheus.Gauge
}

// NewMetrics registers and returns the Prometheus metrics.
func NewMetrics(reg prometheus.Registerer) *Metrics {
	factory := promauto.With(reg)
	return &Metrics{
		requestsTotal: factory.NewCounterVec(prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "Total HTTP requests by method, path, and status.",
		}, []string{"method", "path", "status"}),

		requestDuration: factory.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request latency distribution.",
			Buckets: prometheus.DefBuckets,
		}, []string{"method", "path", "status"}),

		requestsInFlight: factory.NewGauge(prometheus.GaugeOpts{
			Name: "http_requests_in_flight",
			Help: "Number of HTTP requests currently being handled.",
		}),
	}
}

// PrometheusMiddleware returns a chi-compatible middleware that records the
// request metrics defined in m.
func PrometheusMiddleware(m *Metrics) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			m.requestsInFlight.Inc()
			defer m.requestsInFlight.Dec()

			rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(rw, r)

			status := strconv.Itoa(rw.status)
			labels := prometheus.Labels{
				"method": r.Method,
				"path":   r.URL.Path,
				"status": status,
			}
			m.requestsTotal.With(labels).Inc()
			m.requestDuration.With(labels).Observe(time.Since(start).Seconds())
		})
	}
}
