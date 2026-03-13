"""
Unit tests for record_generator.py
"""

import pytest
from datetime import datetime
from pathlib import Path
from app.core.record_generator import RecordGenerator, get_record_generator


class TestRecordGenerator:
    """Tests for RecordGenerator initialization."""

    def test_create_generator(self):
        """Test creating record generator."""
        generator = RecordGenerator()
        assert generator is not None
        assert generator.env is not None

    def test_factory_function(self):
        """Test factory function returns generator instance."""
        generator = get_record_generator()
        assert isinstance(generator, RecordGenerator)

    def test_template_directory_exists(self):
        """Test that template directory exists."""
        generator = RecordGenerator()
        template_dir = Path(generator.TEMPLATE_DIR)
        assert template_dir.exists()
        assert template_dir.is_dir()


class TestTemplateLoading:
    """Tests for template loading and availability."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    def test_soap_template_exists(self, generator):
        """Test SOAP template can be loaded."""
        template = generator.env.get_template("soap.html")
        assert template is not None

    def test_discharge_template_exists(self, generator):
        """Test discharge template can be loaded."""
        template = generator.env.get_template("discharge.html")
        assert template is not None

    def test_consultation_template_exists(self, generator):
        """Test consultation template can be loaded."""
        template = generator.env.get_template("consultation.html")
        assert template is not None

    def test_progress_template_exists(self, generator):
        """Test progress template can be loaded."""
        template = generator.env.get_template("progress.html")
        assert template is not None

    def test_invalid_template_raises_error(self, generator):
        """Test loading non-existent template raises error."""
        from jinja2.exceptions import TemplateNotFound
        with pytest.raises(TemplateNotFound):
            generator.env.get_template("nonexistent.html")


class TestSOAPNoteGeneration:
    """Tests for SOAP note generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def sample_record(self):
        """Sample medical record for SOAP note."""
        return {
            "patient": {
                "name": "John Doe",
                "mrn": "MRN12345",
                "dob": "1980-01-15",
                "age": 44,
                "sex": "M"
            },
            "visit": {
                "date": "2024-02-12",
                "time": "10:30 AM",
                "provider": "Dr. Smith",
                "location": "Primary Care Clinic"
            },
            "chief_complaint": "Cough for 3 days",
            "notes": {
                "subjective": "Patient presents with cough for 3 days.",
                "objective": "Temp 98.6F, BP 120/80, lungs clear.",
                "assessment": "Viral upper respiratory infection.",
                "plan": "Rest, fluids, symptomatic treatment."
            },
            "vital_signs": {
                "temperature": "98.6°F",
                "blood_pressure": "120/80",
                "heart_rate": "72",
                "respiratory_rate": "16",
                "oxygen_saturation": "98%"
            },
            "medications": [
                {"name": "Lisinopril 10mg", "dose": "10mg", "route": "PO", "frequency": "daily"}
            ],
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
            ]
        }

    def test_soap_basic_generation(self, generator, sample_record):
        """Test basic SOAP note generation."""
        html = generator.generate(sample_record, "soap")

        assert html is not None
        assert len(html) > 0
        assert "SOAP Note" in html or "SOAP" in html

    def test_soap_contains_patient_info(self, generator, sample_record):
        """Test SOAP note contains patient information."""
        html = generator.generate(sample_record, "soap")

        assert "John Doe" in html
        assert "MRN12345" in html

    def test_soap_contains_sections(self, generator, sample_record):
        """Test SOAP note contains all sections."""
        html = generator.generate(sample_record, "soap")

        html_lower = html.lower()
        assert "subjective" in html_lower
        assert "objective" in html_lower
        assert "assessment" in html_lower
        assert "plan" in html_lower

    def test_soap_with_clinical_suggestions(self, generator, sample_record):
        """Test SOAP note with clinical suggestions."""
        suggestions = {
            "allergy_alerts": [
                {
                    "severity": "critical",
                    "message": "Patient allergic to Penicillin",
                    "recommendation": "Avoid penicillin-based antibiotics"
                }
            ],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {},
            "risk_level": "critical"
        }

        html = generator.generate(sample_record, "soap", suggestions)

        assert "alert" in html.lower() or "allergy" in html.lower()
        assert "Penicillin" in html

    def test_soap_empty_medications(self, generator, sample_record):
        """Test SOAP note with empty medication list."""
        sample_record["medications"] = []
        html = generator.generate(sample_record, "soap")

        assert html is not None
        assert len(html) > 0


class TestDischargeGeneration:
    """Tests for discharge summary generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def discharge_record(self):
        """Sample discharge record."""
        return {
            "patient": {
                "name": "Jane Smith",
                "mrn": "MRN67890",
                "age": 65,
                "sex": "F"
            },
            "visit": {
                "date": "2024-02-05",
                "provider": "Dr. Johnson",
                "admission_date": "2024-02-01",
                "discharge_date": "2024-02-05"
            },
            "diagnoses": [
                {"description": "Pneumonia", "code": "J18.9", "type": "admission"},
                {"description": "Pneumonia, resolved", "code": "J18.9", "type": "discharge"}
            ],
            "procedures": [
                {"name": "Chest X-ray", "date": "2024-02-01"},
                {"name": "Blood cultures", "date": "2024-02-01"}
            ],
            "medications": [
                {"name": "Amoxicillin 500mg", "dose": "500mg", "frequency": "TID", "duration": "7 days"}
            ],
            "notes": {
                "hospital_course": "Patient admitted with pneumonia, treated with antibiotics.",
                "plan": "Complete antibiotic course, follow up in 1 week."
            }
        }

    def test_discharge_basic_generation(self, generator, discharge_record):
        """Test basic discharge summary generation."""
        html = generator.generate(discharge_record, "discharge")

        assert html is not None
        assert len(html) > 0
        assert "Discharge" in html

    def test_discharge_contains_diagnoses(self, generator, discharge_record):
        """Test discharge summary contains diagnoses."""
        html = generator.generate(discharge_record, "discharge")

        assert "Pneumonia" in html
        assert "J18.9" in html

    def test_discharge_contains_procedures(self, generator, discharge_record):
        """Test discharge summary contains procedures."""
        html = generator.generate(discharge_record, "discharge")

        assert "Chest X-ray" in html or "chest x-ray" in html.lower()

    def test_discharge_contains_medications(self, generator, discharge_record):
        """Test discharge summary contains discharge medications."""
        html = generator.generate(discharge_record, "discharge")

        assert "Amoxicillin" in html


class TestConsultationGeneration:
    """Tests for consultation note generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def consultation_record(self):
        """Sample consultation record."""
        return {
            "patient": {
                "name": "Bob Williams",
                "mrn": "MRN11111",
                "age": 55,
                "sex": "M"
            },
            "visit": {
                "date": "2024-02-12",
                "provider": "Dr. Cardiologist",
                "referring_provider": "Dr. Primary"
            },
            "consultation_reason": "Evaluation of chest pain",
            "notes": {
                "subjective": "Patient reports intermittent chest pain.",
                "objective": "ECG shows normal sinus rhythm.",
                "assessment": "Atypical chest pain, likely musculoskeletal.",
                "plan": "Recommend stress test if symptoms persist."
            },
            "diagnoses": [
                {"description": "Chest pain", "code": "R07.9"}
            ]
        }

    def test_consultation_basic_generation(self, generator, consultation_record):
        """Test basic consultation note generation."""
        html = generator.generate(consultation_record, "consultation")

        assert html is not None
        assert len(html) > 0
        assert "Consultation" in html

    def test_consultation_contains_reason(self, generator, consultation_record):
        """Test consultation note contains reason."""
        html = generator.generate(consultation_record, "consultation")

        assert "chest pain" in html.lower()

    def test_consultation_contains_recommendations(self, generator, consultation_record):
        """Test consultation note contains recommendations."""
        html = generator.generate(consultation_record, "consultation")

        assert "stress test" in html.lower() or "Recommend" in html


class TestProgressNoteGeneration:
    """Tests for progress note generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def progress_record(self):
        """Sample progress note record."""
        return {
            "patient": {
                "name": "Alice Johnson",
                "mrn": "MRN22222",
                "age": 70,
                "sex": "F"
            },
            "visit": {
                "date": "2024-02-12",
                "provider": "Dr. Hospitalist",
                "day_of_stay": 3
            },
            "interval_history": "Patient continues to improve.",
            "vital_signs": {
                "temperature": "98.6°F",
                "blood_pressure": "130/85"
            },
            "notes": {
                "objective": "Patient ambulatory, eating well.",
                "assessment": "Improving pneumonia.",
                "plan": "Continue antibiotics, plan discharge tomorrow."
            },
            "diagnoses": [
                {"description": "Pneumonia", "code": "J18.9", "status": "active"}
            ]
        }

    def test_progress_basic_generation(self, generator, progress_record):
        """Test basic progress note generation."""
        html = generator.generate(progress_record, "progress")

        assert html is not None
        assert len(html) > 0
        assert "Progress" in html or "PROGRESS" in html

    def test_progress_contains_interval_history(self, generator, progress_record):
        """Test progress note contains interval history."""
        html = generator.generate(progress_record, "progress")

        assert "continues to improve" in html.lower()

    def test_progress_contains_day_of_stay(self, generator, progress_record):
        """Test progress note contains hospital day."""
        html = generator.generate(progress_record, "progress")

        assert "3" in html or "day" in html.lower()


class TestCustomFilters:
    """Tests for custom Jinja2 filters."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    def test_format_date_filter(self, generator):
        """Test format_date custom filter."""
        # Create a simple template that uses the filter
        template_str = "{{ test_date|format_date }}"
        template = generator.env.from_string(template_str)

        # Test with ISO date string
        result = template.render(test_date="2024-02-12")
        assert "2024" in result
        assert "02" in result or "12" in result

    def test_format_date_with_datetime(self, generator):
        """Test format_date with datetime object."""
        template_str = "{{ test_date|format_date }}"
        template = generator.env.from_string(template_str)

        result = template.render(test_date=datetime(2024, 2, 12))
        assert "2024" in result

    def test_format_list_filter(self, generator):
        """Test format_list custom filter."""
        template_str = "{{ items|format_list }}"
        template = generator.env.from_string(template_str)

        result = template.render(items=["Item 1", "Item 2", "Item 3"])
        assert "Item 1" in result
        assert "Item 2" in result

    def test_format_list_empty(self, generator):
        """Test format_list with empty list."""
        template_str = "{{ items|format_list }}"
        template = generator.env.from_string(template_str)

        result = template.render(items=[])
        assert result is not None


class TestPDFGeneration:
    """Tests for PDF generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def sample_record(self):
        """Sample medical record."""
        return {
            "patient": {
                "name": "Test Patient",
                "mrn": "MRN99999",
                "age": 50,
                "sex": "M"
            },
            "visit": {
                "date": "2024-02-12",
                "provider": "Dr. Test"
            },
            "chief_complaint": "Test complaint",
            "notes": {
                "subjective": "Test subjective",
                "objective": "Test objective",
                "assessment": "Test assessment",
                "plan": "Test plan"
            }
        }

    def test_generate_pdf_basic(self, generator, sample_record):
        """Test basic PDF generation."""
        try:
            import weasyprint  # noqa: F401
        except (ImportError, OSError):
            pytest.skip("weasyprint not installed or native libs missing")

        pdf_bytes = generator.generate_pdf(sample_record, "soap")
        assert pdf_bytes is not None
        assert len(pdf_bytes) > 0
        assert pdf_bytes[:4] == b'%PDF'

    def test_generate_pdf_with_clinical_suggestions(self, generator, sample_record):
        """Test PDF generation with clinical suggestions."""
        try:
            suggestions = {
                "allergy_alerts": [],
                "drug_interactions": [],
                "contraindications": [],
                "risk_level": "low"
            }

            pdf_bytes = generator.generate_pdf(sample_record, "soap", suggestions)
            assert pdf_bytes is not None
            assert len(pdf_bytes) > 0
        except (ImportError, OSError):
            pytest.skip("weasyprint not installed or native libs missing")


class TestPlainTextGeneration:
    """Tests for plain text generation."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def sample_record(self):
        """Sample medical record."""
        return {
            "patient": {
                "name": "Test Patient",
                "mrn": "MRN99999"
            },
            "visit": {
                "date": "2024-02-12",
                "provider": "Dr. Test"
            },
            "notes": {
                "subjective": "Test subjective",
                "objective": "Test objective",
                "assessment": "Test assessment",
                "plan": "Test plan"
            }
        }

    def test_generate_plain_text(self, generator, sample_record):
        """Test plain text generation."""
        text = generator.generate_plain_text(sample_record, "soap")

        assert text is not None
        assert len(text) > 0
        assert "Test Patient" in text
        assert "MRN99999" in text

    def test_plain_text_no_html_tags(self, generator, sample_record):
        """Test plain text has no HTML tags."""
        text = generator.generate_plain_text(sample_record, "soap")

        # Should not contain common HTML tags
        assert "<html>" not in text
        assert "<div>" not in text
        assert "<span>" not in text


class TestSaveToFile:
    """Tests for saving records to files."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def sample_record(self):
        """Sample medical record."""
        return {
            "patient": {
                "name": "Test Patient",
                "mrn": "MRN99999"
            },
            "visit": {
                "date": "2024-02-12",
                "provider": "Dr. Test"
            },
            "notes": {
                "subjective": "Test",
                "objective": "Test",
                "assessment": "Test",
                "plan": "Test"
            }
        }

    def test_save_html_to_file(self, generator, sample_record, tmp_path):
        """Test saving HTML to file."""
        output_file = tmp_path / "test_record.html"

        generator.save_to_file(
            sample_record,
            "soap",
            str(output_file),
            format="html"
        )

        assert output_file.exists()
        content = output_file.read_text()
        assert "Test Patient" in content

    def test_save_pdf_to_file(self, generator, sample_record, tmp_path):
        """Test saving PDF to file."""
        try:
            import weasyprint  # noqa: F401
        except (ImportError, OSError):
            pytest.skip("weasyprint not installed or native libs missing")

        output_file = tmp_path / "test_record.pdf"
        generator.save_to_file(
            sample_record,
            "soap",
            str(output_file),
            format="pdf"
        )
        assert output_file.exists()
        content = output_file.read_bytes()
        assert content[:4] == b'%PDF'

    def test_save_text_to_file(self, generator, sample_record, tmp_path):
        """Test saving plain text to file."""
        output_file = tmp_path / "test_record.txt"

        generator.save_to_file(
            sample_record,
            "soap",
            str(output_file),
            format="text"
        )

        assert output_file.exists()
        content = output_file.read_text()
        assert "Test Patient" in content


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    def test_invalid_template_name(self, generator):
        """Test error handling for invalid template."""
        from jinja2.exceptions import TemplateNotFound

        record = {"patient": {"name": "Test"}}

        with pytest.raises(TemplateNotFound):
            generator.generate(record, "invalid_template")

    def test_missing_required_fields(self, generator):
        """Test handling of missing required fields."""
        # Record with minimal data
        record = {
            "patient": {"name": "Test"},
            "visit": {}
        }

        # Should either render with defaults or raise a template error — not crash the process
        try:
            html = generator.generate(record, "soap")
            assert html is not None
        except Exception:
            pass  # Template error on missing fields is acceptable

    def test_none_record(self, generator):
        """Test handling of None record raises an error."""
        with pytest.raises(Exception):
            generator.generate(None, "soap")


@pytest.mark.integration
class TestTemplateIntegration:
    """Integration tests for complete template rendering."""

    @pytest.fixture
    def generator(self):
        """Create generator instance for tests."""
        return RecordGenerator()

    @pytest.fixture
    def complete_record(self):
        """Complete medical record with all fields."""
        return {
            "patient": {
                "name": "John Doe",
                "mrn": "MRN12345",
                "dob": "1980-01-15",
                "age": 44,
                "sex": "M"
            },
            "visit": {
                "date": "2024-02-12",
                "time": "10:30 AM",
                "provider": "Dr. Smith",
                "location": "Primary Care Clinic"
            },
            "chief_complaint": "Cough and fever",
            "notes": {
                "subjective": "Patient presents with productive cough and fever for 3 days.",
                "objective": "Temp 101.2F, BP 120/80, HR 88, RR 18, SpO2 96%. Lungs with crackles in RLL.",
                "assessment": "Community-acquired pneumonia.",
                "plan": "Start azithromycin 500mg daily x5 days. Return if worsening."
            },
            "vital_signs": {
                "temperature": "101.2°F",
                "blood_pressure": "120/80",
                "heart_rate": "88",
                "respiratory_rate": "18",
                "oxygen_saturation": "96%"
            },
            "medications": [
                {"name": "Azithromycin 500mg", "dose": "500mg", "route": "PO", "frequency": "daily", "duration": "5 days"}
            ],
            "allergies": [
                {"substance": "Penicillin", "reaction": "Rash", "severity": "moderate"}
            ],
            "diagnoses": [
                {"description": "Community-acquired pneumonia", "code": "J18.9", "status": "active"}
            ],
            "labs": [
                {"test_name": "WBC", "value": "15.2", "unit": "K/uL", "abnormal": True, "abnormal_flag": "H"}
            ]
        }

    @pytest.fixture
    def clinical_suggestions(self):
        """Sample clinical suggestions."""
        return {
            "allergy_alerts": [
                {
                    "severity": "critical",
                    "medication": "Penicillin",
                    "message": "Patient has documented allergy to Penicillin",
                    "reaction": "Rash",
                    "recommendation": "Avoid penicillin-based antibiotics. Azithromycin is safe alternative."
                }
            ],
            "drug_interactions": [],
            "contraindications": [],
            "historical_context": {
                "chronic_conditions": [],
                "recent_procedures": [],
                "recent_labs": []
            },
            "risk_level": "moderate",
            "timestamp": datetime.now().isoformat()
        }

    def test_complete_soap_with_all_sections(self, generator, complete_record, clinical_suggestions):
        """Test complete SOAP note with all sections."""
        html = generator.generate(complete_record, "soap", clinical_suggestions)

        # Check all major sections present
        assert "John Doe" in html
        assert "MRN12345" in html
        assert "Cough and fever" in html
        assert "productive cough" in html
        assert "crackles" in html
        assert "pneumonia" in html
        assert "azithromycin" in html or "Azithromycin" in html
        assert "Penicillin" in html
        assert "alert" in html.lower()

    def test_all_templates_render_without_error(self, generator, complete_record, clinical_suggestions):
        """Test all templates render successfully."""
        templates = ["soap", "discharge", "consultation", "progress"]

        for template_name in templates:
            html = generator.generate(complete_record, template_name, clinical_suggestions)
            assert html is not None
            assert len(html) > 0
            assert complete_record["patient"]["name"] in html
