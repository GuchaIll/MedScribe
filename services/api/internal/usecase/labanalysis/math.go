// Package labanalysis provides pure computation functions for clinical lab
// trend analysis and risk scoring. Functions accept entity types as parameters
// and have no repository calls or side effects, making them independently
// testable and reusable across multiple use-cases.
package labanalysis

import (
	"github.com/medscribe/services/api/internal/entity"
)

// ComputeLabTrends extracts and aggregates lab values from a slice of medical
// records, optionally filtered to a single test name. The result is a list of
// LabTrend entries ordered by test name, each carrying the ordered value
// series, derived trend direction, and min/max bounds.
//
// This ports the PatientModel.compute_lab_trends logic from patient_model.py.
// Full statistical analysis (regression, outlier detection) is deferred to the
// orchestrator in Phase 8.
func ComputeLabTrends(records []*entity.MedicalRecord, filterName *string) ([]entity.LabTrend, error) {
	type obs struct {
		val float64
		ts  int64
	}
	byTest := map[string][]obs{}

	for _, rec := range records {
		labs, _ := extractList(rec.StructuredData, "labs")
		for _, lab := range labs {
			lm, ok := lab.(map[string]any)
			if !ok {
				continue
			}
			name, _ := lm["test_name"].(string)
			if name == "" {
				continue
			}
			if filterName != nil && name != *filterName {
				continue
			}
			val, _ := toFloat64(lm["value"])
			ts := rec.CreatedAt.UnixMilli()
			byTest[name] = append(byTest[name], obs{val: val, ts: ts})
		}
	}

	trends := make([]entity.LabTrend, 0, len(byTest))
	for name, obs := range byTest {
		vals := make([]float64, len(obs))
		ts := make([]int64, len(obs))
		for i, o := range obs {
			vals[i] = o.val
			ts[i] = o.ts
		}
		trend := deriveTrend(vals)
		min, max := minMax(vals)
		trends = append(trends, entity.LabTrend{
			TestName:   name,
			Values:     vals,
			Timestamps: ts,
			Trend:      trend,
			Min:        min,
			Max:        max,
			Latest:     vals[len(vals)-1],
		})
	}
	return trends, nil
}

// ComputeRiskScore returns a basic composite risk score for a patient given
// their demographics and record history. Full ML-based scoring will replace
// this heuristic in Phase 8 (Evaluation Framework) via the Rust inference
// service gRPC endpoint.
func ComputeRiskScore(p *entity.Patient, records []*entity.MedicalRecord) *entity.RiskScore {
	score := 0.0
	factors := []string{}

	if p.Age != nil && *p.Age >= 65 {
		score += 0.2
		factors = append(factors, "age >= 65")
	}
	if len(records) == 0 {
		score += 0.1
		factors = append(factors, "no prior records")
	}

	level := "low"
	switch {
	case score >= 0.7:
		level = "critical"
	case score >= 0.5:
		level = "high"
	case score >= 0.3:
		level = "moderate"
	}

	return &entity.RiskScore{
		PatientID: p.ID,
		Score:     score,
		Level:     level,
		Factors:   factors,
	}
}

// ─── internal helpers ─────────────────────────────────────────────────────────

// extractList retrieves a []any value at key from a map[string]any.
func extractList(m map[string]any, key string) ([]any, bool) {
	v, ok := m[key]
	if !ok {
		return nil, false
	}
	l, ok := v.([]any)
	return l, ok
}

// toFloat64 converts common numeric interface{} types to float64.
func toFloat64(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case float32:
		return float64(n), true
	case int:
		return float64(n), true
	}
	return 0, false
}

// minMax returns the minimum and maximum of a float64 slice.
// Returns (0, 0) for an empty slice.
func minMax(vals []float64) (float64, float64) {
	if len(vals) == 0 {
		return 0, 0
	}
	mn, mx := vals[0], vals[0]
	for _, v := range vals[1:] {
		if v < mn {
			mn = v
		}
		if v > mx {
			mx = v
		}
	}
	return mn, mx
}

// deriveTrend classifies a float64 time-series as "worsening", "improving",
// or "stable" by comparing the first and last values using a 5% relative delta
// threshold.
func deriveTrend(vals []float64) string {
	if len(vals) < 2 {
		return "stable"
	}
	first := vals[0]
	last := vals[len(vals)-1]
	delta := last - first
	threshold := 0.05 * first
	if delta > threshold {
		return "worsening"
	}
	if delta < -threshold {
		return "improving"
	}
	return "stable"
}
