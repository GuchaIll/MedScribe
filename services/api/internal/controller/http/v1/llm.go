package v1

import (
	"net/http"

	"go.uber.org/zap"
)

// LLMHandler handles /api/llm/* routes.
type LLMHandler struct {
	log *zap.Logger
}

func NewLLMHandler(log *zap.Logger) *LLMHandler {
	return &LLMHandler{log: log}
}

// providerMeta mirrors the PROVIDER_DESCRIPTIONS map from llm_config.py.
var providerMeta = []map[string]any{
	{
		"name":         "groq",
		"display_name": "Groq",
		"description":  "Fast Groq API — best for latency-sensitive applications",
		"default_model": "llama-3.3-70b-versatile",
	},
	{
		"name":         "openai",
		"display_name": "OpenAI",
		"description":  "OpenAI GPT models",
		"default_model": "gpt-4-turbo-preview",
	},
	{
		"name":         "anthropic",
		"display_name": "Anthropic Claude",
		"description":  "Anthropic Claude models — excellent reasoning",
		"default_model": "claude-3-opus-20240229",
	},
	{
		"name":         "google",
		"display_name": "Google Gemini",
		"description":  "Google Gemini models — multimodal capabilities",
		"default_model": "gemini-pro",
	},
	{
		"name":         "openrouter",
		"display_name": "OpenRouter",
		"description":  "OpenRouter — access to 100+ open-source models",
		"default_model": "meta-llama/llama-2-70b-chat",
	},
	{
		"name":         "vllm",
		"display_name": "vLLM (local)",
		"description":  "Local vLLM endpoint — OpenAI-compatible API",
		"default_model": "",
	},
}

func (h *LLMHandler) GetProviders(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"providers": providerMeta})
}

// SelectProvider sets the active LLM provider for the authenticated session.
// Phase 1: returns 200 but does not persist the selection.
// Phase 5 (Dynamic LLM Routing) will wire this to the router optimizer.
func (h *LLMHandler) SelectProvider(w http.ResponseWriter, r *http.Request) {
	var body struct {
		ProviderName string `json:"provider_name"`
	}
	if !bindJSON(w, r, &body) {
		return
	}

	// Validate provider name.
	valid := false
	for _, p := range providerMeta {
		if p["name"] == body.ProviderName {
			valid = true
			break
		}
	}
	if !valid {
		writeJSONError(w, http.StatusBadRequest, "unknown provider: "+body.ProviderName)
		return
	}

	// TODO Phase 5: persist selection to user session / Redis.
	writeJSON(w, http.StatusOK, map[string]any{
		"provider": body.ProviderName,
		"message":  "provider selected",
	})
}
