package usecase

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	miniredis "github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/pkg/cache"
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

	endResp, err := uc.EndSession(context.Background(), "s1")
	if err != nil {
		t.Fatalf("end err: %v", err)
	}
	if endResp.Status != "completed" || endResp.Duration == nil || *endResp.Duration <= 0 {
		t.Fatalf("unexpected end response: %+v", endResp)
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

func TestSessionUploadDocumentNotImplemented(t *testing.T) {
	rdb := testRedis(t)
	uc := NewSessionUseCase(&mockSessionRepo{}, &mockPublisher{}, rdb, testCache(), "pipeline.trigger", zap.NewNop())
	_, err := uc.UploadDocument(context.Background(), "s1", newFileHeader("a.txt"), nil)
	if err == nil || !strings.Contains(err.Error(), "not yet implemented") {
		t.Fatalf("expected not implemented error, got %v", err)
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
