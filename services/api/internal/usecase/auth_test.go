package usecase

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/medscribe/services/api/internal/entity"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
	"go.uber.org/zap"
)

func TestAuthRegisterConflict(t *testing.T) {
	uc := NewAuthUseCase(&mockUserRepo{
		getByEmailFn: func(_ context.Context, _ string) (*entity.User, error) {
			return &entity.User{ID: "u1"}, nil
		},
	}, "secret", time.Hour, zap.NewNop())

	_, err := uc.Register(context.Background(), RegisterRequest{
		Email:    "a@example.com",
		Password: "pw",
		Role:     string(entity.UserRoleDoctor),
	})
	if err != entity.ErrAlreadyExists {
		t.Fatalf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestAuthRegisterSuccessHashesAndRedacts(t *testing.T) {
	var createdUser *entity.User
	repo := &mockUserRepo{
		getByEmailFn: func(_ context.Context, _ string) (*entity.User, error) {
			return nil, entity.ErrNotFound
		},
		createFn: func(_ context.Context, u *entity.User) (*entity.User, error) {
			createdUser = u
			return &entity.User{
				ID:             u.ID,
				Email:          u.Email,
				HashedPassword: u.HashedPassword,
				Role:           u.Role,
			}, nil
		},
	}
	uc := NewAuthUseCase(repo, "secret", time.Hour, zap.NewNop())

	out, err := uc.Register(context.Background(), RegisterRequest{
		Email:    "a@example.com",
		Password: "StrongPass!123",
		FullName: "A",
		Role:     string(entity.UserRoleDoctor),
	})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if createdUser == nil || createdUser.HashedPassword == "" {
		t.Fatalf("expected hashed password in repository create")
	}
	if pgxrepo.CheckPassword(createdUser.HashedPassword, "StrongPass!123") == false {
		t.Fatalf("expected created hash to validate original password")
	}
	if out.HashedPassword != "" {
		t.Fatalf("expected returned hashed password to be redacted")
	}
}

func TestAuthLoginUnauthorizedAndForbidden(t *testing.T) {
	t.Run("unknown user", func(t *testing.T) {
		uc := NewAuthUseCase(&mockUserRepo{
			getByEmailFn: func(_ context.Context, _ string) (*entity.User, error) {
				return nil, entity.ErrNotFound
			},
		}, "secret", time.Hour, zap.NewNop())
		_, err := uc.Login(context.Background(), LoginRequest{Email: "x", Password: "y"})
		if err != entity.ErrUnauthorized {
			t.Fatalf("expected ErrUnauthorized, got %v", err)
		}
	})

	t.Run("inactive user", func(t *testing.T) {
		hash, _ := pgxrepo.HashPassword("ok")
		uc := NewAuthUseCase(&mockUserRepo{
			getByEmailFn: func(_ context.Context, _ string) (*entity.User, error) {
				return &entity.User{ID: "u1", HashedPassword: hash, IsActive: false}, nil
			},
		}, "secret", time.Hour, zap.NewNop())
		_, err := uc.Login(context.Background(), LoginRequest{Email: "x", Password: "ok"})
		if err != entity.ErrForbidden {
			t.Fatalf("expected ErrForbidden, got %v", err)
		}
	})
}

func TestAuthLoginSuccessAndTokenValidation(t *testing.T) {
	hash, _ := pgxrepo.HashPassword("ok")
	uc := NewAuthUseCase(&mockUserRepo{
		getByEmailFn: func(_ context.Context, _ string) (*entity.User, error) {
			return &entity.User{
				ID:             "u1",
				Email:          "a@example.com",
				HashedPassword: hash,
				IsActive:       true,
				Role:           entity.UserRoleDoctor,
				Permissions:    []string{"read"},
			}, nil
		},
	}, "secret", time.Hour, zap.NewNop())

	login, err := uc.Login(context.Background(), LoginRequest{Email: "a@example.com", Password: "ok"})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if login.AccessToken == "" {
		t.Fatalf("expected access token")
	}
	if login.Profile.HashedPassword != "" {
		t.Fatalf("expected redacted hash")
	}

	claims, err := uc.ValidateToken(context.Background(), login.AccessToken)
	if err != nil {
		t.Fatalf("unexpected validate err: %v", err)
	}
	if claims.UserID != "u1" || claims.Role != "doctor" {
		t.Fatalf("unexpected claims: %+v", claims)
	}
}

func TestAuthValidateTokenRejectsInvalidAndWrongAlgorithm(t *testing.T) {
	uc := NewAuthUseCase(&mockUserRepo{}, "secret", time.Hour, zap.NewNop())

	if _, err := uc.ValidateToken(context.Background(), "not-a-token"); err != entity.ErrUnauthorized {
		t.Fatalf("expected unauthorized for malformed token, got %v", err)
	}

	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate key: %v", err)
	}
	token := jwt.NewWithClaims(jwt.SigningMethodRS256, jwt.MapClaims{
		"sub": "u1", "role": "doctor", "exp": time.Now().Add(time.Hour).Unix(),
	})
	tokenStr, err := token.SignedString(privateKey)
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	if _, err = uc.ValidateToken(context.Background(), tokenStr); err != entity.ErrUnauthorized {
		t.Fatalf("expected unauthorized for wrong signing alg, got %v", err)
	}
}
