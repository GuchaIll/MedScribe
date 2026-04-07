# Issue #34 -- JWT Authentication, RBAC, and Security

**Title:** feat(auth): implement JWT authentication and role-based access control

**Phase:** 4 (Go Auth + Security) -- Steps 15-19

**Resume bullets served:** V2#5 (HIPAA-compliant, AES-256, JWT-based RBAC)

---

## Overview

Add comprehensive security to the Go API gateway: JWT-based authentication, role-based access control, S3 storage with server-side encryption, PHI field-level encryption, and automatic audit logging. This phase addresses HIPAA compliance requirements.

## Goals

- Secure all API endpoints with JWT authentication
- Enforce role-based permissions for all operations
- Encrypt PHI data at rest (both S3 and database)
- Maintain comprehensive audit trail of all write operations

## Scope

- Directory: `services/api/auth/`, `services/api/storage/`, `services/api/store/`, `services/api/middleware/`
- Applies to all protected API routes

## Tasks

### JWT Authentication (Step 15)
- [ ] Implement `services/api/auth/jwt.go`:
  - [ ] Token issuance at `POST /api/auth/login`:
    - Verify bcrypt hash against `users.hashed_password` column
    - Issue JWT with claims: `user_id`, `role`, `permissions`
    - Configurable token expiration (access token + refresh token)
  - [ ] Token verification middleware:
    - Extract Bearer token from Authorization header
    - Validate signature, expiration, issuer
    - Inject claims into request context
  - [ ] Token refresh endpoint at `POST /api/auth/refresh`
- [ ] Use `golang-jwt/jwt/v5` library
- [ ] JWT signing key from `JWT_SECRET` environment variable

### RBAC Enforcement (Step 16)
- [ ] Implement `services/api/auth/rbac.go`:
  - [ ] Define role enum matching existing `User.role` from `models.py`:
    - `DOCTOR` -- full access to all endpoints
    - `NURSE` -- read access, limited write access, no pipeline trigger
    - `ADMIN` -- user management, system configuration
    - `MEDICAL_ASSISTANT` -- session and transcription access, no direct patient record modification
  - [ ] Define permission sets per role:
    - Map roles to allowed HTTP methods and route patterns
    - Granular permissions: `session:create`, `session:read`, `pipeline:trigger`, `patient:write`, `admin:users`
  - [ ] RBAC middleware:
    - Read `role` from JWT claims in request context
    - Check against route-level permission requirements
    - Return 403 Forbidden if insufficient permissions
- [ ] Apply RBAC middleware to all protected routes

### S3 Storage Backend (Step 17)
- [ ] Implement `services/api/storage/s3.go`:
  - [ ] Implement the same contract as current `base.py` ABC:
    - `Upload(ctx, key string, data io.Reader) error`
    - `Download(ctx, key string) (io.ReadCloser, error)`
    - `Delete(ctx, key string) error`
    - `Exists(ctx, key string) (bool, error)`
    - `List(ctx, prefix string) ([]string, error)`
    - `GetURL(ctx, key string, expiry time.Duration) (string, error)` -- presigned URL
  - [ ] Use AWS SDK for Go v2 (`github.com/aws/aws-sdk-go-v2`)
  - [ ] Enable SSE-S3 for AES-256 encryption at rest on all uploads
  - [ ] Configurable bucket name and region from environment variables
- [ ] MinIO container in `docker-compose.yml` for local development:
  - [ ] S3-compatible API, no AWS credentials required
  - [ ] Pre-create bucket on startup

### PHI Field-Level Encryption (Step 18)
- [ ] Implement `services/api/store/encryption.go`:
  - [ ] AES-256-GCM encryption for sensitive patient fields:
    - `Patient.full_name`
    - `Patient.dob`
    - Any fields stored in `Patient.encrypted_demographics` column
  - [ ] Encrypt before PostgreSQL write, decrypt after read
  - [ ] Encryption key from `ENCRYPTION_KEY` environment variable
  - [ ] Key rotation support: store key version with encrypted data
  - [ ] The `Patient.encrypted_demographics` column already exists in `models.py`

### Automatic Audit Logging (Step 19)
- [ ] Implement `services/api/middleware/audit.go`:
  - [ ] Middleware that intercepts all write operations (POST, PUT, PATCH, DELETE)
  - [ ] Log to `audit_logs` table with:
    - `user_id` (from JWT claims)
    - `action` (HTTP method + route)
    - `resource_type` (e.g., "patient", "session", "medical_record")
    - `resource_id` (extracted from URL path)
    - `ip_address` (from request)
    - `user_agent`
    - `timestamp`
    - `request_body_hash` (SHA-256 of request body, not the body itself)
  - [ ] Async write to avoid adding latency to the request path
  - [ ] Audit log entries are immutable (append-only table)

## Acceptance Criteria

- Unauthenticated requests to protected endpoints return 401 Unauthorized
- NURSE role attempting to trigger pipeline returns 403 Forbidden
- S3 upload includes AES-256 SSE header in the request
- PHI fields are encrypted in a PostgreSQL database dump (not readable as plaintext)
- All write operations produce audit log entries with correct user attribution
- Token refresh works correctly and extends session without re-login
- MinIO works as S3 drop-in replacement in local development

## Implementation Notes

- Use `golang-jwt/jwt/v5` for JWT operations
- Store minimal claims in JWT (user_id, role) to keep token size small
- Keep auth middleware lightweight and composable (separate JWT verification from RBAC check)
- PHI encryption uses AES-256-GCM (authenticated encryption) to prevent tampering
- Audit logging should be non-blocking: use a channel/goroutine to write audit entries asynchronously
- The `audit_logs` table schema already exists in `models.py`

## Files to Create

```
services/api/auth/
  jwt.go           -- JWT issuance, verification, refresh
  rbac.go          -- Role definitions, permission sets, RBAC middleware

services/api/storage/
  s3.go            -- S3/MinIO storage backend with AES-256 SSE

services/api/store/
  encryption.go    -- AES-256-GCM field-level encryption for PHI

services/api/middleware/
  audit.go         -- Automatic audit logging for write operations
```

## Dependencies

- `github.com/golang-jwt/jwt/v5` -- JWT operations
- `github.com/aws/aws-sdk-go-v2` -- S3 client
- `golang.org/x/crypto/bcrypt` -- password hashing
