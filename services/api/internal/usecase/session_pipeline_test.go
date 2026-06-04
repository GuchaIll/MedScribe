package usecase

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	miniredis "github.com/alicebob/miniredis/v2"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/pkg/cache"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

func testCache() *cache.TTLCache {
	return cache.New(5 * time.Second)
}

func testRedis(t *testing.T) *redis.Client {
	t.Helper()
	mr := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	t.Cleanup(func() {
		_ = client.Close()
		mr.Close()
	})
	return client
}

func TestSessionStartAndEnd(t *testing.T) {
	rdb := testRedis(t)
	repo := &mockSessionRepo{
		createFn: func(_ context.Context, s *entity.Session) (*entity.Session, error) {
			s.ID = "s1"
			return s, nil
		},
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			started := time.Now().Add(-2 * time.Minute)
			return &entity.Session{
				ID:        "s1",
				Status:    entity.SessionStatusActive,
				StartedAt: started,
			}, nil
		},
		updateFn: func(_ context.Context, s *entity.Session) (*entity.Session, error) {
			return s, nil
		},
	}
	uc := NewSessionUseCase(repo, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	startResp, err := uc.StartSession(context.Background(), "test-user-id")
	if err != nil {
		t.Fatalf("start err: %v", err)
	}
	if startResp.SessionID == "" || startResp.Status != "active" {
		t.Fatalf("unexpected start response: %+v", startResp)
	}
	if startResp.SpeakerRoleCheck == nil || startResp.SpeakerRoleCheck.Status != speakerRoleStatusPending {
		t.Fatalf("expected speaker role check in start response, got %+v", startResp.SpeakerRoleCheck)
	}
	if startResp.SpeakerRoleCheck.ExpectedSpeakers != 2 {
		t.Fatalf("expected two-speaker onboarding, got %+v", startResp.SpeakerRoleCheck)
	}

	endResp, err := uc.EndSession(context.Background(), "s1")
	if err != nil {
		t.Fatalf("end err: %v", err)
	}
	if endResp.Status != "completed" || endResp.Duration == nil || *endResp.Duration <= 0 {
		t.Fatalf("unexpected end response: %+v", endResp)
	}
	state, err := readActiveSessionState(context.Background(), rdb, "s1")
	if err != nil {
		t.Fatalf("read active session state: %v", err)
	}
	if state == nil || state.Status != "completed" {
		t.Fatalf("expected completed active session state, got %+v", state)
	}
	if state.SpeakerRoleCheck.ExpectedSpeakers != 2 {
		t.Fatalf("expected speaker role check state to persist, got %+v", state.SpeakerRoleCheck)
	}
}

func TestUploadSpeakerRoleSampleCapturesTwoRoleOnboarding(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		createFn: func(_ context.Context, s *entity.Session) (*entity.Session, error) {
			s.ID = "s1"
			return s, nil
		},
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	if _, err := uc.StartSession(context.Background(), "doctor-1"); err != nil {
		t.Fatalf("start session: %v", err)
	}

	clinicianResp, err := uc.UploadSpeakerRoleSample(
		context.Background(),
		"s1",
		UploadSpeakerRoleSampleRequest{Role: "clinician"},
		newFileHeader("clinician.wav"),
		newMultipartFile("clinician-audio"),
	)
	if err != nil {
		t.Fatalf("upload clinician sample: %v", err)
	}
	if clinicianResp.Status != speakerRoleStatusCollecting {
		t.Fatalf("expected collecting after first sample, got %+v", clinicianResp)
	}

	patientResp, err := uc.UploadSpeakerRoleSample(
		context.Background(),
		"s1",
		UploadSpeakerRoleSampleRequest{Role: "patient"},
		newFileHeader("patient.wav"),
		newMultipartFile("patient-audio"),
	)
	if err != nil {
		t.Fatalf("upload patient sample: %v", err)
	}
	if patientResp.Status != speakerRoleStatusReady || len(patientResp.Samples) != 2 {
		t.Fatalf("expected ready state with two samples, got %+v", patientResp)
	}

	state, err := readActiveSessionState(context.Background(), rdb, "s1")
	if err != nil {
		t.Fatalf("read active session state: %v", err)
	}
	if state == nil || state.SpeakerRoleCheck.Status != speakerRoleStatusReady {
		t.Fatalf("expected ready speaker role check state, got %+v", state)
	}
}

func TestUploadSpeakerRoleSampleRejectsUnknownRole(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	_, err := uc.UploadSpeakerRoleSample(
		context.Background(),
		"s1",
		UploadSpeakerRoleSampleRequest{Role: "scribe"},
		newFileHeader("sample.wav"),
		newMultipartFile("audio"),
	)
	if !errors.Is(err, entity.ErrInvalidInput) {
		t.Fatalf("expected ErrInvalidInput, got %v", err)
	}
}

func TestUploadAudioSegmentQueuesTranscriptJob(t *testing.T) {
	rdb := testRedis(t)
	var (
		publishedTopic string
		publishedKey   string
		publishedBody  map[string]any
	)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{
		publishJSONFn: func(_ context.Context, topic, key string, v any) error {
			publishedTopic = topic
			publishedKey = key
			body, ok := v.(audioSegmentIngestMsg)
			if !ok {
				t.Fatalf("expected audioSegmentIngestMsg, got %T", v)
			}
			publishedBody = map[string]any{
				"segment_id": body.SegmentID,
				"mime_type":  body.MimeType,
			}
			return nil
		},
	}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	resp, err := uc.UploadAudioSegment(
		context.Background(),
		"s1",
		UploadAudioSegmentRequest{
			SegmentID:         "seg-1",
			StartedAtMs:       100,
			EndedAtMs:         250,
			SampleRateHz:      16000,
			MimeType:          "audio/wav",
			OptimisticText:    "hello",
			OptimisticSpeaker: "Patient",
		},
		newFileHeader("segment.wav"),
		newMultipartFile("wav-bytes"),
	)
	if err != nil {
		t.Fatalf("upload audio segment: %v", err)
	}
	if !resp.Accepted || resp.Status != "queued" {
		t.Fatalf("unexpected response: %+v", resp)
	}
	if publishedTopic != audioIngestTopic || publishedKey != "s1" || publishedBody["segment_id"] != "seg-1" {
		t.Fatalf("unexpected published audio job: topic=%q key=%q body=%+v", publishedTopic, publishedKey, publishedBody)
	}

	state, err := readActiveSessionState(context.Background(), rdb, "s1")
	if err != nil {
		t.Fatalf("read active session state: %v", err)
	}
	if state == nil || len(state.TranscriptJobs) != 1 || state.TranscriptJobs[0].OptimisticSpeaker != "Patient" {
		t.Fatalf("expected queued transcript job in active state, got %+v", state)
	}
}

func TestSessionEndFlushesBufferedTranscript(t *testing.T) {
	rdb := testRedis(t)
	var updatedWorkflowState *string
	repo := &mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			started := time.Now().Add(-30 * time.Second)
			return &entity.Session{
				ID:        "s1",
				Status:    entity.SessionStatusActive,
				StartedAt: started,
			}, nil
		},
		updateFn: func(_ context.Context, s *entity.Session) (*entity.Session, error) {
			updatedWorkflowState = s.WorkflowState
			return s, nil
		},
	}
	uc := NewSessionUseCase(repo, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	for _, req := range []TranscribeRequest{
		{SessionID: "s1", Speaker: "doctor", Text: "How are you feeling today?"},
		{SessionID: "s1", Speaker: "patient", Text: "Shortness of breath is better."},
	} {
		if _, err := uc.ProcessTranscription(context.Background(), req); err != nil {
			t.Fatalf("buffer turn: %v", err)
		}
	}

	if _, err := uc.EndSession(context.Background(), "s1"); err != nil {
		t.Fatalf("end session: %v", err)
	}
	if updatedWorkflowState == nil || *updatedWorkflowState == "" {
		t.Fatalf("expected workflow state to be flushed")
	}

	var state map[string]any
	if err := json.Unmarshal([]byte(*updatedWorkflowState), &state); err != nil {
		t.Fatalf("decode workflow state: %v", err)
	}
	rawTurns, ok := state["transcript_turns"]
	if !ok {
		t.Fatalf("expected transcript_turns in workflow state")
	}
	b, err := json.Marshal(rawTurns)
	if err != nil {
		t.Fatalf("marshal transcript turns: %v", err)
	}
	var turns []entity.TranscriptTurn
	if err = json.Unmarshal(b, &turns); err != nil {
		t.Fatalf("unmarshal transcript turns: %v", err)
	}
	if len(turns) != 2 {
		t.Fatalf("expected 2 transcript turns, got %d", len(turns))
	}
	if remaining, err := rdb.LLen(context.Background(), transcriptBufferKey("s1")).Result(); err != nil || remaining != 0 {
		t.Fatalf("expected empty transcript buffer, remaining=%d err=%v", remaining, err)
	}
}

func TestSessionEndClosedReturnsConflict(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{Status: entity.SessionStatusCompleted}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	_, err := uc.EndSession(context.Background(), "s1")
	if err != entity.ErrSessionClosed {
		t.Fatalf("expected ErrSessionClosed, got %v", err)
	}
}

func TestSessionProcessTranscriptionRequiresSession(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return nil, entity.ErrNotFound
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	_, err := uc.ProcessTranscription(context.Background(), TranscribeRequest{
		SessionID: "missing",
		Text:      "hello",
		Speaker:   "doctor",
	})
	if err != entity.ErrNotFound {
		t.Fatalf("expected ErrNotFound, got %v", err)
	}
}

func TestSessionProcessTranscriptionBuffersTurnsInRedis(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	resp1, err := uc.ProcessTranscription(context.Background(), TranscribeRequest{
		SessionID: "s1",
		Text:      "First line",
		Speaker:   "doctor",
	})
	if err != nil {
		t.Fatalf("first transcription err: %v", err)
	}
	resp2, err := uc.ProcessTranscription(context.Background(), TranscribeRequest{
		SessionID: "s1",
		Text:      "Second line",
		Speaker:   "patient",
	})
	if err != nil {
		t.Fatalf("second transcription err: %v", err)
	}
	if resp1.TurnsStored != 1 || resp2.TurnsStored != 2 {
		t.Fatalf("unexpected buffered counts: resp1=%+v resp2=%+v", resp1, resp2)
	}
}

func TestSessionProcessTranscriptionRejectsClosedSession(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusCompleted}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	_, err := uc.ProcessTranscription(context.Background(), TranscribeRequest{
		SessionID: "s1",
		Text:      "hello",
		Speaker:   "doctor",
	})
	if err != entity.ErrSessionClosed {
		t.Fatalf("expected ErrSessionClosed, got %v", err)
	}
}

func TestSessionPassthroughMethods(t *testing.T) {
	rdb := testRedis(t)
	repo := &mockSessionRepo{
		getRecordFn: func(_ context.Context, _ string) (*entity.MedicalRecord, error) {
			return &entity.MedicalRecord{ID: "mr1"}, nil
		},
		getDocumentsFn: func(_ context.Context, _ string) ([]*entity.Document, error) {
			return []*entity.Document{{ID: "d1"}}, nil
		},
		getQueueFn: func(_ context.Context, _ string) ([]*entity.QueueItem, error) {
			return []*entity.QueueItem{{ID: "q1"}}, nil
		},
		updateQueueItemFn: func(_ context.Context, _, _, _ string) (*entity.QueueItem, error) {
			return &entity.QueueItem{ID: "q1", Status: "approved"}, nil
		},
	}
	uc := NewSessionUseCase(repo, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	rec, err := uc.GetRecord(context.Background(), "s1")
	if err != nil || rec.ID != "mr1" {
		t.Fatalf("unexpected record result: %+v, err=%v", rec, err)
	}
	docs, err := uc.GetDocuments(context.Background(), "s1")
	if err != nil || len(docs) != 1 {
		t.Fatalf("unexpected documents: %+v, err=%v", docs, err)
	}
	items, err := uc.GetQueue(context.Background(), "s1")
	if err != nil || len(items) != 1 {
		t.Fatalf("unexpected queue: %+v, err=%v", items, err)
	}
	item, err := uc.UpdateQueueItem(context.Background(), "s1", "q1", "approved")
	if err != nil || item.Status != "approved" {
		t.Fatalf("unexpected updated queue item: %+v, err=%v", item, err)
	}
}

func TestSessionUploadDocumentQueuesOCRJob(t *testing.T) {
	rdb := testRedis(t)
	var publishedTopic string
	var publishedPayload map[string]any
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{
		publishJSONFn: func(_ context.Context, topic, _ string, payload any) error {
			publishedTopic = topic
			publishedPayload = payload.(map[string]any)
			return nil
		},
	}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	doc, err := uc.UploadDocument(context.Background(), "s1", newFileHeader("scan.pdf"), newMultipartFile("pdf-bytes"))
	if err != nil {
		t.Fatalf("upload document err: %v", err)
	}
	if doc.ID == "" || doc.StoragePath == "" {
		t.Fatalf("expected queued document metadata, got %+v", doc)
	}
	if publishedTopic != ocrJobsTopic {
		t.Fatalf("expected OCR publish topic %q, got %q", ocrJobsTopic, publishedTopic)
	}
	if publishedPayload["document_id"] != doc.ID || publishedPayload["session_id"] != "s1" {
		t.Fatalf("unexpected OCR publish payload: %+v", publishedPayload)
	}
	docs, err := uc.GetDocuments(context.Background(), "s1")
	if err != nil {
		t.Fatalf("get documents err: %v", err)
	}
	if len(docs) != 1 || docs[0].ID != doc.ID {
		t.Fatalf("expected pending document in document list, got %+v", docs)
	}
	state, err := readActiveSessionState(context.Background(), rdb, "s1")
	if err != nil {
		t.Fatalf("read active session state: %v", err)
	}
	if state == nil || len(state.PendingDocuments) != 1 || len(state.OCRJobs) != 1 {
		t.Fatalf("expected pending doc and OCR job in active session state, got %+v", state)
	}
	jobID, _ := publishedPayload["job_id"].(string)
	if jobID == "" {
		t.Fatalf("expected OCR publish payload to contain job_id")
	}
	jobStatus, err := rdb.Get(context.Background(), ocrJobStatusKey(jobID)).Result()
	if err != nil || !strings.Contains(jobStatus, "\"status\":\"queued\"") {
		t.Fatalf("expected queued OCR job status, value=%q err=%v", jobStatus, err)
	}
}

func TestGetDocumentsMergesPersistedAndActiveState(t *testing.T) {
	rdb := testRedis(t)
	now := time.Now().UTC()
	uc := NewSessionUseCase(&mockSessionRepo{
		getDocumentsFn: func(_ context.Context, _ string) ([]*entity.Document, error) {
			return []*entity.Document{{
				ID:           "doc-1",
				SessionID:    "s1",
				OriginalName: "scan.pdf",
				Status:       "processed",
				CreatedAt:    now,
			}}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	if err := updateActiveSessionState(context.Background(), rdb, "s1", func(state *activeSessionState) {
		state.PendingDocuments = []entity.Document{{
			ID:                "doc-1",
			SessionID:         "s1",
			OriginalName:      "scan.pdf",
			Status:            "conflicts",
			ConflictsDetected: 2,
			CreatedAt:         now,
		}}
	}); err != nil {
		t.Fatalf("update active session state: %v", err)
	}

	docs, err := uc.GetDocuments(context.Background(), "s1")
	if err != nil {
		t.Fatalf("get documents err: %v", err)
	}
	if len(docs) != 1 {
		t.Fatalf("expected deduped documents, got %+v", docs)
	}
	if docs[0].Status != "conflicts" || docs[0].ConflictsDetected != 2 {
		t.Fatalf("expected active-session document to override persisted doc, got %+v", docs[0])
	}
}

func TestPipelineTriggerAndStatus(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{
		getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
			return &entity.Session{ID: "s1", Status: entity.SessionStatusActive}, nil
		},
	}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

	triggerResp, err := uc.TriggerPipeline(context.Background(), TriggerPipelineRequest{
		SessionID: "s1",
		PatientID: "p1",
		DoctorID:  "d1",
		Segments:  []TranscriptSegmentInput{{Speaker: "doctor", RawText: "Hi"}},
	})
	if err != nil {
		t.Fatalf("trigger err: %v", err)
	}
	if !triggerResp.Accepted || triggerResp.PipelineID == "" {
		t.Fatalf("unexpected trigger response: %+v", triggerResp)
	}

	status, err := uc.GetPipelineStatus(context.Background(), "s1")
	if err != nil {
		t.Fatalf("status err: %v", err)
	}
	if status.Status != "pending" || status.PipelineID == "" {
		t.Fatalf("unexpected status: %+v", status)
	}
}

func TestPipelineFailurePaths(t *testing.T) {
	t.Run("closed session", func(t *testing.T) {
		rdb := testRedis(t)
		uc := NewSessionUseCase(&mockSessionRepo{
			getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
				return &entity.Session{Status: entity.SessionStatusCompleted}, nil
			},
		}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())
		_, err := uc.TriggerPipeline(context.Background(), TriggerPipelineRequest{SessionID: "s1"})
		if err != entity.ErrSessionClosed {
			t.Fatalf("expected ErrSessionClosed, got %v", err)
		}
	})

	t.Run("publish failure", func(t *testing.T) {
		rdb := testRedis(t)
		uc := NewSessionUseCase(&mockSessionRepo{
			getByIDFn: func(_ context.Context, _ string) (*entity.Session, error) {
				return &entity.Session{Status: entity.SessionStatusActive}, nil
			},
		}, &mockPublisher{
			publishJSONFn: func(_ context.Context, _, _ string, _ any) error {
				return errors.New("kafka down")
			},
		}, rdb, testCache(), "pipeline.trigger", zap.NewNop())
		_, err := uc.TriggerPipeline(context.Background(), TriggerPipelineRequest{SessionID: "s1"})
		if err == nil || !strings.Contains(err.Error(), "publish to Kafka") {
			t.Fatalf("expected publish error, got %v", err)
		}
	})

	t.Run("not found and bad json", func(t *testing.T) {
		rdb := testRedis(t)
		uc := NewSessionUseCase(&mockSessionRepo{}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())

		_, err := uc.GetPipelineStatus(context.Background(), "missing")
		if err != entity.ErrNotFound {
			t.Fatalf("expected ErrNotFound, got %v", err)
		}

		if err = rdb.Set(context.Background(), "pipeline:s2", "{bad-json", time.Hour).Err(); err != nil {
			t.Fatalf("seed bad json: %v", err)
		}
		_, err = uc.GetPipelineStatus(context.Background(), "s2")
		if err == nil || !strings.Contains(err.Error(), "unmarshal") {
			t.Fatalf("expected unmarshal error, got %v", err)
		}
	})
}
