// Package httpcontroller wires the chi router, mounts all v1 routes,
// and attaches the middleware stack.
package httpcontroller

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	chimiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.uber.org/zap"

	"github.com/medscribe/services/api/config"
	"github.com/medscribe/services/api/internal/controller/http/middleware"
	v1 "github.com/medscribe/services/api/internal/controller/http/v1"
	"github.com/medscribe/services/api/internal/usecase"
)

// Router assembles the full chi mux.
func Router(
	cfg *config.Config,
	log *zap.Logger,
	reg *prometheus.Registry,
	authUC usecase.AuthUseCase,
	sessionUC usecase.SessionUseCase,
	patientUC usecase.PatientUseCase,
	assistantUC usecase.AssistantUseCase,
) http.Handler {
	r := chi.NewRouter()

	// ─── global middleware ────────────────────────────────────────────────────
	r.Use(chimiddleware.RealIP)
	r.Use(chimiddleware.RequestID)
	r.Use(chimiddleware.Recoverer)
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   cfg.CORS.AllowedOrigins,
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-Request-ID"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	m := middleware.NewMetrics(reg)
	r.Use(middleware.PrometheusMiddleware(m))
	r.Use(middleware.RequestLogger(log))

	jwtMiddleware := middleware.JWTAuth(authUC, log)

	// ─── public routes ────────────────────────────────────────────────────────
	r.Get("/health", healthHandler)
	r.Get("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{Registry: reg}).ServeHTTP)

	r.Route("/api/auth", func(r chi.Router) {
		authH := v1.NewAuthHandler(authUC, log)
		r.Post("/register", authH.Register)
		r.Post("/login", authH.Login)
		r.With(jwtMiddleware).Get("/profile", authH.GetProfile)
	})

	// ─── protected routes ─────────────────────────────────────────────────────
	r.Group(func(r chi.Router) {
		r.Use(jwtMiddleware)

		// Session
		sessionH := v1.NewSessionHandler(sessionUC, log)
		r.Route("/api/session", func(r chi.Router) {
			r.Post("/start", sessionH.Start)
			r.Post("/{sessionID}/end", sessionH.End)
			r.Post("/{sessionID}/transcribe", sessionH.Transcribe)
			r.Post("/{sessionID}/pipeline", sessionH.TriggerPipeline)
			r.Get("/{sessionID}/pipeline/status", sessionH.PipelineStatus)
			r.Post("/{sessionID}/upload", sessionH.UploadDocument)
			r.Get("/{sessionID}/record", sessionH.GetRecord)
			r.Get("/{sessionID}/documents", sessionH.GetDocuments)
			r.Get("/{sessionID}/queue", sessionH.GetQueue)
			r.Patch("/{sessionID}/queue/{itemID}", sessionH.UpdateQueueItem)
			r.Post("/{sessionID}/assistant", v1.NewAssistantHandler(assistantUC, log).Query)
		})

		// Patient
		patientH := v1.NewPatientHandler(patientUC, log)
		r.Route("/api/patient", func(r chi.Router) {
			r.Get("/{patientID}/profile", patientH.GetProfile)
			r.Get("/{patientID}/lab-trends", patientH.GetLabTrends)
			r.Get("/{patientID}/risk-score", patientH.GetRiskScore)
		})

		// Records
		recordsH := v1.NewRecordsHandler(log)
		r.Route("/api/records", func(r chi.Router) {
			r.Post("/generate", recordsH.Generate)
			r.Post("/preview", recordsH.Preview)
			r.Post("/regenerate", recordsH.Regenerate)
			r.Post("/commit", recordsH.Commit)
			r.Get("/patient/{patientID}/history", recordsH.History)
			r.Get("/templates", recordsH.ListTemplates)
		})

		// LLM provider config
		llmH := v1.NewLLMHandler(log)
		r.Route("/api/llm", func(r chi.Router) {
			r.Get("/providers", llmH.GetProviders)
			r.Post("/provider", llmH.SelectProvider)
		})

		// Transcript
		transcriptH := v1.NewTranscriptHandler(log)
		r.Post("/api/transcript/reclassify", transcriptH.Reclassify)
	})

	return r
}

// healthHandler returns a simple 200 JSON liveness response.
func healthHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"service": "medscribe-api",
	})
}
