package labanalysis

import (
	"testing"
	"time"

	"github.com/medscribe/services/api/internal/entity"
)

func TestComputeLabTrendsBasicAndFiltered(t *testing.T) {
	now := time.Now()
	records := []*entity.MedicalRecord{
		{
			CreatedAt: now.Add(-2 * time.Hour),
			StructuredData: map[string]any{
				"labs": []any{
					map[string]any{"test_name": "A1c", "value": 7.0},
					map[string]any{"test_name": "LDL", "value": 100.0},
				},
			},
		},
		{
			CreatedAt: now,
			StructuredData: map[string]any{
				"labs": []any{
					map[string]any{"test_name": "A1c", "value": 8.0},
				},
			},
		},
	}

	all, err := ComputeLabTrends(records, nil)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(all) != 2 {
		t.Fatalf("expected 2 trend groups, got %d", len(all))
	}

	filter := "A1c"
	a1cOnly, err := ComputeLabTrends(records, &filter)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(a1cOnly) != 1 {
		t.Fatalf("expected 1 filtered trend group, got %d", len(a1cOnly))
	}
	if a1cOnly[0].Min != 7.0 || a1cOnly[0].Max != 8.0 || a1cOnly[0].Latest != 8.0 {
		t.Fatalf("unexpected min/max/latest: %+v", a1cOnly[0])
	}
	if a1cOnly[0].Trend != "worsening" {
		t.Fatalf("expected worsening trend, got %s", a1cOnly[0].Trend)
	}
}

func TestComputeRiskScoreThresholds(t *testing.T) {
	age70 := 70
	score := ComputeRiskScore(&entity.Patient{ID: "p1", Age: &age70}, nil)
	if score.Level != "moderate" || score.Score < 0.3 {
		t.Fatalf("unexpected high-age empty-history score: %+v", score)
	}

	age50 := 50
	score = ComputeRiskScore(&entity.Patient{ID: "p2", Age: &age50}, []*entity.MedicalRecord{{ID: "r1"}})
	if score.Level != "low" {
		t.Fatalf("expected low level for baseline score, got %+v", score)
	}
}

func TestDeriveTrendImprovingStableWorsening(t *testing.T) {
	if got := deriveTrend([]float64{10, 9}); got != "improving" {
		t.Fatalf("expected improving, got %s", got)
	}
	if got := deriveTrend([]float64{10, 10.1}); got != "stable" {
		t.Fatalf("expected stable around 5%% threshold, got %s", got)
	}
	if got := deriveTrend([]float64{10, 11}); got != "worsening" {
		t.Fatalf("expected worsening, got %s", got)
	}
}
