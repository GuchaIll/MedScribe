from typing import Any, Dict

# Deterministic validation contract for structured clinical records.
CONTRACT: Dict[str, Any] = {
    "fields": {
        "patient": {
            "type": dict,
            "required": True,
            "schema": {
                "name": {"type": str, "required": True, "non_empty": True},
                "dob": {"type": str, "required": True, "iso_format": True},
                "age": {"type": int, "required": False, "min_confidence": 0.9},
                "sex": {"type": str, "required": False},
                "mrn": {"type": str, "required": False},
            },
        },
        "visit": {
            "type": dict,
            "required": True,
            "schema": {
                "date": {"type": str, "required": True, "iso_format": True},
                "type": {"type": str, "required": False},
                "location": {"type": str, "required": False},
                "provider": {"type": str, "required": False},
            },
        },
        "diagnoses": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "code": {"type": str, "required": True, "non_empty": True},
                    "description": {"type": str, "required": False},
                    "confidence": {"type": float, "required": False},
                }
            },
        },
        "medications": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "name": {"type": str, "required": True, "non_empty": True},
                    "dose": {"type": str, "required": False},
                    "route": {"type": str, "required": False},
                    "frequency": {"type": str, "required": False},
                    "start_date": {"type": str, "required": False, "iso_format": True},
                    "confidence": {"type": float, "required": False},
                }
            },
        },
        "allergies": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "substance": {"type": str, "required": True, "non_empty": True},
                    "reaction": {"type": str, "required": False},
                    "severity": {"type": str, "required": False},
                }
            },
        },
        "problems": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "name": {"type": str, "required": True, "non_empty": True},
                    "status": {"type": str, "required": False},
                }
            },
        },
        "labs": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "test": {"type": str, "required": True, "non_empty": True},
                    "value": {"type": str, "required": False},
                    "unit": {"type": str, "required": False},
                    "date": {"type": str, "required": False, "iso_format": True},
                }
            },
        },
        "procedures": {
            "type": list,
            "required": False,
            "item_schema": {
                "schema": {
                    "name": {"type": str, "required": True, "non_empty": True},
                    "date": {"type": str, "required": False, "iso_format": True},
                }
            },
        },
        "notes": {
            "type": dict,
            "required": False,
            "schema": {
                "subjective": {"type": str, "required": False},
                "objective": {"type": str, "required": False},
                "assessment": {"type": str, "required": False},
                "plan": {"type": str, "required": False},
            },
        },
    }
}
