# chore — commit client/v2 to git

**Issue:** none yet (draft C0 in the planning-doc issue breakdown)
**Parent issue:** none
**Sub-issues:** none
**Branch:** `chore/commit-client-v2`
**Source docs:** docs/v2_integration_plan.md, docs/whisperwave_integration.md

## Goal

`client/v2/` (the Lovable-rebuilt Vite frontend) is tracked in git on `main`, so every later v2 issue can land as a normal PR.

## Scope

In scope:
- All `client/v2/` source, config, `public/`, `supabase/config.toml` and migrations, `Dockerfile.dev`, `package-lock.json`

Out of scope:
- `client/v2/.env` (secrets; ignored by `client/v2/.gitignore`)
- `node_modules/`, `dist/`, `.DS_Store`
- `bun.lockb`: `Dockerfile.dev` and npm scripts use npm, so only `package-lock.json` is committed to avoid two lockfiles drifting
- Fixing existing lint errors
- docker-compose wiring for v2 (lives on the feature branch with the compose changes)

## Steps

1. Branch from `origin/main`
2. Copy `client/v2/` excluding the out-of-scope files
3. Add `bun.lockb` to `client/v2/.gitignore`
4. Verify build and tests, commit, push, open PR

## Test criteria

Commands:
- `npm run build` passes
- `npx vitest run` passes
- `npm run lint` recorded (pre-existing failures, not fixed here)

Acceptance:
- [ ] No `.env`, `node_modules`, or `dist` files in the diff
- [ ] `git status` in the main checkout no longer lists `client/v2/` as untracked after this merges and is pulled

## Risks and open questions

- `supabase/config.toml` holds the Supabase project id. It is a public identifier, not a secret; the publishable key stays in `.env`.
- Lint has 6 errors and 13 warnings today; track as a follow-up issue.
