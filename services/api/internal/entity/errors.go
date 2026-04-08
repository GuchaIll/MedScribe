package entity

import "errors"

// Domain errors — returned by UseCases and translated to HTTP status codes
// by the controller layer. Never wrap transport-layer errors here.
var (
	ErrNotFound      = errors.New("resource not found")
	ErrAlreadyExists = errors.New("resource already exists")
	ErrStaleData     = errors.New("optimistic concurrency conflict — version mismatch")
	ErrUnauthorized  = errors.New("unauthorized")
	ErrForbidden     = errors.New("forbidden")
	ErrInvalidInput  = errors.New("invalid input")
	ErrSessionClosed = errors.New("session is already closed")
	ErrPipelineBusy  = errors.New("pipeline is already running for this session")
)
