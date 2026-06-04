package integration

import (
	"encoding/json"
	"net/http"
	"testing"

	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/usecase"
)

func TestTranscriptionServiceIntegration(t *testing.T) {
	env := newAuthenticatedSessionEnv(t)
	if env == nil {
		return
	}

	t.Run("buffers turns and flushes them on session end", func(t *testing.T) {
		sessionID := env.startSession(t)

		firstResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/transcribe", map[string]any{
			"text":    "How are you feeling today?",
			"speaker": "doctor",
		}, env.token)
		if firstResp.StatusCode != http.StatusOK {
			t.Fatalf("expected first transcribe 200, got %d body=%s", firstResp.StatusCode, readAndCloseBody(t, firstResp))
		}
		first := decodeJSON[usecase.TranscribeResponse](t, firstResp)
		if first.SessionID != sessionID || first.TurnsStored != 1 || first.Source != "gateway" {
			t.Fatalf("unexpected first transcription response: %+v", first)
		}

		secondResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/transcribe", map[string]any{
			"text":    "Breathing is much better now.",
			"speaker": "patient",
		}, env.token)
		if secondResp.StatusCode != http.StatusOK {
			t.Fatalf("expected second transcribe 200, got %d body=%s", secondResp.StatusCode, readAndCloseBody(t, secondResp))
		}
		second := decodeJSON[usecase.TranscribeResponse](t, secondResp)
		if second.TurnsStored != 2 || second.Speaker != "patient" {
			t.Fatalf("unexpected second transcription response: %+v", second)
		}

		rawTurns, err := env.rdb.LRange(env.ctx, transcriptBufferRedisKey(sessionID), 0, -1).Result()
		if err != nil {
			t.Fatalf("read buffered transcript turns: %v", err)
		}
		if len(rawTurns) != 2 {
			t.Fatalf("expected 2 buffered transcript turns, got %d", len(rawTurns))
		}

		var bufferedTurns []entity.TranscriptTurn
		for _, raw := range rawTurns {
			var turn entity.TranscriptTurn
			if err = json.Unmarshal([]byte(raw), &turn); err != nil {
				t.Fatalf("decode buffered transcript turn: %v", err)
			}
			bufferedTurns = append(bufferedTurns, turn)
		}
		if bufferedTurns[0].Speaker != "doctor" || bufferedTurns[1].Speaker != "patient" {
			t.Fatalf("unexpected buffered transcript turns: %+v", bufferedTurns)
		}

		activeBeforeEnd := mustReadRedisJSON[activeSessionSnapshot](t, env, activeSessionRedisKey(sessionID))
		if activeBeforeEnd.Status != "active" || activeBeforeEnd.TranscriptTurnsBuffered != 2 {
			t.Fatalf("unexpected active session state before end: %+v", activeBeforeEnd)
		}
		if len(activeBeforeEnd.RecentTranscript) != 2 {
			t.Fatalf("expected 2 recent transcript turns, got %+v", activeBeforeEnd.RecentTranscript)
		}

		endResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/end", nil, env.token)
		if endResp.StatusCode != http.StatusOK {
			t.Fatalf("expected end session 200, got %d body=%s", endResp.StatusCode, readAndCloseBody(t, endResp))
		}
		end := decodeJSON[usecase.SessionEndResponse](t, endResp)
		if end.Status != "completed" || end.Duration == nil || *end.Duration <= 0 {
			t.Fatalf("unexpected end session response: %+v", end)
		}

		var (
			status        string
			workflowState *string
		)
		if err = env.pool.QueryRow(env.ctx, `
			SELECT status::text, workflow_state
			FROM sessions
			WHERE id = $1
		`, sessionID).Scan(&status, &workflowState); err != nil {
			t.Fatalf("query completed session: %v", err)
		}
		if status != "completed" || workflowState == nil || *workflowState == "" {
			t.Fatalf("expected completed session with workflow state, status=%q workflow_state=%v", status, workflowState)
		}

		var persisted workflowStateSnapshot
		if err = json.Unmarshal([]byte(*workflowState), &persisted); err != nil {
			t.Fatalf("decode persisted workflow state: %v", err)
		}
		if persisted.TranscriptTurnCount != 2 || len(persisted.TranscriptTurns) != 2 {
			t.Fatalf("unexpected persisted transcript summary: %+v", persisted)
		}
		if persisted.TranscriptTurns[0].Text != "How are you feeling today?" ||
			persisted.TranscriptTurns[1].Text != "Breathing is much better now." {
			t.Fatalf("unexpected persisted transcript turns: %+v", persisted.TranscriptTurns)
		}
		if persisted.TranscriptBufferFlushedAt == "" {
			t.Fatalf("expected transcript_buffer_flushed_at in workflow state")
		}

		exists, err := env.rdb.Exists(env.ctx, transcriptBufferRedisKey(sessionID)).Result()
		if err != nil {
			t.Fatalf("check transcript buffer existence: %v", err)
		}
		if exists != 0 {
			t.Fatalf("expected transcript buffer key to be removed, exists=%d", exists)
		}

		activeAfterEnd := mustReadRedisJSON[activeSessionSnapshot](t, env, activeSessionRedisKey(sessionID))
		if activeAfterEnd.Status != "completed" || activeAfterEnd.TranscriptTurnsBuffered != 0 || activeAfterEnd.CompletedAtMs == nil {
			t.Fatalf("unexpected active session state after end: %+v", activeAfterEnd)
		}
	})

	t.Run("rejects transcription for closed sessions", func(t *testing.T) {
		sessionID := env.startSession(t)

		endResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/end", nil, env.token)
		if endResp.StatusCode != http.StatusOK {
			t.Fatalf("expected end session 200, got %d body=%s", endResp.StatusCode, readAndCloseBody(t, endResp))
		}
		_ = endResp.Body.Close()

		transcribeResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/transcribe", map[string]any{
			"text":    "This should be rejected",
			"speaker": "doctor",
		}, env.token)
		if transcribeResp.StatusCode != http.StatusConflict {
			t.Fatalf("expected transcribe on closed session 409, got %d body=%s", transcribeResp.StatusCode, readAndCloseBody(t, transcribeResp))
		}
		_ = transcribeResp.Body.Close()

		exists, err := env.rdb.Exists(env.ctx, transcriptBufferRedisKey(sessionID)).Result()
		if err != nil {
			t.Fatalf("check transcript buffer existence: %v", err)
		}
		if exists != 0 {
			t.Fatalf("expected no transcript buffer for closed session, exists=%d", exists)
		}
	})
}
