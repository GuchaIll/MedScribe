// Command medscribe-api is the entry point for the MedScribe Go service.
//
// A single binary runs in one of several modes (see internal/app):
//
//	--mode=gateway          HTTP API only
//	--mode=pipeline-worker  pipeline.trigger Kafka consumer
//	--mode=ocr-worker       ocr.jobs Kafka consumer
//	--mode=audio-worker     audio.ingest Kafka consumer
//	--mode=all              everything in one process (default; local/dev)
//
// The mode may also be set via the MEDSCRIBE_MODE environment variable; the
// --mode flag takes precedence when provided.
package main

import (
	"flag"
	"os"

	"github.com/medscribe/services/api/config"
	"github.com/medscribe/services/api/internal/app"
)

func main() {
	mode := flag.String("mode", envOr("MEDSCRIBE_MODE", app.ModeAll),
		"process mode: gateway|pipeline-worker|ocr-worker|audio-worker|all")
	flag.Parse()

	cfg, err := config.New()
	if err != nil {
		panic("failed to load config: " + err.Error())
	}
	app.Run(cfg, *mode)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
