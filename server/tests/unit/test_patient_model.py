from datetime import datetime

import pytest

from app.core.patient_model import (
    PatientModel,
    _parse_date,
    _safe_float,
    _trend_direction,
)


@pytest.mark.unit
class TestPatientModelHelpers:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ([1.0], "insufficient_data"),
            ([1.0, 2.0, 3.0, 4.0], "increasing"),
            ([4.0, 3.0, 2.0, 1.0], "decreasing"),
            ([10.0, 10.3, 9.9], "stable"),
            ([10.0, 13.0, 11.0, 14.0, 12.0], "fluctuating"),
        ],
    )
    def test_trend_direction_variants(self, values, expected):
        assert _trend_direction(values) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2024-01-02T03:04:05.123456", datetime(2024, 1, 2, 3, 4, 5, 123456)),
            ("2024-01-02T03:04:05", datetime(2024, 1, 2, 3, 4, 5)),
            ("2024-01-02", datetime(2024, 1, 2)),
        ],
    )
    def test_parse_date_supported_formats(self, raw, expected):
        assert _parse_date(raw) == expected

    def test_parse_date_invalid_falls_back_to_min(self):
        assert _parse_date("not-a-date") == datetime.min
        assert _parse_date("") == datetime.min

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("1.5", 1.5),
            (2, 2.0),
            (None, None),
            ("bad", None),
        ],
    )
    def test_safe_float_handles_valid_and_invalid_values(self, value, expected):
        assert _safe_float(value) == expected


@pytest.mark.unit
class TestPatientModel:
    def test_compute_lab_trends_sorts_values_and_ignores_invalid_entries(self):
        lab_history = [
            {"test_name": "A1C", "value": "7.2", "unit": "%", "date": "2024-03-01"},
            {"test_name": "A1C", "value": "bad", "unit": "%", "date": "2024-02-01"},
            {"test_name": "A1C", "value": "6.8", "unit": "%", "date": "2024-01-01"},
            {"test_name": "A1C", "value": "7.5", "unit": "%", "date": "2024-04-01", "abnormal": True},
            {"test_name": "", "value": "4.0", "date": "2024-01-01"},
        ]

        trends = PatientModel.compute_lab_trends(lab_history)

        assert len(trends) == 1
        assert trends[0]["test_name"] == "A1C"
        assert [point["value"] for point in trends[0]["data_points"]] == [6.8, 7.2, 7.5]
        assert trends[0]["trend_direction"] == "increasing"
        assert trends[0]["latest_value"] == 7.5
        assert trends[0]["latest_status"] == "abnormal"
        assert trends[0]["unit"] == "%"

    def test_compute_lab_trends_returns_insufficient_data_when_below_threshold(self):
        trends = PatientModel.compute_lab_trends(
            [{"test_name": "Sodium", "value": "140", "unit": "mmol/L", "date": "2024-01-01"}],
            min_points=2,
        )

        assert trends[0]["trend_direction"] == "insufficient_data"
        assert trends[0]["latest_status"] == "normal"

    def test_compute_medication_timeline_deduplicates_case_insensitively(self):
        medication_history = [
            {
                "name": "Metformin",
                "dose": "500mg",
                "route": "PO",
                "frequency": "BID",
                "status": "active",
                "last_recorded": "2024-01-01",
            },
            {
                "name": "metformin",
                "dose": "1000mg",
                "route": "PO",
                "frequency": "daily",
                "status": "discontinued",
                "last_recorded": "2024-03-01",
            },
            {
                "name": "Lisinopril",
                "dose": "10mg",
                "route": "PO",
                "frequency": "daily",
                "status": "active",
                "last_recorded": "2024-02-01",
            },
        ]

        timeline = PatientModel.compute_medication_timeline(medication_history)
        metformin = next(
            medication for medication in timeline["medications"] if medication["name"] == "metformin"
        )

        assert len(timeline["medications"]) == 2
        assert metformin["first_recorded"] == "2024-01-01"
        assert metformin["last_recorded"] == "2024-03-01"
        assert timeline["total_active"] == 1
        assert timeline["total_discontinued"] == 1
        assert timeline["adherence_score"] == 0.5

    def test_compute_medication_timeline_defaults_to_full_adherence_without_active_meds(self):
        timeline = PatientModel.compute_medication_timeline(
            [{"name": "Metformin", "status": "discontinued", "last_recorded": "2024-01-01"}]
        )

        assert timeline["total_active"] == 0
        assert timeline["total_discontinued"] == 1
        assert timeline["adherence_score"] == 1.0

    def test_compute_risk_score_accumulates_weighted_factors(self):
        diagnoses = [
            {"description": "Type 2 diabetes mellitus"},
            {"description": "Chronic kidney disease stage 3"},
            {"description": "Chronic heart failure"},
        ]
        medications = [{"name": f"Med {index}", "status": "active"} for index in range(11)]
        labs = [{"name": f"Lab {index}", "abnormal": True} for index in range(6)]

        risk = PatientModel.compute_risk_score(
            patient_info={"age": 78, "sex": "F"},
            diagnoses=diagnoses,
            medications=medications,
            labs=labs,
            visit_count=13,
        )

        assert risk["score"] == 78
        assert risk["level"] == "high"
        assert "Elderly patient (age 78)" in risk["factors"]
        assert "Condition: Type 2 diabetes mellitus" in risk["factors"]
        assert "Condition: Chronic kidney disease stage 3" in risk["factors"]
        assert "Condition: Chronic heart failure" in risk["factors"]
        assert "Polypharmacy — 11 active meds" in risk["factors"]
        assert "6 abnormal lab results" in risk["factors"]
        assert "Frequent visits (13)" in risk["factors"]
        datetime.fromisoformat(risk["computed_at"])

    def test_compute_risk_score_caps_score_at_one_hundred(self):
        diagnoses = [{"description": "Cancer"} for _ in range(10)]
        medications = [{"name": f"Med {index}", "status": "active"} for index in range(12)]
        labs = [{"abnormal": True} for _ in range(8)]

        risk = PatientModel.compute_risk_score(
            patient_info={"age": 90},
            diagnoses=diagnoses,
            medications=medications,
            labs=labs,
            visit_count=20,
        )

        assert risk["score"] == 100
        assert risk["level"] == "high"

    def test_build_patient_profile_aggregates_supported_record_data(self):
        patient_info = {"id": "patient-1", "full_name": "Jane Doe", "age": 68, "sex": "F"}
        records = [
            {
                "labs": [
                    {"test_name": "A1C", "value": "7.0", "unit": "%", "date": "2024-01-01"},
                    "skip-me",
                ],
                "medications": [
                    {
                        "name": "Metformin",
                        "status": "active",
                        "dose": "500mg",
                        "last_recorded": "2024-01-01",
                    }
                ],
                "diagnoses": [{"description": "Diabetes mellitus"}],
            },
            {
                "labs": [
                    {
                        "test_name": "A1C",
                        "value": "7.4",
                        "unit": "%",
                        "date": "2024-02-01",
                        "abnormal": True,
                    }
                ],
                "medications": [
                    {
                        "name": "Lisinopril",
                        "status": "active",
                        "dose": "10mg",
                        "last_recorded": "2024-02-01",
                    }
                ],
                "diagnoses": [{"description": "Hypertension"}],
            },
        ]

        profile = PatientModel.build_patient_profile(patient_info, records)

        assert profile["patient_id"] == "patient-1"
        assert profile["visit_count"] == 2
        assert profile["patient_info"]["full_name"] == "Jane Doe"
        assert profile["lab_trends"][0]["trend_direction"] == "increasing"
        assert profile["medication_timeline"]["total_active"] == 2
        assert profile["risk_score"]["level"] == "moderate"
