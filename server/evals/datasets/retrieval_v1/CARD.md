# Dataset card: retrieval_v1

Labeled retrieval eval set for patient-scoped chunk retrieval. Introduced in #104; reused by #98.

## Contents

- `corpus/<patient_id>/<doc_id>.txt`: 40 documents, 10 patients (`p01`-`p10`), 4 documents each,
  35.6k characters total. Document types: progress and clinic notes, lab flowsheets, medication
  lists, discharge summaries, imaging and procedure reports, consults.
- `queries.jsonl`: 100 queries, 10 per patient.

| Stratum | n | What it tests |
|---|---|---|
| `exact_term` | 22 | Query uses a term that appears in the answer (`finerenone`, `LI-RADS LR-5`) |
| `paraphrase` | 22 | Query shares little or no vocabulary with the answer ("why was his sulfonylurea taken away") |
| `numeric` | 22 | A specific value, often one of several dated values for the same test ("most recent A1c") |
| `medication` | 22 | Dose, change, schedule, or instruction for a named drug |
| `negative` | 12 | The answer is not in this patient's records but is in another patient's |

## Row schema

```json
{"query_id": "p01-q06", "patient_id": "p01", "query": "most recent hemoglobin A1c result",
 "stratum": "numeric", "gold": [{"doc_id": "p01_labs", "quote": "Hemoglobin A1c: 7.6 %"}]}
```

`gold` lists every passage that answers the query (1-2 spans). A retrieved chunk is a hit when its
whitespace- and case-normalized text contains a normalized gold quote. Negatives have `gold: []`.

## How it was made

- Written by hand by one author (an AI coding agent, reviewed in PR) on 2026-11-12. No real patient
  data and no real names, dates of birth, MRNs, or facilities. Every document says
  "Synthetic record for evaluation only."
- Clinical content is plausible but invented. Values are internally consistent per patient (for
  example eGFR 52 -> 49 -> 48 across three dates) so numeric queries have same-test distractors.
- Drugs and tests repeat across patients on purpose (furosemide, acetaminophen limits, FEV1,
  A1c), so a cross-patient leak would be visible as a wrong hit.
- Queries were written after the documents, against their text.

## Known limits

- Small per-patient pools (9-13 chunks with the 500/50 chunker). Random top-5 recall is about 52%.
- One author for corpus and queries: paraphrase difficulty is bounded by that author.
- English only, clean text; no OCR noise, no tables split across pages (#98 adds those).
- No page structure: each document is one text block.

## Validation

`load_eval_set()` rejects: bad JSON, unknown fields, ids outside `[a-z0-9][a-z0-9_-]*`, duplicate
ids, negatives with gold, positives without gold, gold in another patient's document, a quote not
found, a quote found in two documents of the same patient, and a quote split across chunks.
`evals/deterministic/test_retrieval_eval.py::TestRetrievalV1Dataset` checks size and strata.
