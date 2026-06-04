package integration

import (
	"bytes"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/medscribe/services/api/internal/entity"
)

func TestOCRServiceIntegration(t *testing.T) {
	env := newAuthenticatedSessionEnv(t)
	if env == nil {
		return
	}

	t.Run("queues uploaded documents for asynchronous OCR", func(t *testing.T) {
		sessionID := env.startSession(t)
		fileName := "../scan?.pdf"
		fileBytes := []byte("%PDF-1.4\n% integration test upload\n")

		uploadResp := doMultipartFile(
			t,
			env.srv,
			http.MethodPost,
			"/api/session/"+sessionID+"/upload",
			"file",
			fileName,
			fileBytes,
			"application/pdf",
			env.token,
		)
		if uploadResp.StatusCode != http.StatusAccepted {
			t.Fatalf("expected upload 202, got %d body=%s", uploadResp.StatusCode, readAndCloseBody(t, uploadResp))
		}
		doc := decodeJSON[entity.Document](t, uploadResp)
		if doc.ID == "" || doc.SessionID != sessionID {
			t.Fatalf("unexpected uploaded document payload: %+v", doc)
		}
		if doc.OriginalName != fileName || doc.MimeType != "application/pdf" {
			t.Fatalf("unexpected uploaded document metadata: %+v", doc)
		}
		if !strings.Contains(doc.StoragePath, filepath.Join(os.TempDir(), "medscribe", "ocr-spool", sessionID)) {
			t.Fatalf("expected storage path inside OCR spool dir, got %q", doc.StoragePath)
		}
		if strings.Contains(filepath.Base(doc.StoragePath), "..") || strings.Contains(filepath.Base(doc.StoragePath), "?") {
			t.Fatalf("expected sanitized spool filename, got %q", filepath.Base(doc.StoragePath))
		}
		t.Cleanup(func() { _ = os.Remove(doc.StoragePath) })

		spooledBytes, err := os.ReadFile(doc.StoragePath)
		if err != nil {
			t.Fatalf("read spooled OCR upload: %v", err)
		}
		if !bytes.Equal(spooledBytes, fileBytes) {
			t.Fatalf("unexpected spooled document bytes: got %q want %q", string(spooledBytes), string(fileBytes))
		}

		var persistedCount int
		if err = env.pool.QueryRow(env.ctx, `
			SELECT COUNT(*)
			FROM session_documents
			WHERE session_id = $1
		`, sessionID).Scan(&persistedCount); err != nil {
			t.Fatalf("count persisted session documents: %v", err)
		}
		if persistedCount != 0 {
			t.Fatalf("expected OCR upload to remain pending until worker completion, found %d persisted documents", persistedCount)
		}

		docsResp := doJSON(t, env.srv, http.MethodGet, "/api/session/"+sessionID+"/documents", nil, env.token)
		if docsResp.StatusCode != http.StatusOK {
			t.Fatalf("expected documents list 200, got %d body=%s", docsResp.StatusCode, readAndCloseBody(t, docsResp))
		}
		docs := decodeJSON[documentListResponse](t, docsResp)
		if len(docs.Documents) != 1 || docs.Documents[0].ID != doc.ID {
			t.Fatalf("expected pending document in GET /documents, got %+v", docs.Documents)
		}

		activeState := mustReadRedisJSON[activeSessionSnapshot](t, env, activeSessionRedisKey(sessionID))
		if len(activeState.PendingDocuments) != 1 || activeState.PendingDocuments[0].ID != doc.ID {
			t.Fatalf("expected pending document in active session state, got %+v", activeState.PendingDocuments)
		}
		if len(activeState.OCRJobs) != 1 || activeState.OCRJobs[0].DocumentID != doc.ID || activeState.OCRJobs[0].Status != "queued" {
			t.Fatalf("expected queued OCR job in active session state, got %+v", activeState.OCRJobs)
		}

		jobKeys, err := env.rdb.Keys(env.ctx, "ocr:job:*").Result()
		if err != nil {
			t.Fatalf("list OCR job keys: %v", err)
		}
		if len(jobKeys) != 1 {
			t.Fatalf("expected 1 OCR job key, got %d (%v)", len(jobKeys), jobKeys)
		}

		job := mustReadRedisJSON[ocrQueuedJob](t, env, jobKeys[0])
		if job.Status != "queued" || job.JobType != "ocr" || job.DocumentID != doc.ID || job.SessionID != sessionID {
			t.Fatalf("unexpected queued OCR job payload: %+v", job)
		}
		if job.StoragePath != doc.StoragePath || job.MimeType != doc.MimeType {
			t.Fatalf("unexpected queued OCR job storage payload: %+v", job)
		}
	})

	t.Run("rejects OCR uploads after the session is closed", func(t *testing.T) {
		sessionID := env.startSession(t)

		endResp := doJSON(t, env.srv, http.MethodPost, "/api/session/"+sessionID+"/end", nil, env.token)
		if endResp.StatusCode != http.StatusOK {
			t.Fatalf("expected end session 200, got %d body=%s", endResp.StatusCode, readAndCloseBody(t, endResp))
		}
		_ = endResp.Body.Close()

		uploadResp := doMultipartFile(
			t,
			env.srv,
			http.MethodPost,
			"/api/session/"+sessionID+"/upload",
			"file",
			"closed-session.pdf",
			[]byte("%PDF-1.4\nclosed session upload\n"),
			"application/pdf",
			env.token,
		)
		if uploadResp.StatusCode != http.StatusConflict {
			t.Fatalf("expected upload on closed session 409, got %d body=%s", uploadResp.StatusCode, readAndCloseBody(t, uploadResp))
		}
		_ = uploadResp.Body.Close()

		jobKeys, err := env.rdb.Keys(env.ctx, "ocr:job:*").Result()
		if err != nil {
			t.Fatalf("list OCR job keys: %v", err)
		}
		if len(jobKeys) != 0 {
			t.Fatalf("expected no OCR jobs for closed session upload, got %v", jobKeys)
		}

		var persistedCount int
		if err = env.pool.QueryRow(env.ctx, `
			SELECT COUNT(*)
			FROM session_documents
			WHERE session_id = $1
		`, sessionID).Scan(&persistedCount); err != nil {
			t.Fatalf("count persisted session documents: %v", err)
		}
		if persistedCount != 0 {
			t.Fatalf("expected no persisted documents for closed session upload, found %d", persistedCount)
		}
	})
}
