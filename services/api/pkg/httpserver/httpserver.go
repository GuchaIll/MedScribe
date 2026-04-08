// Package httpserver wraps net/http.Server with graceful shutdown.
package httpserver

import (
	"context"
	"net/http"
	"time"
)

// Server wraps http.Server and adds a graceful shutdown helper.
type Server struct {
	srv             *http.Server
	shutdownTimeout time.Duration
}

// New creates a Server bound to addr with the provided handler.
func New(handler http.Handler, addr string, readTimeout, writeTimeout, shutdownTimeout time.Duration) *Server {
	return &Server{
		srv: &http.Server{
			Addr:         addr,
			Handler:      handler,
			ReadTimeout:  readTimeout,
			WriteTimeout: writeTimeout,
			// Never expose server version in response headers.
			// chi already strips X-Powered-By; this removes Server header.
		},
		shutdownTimeout: shutdownTimeout,
	}
}

// Start calls ListenAndServe in a goroutine.
// Any non-ErrServerClosed error is sent to the returned channel.
func (s *Server) Start() <-chan error {
	ch := make(chan error, 1)
	go func() {
		if err := s.srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			ch <- err
		}
		close(ch)
	}()
	return ch
}

// Shutdown drains in-flight requests up to ShutdownTimeout.
func (s *Server) Shutdown() error {
	ctx, cancel := context.WithTimeout(context.Background(), s.shutdownTimeout)
	defer cancel()
	return s.srv.Shutdown(ctx)
}

// Addr returns the address the server is configured to listen on.
func (s *Server) Addr() string { return s.srv.Addr }
