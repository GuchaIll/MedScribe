# 53 — fix(retrieval): per-fact chunk provenance, span locators, observed_at + received_at (Phase 1B)

**Issue:** #53
**Parent issue:** #77 (epic: agent refactor Phases 0–5)
**Sub-issues:** none
**Branch:** `fix/53-chunk-provenance-span-locators`
**Source docs:** `docs/agent_refactor_plan.md` §11 Phase 1B items 1–6, 8–9; §18.3; §20.3; `docs/design/copilot-runtime-design.md` (file ownership, target layout)

## Goal

Every extracted fact cites the specific chunk it came from (not `chunks[0]`), carries a character-span locator, and all DB tables written by workstream B carry `received_at`. A multi-chunk golden batch passes end-to-end: fact from chunk N has `chunk_id == N`, span indexes into that chunk's text, `observed_at` and `received_at` round-trip through Postgres.

## Scope

In scope:
- `nodes/extract.py` — per-fact chunk lookup + `chunk_id` + `{page, char_start, char_end}` locator; snippet grounding check
- `nodes/record_schema.py` — `source_chunk_ids: List[str]` on `LabResult`, `Vitals`, `Medication`, `Allergy`, `Problem`; `observed_at: Optional[str]` on `LabResult`
- `database/models.py` — `source_chunk_ids` on `ClinicalEmbedding`; `document_id` + `page` on `ChunkEmbedding`; `received_at` on `ChunkEmbedding` + `ClinicalEmbedding` (with legacy fallback)
- `services/embedding_service.py` — write paths carry chunk ids and `received_at` (#53 tag in copilot-runtime-design.md)
- `migrations/versions/<rev>_provenance_receipt_locators.py` — single Alembic migration for all new columns

Out of scope:
- `agents/session/receipt_ledger.py` — `as_of_receipt` per query and relevance metadata (#84 owns this)
- Observations store / `observation_repo.py` — normalized observations table (#54 owns this)
- `agents/tool_contracts.py` `Citation.received_at` + `evidence_state` — workstream A contract (#50 owns this)
- `persist_results.py` write-path for `source_chunk_ids` on `MedicalRecord.structured_data` — tested via round-trip here; deep wiring deferred to #54
- Moving `nodes/` into `compile/stages/` — #61 owns that relocation

## Steps

1. **`nodes/record_schema.py`** — add `source_chunk_ids: List[str]` (default `[]`) to `LabResult`, `Vitals`, `Medication`, `Allergy`, `Problem`; add `observed_at: Optional[str]` (ISO-8601, default `None`) to `LabResult`

2. **`database/models.py`** — add columns to `ClinicalEmbedding`: `source_chunk_ids ARRAY(String)` nullable; `received_at DateTime` nullable. Add to `ChunkEmbedding`: `document_id String(100)` nullable, `page Integer` nullable, `received_at DateTime` nullable, `received_at_is_legacy Boolean` default False

3. **`migrations/versions/<rev>_provenance_receipt_locators.py`** — Alembic migration adding all columns from step 2 plus `lab_results.observed_at` (legacy rows: `received_at` server_default to `created_at`, `received_at_is_legacy` to True)

4. **`services/embedding_service.py`** — update `store_chunk_embedding(...)` to accept `document_id`, `page`, `received_at`; update `store_clinical_embedding(...)` to accept `source_chunk_ids`, `received_at`; pass `datetime.utcnow()` as `received_at` at call sites

5. **`nodes/extract.py`** — replace `chunks[0]` hardcode in `_call_category_extraction` with `_find_best_chunk(evidence_text, chunks)` that returns `(chunk, char_start, char_end)` via case-insensitive substring search; build `locator = {page, char_start, char_end}` and set `chunk_id` from matched chunk (fall back to `chunks[0]` with empty locator if no match); set `source_chunk_ids` on the returned fact

6. **`nodes/extract.py`** — in `_ensure_evidence_spans`: after locator assignment, verify `snippet` normalizes to a substring of the cited chunk text; if not, set `evidence["grounded"] = False`; if yes, set `evidence["grounded"] = True`

7. **`tests/test_extract_candidates.py`** — golden batch fixture: 2 chunks, one lab fact whose `evidence_text` appears only in chunk 1; assert `chunk_id`, `locator.char_start/char_end`, `grounded=True`; also assert `source_chunk_ids` and `received_at` round-trip through `store_clinical_embedding` (mocked DB session or real with pytest-postgresql)

## Test criteria

Commands:
- `cd server && python -m pytest tests/test_extract_candidates.py -v` passes
- `cd server && alembic upgrade head` applies cleanly against a fresh test DB

Acceptance (from issue #53):
- [ ] `nodes/extract.py` returns chunk id per fact (not `chunks[0]`); `provenance.evidence[]` has `chunk_id` + locator
- [ ] Evidence snippet is a normalized substring of cited chunk, else marked ungrounded
- [ ] `source_chunk_ids[]` on `LabResult`, `Vitals`, `Medication`, `Allergy`, `Problem`
- [ ] `clinical_embeddings.source_chunk_ids` column + write path
- [ ] `chunk_embeddings.document_id` + `page` + write path
- [ ] `LabResult.observed_at` (ISO-8601) + Alembic migration; legacy rows null
- [ ] `received_at` on `chunk_embeddings`, `clinical_embeddings`; legacy rows fall back to record creation time, flagged
- [ ] Span locator `{page, char_start, char_end}` on document chunks and `provenance.evidence[]`

## Risks and open questions

- **Transcript segments:** the issue says `received_at` on transcript segments, but no `TranscriptSegment` table exists — chunks are stored in `chunk_embeddings`. Applying `received_at` to `chunk_embeddings` (source_type=transcript) covers transcript chunks. If a separate segments table is needed that is owned by a later issue.
- **ARRAY type portability:** `ARRAY(String)` is Postgres-specific. `embedding_service.py` already assumes Postgres (pgvector), so this is acceptable. SQLite test shims would need JSON fallback — noted but deferred.
- **Locator page field on transcript chunks:** transcript chunks have no page; `page` stays null for source_type=transcript. Document chunks carry page from the OCR pipeline.
