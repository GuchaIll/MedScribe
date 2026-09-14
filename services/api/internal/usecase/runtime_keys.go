package usecase

import (
	"fmt"
	"time"
)

const (
	transcriptBufferTTL = 24 * time.Hour
)

func transcriptBufferKey(sessionID string) string {
	return fmt.Sprintf("session:%s:transcript:pending", sessionID)
}

func activeSessionKey(sessionID string) string {
	return fmt.Sprintf("session:%s:active", sessionID)
}

func audioSegmentJobKey(segmentID string) string {
	return fmt.Sprintf("transcript:segment:%s", segmentID)
}

func ocrJobStatusKey(jobID string) string {
	return fmt.Sprintf("ocr:job:%s", jobID)
}

func assistantCachePrefix(sessionID string) string {
	return fmt.Sprintf("session:%s:assistant", sessionID)
}
