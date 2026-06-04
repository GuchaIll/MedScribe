package usecase

import (
	"context"
	"fmt"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"go.uber.org/zap"
)

const (
	speakerRoleMethodReferenceSamples = "reference_voice_samples"
	speakerRoleStatusPending          = "pending"
	speakerRoleStatusCollecting       = "collecting"
	speakerRoleStatusReady            = "ready_for_matching"
	speakerRoleSampleStatusCaptured   = "captured"
)

var speakerRoleTargetRoles = []string{"Clinician", "Patient"}

func defaultSpeakerRoleCheckState() speakerRoleCheckState {
	return speakerRoleCheckState{
		Required:         true,
		Status:           speakerRoleStatusPending,
		Method:           speakerRoleMethodReferenceSamples,
		ExpectedSpeakers: 2,
		TargetRoles:      append([]string(nil), speakerRoleTargetRoles...),
		Instructions: []string{
			"Record one short voice sample for the clinician.",
			"Record one short voice sample for the patient.",
			"Keep the MVP constrained to exactly two speakers for this session.",
		},
	}
}

func buildSpeakerRoleCheckResponse(sessionID string, state speakerRoleCheckState) *SpeakerRoleCheckResponse {
	normalized := normalizeSpeakerRoleCheckState(state)
	resp := &SpeakerRoleCheckResponse{
		SessionID:        sessionID,
		Required:         normalized.Required,
		Status:           normalized.Status,
		Method:           normalized.Method,
		ExpectedSpeakers: normalized.ExpectedSpeakers,
		TargetRoles:      append([]string(nil), normalized.TargetRoles...),
		Instructions:     append([]string(nil), normalized.Instructions...),
	}
	if len(normalized.Samples) == 0 {
		return resp
	}
	resp.Samples = make([]SpeakerRoleSampleInfo, 0, len(normalized.Samples))
	for _, sample := range normalized.Samples {
		resp.Samples = append(resp.Samples, SpeakerRoleSampleInfo{
			Role:         sample.Role,
			Status:       sample.Status,
			FileName:     sample.FileName,
			MimeType:     sample.MimeType,
			UploadedAtMs: sample.UploadedAtMs,
		})
	}
	return resp
}

func normalizeSpeakerRoleCheckState(state speakerRoleCheckState) speakerRoleCheckState {
	if !state.Required && state.Status == "" && state.Method == "" && state.ExpectedSpeakers == 0 &&
		len(state.TargetRoles) == 0 && len(state.Instructions) == 0 && len(state.Samples) == 0 {
		return defaultSpeakerRoleCheckState()
	}
	if !state.Required {
		state.Required = true
	}
	if state.Method == "" {
		state.Method = speakerRoleMethodReferenceSamples
	}
	if state.ExpectedSpeakers == 0 {
		state.ExpectedSpeakers = 2
	}
	if len(state.TargetRoles) == 0 {
		state.TargetRoles = append([]string(nil), speakerRoleTargetRoles...)
	}
	if len(state.Instructions) == 0 {
		state.Instructions = defaultSpeakerRoleCheckState().Instructions
	}
	state.Status = deriveSpeakerRoleCheckStatus(state.Samples)
	return state
}

func deriveSpeakerRoleCheckStatus(samples []speakerRoleSampleState) string {
	seen := make(map[string]struct{}, len(samples))
	for _, sample := range samples {
		if sample.Role == "" || sample.Status != speakerRoleSampleStatusCaptured {
			continue
		}
		seen[sample.Role] = struct{}{}
	}
	switch len(seen) {
	case 0:
		return speakerRoleStatusPending
	case 1:
		return speakerRoleStatusCollecting
	default:
		return speakerRoleStatusReady
	}
}

func normalizeSpeakerRole(role string) (string, error) {
	switch strings.ToLower(strings.TrimSpace(role)) {
	case "clinician", "doctor", "provider":
		return "Clinician", nil
	case "patient":
		return "Patient", nil
	default:
		return "", entity.ErrInvalidInput
	}
}

func upsertSpeakerRoleSample(samples []speakerRoleSampleState, sample speakerRoleSampleState) []speakerRoleSampleState {
	if len(samples) == 0 {
		return []speakerRoleSampleState{sample}
	}
	next := append([]speakerRoleSampleState(nil), samples...)
	for idx := range next {
		if next[idx].Role == sample.Role {
			next[idx] = sample
			return next
		}
	}
	return append(next, sample)
}

func (uc *sessionUseCase) UploadSpeakerRoleSample(
	ctx context.Context,
	sessionID string,
	req UploadSpeakerRoleSampleRequest,
	fh *multipart.FileHeader,
	file multipart.File,
) (*SpeakerRoleCheckResponse, error) {
	session, err := uc.sessions.GetByID(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	if session.Status == entity.SessionStatusCompleted {
		return nil, entity.ErrSessionClosed
	}
	if fh == nil || file == nil {
		return nil, entity.ErrInvalidInput
	}

	role, err := normalizeSpeakerRole(req.Role)
	if err != nil {
		return nil, err
	}

	now := time.Now().UTC()
	sampleID := uuid.NewString()
	storagePath, err := spoolSpeakerRoleSample(sessionID, sampleID, role, fh.Filename, file)
	if err != nil {
		return nil, fmt.Errorf("upload speaker role sample: spool file: %w", err)
	}

	sample := speakerRoleSampleState{
		Role:         role,
		Status:       speakerRoleSampleStatusCaptured,
		FileName:     fh.Filename,
		MimeType:     fh.Header.Get("Content-Type"),
		StoragePath:  storagePath,
		UploadedAtMs: now.UnixMilli(),
	}

	var nextState speakerRoleCheckState
	if err = updateActiveSessionState(ctx, uc.redis, sessionID, func(state *activeSessionState) {
		state.SpeakerRoleCheck = normalizeSpeakerRoleCheckState(state.SpeakerRoleCheck)
		state.SpeakerRoleCheck.Samples = upsertSpeakerRoleSample(state.SpeakerRoleCheck.Samples, sample)
		state.SpeakerRoleCheck.Status = deriveSpeakerRoleCheckStatus(state.SpeakerRoleCheck.Samples)
		nextState = state.SpeakerRoleCheck
	}); err != nil {
		return nil, fmt.Errorf("upload speaker role sample: update active session state: %w", err)
	}

	uc.log.Info("speaker role sample captured",
		zap.String("session_id", sessionID),
		zap.String("role", role),
		zap.String("path", storagePath),
	)

	return buildSpeakerRoleCheckResponse(sessionID, nextState), nil
}

func spoolSpeakerRoleSample(
	sessionID string,
	sampleID string,
	role string,
	fileName string,
	src multipart.File,
) (string, error) {
	baseDir := filepath.Join(os.TempDir(), "medscribe", "speaker-role-check", sessionID)
	if err := os.MkdirAll(baseDir, 0o755); err != nil {
		return "", err
	}

	safeName := sanitizeFileName(fileName)
	if safeName == "" {
		safeName = "sample.wav"
	}
	targetPath := filepath.Join(baseDir, fmt.Sprintf("%s-%s-%s", sampleID, strings.ToLower(role), safeName))

	dst, err := os.Create(targetPath)
	if err != nil {
		return "", err
	}
	defer dst.Close()

	if _, err = io.Copy(dst, src); err != nil {
		return "", err
	}
	return targetPath, nil
}
