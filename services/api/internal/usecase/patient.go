package usecase

import (
	"context"
	"fmt"

	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/repo"
	"github.com/medscribe/services/api/internal/usecase/labanalysis"
	"go.uber.org/zap"
)

// patientUseCase implements PatientUseCase. Computation-heavy operations
// (lab trend analysis, risk scoring) are delegated to the labanalysis package,
// which contains pure functions with no repository calls or side effects.
type patientUseCase struct {
	patients repo.PatientRepository
	log      *zap.Logger
}

// NewPatientUseCase wires the patient use-case.
func NewPatientUseCase(patients repo.PatientRepository, log *zap.Logger) PatientUseCase {
	return &patientUseCase{patients: patients, log: log}
}

func (uc *patientUseCase) GetProfile(ctx context.Context, patientID string) (*PatientProfileResponse, error) {
	p, err := uc.patients.GetByID(ctx, patientID)
	if err != nil {
		return nil, err
	}

	records, err := uc.patients.HistoryRecords(ctx, patientID, 100, 0)
	if err != nil {
		uc.log.Warn("could not load history records for profile",
			zap.String("patient_id", patientID), zap.Error(err))
		records = nil
	}

	labTrends, err := labanalysis.ComputeLabTrends(records, nil)
	if err != nil {
		uc.log.Warn("could not compute lab trends", zap.Error(err))
	}

	riskScore := labanalysis.ComputeRiskScore(p, records)

	return &PatientProfileResponse{
		Patient:     p,
		LabTrends:   labTrends,
		RiskScore:   riskScore,
		RecordCount: len(records),
	}, nil
}

func (uc *patientUseCase) GetLabTrends(
	ctx context.Context, patientID string, testName *string,
) ([]entity.LabTrend, error) {
	records, err := uc.patients.HistoryRecords(ctx, patientID, 100, 0)
	if err != nil {
		return nil, fmt.Errorf("get lab trends: %w", err)
	}
	return labanalysis.ComputeLabTrends(records, testName)
}

func (uc *patientUseCase) GetRiskScore(ctx context.Context, patientID string) (*entity.RiskScore, error) {
	p, err := uc.patients.GetByID(ctx, patientID)
	if err != nil {
		return nil, err
	}
	records, _ := uc.patients.HistoryRecords(ctx, patientID, 20, 0)
	return labanalysis.ComputeRiskScore(p, records), nil
}

func (uc *patientUseCase) GetHistoryRecords(
	ctx context.Context, patientID string, limit, offset int,
) ([]*entity.MedicalRecord, error) {
	return uc.patients.HistoryRecords(ctx, patientID, limit, offset)
}
