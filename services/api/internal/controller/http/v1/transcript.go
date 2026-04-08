package v1

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"

	"go.uber.org/zap"
)

// TranscriptHandler handles /api/transcript/* routes.
type TranscriptHandler struct {
	log *zap.Logger
}

func NewTranscriptHandler(log *zap.Logger) *TranscriptHandler {
	return &TranscriptHandler{log: log}
}

type transcriptMessage struct {
	ID        string `json:"id"`
	Speaker   string `json:"speaker"`
	Content   string `json:"content"`
	Timestamp string `json:"timestamp"`
	Type      string `json:"type"` // user | system
}

// Reclassify uses the Groq API to classify each utterance as Clinician or Patient.
// Ports /api/transcript/reclassify from transcript.py.
//
// Security: the Groq API key is read from the environment, never from the
// request body or query string.
func (h *TranscriptHandler) Reclassify(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Messages []transcriptMessage `json:"messages"`
	}
	if !bindJSON(w, r, &req) {
		return
	}
	if len(req.Messages) == 0 {
		writeJSON(w, http.StatusOK, map[string]any{"messages": []any{}})
		return
	}

	groqKey := os.Getenv("GROQ_API_KEY")
	if groqKey == "" {
		writeJSONError(w, http.StatusServiceUnavailable,
			"GROQ_API_KEY not set — speaker reclassification unavailable")
		return
	}

	transcript := ""
	for i, msg := range req.Messages {
		transcript += fmt.Sprintf("[%d] %s\n", i, msg.Content)
	}

	prompt := "You are analyzing a medical consultation transcript to identify who said each utterance.\n\n" +
		"Classify each utterance as either \"Clinician\" or \"Patient\":\n" +
		"- Clinician: asks structured diagnostic questions, uses medical terminology, gives instructions, describes treatment plans\n" +
		"- Patient: describes symptoms, answers questions, expresses concerns, describes daily life and history\n\n" +
		"Transcript:\n" + transcript + "\n\n" +
		"Return ONLY a JSON array with one entry per utterance, in the same order.\n" +
		"Each entry must be: {\"index\": 0, \"speaker\": \"Clinician\"}\n" +
		"No explanation. No markdown. Just the raw JSON array."

	classifications, err := callGroqChatAPI(r.Context(), groqKey, prompt, h.log)
	if err != nil {
		h.log.Error("groq reclassify call failed", zap.Error(err))
		writeJSONError(w, http.StatusBadGateway, "reclassification service error")
		return
	}

	// Apply classifications back to messages.
	result := make([]transcriptMessage, len(req.Messages))
	copy(result, req.Messages)

	for _, c := range classifications {
		cm, ok := c.(map[string]any)
		if !ok {
			continue
		}
		idx, _ := toInt(cm["index"])
		speaker, _ := cm["speaker"].(string)
		if idx >= 0 && idx < len(result) && speaker != "" {
			result[idx].Speaker = speaker
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"messages": result})
}

// callGroqChatAPI sends a single user message to Groq and parses the response
// as a JSON array. It is deliberately simple — no streaming, no retries.
// Phase 5 will replace this with the full LLM dispatch layer.
func callGroqChatAPI(ctx context.Context, apiKey, prompt string, log *zap.Logger) ([]any, error) {
	body, _ := json.Marshal(map[string]any{
		"model": "llama-3.3-70b-versatile",
		"messages": []map[string]string{
			{"role": "user", "content": prompt},
		},
	})

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		"https://api.groq.com/openai/v1/chat/completions",
		io.NopCloser(bytes.NewReader(body)))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+apiKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		data, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("groq API returned %d: %s", resp.StatusCode, string(data))
	}

	var groqResp struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&groqResp); err != nil {
		return nil, fmt.Errorf("decode groq response: %w", err)
	}
	if len(groqResp.Choices) == 0 {
		return nil, fmt.Errorf("groq returned no choices")
	}

	var result []any
	if err = json.Unmarshal([]byte(groqResp.Choices[0].Message.Content), &result); err != nil {
		return nil, fmt.Errorf("parse classification JSON: %w", err)
	}
	return result, nil
}

func toInt(v any) (int, bool) {
	switch n := v.(type) {
	case float64:
		return int(n), true
	case int:
		return n, true
	}
	return 0, false
}
