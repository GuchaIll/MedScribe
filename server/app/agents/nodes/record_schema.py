from typing import List, Optional

from pydantic import BaseModel, Field


class Patient(BaseModel):
    name: str
    dob: str
    age: Optional[int] = None
    sex: Optional[str] = None
    mrn: Optional[str] = None


class Visit(BaseModel):
    date: str
    type: Optional[str] = None
    location: Optional[str] = None
    provider: Optional[str] = None


class Diagnosis(BaseModel):
    code: str
    description: Optional[str] = None
    confidence: Optional[float] = None


class Medication(BaseModel):
    name: str
    dose: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    start_date: Optional[str] = None
    confidence: Optional[float] = None


class Allergy(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: Optional[str] = None


class Problem(BaseModel):
    name: str
    status: Optional[str] = None


class Lab(BaseModel):
    test: str
    value: Optional[str] = None
    unit: Optional[str] = None
    date: Optional[str] = None


class Procedure(BaseModel):
    name: str
    date: Optional[str] = None


class Notes(BaseModel):
    subjective: Optional[str] = None
    objective: Optional[str] = None
    assessment: Optional[str] = None
    plan: Optional[str] = None


class StructuredRecord(BaseModel):
    patient: Patient
    visit: Visit
    diagnoses: List[Diagnosis] = Field(default_factory=list)
    medications: List[Medication] = Field(default_factory=list)
    allergies: List[Allergy] = Field(default_factory=list)
    problems: List[Problem] = Field(default_factory=list)
    labs: List[Lab] = Field(default_factory=list)
    procedures: List[Procedure] = Field(default_factory=list)
    notes: Optional[Notes] = None
