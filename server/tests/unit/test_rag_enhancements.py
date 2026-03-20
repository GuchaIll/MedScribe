"""
Unit tests for RAG enhancement components:
  - HybridRetrievalService (RRF fusion, tsquery building)
  - Clinical-aware chunking (section detection, clinical splitter)
  - IterativeRetrievalService (multi-pass retrieval, query decomposition)
  - Integration of hybrid search into evidence node
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any, Dict, List


# ============================================================================
#  HybridRetrievalService Tests
# ============================================================================


class TestBuildTsquery:
    """Tests for _build_tsquery -- converts queries to PostgreSQL tsquery."""

    def _make_service(self):
        from app.services.hybrid_retrieval import HybridRetrievalService
        return HybridRetrievalService(
            db=MagicMock(),
            embedding_service=MagicMock(),
        )

    def test_basic_query(self):
        svc = self._make_service()
        result = svc._build_tsquery("lisinopril blood pressure")
        assert "lisinopril:*" in result
        assert "blood:*" in result
        assert "pressure:*" in result
        assert " | " in result

    def test_short_tokens_filtered(self):
        svc = self._make_service()
        result = svc._build_tsquery("a I lisinopril")
        assert "lisinopril:*" in result
        # single-char tokens should be excluded
        assert "a:*" not in result.split(" | ")

    def test_empty_query(self):
        svc = self._make_service()
        assert svc._build_tsquery("") == ""

    def test_only_short_tokens(self):
        svc = self._make_service()
        assert svc._build_tsquery("a I") == ""

    def test_hyphenated_drug_name(self):
        svc = self._make_service()
        result = svc._build_tsquery("co-amoxiclav 500mg")
        assert "co-amoxiclav:*" in result
        assert "500mg:*" in result

    def test_special_characters_stripped(self):
        svc = self._make_service()
        result = svc._build_tsquery("blood? pressure! (systolic)")
        assert "blood:*" in result
        assert "pressure:*" in result
        assert "systolic:*" in result


class TestRRFFusion:
    """Tests for _rrf_fuse -- Reciprocal Rank Fusion merging."""

    def _make_service(self, rrf_k=60, dense_weight=1.0, sparse_weight=1.0):
        from app.services.hybrid_retrieval import HybridRetrievalService
        return HybridRetrievalService(
            db=MagicMock(),
            embedding_service=MagicMock(),
            rrf_k=rrf_k,
            dense_weight=dense_weight,
            sparse_weight=sparse_weight,
        )

    def test_single_retriever_dense_only(self):
        svc = self._make_service()
        dense = [
            {"chunk_id": "c1", "chunk_text": "alpha", "similarity": 0.9},
            {"chunk_id": "c2", "chunk_text": "beta", "similarity": 0.7},
        ]
        fused = svc._rrf_fuse(dense, [], id_key="chunk_id")
        assert len(fused) == 2
        assert fused[0]["chunk_id"] == "c1"
        assert "rrf_score" in fused[0]
        assert fused[0]["rrf_score"] > fused[1]["rrf_score"]

    def test_single_retriever_sparse_only(self):
        svc = self._make_service()
        sparse = [
            {"chunk_id": "c1", "chunk_text": "alpha", "similarity": 0.8},
        ]
        fused = svc._rrf_fuse([], sparse, id_key="chunk_id")
        assert len(fused) == 1
        assert fused[0]["chunk_id"] == "c1"

    def test_both_retrievers_overlap(self):
        svc = self._make_service(rrf_k=60)
        dense = [
            {"chunk_id": "c1", "chunk_text": "overlap", "similarity": 0.9},
            {"chunk_id": "c2", "chunk_text": "dense only", "similarity": 0.7},
        ]
        sparse = [
            {"chunk_id": "c1", "chunk_text": "overlap", "similarity": 0.5},
            {"chunk_id": "c3", "chunk_text": "sparse only", "similarity": 0.4},
        ]
        fused = svc._rrf_fuse(dense, sparse, id_key="chunk_id")

        ids = [f["chunk_id"] for f in fused]
        # c1 appears in both -> should get highest score
        assert ids[0] == "c1"
        assert len(fused) == 3
        # c1 gets contributions from both retrievers
        c1_score = fused[0]["rrf_score"]
        c2_score = next(f["rrf_score"] for f in fused if f["chunk_id"] == "c2")
        assert c1_score > c2_score

    def test_empty_both(self):
        svc = self._make_service()
        assert svc._rrf_fuse([], [], id_key="chunk_id") == []

    def test_rrf_k_affects_scores(self):
        svc_low = self._make_service(rrf_k=1)
        svc_high = self._make_service(rrf_k=100)
        dense = [{"chunk_id": "c1", "chunk_text": "x", "similarity": 0.9}]
        score_low = svc_low._rrf_fuse(dense, [], id_key="chunk_id")[0]["rrf_score"]
        score_high = svc_high._rrf_fuse(dense, [], id_key="chunk_id")[0]["rrf_score"]
        # Lower k -> score = 1/(1+1) = 0.5; higher k -> score = 1/(100+1)
        assert score_low > score_high

    def test_weight_adjustment(self):
        svc_dense = self._make_service(dense_weight=2.0, sparse_weight=1.0)
        svc_sparse = self._make_service(dense_weight=1.0, sparse_weight=2.0)

        doc = [{"chunk_id": "c1", "chunk_text": "x", "similarity": 0.9}]
        dense_boosted = svc_dense._rrf_fuse(doc, [], id_key="chunk_id")[0]["rrf_score"]
        sparse_boosted = svc_sparse._rrf_fuse([], doc, id_key="chunk_id")[0]["rrf_score"]

        # Both docs at rank 1, but dense_boosted uses weight=2, sparse_boosted uses weight=2
        # The scores should be identical because both are at same position with same weight
        assert dense_boosted == sparse_boosted

    def test_dedup_preserves_first_seen_data(self):
        svc = self._make_service()
        dense = [{"chunk_id": "c1", "chunk_text": "from_dense", "similarity": 0.9}]
        sparse = [{"chunk_id": "c1", "chunk_text": "from_sparse", "similarity": 0.5}]
        fused = svc._rrf_fuse(dense, sparse, id_key="chunk_id")
        # First-seen copy is from dense
        assert fused[0]["chunk_text"] == "from_dense"


class TestHybridSearchPublicAPI:
    """Tests for the public search methods (mock the internal methods)."""

    def _make_service(self):
        from app.services.hybrid_retrieval import HybridRetrievalService
        svc = HybridRetrievalService(
            db=MagicMock(),
            embedding_service=MagicMock(),
        )
        return svc

    def test_search_chunks_combines_dense_and_sparse(self):
        svc = self._make_service()
        svc._dense_chunk_search = MagicMock(return_value=[
            {"chunk_id": "d1", "chunk_text": "dense", "similarity": 0.8},
        ])
        svc._sparse_chunk_search = MagicMock(return_value=[
            {"chunk_id": "s1", "chunk_text": "sparse", "similarity": 0.5},
        ])
        results = svc.search_chunks("session1", "test query", top_k=5)
        assert len(results) == 2
        svc._dense_chunk_search.assert_called_once()
        svc._sparse_chunk_search.assert_called_once()

    def test_search_chunks_respects_top_k(self):
        svc = self._make_service()
        svc._dense_chunk_search = MagicMock(return_value=[
            {"chunk_id": f"d{i}", "chunk_text": f"text{i}", "similarity": 0.9 - i * 0.1}
            for i in range(5)
        ])
        svc._sparse_chunk_search = MagicMock(return_value=[])
        results = svc.search_chunks("s1", "query", top_k=3)
        assert len(results) == 3

    def test_search_patient_facts_delegates(self):
        svc = self._make_service()
        svc._dense_fact_search = MagicMock(return_value=[
            {"id": 1, "fact_type": "medication", "similarity": 0.9},
        ])
        svc._sparse_fact_search = MagicMock(return_value=[])
        results = svc.search_patient_facts("P001", "lisinopril", top_k=5)
        assert len(results) == 1
        svc._dense_fact_search.assert_called_once()
        svc._sparse_fact_search.assert_called_once()

    def test_dense_failure_returns_sparse_only(self):
        svc = self._make_service()
        svc._dense_chunk_search = MagicMock(return_value=[])
        svc._sparse_chunk_search = MagicMock(return_value=[
            {"chunk_id": "s1", "chunk_text": "keyword match", "similarity": 0.4},
        ])
        results = svc.search_chunks("s1", "query")
        assert len(results) == 1
        assert results[0]["chunk_id"] == "s1"


# ============================================================================
#  Clinical-Aware Chunking Tests
# ============================================================================


class TestDetectSections:
    """Tests for clinical section detection."""

    def test_soap_sections(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = (
            "SUBJECTIVE: Patient reports headache.\n"
            "OBJECTIVE: BP 120/80, HR 72.\n"
            "ASSESSMENT: Tension headache.\n"
            "PLAN: Ibuprofen 400mg PRN."
        )
        sections = detect_sections(text)
        headings = [s.heading for s in sections]
        assert "SUBJECTIVE" in headings
        assert "OBJECTIVE" in headings
        assert "ASSESSMENT" in headings
        assert "PLAN" in headings

    def test_soap_abbreviations(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = (
            "S: Patient reports cough.\n"
            "O: Lung sounds clear.\n"
            "A: Upper respiratory infection.\n"
            "P: Rest and fluids."
        )
        sections = detect_sections(text)
        headings = [s.heading for s in sections]
        assert "SUBJECTIVE" in headings
        assert "OBJECTIVE" in headings
        assert "ASSESSMENT" in headings
        assert "PLAN" in headings

    def test_clinical_headings(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = (
            "CHIEF COMPLAINT: Chest pain.\n"
            "MEDICATIONS: Aspirin 81mg daily.\n"
            "ALLERGIES: NKDA.\n"
            "VITAL SIGNS: BP 130/85."
        )
        sections = detect_sections(text)
        headings = [s.heading for s in sections]
        assert "CHIEF COMPLAINT" in headings
        assert "MEDICATIONS" in headings
        assert "ALLERGIES" in headings
        assert "VITAL SIGNS" in headings

    def test_no_sections_returns_unknown(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = "Patient came in today feeling unwell. General exam unremarkable."
        sections = detect_sections(text)
        assert len(sections) == 1
        assert sections[0].heading == "UNKNOWN"

    def test_preamble_before_first_heading(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = (
            "Dr. Smith - Encounter Note\n"
            "Date: 2025-01-15\n\n"
            "CHIEF COMPLAINT: Headache.\n"
            "MEDICATIONS: None."
        )
        sections = detect_sections(text)
        headings = [s.heading for s in sections]
        assert headings[0] == "PREAMBLE"
        assert "CHIEF COMPLAINT" in headings

    def test_empty_text_returns_unknown(self):
        from app.agents.nodes.clinical_chunking import detect_sections
        text = "   "
        sections = detect_sections(text)
        assert len(sections) == 1
        assert sections[0].heading == "UNKNOWN"


class TestClinicalTextSplitter:
    """Tests for clinical_text_splitter."""

    def test_short_text_single_chunk(self):
        from app.agents.nodes.clinical_chunking import clinical_text_splitter
        text = "SUBJECTIVE: Brief complaint."
        chunks = clinical_text_splitter(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0].section == "SUBJECTIVE"

    def test_long_section_splits(self):
        from app.agents.nodes.clinical_chunking import clinical_text_splitter
        long_text = "MEDICATIONS: " + " ".join(
            f"Drug{i} 10mg daily." for i in range(100)
        )
        chunks = clinical_text_splitter(long_text, chunk_size=200, overlap=20)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.section == "MEDICATIONS"

    def test_multiple_sections_preserved(self):
        from app.agents.nodes.clinical_chunking import clinical_text_splitter
        text = (
            "ALLERGIES: Penicillin - rash.\n"
            "MEDICATIONS: Metformin 500mg BID.\n"
            "DIAGNOSES: Type 2 Diabetes."
        )
        chunks = clinical_text_splitter(text, chunk_size=500)
        sections = {c.section for c in chunks}
        assert "ALLERGIES" in sections
        assert "MEDICATIONS" in sections

    def test_empty_text_returns_empty(self):
        from app.agents.nodes.clinical_chunking import clinical_text_splitter
        assert clinical_text_splitter("") == []
        assert clinical_text_splitter("   ") == []

    def test_chunk_index_tracking(self):
        from app.agents.nodes.clinical_chunking import clinical_text_splitter
        long_text = "PLAN: " + "Follow up in 2 weeks. " * 50
        chunks = clinical_text_splitter(long_text, chunk_size=100, overlap=10)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
            assert chunk.total_section_chunks == len(chunks)


class TestClinicalChunkConversationLog:
    """Tests for clinical_chunk_conversation_log."""

    def _make_log(self, *texts):
        log = []
        for i, text in enumerate(texts):
            log.append({
                "timestamp": float(i),
                "segments": [{
                    "start": float(i),
                    "end": float(i + 1),
                    "speaker": "Doctor",
                    "raw_text": text,
                    "cleaned_text": text,
                    "uncertainties": [],
                    "confidence": "high",
                }],
            })
        return log

    def test_basic_chunking(self):
        from app.agents.nodes.clinical_chunking import clinical_chunk_conversation_log
        log = self._make_log(
            "MEDICATIONS: aspirin 81mg daily",
            "ALLERGIES: NKDA",
        )
        chunks = clinical_chunk_conversation_log(log)
        assert len(chunks) > 0
        assert all("chunk_id" in c for c in chunks)
        assert all(c["source"] == "transcript" for c in chunks)

    def test_metadata_includes_section(self):
        from app.agents.nodes.clinical_chunking import clinical_chunk_conversation_log
        log = self._make_log("ALLERGIES: Penicillin")
        chunks = clinical_chunk_conversation_log(log)
        assert chunks[0]["metadata"]["chunking_strategy"] == "clinical_aware"

    def test_empty_log(self):
        from app.agents.nodes.clinical_chunking import clinical_chunk_conversation_log
        assert clinical_chunk_conversation_log([]) == []


# ============================================================================
#  IterativeRetrievalService Tests
# ============================================================================


class TestIterativeRetrieval:
    """Tests for IterativeRetrievalService."""

    def _make_hybrid_mock(self, chunk_results=None, fact_results=None):
        mock = MagicMock()
        mock.search_chunks.return_value = chunk_results or []
        mock.search_chunks_for_patient.return_value = chunk_results or []
        mock.search_patient_facts.return_value = fact_results or []
        return mock

    def _make_service(self, hybrid_mock, llm_factory=None, min_results=3):
        from app.services.iterative_retrieval import IterativeRetrievalService
        return IterativeRetrievalService(
            hybrid_service=hybrid_mock,
            llm_factory=llm_factory,
            min_results=min_results,
        )

    def test_pass1_sufficient_skips_refinement(self):
        results = [
            {"chunk_id": f"c{i}", "chunk_text": f"t{i}", "rrf_score": 0.5}
            for i in range(5)
        ]
        hybrid = self._make_hybrid_mock(chunk_results=results)
        svc = self._make_service(hybrid, min_results=3)

        out = svc.retrieve_chunks("s1", "test query", top_k=8)
        assert len(out) == 5
        # Only one call to search_chunks (pass 1 only)
        assert hybrid.search_chunks.call_count == 1

    def test_pass2_decomposition_triggered(self):
        """When pass 1 returns too few results, pass 2 decomposes the query."""
        hybrid = self._make_hybrid_mock(chunk_results=[
            {"chunk_id": "c1", "chunk_text": "t1", "rrf_score": 0.1}
        ])
        svc = self._make_service(hybrid, min_results=5)

        out = svc.retrieve_chunks("s1", "allergies and medications")
        # Should have called search_chunks multiple times (pass 1 + sub-questions)
        assert hybrid.search_chunks.call_count > 1

    def test_dedup_across_passes(self):
        """Same chunk_id from multiple passes is not duplicated."""
        same_result = [
            {"chunk_id": "c1", "chunk_text": "same", "rrf_score": 0.5}
        ]
        hybrid = self._make_hybrid_mock(chunk_results=same_result)
        svc = self._make_service(hybrid, min_results=10)

        out = svc.retrieve_chunks("s1", "allergies and medications")
        # Despite multiple passes returning c1, it should appear only once
        chunk_ids = [r["chunk_id"] for r in out]
        assert chunk_ids.count("c1") == 1

    def test_patient_fact_retrieval(self):
        facts = [
            {"id": 1, "fact_type": "allergy", "rrf_score": 0.8},
            {"id": 2, "fact_type": "medication", "rrf_score": 0.7},
            {"id": 3, "fact_type": "diagnosis", "rrf_score": 0.6},
        ]
        hybrid = self._make_hybrid_mock(fact_results=facts)
        svc = self._make_service(hybrid, min_results=3)

        out = svc.retrieve_patient_facts("P001", "what are the allergies")
        assert len(out) == 3

    def test_patient_chunks_retrieval(self):
        chunks = [
            {"chunk_id": f"c{i}", "chunk_text": f"t{i}", "rrf_score": 0.5}
            for i in range(4)
        ]
        hybrid = self._make_hybrid_mock(chunk_results=chunks)
        svc = self._make_service(hybrid, min_results=3)

        out = svc.retrieve_patient_chunks("P001", "test query")
        assert len(out) == 4

    def test_ranking_by_rrf_score(self):
        """When pass 1 is sufficient, results are returned in search order."""
        results = [
            {"chunk_id": "c1", "chunk_text": "first", "rrf_score": 0.9},
            {"chunk_id": "c2", "chunk_text": "second", "rrf_score": 0.5},
            {"chunk_id": "c3", "chunk_text": "third", "rrf_score": 0.1},
        ]
        hybrid = self._make_hybrid_mock(chunk_results=results)
        svc = self._make_service(hybrid, min_results=3)

        out = svc.retrieve_chunks("s1", "test", top_k=3)
        # Pass 1 was sufficient, so original order from hybrid is preserved
        assert len(out) == 3
        assert out[0]["chunk_id"] == "c1"

    def test_multi_pass_results_ranked_by_score(self):
        """When multi-pass triggers, _rank_and_trim sorts by rrf_score."""
        from app.services.iterative_retrieval import IterativeRetrievalService
        hybrid = MagicMock()
        # Pass 1 returns too few results (only 1)
        hybrid.search_chunks.side_effect = [
            [{"chunk_id": "c1", "chunk_text": "low", "rrf_score": 0.1}],
            [{"chunk_id": "c2", "chunk_text": "high", "rrf_score": 0.9}],
            [{"chunk_id": "c3", "chunk_text": "mid", "rrf_score": 0.5}],
            [],  # pass 3 expansion returns nothing
            [],
        ]
        svc = IterativeRetrievalService(
            hybrid_service=hybrid, llm_factory=None, min_results=5,
        )
        out = svc.retrieve_chunks("s1", "allergies and medications", top_k=3)
        # After multi-pass, results should be sorted by rrf_score
        scores = [r["rrf_score"] for r in out]
        assert scores == sorted(scores, reverse=True)


class TestHeuristicDecompose:
    """Tests for heuristic query decomposition (no LLM)."""

    def _make_service(self):
        from app.services.iterative_retrieval import IterativeRetrievalService
        return IterativeRetrievalService(
            hybrid_service=MagicMock(),
            llm_factory=None,  # No LLM -> heuristic
        )

    def test_and_conjunction_split(self):
        svc = self._make_service()
        subs = svc._heuristic_decompose("allergies and medications")
        assert len(subs) == 2
        assert any("allergies" in s.lower() for s in subs)
        assert any("medications" in s.lower() for s in subs)

    def test_ampersand_split(self):
        svc = self._make_service()
        subs = svc._heuristic_decompose("vital signs & lab results")
        assert len(subs) == 2

    def test_no_conjunction_returns_empty(self):
        svc = self._make_service()
        subs = svc._heuristic_decompose("what medications is patient on")
        # No "and" -> no split, but quoted-term extraction also empty
        assert subs == []

    def test_quoted_terms_extracted(self):
        svc = self._make_service()
        subs = svc._heuristic_decompose('Is "lisinopril" related to "cough"?')
        assert "lisinopril" in subs
        assert "cough" in subs

    def test_max_sub_questions_limit(self):
        svc = self._make_service()
        svc.max_sub_questions = 2
        subs = svc._heuristic_decompose("a and b and c and d and e")
        assert len(subs) <= 2


class TestClinicalTermExpansion:
    """Tests for _expand_clinical_terms."""

    def _make_service(self):
        from app.services.iterative_retrieval import IterativeRetrievalService
        return IterativeRetrievalService(
            hybrid_service=MagicMock(),
            llm_factory=None,
        )

    def test_bp_expands(self):
        svc = self._make_service()
        expanded = svc._expand_clinical_terms("what is the bp")
        assert len(expanded) >= 1
        assert any("blood pressure" in e for e in expanded)

    def test_hba1c_expands(self):
        svc = self._make_service()
        expanded = svc._expand_clinical_terms("latest hba1c level")
        assert len(expanded) >= 1
        assert any("hemoglobin" in e.lower() for e in expanded)

    def test_no_abbreviation_returns_empty(self):
        svc = self._make_service()
        expanded = svc._expand_clinical_terms("patient has headache")
        assert expanded == []

    def test_max_two_expansions(self):
        svc = self._make_service()
        expanded = svc._expand_clinical_terms("bp hr rr temp o2 spo2")
        assert len(expanded) <= 2


# ============================================================================
#  AssistantService Integration Tests
# ============================================================================


class TestAssistantServiceHybridIntegration:
    """Tests that AssistantService uses hybrid/iterative when available."""

    def _make_embedding_service(self):
        mock = MagicMock()
        mock.embed_text.return_value = MagicMock()  # numpy-like
        mock.search_patient_facts.return_value = []
        return mock

    def _make_record_repo(self):
        mock = MagicMock()
        mock.get_for_patient.return_value = []
        return mock

    def _make_llm_factory(self, answer="Test answer"):
        def factory():
            llm = MagicMock()
            llm.generate_response.return_value = answer
            return llm
        return factory

    def test_init_accepts_hybrid_and_iterative(self):
        from app.services.assistant_service import AssistantService
        svc = AssistantService(
            embedding_service=self._make_embedding_service(),
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
            hybrid_retrieval=MagicMock(),
            iterative_retrieval=MagicMock(),
        )
        assert svc._hybrid is not None
        assert svc._iterative is not None

    def test_init_defaults_to_none(self):
        from app.services.assistant_service import AssistantService
        svc = AssistantService(
            embedding_service=self._make_embedding_service(),
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
        )
        assert svc._hybrid is None
        assert svc._iterative is None

    def test_retrieve_facts_uses_iterative_when_available(self):
        import numpy as np
        from app.services.assistant_service import AssistantService

        iterative = MagicMock()
        iterative.retrieve_patient_facts.return_value = [
            {"fact_type": "allergy", "similarity": 0.9, "fact_data": {}}
        ]

        svc = AssistantService(
            embedding_service=self._make_embedding_service(),
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
            iterative_retrieval=iterative,
        )

        result = svc._retrieve_clinical_facts(
            "P001", np.zeros(768), question="allergies"
        )
        assert len(result) == 1
        iterative.retrieve_patient_facts.assert_called_once()

    def test_retrieve_facts_falls_back_to_hybrid(self):
        import numpy as np
        from app.services.assistant_service import AssistantService

        hybrid = MagicMock()
        hybrid.search_patient_facts.return_value = [
            {"fact_type": "medication", "similarity": 0.8, "fact_data": {}}
        ]

        svc = AssistantService(
            embedding_service=self._make_embedding_service(),
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
            hybrid_retrieval=hybrid,
        )

        result = svc._retrieve_clinical_facts(
            "P001", np.zeros(768), question="medications"
        )
        assert len(result) == 1
        hybrid.search_patient_facts.assert_called_once()

    def test_retrieve_facts_falls_back_to_dense(self):
        import numpy as np
        from app.services.assistant_service import AssistantService

        embed_svc = self._make_embedding_service()
        embed_svc.search_patient_facts.return_value = [
            {"fact_type": "diagnosis", "similarity": 0.7, "fact_data": {}}
        ]

        svc = AssistantService(
            embedding_service=embed_svc,
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
            # No hybrid or iterative
        )

        result = svc._retrieve_clinical_facts(
            "P001", np.zeros(768), question="diagnoses"
        )
        assert len(result) == 1
        embed_svc.search_patient_facts.assert_called_once()

    def test_retrieve_chunks_uses_iterative(self):
        import numpy as np
        from app.services.assistant_service import AssistantService

        iterative = MagicMock()
        iterative.retrieve_patient_chunks.return_value = [
            {"chunk_text": "result", "source_type": "transcript", "similarity": 0.8}
        ]

        svc = AssistantService(
            embedding_service=self._make_embedding_service(),
            record_repo=self._make_record_repo(),
            llm_factory=self._make_llm_factory(),
            db=MagicMock(),
            iterative_retrieval=iterative,
        )

        result = svc._retrieve_chunks_for_patient(
            "P001", np.zeros(768), question="test"
        )
        assert len(result) == 1
        iterative.retrieve_patient_chunks.assert_called_once()


# ============================================================================
#  Evidence Node Hybrid Integration Tests
# ============================================================================


class TestEvidenceNodeHybridStrategy:
    """Tests that evidence node uses hybrid retrieval when available."""

    def _make_state(self, session_id="S001", facts=None, chunks=None):
        return {
            "session_id": session_id,
            "patient_id": "P001",
            "doctor_id": "D001",
            "candidate_facts": facts or [],
            "chunks": chunks or [],
            "conversation_log": [],
            "evidence_map": {},
            "controls": {"attempts": {}, "budget": {}, "trace_log": []},
        }

    def _make_ctx(self, embedding_service=None, hybrid_service=None):
        ctx = MagicMock()
        ctx.embedding_service = embedding_service
        ctx.hybrid_retrieval_service = hybrid_service
        return ctx

    def test_hybrid_strategy_selected_when_available(self):
        from app.agents.nodes.evidence import retrieve_evidence_node

        hybrid = MagicMock()
        hybrid.search_chunks.return_value = [
            {
                "chunk_id": "c1",
                "chunk_text": "test medication lisinopril",
                "source_type": "transcript",
                "start_time": 0.0,
                "end_time": 5.0,
                "rrf_score": 0.5,
            }
        ]

        ctx = self._make_ctx(
            embedding_service=MagicMock(),
            hybrid_service=hybrid,
        )

        facts = [{
            "fact_id": "f1",
            "type": "medication",
            "value": "lisinopril",
            "provenance": {},
            "confidence": 0.9,
        }]

        state = self._make_state(facts=facts)
        result = retrieve_evidence_node(state, ctx)

        # Should have used hybrid strategy
        trace = result["controls"]["trace_log"][-1]
        assert trace["strategy"] == "hybrid"
        assert "f1" in result["evidence_map"]

    def test_fallback_to_pgvector_when_no_hybrid(self):
        from app.agents.nodes.evidence import retrieve_evidence_node

        embed = MagicMock()
        embed.embed_text.return_value = MagicMock()
        embed.search_similar_chunks.return_value = []

        ctx = self._make_ctx(
            embedding_service=embed,
            hybrid_service=None,
        )

        facts = [{
            "fact_id": "f1",
            "type": "allergy",
            "value": "penicillin",
            "provenance": {},
            "confidence": 0.8,
        }]

        state = self._make_state(facts=facts)
        result = retrieve_evidence_node(state, ctx)

        trace = result["controls"]["trace_log"][-1]
        assert trace["strategy"] == "pgvector"

    def test_no_facts_skips_retrieval(self):
        from app.agents.nodes.evidence import retrieve_evidence_node

        ctx = self._make_ctx(embedding_service=MagicMock())
        state = self._make_state(facts=[])
        result = retrieve_evidence_node(state, ctx)

        trace = result["controls"]["trace_log"][-1]
        assert trace["action"] == "skipped"


# ============================================================================
#  AgentContext Integration Tests
# ============================================================================


class TestAgentContextHybridWiring:
    """Tests that AgentContext correctly wires hybrid_retrieval_service."""

    def test_hybrid_field_exists(self):
        from app.agents.config import AgentContext
        ctx = AgentContext()
        assert ctx.hybrid_retrieval_service is None

    def test_hybrid_field_can_be_set(self):
        from app.agents.config import AgentContext
        mock_hybrid = MagicMock()
        ctx = AgentContext(hybrid_retrieval_service=mock_hybrid)
        assert ctx.hybrid_retrieval_service is mock_hybrid
