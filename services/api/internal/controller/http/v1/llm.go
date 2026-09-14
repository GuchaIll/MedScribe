package v1

import (
	"net/http"
	"os"
	"strings"

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
	selectedProvider := strings.ToLower(strings.TrimSpace(os.Getenv("LLM_PROVIDER")))
	selectedModel := strings.TrimSpace(os.Getenv("LLM_NAME"))

	withAvailability := make([]map[string]any, 0, len(providerMeta))
	availableNames := make([]string, 0, len(providerMeta))
	for _, provider := range providerMeta {
		name, _ := provider["name"].(string)
		available := isProviderConfigured(name)

		next := map[string]any{
			"name":          provider["name"],
			"display_name":  provider["display_name"],
			"description":   provider["description"],
			"default_model": provider["default_model"],
			"available":     available,
		}
		if available {
			availableNames = append(availableNames, name)
		}
		if selectedProvider != "" && selectedModel != "" && name == selectedProvider {
			next["default_model"] = selectedModel
		}
		withAvailability = append(withAvailability, next)
	}

	defaultProvider := selectedProvider
	if defaultProvider == "" || !isProviderConfigured(defaultProvider) {
		defaultProvider = firstAvailableProvider()
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"providers":         withAvailability,
		"default_provider":  defaultProvider,
		"selected_provider": defaultProvider,
		"available_count":   len(availableNames),
	})
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
		"model":    modelForProvider(body.ProviderName),
		"message":  "provider selected",
	})
}

func isProviderConfigured(name string) bool {
	switch strings.ToLower(strings.TrimSpace(name)) {
	case "groq":
		return strings.TrimSpace(os.Getenv("GROQ_API_KEY")) != ""
	case "openai":
		return strings.TrimSpace(os.Getenv("OPENAI_API_KEY")) != ""
	case "anthropic":
		return strings.TrimSpace(os.Getenv("ANTHROPIC_API_KEY")) != ""
	case "google":
		return strings.TrimSpace(os.Getenv("GOOGLE_API_KEY")) != ""
	case "openrouter":
		return strings.TrimSpace(os.Getenv("OPENROUTER_API_KEY")) != ""
	default:
		return false
	}
}

func firstAvailableProvider() string {
	for _, name := range []string{"groq", "openai", "anthropic", "google", "openrouter"} {
		if isProviderConfigured(name) {
			return name
		}
	}
	return ""
}

func modelForProvider(name string) string {
	selectedProvider := strings.ToLower(strings.TrimSpace(os.Getenv("LLM_PROVIDER")))
	selectedModel := strings.TrimSpace(os.Getenv("LLM_NAME"))
	if selectedProvider != "" && selectedModel != "" && selectedProvider == strings.ToLower(strings.TrimSpace(name)) {
		return selectedModel
	}
	for _, provider := range providerMeta {
		if provider["name"] == strings.ToLower(strings.TrimSpace(name)) {
			if model, ok := provider["default_model"].(string); ok {
				return model
			}
		}
	}
	return ""
}
