// Package app wires all dependencies together (DI root) and runs the
// HTTP server. Following go-clean-template conventions:
//   - All concrete types are created here and injected as interfaces.
//   - No business logic lives in this package.
//   - Shutdown is handled gracefully via OS signal handling.
package app

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"go.uber.org/zap"

	"github.com/medscribe/services/api/config"
	httpcontroller "github.com/medscribe/services/api/internal/controller/http"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
	"github.com/medscribe/services/api/internal/usecase"
	"github.com/medscribe/services/api/internal/usecase/pipelineproxy"
	"github.com/medscribe/services/api/pkg/cache"
	"github.com/medscribe/services/api/pkg/httpserver"
	"github.com/medscribe/services/api/pkg/kafka"
	"github.com/medscribe/services/api/pkg/logger"
	"github.com/medscribe/services/api/pkg/postgres"
	"github.com/medscribe/services/api/pkg/redisclient"
)

// Run is the application entry point. It blocks until a shutdown signal.
func Run(cfg *config.Config) {
	// ─── logger ───────────────────────────────────────────────────────────────
	log, err := logger.New(cfg.Log.Level)
	if err != nil {
		panic("failed to build logger: " + err.Error())
	}
	defer func() { _ = log.Sync() }()
	zap.ReplaceGlobals(log)

	log.Info("medscribe api-gateway starting",
		zap.String("port", cfg.HTTP.Port),
		zap.String("log_level", cfg.Log.Level),
	)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// ─── PostgreSQL ───────────────────────────────────────────────────────────
	pool, err := postgres.New(ctx, cfg.Database)
	if err != nil {
		log.Fatal("postgres: failed to connect", zap.Error(err))
	}
	defer pool.Close()
	log.Info("postgres: connected")

	// ─── Redis ────────────────────────────────────────────────────────────────
	redisClient, err := redisclient.New(ctx, cfg.Redis)
	if err != nil {
		log.Fatal("redis: failed to connect", zap.Error(err))
	}
	defer func() { _ = redisClient.Close() }()
	log.Info("redis: connected")

	// ─── Kafka producer ───────────────────────────────────────────────────────
	producer, err := kafka.New(cfg.Kafka)
	if err != nil {
		log.Fatal("kafka: failed to create producer", zap.Error(err))
	}
	defer producer.Close()
	log.Info("kafka: producer ready")

	// ─── pipeline proxy consumer ──────────────────────────────────────────
	// Consumes pipeline.trigger messages from Kafka and forwards them to the
	// internal Python FastAPI server. This is the strangler-fig bridge: Go
	// handles ingress + queueing, Python executes the 18-node LangGraph
	// clinical pipeline.
	proxyHandler := pipelineproxy.NewHandler(
		pipelineproxy.Config{
			PythonBaseURL:  cfg.PythonBackend.BaseURL,
			RequestTimeout: cfg.PythonBackend.PipelineTimeout,
		},
		redisClient,
		log.Named("pipelineproxy"),
	)
	pipelineConsumer, err := kafka.NewConsumer(
		cfg.Kafka,
		cfg.Kafka.PipelineTopic,
		cfg.PythonBackend.ConsumerGroup,
		proxyHandler.Handle,
		log.Named("kafka.consumer"),
	)
	if err != nil {
		log.Fatal("kafka: failed to create pipeline consumer", zap.Error(err))
	}
	pipelineConsumer.Start(ctx)
	defer pipelineConsumer.Close()
	log.Info("kafka: pipeline proxy consumer started",
		zap.String("topic", cfg.Kafka.PipelineTopic),
		zap.String("group", cfg.PythonBackend.ConsumerGroup),
	)

	// ─── repositories ─────────────────────────────────────────────────────────
	sessionRepo := pgxrepo.NewSessionRepo(pool)
	patientRepo := pgxrepo.NewPatientRepo(pool)
	userRepo := pgxrepo.NewUserRepo(pool)

	// ─── use-cases ────────────────────────────────────────────────────────────
	authUC := usecase.NewAuthUseCase(
		userRepo,
		cfg.Auth.JWTSecret,
		cfg.Auth.TokenTTL,
		log,
	)
	sessionUC := usecase.NewSessionUseCase(
		sessionRepo,
		producer,
		redisClient,
		cache.New(time.Hour),
		cfg.Kafka.PipelineTopic,
		log,
	)
	patientUC := usecase.NewPatientUseCase(patientRepo, log)

	// AssistantUseCase is a placeholder for Phase 2 (RAG wired to pgvector).
	// For now it returns a not-implemented error on every call.
	var assistantUC usecase.AssistantUseCase = &stubAssistant{}

	// ─── Prometheus registry ──────────────────────────────────────────────────
	reg := prometheus.NewRegistry()
	reg.MustRegister(prometheus.NewGoCollector())
	reg.MustRegister(prometheus.NewProcessCollector(prometheus.ProcessCollectorOpts{}))

	// ─── HTTP server ──────────────────────────────────────────────────────────
	router := httpcontroller.Router(cfg, log, reg, authUC, sessionUC, patientUC, assistantUC)
	server := httpserver.New(
		router,
		":"+cfg.HTTP.Port,
		cfg.HTTP.ReadTimeout,
		cfg.HTTP.WriteTimeout,
		cfg.HTTP.ShutdownTimeout,
	)

	serverErr := server.Start()
	log.Info("http server listening", zap.String("addr", server.Addr()))

	// ─── wait for shutdown ────────────────────────────────────────────────────
	select {
	case err = <-serverErr:
		log.Error("http server error", zap.Error(err))
	case <-ctx.Done():
		log.Info("shutdown signal received")
	}

	log.Info("shutting down http server")
	if err = server.Shutdown(); err != nil {
		log.Error("graceful shutdown error", zap.Error(err))
	}
	log.Info("medscribe api-gateway stopped")
}

// stubAssistant satisfies the AssistantUseCase interface until Phase 2.
type stubAssistant struct{}

func (s *stubAssistant) Query(_ context.Context, _, _, _ string) (*usecase.AssistantResponse, error) {
	return nil, usecase.ErrNotImplemented
}
