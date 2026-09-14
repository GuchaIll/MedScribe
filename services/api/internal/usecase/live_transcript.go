package usecase

import "context"

func (uc *sessionUseCase) GetLiveTranscript(ctx context.Context, sessionID string) (*LiveTranscriptResponse, error) {
	state, err := readActiveSessionState(ctx, uc.redis, sessionID)
	if err != nil {
		return nil, err
	}
	if state == nil {
		return &LiveTranscriptResponse{SessionID: sessionID}, nil
	}

	resp := &LiveTranscriptResponse{
		SessionID:             sessionID,
		TranscriptJobs:        make([]LiveTranscriptJob, 0, len(state.TranscriptJobs)),
		AuthoritativeSegments: make([]LiveAuthoritativeSegment, 0, len(state.AuthoritativeSegments)),
	}
	for _, job := range state.TranscriptJobs {
		resp.TranscriptJobs = append(resp.TranscriptJobs, LiveTranscriptJob{
			SegmentID:         job.SegmentID,
			Status:            job.Status,
			OptimisticText:    job.OptimisticText,
			OptimisticSpeaker: job.OptimisticSpeaker,
			Error:             job.Error,
		})
	}
	for _, seg := range state.AuthoritativeSegments {
		resp.AuthoritativeSegments = append(resp.AuthoritativeSegments, LiveAuthoritativeSegment{
			SegmentID:               seg.SegmentID,
			Text:                    seg.Text,
			SpeakerID:               seg.SpeakerID,
			SpeakerRole:             seg.SpeakerRole,
			RoleConfidence:          seg.RoleConfidence,
			TranscriptionConfidence: seg.TranscriptionConfidence,
			Source:                  seg.Source,
		})
	}
	return resp, nil
}
