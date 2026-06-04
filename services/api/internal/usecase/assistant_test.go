package usecase

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

func TestAssistantQueryUsesActiveSessionTranscript(t *testing.T) {
	rdb := testRedis(t)
	err := writeActiveSessionState(context.Background(), rdb, &activeSessionState{
		SessionID: "s1",
		Status:    string(entity.SessionStatusActive),
		RecentTranscript: []entity.TranscriptTurn{
			{SessionID: "s1", Speaker: "doctor", Text: "How is your breathing today?", Timestamp: time.Now().UTC()},
			{SessionID: "s1", Speaker: "patient", Text: "Breathing is much better than yesterday.", Timestamp: time.Now().UTC()},
		},
	})
	if err != nil {
		t.Fatalf("seed active session state: %v", err)
	}

	uc := NewAssistantUseCase(
		rdb,
		&mockSessionRepo{},
		&mockPatientRepo{},
		zap.NewNop(),
	)

	resp, err := uc.Query(context.Background(), "s1", "", "What did we discuss in the session?")
	if err != nil {
		t.Fatalf("assistant query err: %v", err)
	}
	if !strings.Contains(resp.Answer, "doctor:") || !strings.Contains(resp.Answer, "patient:") {
		t.Fatalf("expected transcript-backed answer, got %+v", resp)
	}
	if resp.LowConfidence {
		t.Fatalf("expected direct transcript answer to be high confidence")
	}
}

func TestAssistantQueryUsesPatientFacts(t *testing.T) {
	rdb := testRedis(t)
	age := 68
	sex := "female"
	uc := NewAssistantUseCase(
		rdb,
		&mockSessionRepo{},
		&mockPatientRepo{
			getByIDFn: func(_ context.Context, id string) (*entity.Patient, error) {
				return &entity.Patient{
					ID:       id,
					FullName: "Jane Smith",
					MRN:      "MRN-42",
					Age:      &age,
					Sex:      &sex,
					DOB:      time.Date(1958, time.July, 9, 0, 0, 0, 0, time.UTC),
				}, nil
			},
		},
		zap.NewNop(),
	)

	resp, err := uc.Query(context.Background(), "", "p1", "What is the patient's MRN?")
	if err != nil {
		t.Fatalf("assistant query err: %v", err)
	}
	if !strings.Contains(resp.Answer, "MRN-42") {
		t.Fatalf("expected patient DB-backed answer, got %+v", resp)
	}
	if resp.LowConfidence {
		t.Fatalf("expected exact patient fact answer to be high confidence")
	}
}
