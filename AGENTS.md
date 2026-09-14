# AGENTS.md

Rules for any coding agent (Claude Code, Copilot, Codex, others) working in this repo.
`CLAUDE.md` imports this file; keep the rules here so there is one source.

## Issue workflow

Every change is tied to a GitHub issue and ships as its own branch and pull request.

### 1. Check issue hierarchy before starting

Before touching code for issue `#N`:

```bash
gh issue view N
gh api repos/GuchaIll/MedScribe/issues/N/sub_issues --jq '.[] | "#\(.number) \(.state) \(.title)"'
gh api repos/GuchaIll/MedScribe/issues/N/parent --jq '"#\(.number) \(.title)"' 2>/dev/null
```

- **Issue has sub-issues:** do not implement the parent as one change. Work each sub-issue on its own branch and PR, in dependency order. The parent's plan lists the sub-issues and their order.
- **Issue is a sub-issue:** read the parent issue and its plan first so the work matches the parent's scope.
- Also check the issue body for task lists and `Depends:` lines. Do not start an issue whose dependencies are still open without saying so.

### 2. Always create a new branch

- Branch from an up-to-date `main`: `git fetch origin && git switch -c <type>/<N>-<slug> origin/main`
- `<type>` is one of `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.
- One issue per branch. Never commit issue work directly to `main` or onto another issue's branch.
- If the working tree has unrelated uncommitted changes, use `git worktree add` instead of carrying them over.

### 3. Write a planning document before working

- Create `docs/plans/<N>-<slug>.md` from [docs/plans/TEMPLATE.md](docs/plans/TEMPLATE.md) before writing code.
- Commit the plan as the first commit on the branch.
- If the plan changes during the work, update the doc in the same PR.

### 4. Always push and raise a PR when the issue is done

1. Run the test criteria from the plan and record the results.
2. `git push -u origin <branch>`
3. `gh pr create --base main` with a body that contains all of these sections:

```markdown
## Changes
- <what changed, grouped by area, with file paths>

## Plan
[docs/plans/<N>-<slug>.md](https://github.com/GuchaIll/MedScribe/blob/<branch>/docs/plans/<N>-<slug>.md)

## Test criteria
- [x] <command run> — <result>
- [x] <acceptance criterion from the issue> — <how it was verified>
- [ ] <anything not verified, and why>

Closes #N
```

- Report failing or skipped checks honestly in the Test criteria section. Do not drop them.
- Do not merge the PR yourself unless asked.

## Project pointers

- System architecture: [docs/architecture.md](docs/architecture.md)
- Agent/pipeline refactor plan (current direction): [docs/agent_refactor_plan.md](docs/agent_refactor_plan.md)
- Frozen runtime contract, with change-control rules: [docs/copilot_runtime_contract.md](docs/copilot_runtime_contract.md)
- Some of these docs are still landing from `fix/transcript-error-handling`; if a link is missing on `main`, read it on that branch.
- `distributed_plan.md` and `distributed_plan2.md` are superseded. The Python LangGraph pipeline is being refactored in place, not ported to Go or Rust.

## General

- No emoji in generated text, messages, UI copy, or code.
