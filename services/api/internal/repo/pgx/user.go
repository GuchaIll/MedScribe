package pgxrepo

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/medscribe/services/api/internal/entity"
	"golang.org/x/crypto/bcrypt"
)

// UserRepo implements repo.UserRepository using pgxpool.
type UserRepo struct {
	db *pgxpool.Pool
}

func NewUserRepo(db *pgxpool.Pool) *UserRepo {
	return &UserRepo{db: db}
}

func (r *UserRepo) Create(ctx context.Context, u *entity.User) (*entity.User, error) {
	const q = `
		INSERT INTO users
			(id, username, email, hashed_password, full_name, role,
			 permissions, is_active, created_at, updated_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,true,NOW(),NOW())
		RETURNING id, username, email, hashed_password, full_name, role,
		          permissions, is_active, last_login, created_at, updated_at`

	row := r.db.QueryRow(ctx, q,
		u.ID, u.Username, u.Email, u.HashedPassword, u.FullName,
		string(u.Role), u.Permissions,
	)
	return scanUser(row)
}

func (r *UserRepo) GetByID(ctx context.Context, id string) (*entity.User, error) {
	const q = `
		SELECT id, username, email, hashed_password, full_name, role,
		       permissions, is_active, last_login, created_at, updated_at
		FROM users WHERE id = $1`
	return scanUser(r.db.QueryRow(ctx, q, id))
}

func (r *UserRepo) GetByEmail(ctx context.Context, email string) (*entity.User, error) {
	const q = `
		SELECT id, username, email, hashed_password, full_name, role,
		       permissions, is_active, last_login, created_at, updated_at
		FROM users WHERE email = $1`
	return scanUser(r.db.QueryRow(ctx, q, email))
}

func (r *UserRepo) GetByUsername(ctx context.Context, username string) (*entity.User, error) {
	const q = `
		SELECT id, username, email, hashed_password, full_name, role,
		       permissions, is_active, last_login, created_at, updated_at
		FROM users WHERE username = $1`
	return scanUser(r.db.QueryRow(ctx, q, username))
}

func (r *UserRepo) UpdateLastLogin(ctx context.Context, userID string) error {
	const q = `UPDATE users SET last_login = NOW(), updated_at = NOW() WHERE id = $1`
	_, err := r.db.Exec(ctx, q, userID)
	return err
}

// HashPassword hashes a plaintext password with bcrypt cost 12.
func HashPassword(password string) (string, error) {
	b, err := bcrypt.GenerateFromPassword([]byte(password), 12)
	if err != nil {
		return "", fmt.Errorf("hash password: %w", err)
	}
	return string(b), nil
}

// CheckPassword verifies a plaintext password against a bcrypt hash.
func CheckPassword(hash, password string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func scanUser(row pgx.Row) (*entity.User, error) {
	var u entity.User
	var role string
	err := row.Scan(
		&u.ID, &u.Username, &u.Email, &u.HashedPassword, &u.FullName, &role,
		&u.Permissions, &u.IsActive, &u.LastLogin, &u.CreatedAt, &u.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, entity.ErrNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("user: scan: %w", err)
	}
	u.Role = entity.UserRole(role)
	return &u, nil
}
