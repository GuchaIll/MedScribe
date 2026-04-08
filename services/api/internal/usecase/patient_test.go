package usecase

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

func TestPatientProfileSuccessAndHistoryFallback(t *testing.T) {
	now := time.Now()
	uc := NewPatientUseCase(&mockPatientRepo{
		getByIDFn: func(_ context.Context, id string) (*entity.Patient, error) {
			age := 70
			return &entity.Patient{ID: id, Age: &age}, nil
		},
		historyRecordsFn: func(_ context.Context, _ string, _, _ int) ([]*entity.MedicalRecord, error) {
			return []*entity.MedicalRecord{{
				ID:        "r1",
				CreatedAt: now,
				StructuredData: map[string]any{
					"labs": []any{
						map[string]any{"test_name": "A1c", "value": 7.1},
					},
				},
			}}, nil
		},
	}, zap.NewNop())

	profile, err := uc.GetProfile(context.Background(), "p1")
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if profile.RecordCount != 1 || profile.RiskScore == nil {
		t.Fatalf("unexpected profile: %+v", profile)
	}

	uc2 := NewPatientUseCase(&mockPatientRepo{
		getByIDFn: func(_ context.Context, id string) (*entity.Patient, error) {
			return &entity.Patient{ID: id}, nil
		},
		historyRecordsFn: func(_ context.Context, _ string, _, _ int) ([]*entity.MedicalRecord, error) {
			return nil, errors.New("db down")
		},
	}, zap.NewNop())
	profile, err = uc2.GetProfile(context.Background(), "p2")
	if err != nil {
		t.Fatalf("unexpected err on history fallback: %v", err)
	}
	if profile.RecordCount != 0 {
		t.Fatalf("expected fallback to empty records, got %d", profile.RecordCount)
	}
}

func TestPatientLabTrendsAndRiskScore(t *testing.T) {
	now := time.Now()
	uc := NewPatientUseCase(&mockPatientRepo{
		getByIDFn: func(_ context.Context, id string) (*entity.Patient, error) {
			age := 50
			return &entity.Patient{ID: id, Age: &age}, nil
		},
		historyRecordsFn: func(_ context.Context, _ string, _, _ int) ([]*entity.MedicalRecord, error) {
			return []*entity.MedicalRecord{
				{
					CreatedAt: now.Add(-time.Hour),
					StructuredData: map[string]any{
						"labs": []any{map[string]any{"test_name": "A1c", "value": 7.0}},
					},
				},
				{
					CreatedAt: now,
					StructuredData: map[string]any{
						"labs": []any{map[string]any{"test_name": "A1c", "value": 8.0}},
					},
				},
			}, nil
		},
	}, zap.NewNop())

	filter := "A1c"
	trends, err := uc.GetLabTrends(context.Background(), "p1", &filter)
	if err != nil {
		t.Fatalf("unexpected trends err: %v", err)
	}
	if len(trends) != 1 || trends[0].Trend == "" {
		t.Fatalf("unexpected trends: %+v", trends)
	}

	risk, err := uc.GetRiskScore(context.Background(), "p1")
	if err != nil {
		t.Fatalf("unexpected risk err: %v", err)
	}
	if risk.PatientID != "p1" || risk.Level == "" {
		t.Fatalf("unexpected risk score: %+v", risk)
	}
}

func TestPatientLabTrendsErrorPropagation(t *testing.T) {
	uc := NewPatientUseCase(&mockPatientRepo{
		historyRecordsFn: func(_ context.Context, _ string, _, _ int) ([]*entity.MedicalRecord, error) {
			return nil, errors.New("db fail")
		},
	}, zap.NewNop())

	_, err := uc.GetLabTrends(context.Background(), "p1", nil)
	if err == nil {
		t.Fatalf("expected error")
	}
}
