package integration

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
)

func TestUserRepoCreateAndGet(t *testing.T) {
	pool, ctx := setupPostgres(t)
	if pool == nil {
		return
	}
	repo := pgxrepo.NewUserRepo(pool)

	u := &entity.User{
		ID:             uuid.NewString(),
		Username:       "doctor1",
		Email:          "doctor1@example.com",
		HashedPassword: "hashed",
		FullName:       "Doctor One",
		Role:           entity.UserRoleDoctor,
		Permissions:    []string{"read"},
	}
	created, err := repo.Create(ctx, u)
	if err != nil {
		t.Fatalf("create user: %v", err)
	}
	if created.ID == "" || created.Email != u.Email {
		t.Fatalf("unexpected created user: %+v", created)
	}

	fetched, err := repo.GetByEmail(ctx, u.Email)
	if err != nil {
		t.Fatalf("get by email: %v", err)
	}
	if fetched.ID != u.ID {
		t.Fatalf("expected same user id, got %s", fetched.ID)
	}

	_, err = repo.GetByID(ctx, "missing")
	if err != entity.ErrNotFound {
		t.Fatalf("expected ErrNotFound for missing user, got %v", err)
	}
}

func TestSessionRepoQueueAndRecordNotFound(t *testing.T) {
	pool, ctx := setupPostgres(t)
	if pool == nil {
		return
	}
	repo := pgxrepo.NewSessionRepo(pool)

	patientID := "p1"
	doctorID := "d1"
	sessionID := "s1"
	_, err := pool.Exec(ctx, `INSERT INTO patients (id,mrn,full_name,dob) VALUES ($1,$2,$3,$4)`,
		patientID, "MRN-1", "Pat One", time.Now())
	if err != nil {
		t.Fatalf("insert patient: %v", err)
	}
	_, err = pool.Exec(ctx, `INSERT INTO users (id,username,email,hashed_password,role) VALUES ($1,$2,$3,$4,$5)`,
		doctorID, "doc", "doc@example.com", "h", "doctor")
	if err != nil {
		t.Fatalf("insert user: %v", err)
	}
	_, err = pool.Exec(ctx, `INSERT INTO sessions (id,patient_id,doctor_id,status,started_at) VALUES ($1,$2,$3,$4,$5)`,
		sessionID, patientID, doctorID, "active", time.Now())
	if err != nil {
		t.Fatalf("insert session: %v", err)
	}

	queueID := "q1"
	_, err = pool.Exec(ctx, `INSERT INTO modification_queue (id,session_id,field_path,old_value,new_value,reason,status) VALUES ($1,$2,$3,$4,$5,$6,$7)`,
		queueID, sessionID, "diagnoses.0", "", "x", "test", "pending")
	if err != nil {
		t.Fatalf("insert queue item: %v", err)
	}

	item, err := repo.UpdateQueueItem(context.Background(), sessionID, queueID, "approved")
	if err != nil {
		t.Fatalf("update queue item: %v", err)
	}
	if item.Status != "approved" {
		t.Fatalf("expected approved status, got %+v", item)
	}

	_, err = repo.UpdateQueueItem(context.Background(), sessionID, "missing", "approved")
	if err != entity.ErrNotFound {
		t.Fatalf("expected ErrNotFound for queue update miss, got %v", err)
	}

	_, err = repo.GetRecord(context.Background(), sessionID)
	if err != entity.ErrNotFound {
		t.Fatalf("expected ErrNotFound for missing record, got %v", err)
	}
}
