package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds all runtime configuration sourced from environment variables.
// Fields that are required cause a startup panic so K8s restarts the pod
// immediately and operators see a clear error in the crash loop reason.
type Config struct {
	HTTP          HTTPConfig
	Database      DatabaseConfig
	Redis         RedisConfig
	Kafka         KafkaConfig
	Orchestrator  OrchestratorConfig
	PythonBackend PythonBackendConfig
	Auth          AuthConfig
	Log           LogConfig
	CORS          CORSConfig
}

type HTTPConfig struct {
	Port            string
	ReadTimeout     time.Duration
	WriteTimeout    time.Duration
	ShutdownTimeout time.Duration
}

type DatabaseConfig struct {
	// DATABASE_URL — required. Postgres DSN e.g.
	// postgres://user:pass@db:5432/medscribe?sslmode=disable
	URL         string
	MaxConns    int32
	MinConns    int32
	MaxConnLife time.Duration
}

type RedisConfig struct {
	// REDIS_URL — redis://[:password@]host:port/db
	URL string
}

type KafkaConfig struct {
	// KAFKA_BROKERS — comma-separated host:port list
	Brokers       []string
	PipelineTopic string
	// How long the Kafka producer will wait for acks before returning an error.
	ProducerTimeout time.Duration
	// KAFKA_CONSUMER_WORKERS — concurrent handler goroutines for the consumer.
	// Defaults to 4. Set to 1 for serial processing.
	Workers int
}

type OrchestratorConfig struct {
	// ORCHESTRATOR_GRPC_ADDR — host:port of the Go orchestrator gRPC server.
	// When empty the gateway falls back to Kafka-only mode (Phase 1).
	GRPCAddr    string
	DialTimeout time.Duration
}

// PythonBackendConfig holds connection settings for the internal Python
// FastAPI server that runs the LangGraph clinical pipeline. This is the
// strangler-fig bridge: Go handles ingress and queueing, Python executes
// the pipeline until individual nodes are ported.
type PythonBackendConfig struct {
	// PYTHON_BACKEND_URL — internal base URL of the Python FastAPI server,
	// e.g. http://python-backend:8000. No trailing slash.
	BaseURL string
	// PYTHON_PIPELINE_TIMEOUT — max time to wait for a single pipeline run.
	PipelineTimeout time.Duration
	// KAFKA_CONSUMER_GROUP — consumer group for the pipeline proxy.
	ConsumerGroup string
}

type AuthConfig struct {
	// JWT_SECRET_KEY — required. HMAC-SHA256 signing key for JWT.
	JWTSecret string
	TokenTTL  time.Duration
	// ENCRYPTION_KEY — required. 32-byte hex key for AES-256-GCM PHI encryption.
	EncryptionKey string
}

type LogConfig struct {
	// LOG_LEVEL: debug | info | warn | error  (default: info)
	Level string
}

type CORSConfig struct {
	// CORS_ORIGINS — comma-separated list of allowed origins.
	AllowedOrigins []string
}

// New builds a Config from the process environment.
// Panics early on missing required variables.
func New() (*Config, error) {
	cfg := &Config{
		HTTP: HTTPConfig{
			Port:            envOrDefault("PORT", "8080"),
			ReadTimeout:     envDuration("HTTP_READ_TIMEOUT", 15*time.Second),
			WriteTimeout:    envDuration("HTTP_WRITE_TIMEOUT", 30*time.Second),
			ShutdownTimeout: envDuration("HTTP_SHUTDOWN_TIMEOUT", 15*time.Second),
		},
		Database: DatabaseConfig{
			URL:         requireEnv("DATABASE_URL"),
			MaxConns:    int32(envInt("DB_MAX_CONNS", 50)),
			MinConns:    int32(envInt("DB_MIN_CONNS", 50)),
			MaxConnLife: envDuration("DB_MAX_CONN_LIFE", 30*time.Minute),
		},
		Redis: RedisConfig{
			URL: envOrDefault("REDIS_URL", "redis://localhost:6379/0"),
		},
		Kafka: KafkaConfig{
			Brokers:         splitCSV("KAFKA_BROKERS", "localhost:9092"),
			PipelineTopic:   envOrDefault("KAFKA_PIPELINE_TOPIC", "pipeline.trigger"),
			ProducerTimeout: envDuration("KAFKA_PRODUCER_TIMEOUT", 5*time.Second),
			Workers:         envInt("KAFKA_CONSUMER_WORKERS", 4),
		},
		Orchestrator: OrchestratorConfig{
			GRPCAddr:    envOrDefault("ORCHESTRATOR_GRPC_ADDR", ""),
			DialTimeout: envDuration("ORCHESTRATOR_DIAL_TIMEOUT", 5*time.Second),
		},
		PythonBackend: PythonBackendConfig{
			BaseURL:         envOrDefault("PYTHON_BACKEND_URL", "http://localhost:8000"),
			PipelineTimeout: envDuration("PYTHON_PIPELINE_TIMEOUT", 5*time.Minute),
			ConsumerGroup:   envOrDefault("KAFKA_CONSUMER_GROUP", "medscribe-pipeline-proxy"),
		},
		Auth: AuthConfig{
			JWTSecret:     requireEnv("JWT_SECRET_KEY"),
			TokenTTL:      envDuration("JWT_TOKEN_TTL", 24*time.Hour),
			EncryptionKey: requireEnv("ENCRYPTION_KEY"),
		},
		Log: LogConfig{
			Level: envOrDefault("LOG_LEVEL", "info"),
		},
		CORS: CORSConfig{
			AllowedOrigins: splitCSV("CORS_ORIGINS", "http://localhost:3000"),
		},
	}
	return cfg, nil
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func requireEnv(key string) string {
	v := os.Getenv(key)
	if v == "" {
		panic(fmt.Sprintf("required environment variable %q is not set", key))
	}
	return v
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envDuration(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func splitCSV(key, def string) []string {
	raw := envOrDefault(key, def)
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			out = append(out, p)
		}
	}
	return out
}
