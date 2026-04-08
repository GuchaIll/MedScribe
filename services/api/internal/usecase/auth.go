package usecase

import (
	"context"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/medscribe/services/api/internal/entity"
	"github.com/medscribe/services/api/internal/repo"
	pgxrepo "github.com/medscribe/services/api/internal/repo/pgx"
	"go.uber.org/zap"
)

// authUseCase implements AuthUseCase.
type authUseCase struct {
	users     repo.UserRepository
	jwtSecret []byte
	tokenTTL  time.Duration
	log       *zap.Logger
}

// NewAuthUseCase wires the auth use-case.
func NewAuthUseCase(users repo.UserRepository, jwtSecret string, tokenTTL time.Duration, log *zap.Logger) AuthUseCase {
	return &authUseCase{
		users:     users,
		jwtSecret: []byte(jwtSecret),
		tokenTTL:  tokenTTL,
		log:       log,
	}
}

func (uc *authUseCase) Register(ctx context.Context, req RegisterRequest) (*entity.User, error) {
	existing, err := uc.users.GetByEmail(ctx, req.Email)
	if existing != nil {
		return nil, entity.ErrAlreadyExists
	}
	if err != nil && err != entity.ErrNotFound {
		return nil, fmt.Errorf("register: check email: %w", err)
	}

	hashed, err := pgxrepo.HashPassword(req.Password)
	if err != nil {
		return nil, fmt.Errorf("register: hash password: %w", err)
	}

	u := &entity.User{
		ID:             uuid.NewString(),
		Username:       req.Email, // use email as username
		Email:          req.Email,
		HashedPassword: hashed,
		FullName:       req.FullName,
		Role:           entity.UserRole(req.Role),
		IsActive:       true,
	}

	created, err := uc.users.Create(ctx, u)
	if err != nil {
		return nil, fmt.Errorf("register: create user: %w", err)
	}
	created.HashedPassword = "" // never return hash over the wire
	return created, nil
}

func (uc *authUseCase) Login(ctx context.Context, req LoginRequest) (*LoginResponse, error) {
	u, err := uc.users.GetByEmail(ctx, req.Email)
	if err != nil {
		// Return the same error for unknown email or bad password to
		// prevent user enumeration.
		return nil, entity.ErrUnauthorized
	}
	if !pgxrepo.CheckPassword(u.HashedPassword, req.Password) {
		return nil, entity.ErrUnauthorized
	}
	if !u.IsActive {
		return nil, entity.ErrForbidden
	}

	expiresAt := time.Now().Add(uc.tokenTTL)
	token, err := uc.issueToken(u, expiresAt)
	if err != nil {
		return nil, fmt.Errorf("login: issue token: %w", err)
	}

	_ = uc.users.UpdateLastLogin(ctx, u.ID)
	u.HashedPassword = ""

	return &LoginResponse{
		AccessToken: token,
		TokenType:   "Bearer",
		ExpiresAtMs: expiresAt.UnixMilli(),
		Profile:     u,
	}, nil
}

func (uc *authUseCase) GetProfile(ctx context.Context, userID string) (*entity.User, error) {
	u, err := uc.users.GetByID(ctx, userID)
	if err != nil {
		return nil, err
	}
	u.HashedPassword = ""
	return u, nil
}

func (uc *authUseCase) ValidateToken(_ context.Context, tokenStr string) (*Claims, error) {
	token, err := jwt.Parse(tokenStr, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
		}
		return uc.jwtSecret, nil
	}, jwt.WithExpirationRequired())
	if err != nil || !token.Valid {
		return nil, entity.ErrUnauthorized
	}

	mc, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return nil, entity.ErrUnauthorized
	}

	perms, _ := mc["permissions"].([]any)
	permStrs := make([]string, 0, len(perms))
	for _, p := range perms {
		if s, ok := p.(string); ok {
			permStrs = append(permStrs, s)
		}
	}

	exp, _ := mc.GetExpirationTime()
	var expiresMs int64
	if exp != nil {
		expiresMs = exp.UnixMilli()
	}

	return &Claims{
		UserID:      mc["sub"].(string),
		Role:        mc["role"].(string),
		Permissions: permStrs,
		ExpiresAtMs: expiresMs,
	}, nil
}

// ─── helpers ─────────────────────────────────────────────────────────────────

func (uc *authUseCase) issueToken(u *entity.User, expiresAt time.Time) (string, error) {
	claims := jwt.MapClaims{
		"sub":         u.ID,
		"role":        string(u.Role),
		"permissions": u.Permissions,
		"iat":         time.Now().Unix(),
		"exp":         expiresAt.Unix(),
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(uc.jwtSecret)
}
