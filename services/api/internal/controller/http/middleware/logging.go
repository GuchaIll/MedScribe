package middleware

import (
	"net/http"
	"time"

	"go.uber.org/zap"
)

// RequestLogger returns a structured-logging middleware using zap.
// Logs method, path, status, latency, and remote address at INFO level.
// 5xx responses are logged at ERROR level.
func RequestLogger(log *zap.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}

			next.ServeHTTP(rw, r)

			latency := time.Since(start)
			fields := []zap.Field{
				zap.String("method", r.Method),
				zap.String("path", r.URL.Path),
				zap.Int("status", rw.status),
				zap.Duration("latency", latency),
				zap.String("remote_addr", r.RemoteAddr),
				zap.String("user_agent", r.UserAgent()),
			}

			if requestID := r.Header.Get("X-Request-ID"); requestID != "" {
				fields = append(fields, zap.String("request_id", requestID))
			}

			if rw.status >= 500 {
				log.Error("request", fields...)
			} else {
				log.Info("request", fields...)
			}
		})
	}
}

// responseWriter wraps http.ResponseWriter to capture the status code
// written by the handler so it can be logged.
type responseWriter struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (rw *responseWriter) WriteHeader(code int) {
	if !rw.wroteHeader {
		rw.status = code
		rw.wroteHeader = true
		rw.ResponseWriter.WriteHeader(code)
	}
}
