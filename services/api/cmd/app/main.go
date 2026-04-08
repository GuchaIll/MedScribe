// Command medscribe-api is the entry point for the MedScribe Go API gateway.
package main

import (
	"github.com/medscribe/services/api/config"
	"github.com/medscribe/services/api/internal/app"
)

func main() {
	cfg, err := config.New()
	if err != nil {
		panic("failed to load config: " + err.Error())
	}
	app.Run(cfg)
}
