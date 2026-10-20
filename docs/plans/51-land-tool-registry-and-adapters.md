# 51 — Land #51 and #52 on main, aligned with contract 1.2 final

**Issue:** #51 (also closes #52)
**Parent issue:** #77
**Sub-issues:** none
**Branch:** `fix/51-land-tool-registry-and-adapters`
**Source docs:** SDD Appendix A.2 (citation_id), Appendix F.4 P1, F.3 checklist row #51

## Goal

#51 (tool registry) and #52 (LLM adapters) are on `main` and pass against the
final contract 1.2 from #50. Citation ids name the cited span, built only by
`make_citation_id()` and stamped by the registry.

## Why this branch exists

PRs #89 (#51) and #90 (#52) were based on `feat/50-runtime-contract-1.2` and
merged into it after #88 had already merged that branch into `main`. Their
commits never reached `main`, and both issues stayed open.

The `feat/50` head was also broken on its own. #50's last commit (`e6e7375`)
changed the contract after #51 was written:

1. Scope key `doctor_id` became `clinician_id`. `ToolScope` still had
   `doctor_id`, so the import-time assertion against `SCOPE_ARG_KEYS` failed
   and every tool test errored at collection.
2. `Citation.citation_id` became required. The #51 tools and stub fixtures
   built citations without it, and still used retired source kinds
   (`uploaded_doc`, `prior_docs`, `prior_labs`, `prior_visits`) with untyped
   locators.

## Scope

In scope:
- Merge `origin/main` into `feat/50` (clean, no conflicts).
- `ToolScope.doctor_id` renamed to `clinician_id` (`server/app/agents/tools/registry.py`).
- F.4 P1: `make_citation_id(source_kind, source_id, locator)` builds
  `{source_kind}:{source_id}#{locator_key}` for kinds with a locator; the
  validator compares against the builder (`server/app/agents/tool_contracts.py`).
- Registry stamps `citation_id` on every handler citation; handlers never
  build one (`registry.py::_stamp_citation_ids`).
- Stub fixtures and inline test citations moved to 1.2 source kinds and typed
  locators (`server/tests/fixtures/tool_results/*.json`, unit tests).

Out of scope:
- F.4 P3 (`FailureCode.integrity_failed`) and P4 (`AssistAnswer.bundle_ref`
  removal). Both belong to the assist answer path (#57) and ingestion (#59);
  tracked as a follow-up so this branch stays a landing fix.
- Real retrieval handlers. #53 redo owns `document_chunks` and the chunk ids
  the locators point at.

## Steps

1. Merge `origin/main` into the `feat/50` head.
2. Rename the scope key in `ToolScope` and its test.
3. Implement `_locator_key()` and the three-argument `make_citation_id()`.
4. Make `citation_errors()` check the id against the builder once the locator is valid.
5. Add `ToolRegistry._stamp_citation_ids()`, called before the receipt and result are built.
6. Migrate the fixtures and test helpers; add `TestCitationIds`.

## Locator key (SDD A.2)

| Locator | `locator_key` |
| --- | --- |
| `DocumentSpan` | `{chunk_id}:{char_start}-{char_end}` |
| `TranscriptSpan` | `{segment_id}:{t_start_ms}-{t_end_ms}` (integer ms) |
| `RowRef` | `{table}/{row_id}/{column}` (empty column for whole-row) |

## Non-happy path

- Handler citation with an unknown kind, empty source id, or wrong locator
  shape: the builder raises `ContractViolationError`, the registry logs
  `citation id not built` at warning with tool id, invocation id, and index,
  leaves the citation without an id, and `validate_tool_result` refuses the
  result with `ToolResultContractError`. Nothing invalid reaches a caller.
- Handler supplies its own `citation_id` that disagrees with the builder:
  kept as given, then refused by the validator (id mismatch named in the error).
- Empty citation list: unchanged; "must cite" tools are still refused as ungrounded.
- Transcript times given as floats: converted to integer ms in the key, so
  `1.0` and `1.000` give one id.

## Data models

No new model or field. `Citation.citation_id` already exists (#50); this
change fixes the value it holds to the SDD A.2 format. `ToolScope.clinician_id`
is a rename to the contract's existing scope key, read by tool handlers via
`ToolScope.as_dict()`.

## Test criteria

Commands:
- `pytest tests/unit -o addopts="" --continue-on-collection-errors` shows no
  failure that `main` does not already have.
- `pytest tests/unit/test_tool_registry.py tests/unit/test_tool_stubs.py tests/unit/test_tool_runner.py tests/unit/test_tool_call_sites.py tests/unit/test_session_snapshot.py tests/unit/test_safety_tools.py tests/unit/test_intent_contract.py` all pass.

Acceptance:
- [ ] Two spans of one document get two citation ids (F.3 #51 row, P1).
- [ ] Citations carry `citation_id` from `make_citation_id()` only.
- [ ] `ToolScope` fields equal `SCOPE_ARG_KEYS`.
- [ ] #51 and #52 code is on `main`.

## Risks and open questions

- The local `.venv` has no `sqlalchemy`, so 36 test modules fail to collect on
  both `main` and this branch. Not fixed here; noted in the PR.
