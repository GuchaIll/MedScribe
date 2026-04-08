package integration

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	postgrescontainer "github.com/testcontainers/testcontainers-go/modules/postgres"
)

func setupPostgres(t *testing.T) (*pgxpool.Pool, context.Context) {
	t.Helper()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	t.Cleanup(cancel)

	pg, err := postgrescontainer.Run(ctx,
		"pgvector/pgvector:pg15",
		postgrescontainer.WithDatabase("medscribe_test"),
		postgrescontainer.WithUsername("postgres"),
		postgrescontainer.WithPassword("postgres"),
	)
	if err != nil {
		t.Skipf("skipping integration test; postgres container unavailable: %v", err)
		return nil, nil
	}
	t.Cleanup(func() { _ = pg.Terminate(context.Background()) })

	dsn, err := pg.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		t.Fatalf("container connection string: %v", err)
	}
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatalf("pgxpool new: %v", err)
	}
	t.Cleanup(pool.Close)

	ready := false
	for i := 0; i < 30; i++ {
		pingCtx, cancelPing := context.WithTimeout(ctx, 2*time.Second)
		err = pool.Ping(pingCtx)
		cancelPing()
		if err == nil {
			ready = true
			break
		}
		time.Sleep(500 * time.Millisecond)
	}
	if !ready {
		t.Skipf("skipping integration test; postgres container not ready: %v", err)
		return nil, nil
	}

	schemaPath := filepath.Join("testdata", "schema.sql")
	schemaBytes, err := os.ReadFile(schemaPath)
	if err != nil {
		t.Fatalf("read schema: %v", err)
	}
	if _, err = pool.Exec(ctx, string(schemaBytes)); err != nil {
		t.Fatalf("apply schema: %v", err)
	}
	return pool, ctx
}
