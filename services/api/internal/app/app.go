// Package app wires all dependencies together (DI root) and runs the selected
// process mode. Following go-clean-template conventions:
//   - All concrete types are created here and injected as interfaces.
//   - No business logic lives in this package.
//   - Shutdown is handled gracefully via OS signal handling.
//
// The same binary runs in one of several modes (selected by --mode / the Run
// mode arg) so the gateway and the Kafka consumer proxies can be deployed as
// independent Kubernetes workloads off a single image — a strangler-fig step
// toward full service separation:
//
//	gateway          HTTP API only (no Kafka consumers)
//	pipeline-worker  pipeline.trigger consumer -> Python pipeline proxy
//	ocr-worker       ocr.jobs consumer       -> Python OCR proxy
//	audio-worker     audio.ingest consumer   -> speech worker proxy
//	all              everything in one process (local/dev convenience; default)
//
// In production each worker runs as its own Deployment (see infra/k8s/); the
// gateway no longer hosts consumers in-process. `all` exists so `docker compose`
// and local dev keep working as a single process.
package app

import (
	"context"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"

	"github.com/medscribe/services/api/config"
	httpcontroller "github.com/medscribe/services/api/internal/controller/http"
	"github.com/medscribe/services/api/internal/entity"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
	"github.com/medscribe/services/api/internal/usecase"
	"github.com/medscribe/services/api/internal/usecase/audioproxy"
	"github.com/medscribe/services/api/internal/usecase/ocrproxy"
	"github.com/medscribe/services/api/internal/usecase/pipelineproxy"
	"github.com/medscribe/services/api/pkg/cache"
	"github.com/medscribe/services/api/pkg/httpserver"
	"github.com/medscribe/services/api/pkg/kafka"
	"github.com/medscribe/services/api/pkg/logger"
	"github.com/medscribe/services/api/pkg/postgres"
	"github.com/medscribe/services/api/pkg/redisclient"
)

// Process modes.
const (
	ModeGateway        = "gateway"
	ModePipelineWorker = "pipeline-worker"
	ModeOCRWorker      = "ocr-worker"
	ModeAudioWorker    = "audio-worker"
	ModeAll            = "all"
)

// Kafka topics consumed by the proxy workers. PipelineTopic is configurable
// (cfg.Kafka.PipelineTopic); these two are fixed by the Python/speech contract.
const (
	ocrTopic   = "ocr.jobs"
	audioTopic = "audio.ingest"
)

// Run is the application entry point. It blocks until a shutdown signal.
// mode selects which components run (see package doc); empty is treated as ModeAll.
func Run(cfg *config.Config, mode string) {
	if mode == "" {
		mode = ModeAll
	}

	log, err := logger.New(cfg.Log.Level)
	if err != nil {
		panic("failed to build logger: " + err.Error())
	}
	defer func() { _ = log.Sync() }()
	zap.ReplaceGlobals(log)

	log.Info("medscribe starting",
		zap.String("mode", mode),
		zap.String("port", cfg.HTTP.Port),
		zap.String("log_level", cfg.Log.Level),
	)

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	switch mode {
	case ModeGateway:
		runGateway(ctx, cfg, log)
	case ModePipelineWorker:
		runPipelineWorker(ctx, cfg, log)
	case ModeOCRWorker:
		runOCRWorker(ctx, cfg, log)
	case ModeAudioWorker:
		runAudioWorker(ctx, cfg, log)
	case ModeAll:
		runAll(ctx, cfg, log)
	default:
		log.Fatal("unknown --mode",
			zap.String("mode", mode),
			zap.String("valid", "gateway|pipeline-worker|ocr-worker|audio-worker|all"),
		)
	}

	log.Info("medscribe stopped", zap.String("mode", mode))
}

// ─── Mode runners ─────────────────────────────────────────────────────────

// runGateway serves the HTTP API only. No Kafka consumers run here.
func runGateway(ctx context.Context, cfg *config.Config, log *zap.Logger) {
	pool := mustPostgres(ctx, cfg, log)
	defer pool.Close()
	redisClient := mustRedis(ctx, cfg, log)
	defer func() { _ = redisClient.Close() }()
	producer := mustProducer(cfg, log)
	defer producer.Close()

	serveGateway(ctx, cfg, log, pool, redisClient, producer)
}

// runAll runs the gateway plus all three consumer proxies in a single process.
// This is the local/dev (docker compose) convenience mode; production uses the
// split gateway + worker modes.
func runAll(ctx context.Context, cfg *config.Config, log *zap.Logger) {
	pool := mustPostgres(ctx, cfg, log)
	defer pool.Close()
	redisClient := mustRedis(ctx, cfg, log)
	defer func() { _ = redisClient.Close() }()
	producer := mustProducer(cfg, log)
	defer producer.Close()

	pc := startPipelineConsumer(ctx, cfg, redisClient, log)
	defer pc.Close()
	oc := startOCRConsumer(ctx, cfg, redisClient, log)
	defer oc.Close()
	ac := startAudioConsumer(ctx, cfg, producer, redisClient, log)
	defer ac.Close()

	serveGateway(ctx, cfg, log, pool, redisClient, producer)
}

func runPipelineWorker(ctx context.Context, cfg *config.Config, log *zap.Logger) {
	redisClient := mustRedis(ctx, cfg, log)
	defer func() { _ = redisClient.Close() }()
	c := startPipelineConsumer(ctx, cfg, redisClient, log)
	defer c.Close()
	serveWorkerHealth(ctx, cfg, log, ModePipelineWorker)
}

func runOCRWorker(ctx context.Context, cfg *config.Config, log *zap.Logger) {
	redisClient := mustRedis(ctx, cfg, log)
	defer func() { _ = redisClient.Close() }()
	c := startOCRConsumer(ctx, cfg, redisClient, log)
	defer c.Close()
	serveWorkerHealth(ctx, cfg, log, ModeOCRWorker)
}

func runAudioWorker(ctx context.Context, cfg *config.Config, log *zap.Logger) {
	redisClient := mustRedis(ctx, cfg, log)
	defer func() { _ = redisClient.Close() }()
	producer := mustProducer(cfg, log)
	defer producer.Close()
	c := startAudioConsumer(ctx, cfg, producer, redisClient, log)
	defer c.Close()
	serveWorkerHealth(ctx, cfg, log, ModeAudioWorker)
}

// ─── Gateway HTTP wiring (shared by gateway + all) ──────────────────────────

func serveGateway(
	ctx context.Context,
	cfg *config.Config,
	log *zap.Logger,
	pool *pgxpool.Pool,
	redisClient *redis.Client,
	producer *kafka.Producer,
) {
	// ─── repositories ─────────────────────────────────────────────────────
	sessionRepo := pgxrepo.NewSessionRepo(pool)
	patientRepo := pgxrepo.NewPatientRepo(pool)
	userRepo := pgxrepo.NewUserRepo(pool)
	if cfg.Auth.AllowAnonymousDemoAccess {
		if err := ensureDemoUser(ctx, userRepo, log); err != nil {
			log.Fatal("failed to ensure demo user", zap.Error(err))
		}
	}

	// ─── use-cases ────────────────────────────────────────────────────────
	authUC := usecase.NewAuthUseCase(userRepo, cfg.Auth.JWTSecret, cfg.Auth.TokenTTL, log)
	sessionUC := usecase.NewSessionUseCase(
		sessionRepo,
		producer,
		redisClient,
		cache.New(time.Hour),
		cfg.Kafka.PipelineTopic,
		log,
	)
	patientUC := usecase.NewPatientUseCase(patientRepo, log)
	assistantUC := usecase.NewAssistantUseCase(redisClient, sessionRepo, patientRepo, log)

	// ─── Prometheus registry ───────────────────────────────────────────────
	reg := prometheus.NewRegistry()
	reg.MustRegister(prometheus.NewGoCollector())
	reg.MustRegister(prometheus.NewProcessCollector(prometheus.ProcessCollectorOpts{}))

	// ─── HTTP server ────────────────────────────────────────────────────────
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

	awaitShutdown(ctx, log, serverErr, server)
}

// serveWorkerHealth runs a minimal HTTP server (/healthz, /readyz, /metrics)
// for a consumer-only worker so Kubernetes liveness/readiness probes and the
// Prometheus scraper have an endpoint, then blocks until shutdown.
func serveWorkerHealth(ctx context.Context, cfg *config.Config, log *zap.Logger, worker string) {
	reg := prometheus.NewRegistry()
	reg.MustRegister(prometheus.NewGoCollector())
	reg.MustRegister(prometheus.NewProcessCollector(prometheus.ProcessCollectorOpts{}))

	mux := http.NewServeMux()
	ok := func(body string) http.HandlerFunc {
		return func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(body))
		}
	}
	mux.HandleFunc("/health", ok("ok")) // alias for the image's baked HEALTHCHECK
	mux.HandleFunc("/healthz", ok("ok"))
	mux.HandleFunc("/readyz", ok("ready"))
	mux.Handle("/metrics", promhttp.HandlerFor(reg, promhttp.HandlerOpts{}))

	server := httpserver.New(
		mux,
		":"+cfg.HTTP.Port,
		cfg.HTTP.ReadTimeout,
		cfg.HTTP.WriteTimeout,
		cfg.HTTP.ShutdownTimeout,
	)
	serverErr := server.Start()
	log.Info("worker health server listening",
		zap.String("worker", worker),
		zap.String("addr", server.Addr()),
	)

	awaitShutdown(ctx, log, serverErr, server)
}

// awaitShutdown blocks until the HTTP server errors or a shutdown signal
// arrives, then drains the server gracefully.
func awaitShutdown(ctx context.Context, log *zap.Logger, serverErr <-chan error, server *httpserver.Server) {
	select {
	case err := <-serverErr:
		if err != nil {
			log.Error("http server error", zap.Error(err))
		}
	case <-ctx.Done():
		log.Info("shutdown signal received")
	}
	log.Info("shutting down http server")
	if err := server.Shutdown(); err != nil {
		log.Error("graceful shutdown error", zap.Error(err))
	}
}

// ─── Shared infra constructors (fatal on failure) ───────────────────────────

func mustPostgres(ctx context.Context, cfg *config.Config, log *zap.Logger) *pgxpool.Pool {
	pool, err := postgres.New(ctx, cfg.Database)
	if err != nil {
		log.Fatal("postgres: failed to connect", zap.Error(err))
	}
	log.Info("postgres: connected")
	return pool
}

func mustRedis(ctx context.Context, cfg *config.Config, log *zap.Logger) *redis.Client {
	redisClient, err := redisclient.New(ctx, cfg.Redis)
	if err != nil {
		log.Fatal("redis: failed to connect", zap.Error(err))
	}
	log.Info("redis: connected")
	return redisClient
}

func mustProducer(cfg *config.Config, log *zap.Logger) *kafka.Producer {
	producer, err := kafka.New(cfg.Kafka)
	if err != nil {
		log.Fatal("kafka: failed to create producer", zap.Error(err))
	}
	log.Info("kafka: producer ready")
	return producer
}

// ─── Consumer starters ───────────────────────────────────────────────────────

func startPipelineConsumer(ctx context.Context, cfg *config.Config, redisClient *redis.Client, log *zap.Logger) *kafka.Consumer {
	handler := pipelineproxy.NewHandler(
		pipelineproxy.Config{
			PythonBaseURL:  cfg.PythonBackend.BaseURL,
			RequestTimeout: cfg.PythonBackend.PipelineTimeout,
		},
		redisClient,
		log.Named("pipelineproxy"),
	)
	return startConsumer(ctx, cfg, cfg.Kafka.PipelineTopic, cfg.PythonBackend.ConsumerGroup, handler.Handle, log.Named("kafka.consumer"))
}

func startOCRConsumer(ctx context.Context, cfg *config.Config, redisClient *redis.Client, log *zap.Logger) *kafka.Consumer {
	handler := ocrproxy.NewHandler(
		ocrproxy.Config{
			PythonBaseURL:  cfg.PythonBackend.BaseURL,
			RequestTimeout: cfg.PythonBackend.PipelineTimeout,
		},
		redisClient,
		log.Named("ocrproxy"),
	)
	return startConsumer(ctx, cfg, ocrTopic, cfg.PythonBackend.ConsumerGroup+"-ocr", handler.Handle, log.Named("kafka.consumer.ocr"))
}

func startAudioConsumer(ctx context.Context, cfg *config.Config, producer *kafka.Producer, redisClient *redis.Client, log *zap.Logger) *kafka.Consumer {
	handler := audioproxy.NewHandler(
		audioproxy.Config{
			SpeechWorkerBaseURL: cfg.SpeechWorker.BaseURL,
			RequestTimeout:      cfg.SpeechWorker.RequestTimeout,
		},
		producer,
		redisClient,
		log.Named("audioproxy"),
	)
	return startConsumer(ctx, cfg, audioTopic, cfg.SpeechWorker.ConsumerGroup, handler.Handle, log.Named("kafka.consumer.audio"))
}

func startConsumer(
	ctx context.Context,
	cfg *config.Config,
	topic, group string,
	handler kafka.MessageHandler,
	log *zap.Logger,
) *kafka.Consumer {
	consumer, err := kafka.NewConsumer(cfg.Kafka, topic, group, handler, log)
	if err != nil {
		log.Fatal("kafka: failed to create consumer", zap.String("topic", topic), zap.Error(err))
	}
	consumer.Start(ctx)
	log.Info("kafka: consumer started", zap.String("topic", topic), zap.String("group", group))
	return consumer
}

func ensureDemoUser(ctx context.Context, users *pgxrepo.UserRepo, log *zap.Logger) error {
	const demoUserID = "demo-user"

	if _, err := users.GetByID(ctx, demoUserID); err == nil {
		log.Info("demo user ready", zap.String("user_id", demoUserID))
		return nil
	} else if err != entity.ErrNotFound {
		return err
	}

	hash, err := pgxrepo.HashPassword("demo-session-disabled-login")
	if err != nil {
		return err
	}

	_, err = users.Create(ctx, &entity.User{
		ID:             demoUserID,
		Username:       "demo_clinician",
		Email:          "demo@medscribe.local",
		HashedPassword: hash,
		FullName:       "Demo Clinician",
		Role:           entity.UserRoleDoctor,
		Permissions:    []string{"demo"},
		IsActive:       true,
	})
	if err != nil {
		return err
	}

	log.Info("created demo user for anonymous access", zap.String("user_id", demoUserID))
	return nil
}
