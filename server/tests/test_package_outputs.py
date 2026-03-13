import unittest
import sys
import os
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

REPO_ROOT = Path(__file__).resolve().parents[2]

from app.agents.nodes.package import package_outputs_node
from app.agents.nodes.export import write_report_pdf

try:
    import reportlab  # noqa: F401
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False


def _base_state():
    return {
        "session_id": "sess_pkg_test",
        "patient_id": "pat_pkg_test",
        "doctor_id": "doc_pkg_test",
        "conversation_log": [],
        "new_segments": [],
        "session_summary": "Test session summary",
        "patient_record_fields": {},
        "message": None,
        "flags": {},
        "inputs": {},
        "documents": [],
        "chunks": [],
        "candidate_facts": [],
        "evidence_map": {},
        "structured_record": {},
        "provenance": [],
        "validation_report": {},
        "conflict_report": {},
        "clinical_note": "Test clinical note",
        "controls": {
            "attempts": {},
            "budget": {},
            "trace_log": [],
        },
    }


class PackageOutputsTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = REPO_ROOT / "storage" / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.generated_paths = []

    def tearDown(self):
        if os.environ.get("KEEP_TEST_OUTPUTS") == "1":
            return
        for path in self.generated_paths:
            if path.exists():
                path.unlink()

    def test_package_outputs_writes_report_html_pdf(self):
        if not HAS_REPORTLAB:
            self.skipTest("reportlab not available; skipping PDF export test")
        state = _base_state()
        state["structured_record"] = {
            "patient": {"name": "Test Patient", "dob": "1980-01-01"},
            "diagnoses": [{"code": "I10"}],
        }
        state["patient_record_fields"] = {
            "diagnoses": [{"code": "E11"}],
            "visit": {"date": "2025-01-01"},
        }

        new_state = package_outputs_node(state)
        trace_entry = new_state["controls"]["trace_log"][-1]

        report_path = Path(trace_entry["report_path"])
        html_path = Path(trace_entry["html_path"])
        pdf_path = Path(trace_entry["pdf_path"])
        self.generated_paths.extend([report_path, html_path, pdf_path])

        self.assertTrue(report_path.exists())
        self.assertTrue(html_path.exists())
        self.assertTrue(pdf_path.exists())
        self.assertIn("diagnoses", new_state["structured_record"])
        self.assertEqual(len(new_state["structured_record"]["diagnoses"]), 2)


class PdfExportTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = REPO_ROOT / "storage" / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if os.environ.get("KEEP_TEST_OUTPUTS") == "1":
            return
        path = self.output_dir / "pdf_export_text_test.pdf"
        if path.exists():
            path.unlink()

    def test_write_text_pdf_creates_file(self):
        if not HAS_REPORTLAB:
            self.skipTest("reportlab not available; skipping PDF export test")
        output_path = self.output_dir / "pdf_export_text_test.pdf"
        write_report_pdf(
            output_path=output_path,
            title="Test PDF",
            meta=[("Session ID", "sess_001")],
            summary_text="Line 1\nLine 2",
            clinical_note="Note body",
            structured_record={"patient": {"name": "Test", "dob": "1980-01-01"}},
            validation_report={},
            conflict_report={},
        )
        self.assertTrue(output_path.exists())
        self.assertGreater(output_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
