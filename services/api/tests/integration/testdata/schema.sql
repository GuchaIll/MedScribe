CREATE TYPE userrole AS ENUM ('doctor', 'nurse', 'admin', 'medical_assistant');
CREATE TYPE sessionstatus AS ENUM ('active', 'completed', 'error', 'review_pending');

CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name TEXT,
    role userrole NOT NULL,
    permissions TEXT[] NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_login TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE patients (
    id TEXT PRIMARY KEY,
    mrn TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    dob TIMESTAMPTZ NOT NULL,
    age INTEGER NULL,
    sex TEXT NULL,
    encrypted_demographics TEXT NULL,
    created_by TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    patient_id TEXT NULL,
    doctor_id TEXT NOT NULL,
    status sessionstatus NOT NULL DEFAULT 'active',
    visit_type TEXT NULL,
    workflow_state TEXT NULL,
    checkpoint_id TEXT NULL,
    audio_file_path TEXT NULL,
    duration_seconds INTEGER NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE medical_records (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    template_type TEXT NOT NULL DEFAULT 'soap',
    structured_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    clinical_note TEXT NOT NULL DEFAULT '',
    is_finalized BOOLEAN NOT NULL DEFAULT false,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalized_at TIMESTAMPTZ NULL
);

CREATE TABLE session_documents (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    original_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    extracted_text TEXT NULL,
    processed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE modification_queue (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    field_path TEXT NOT NULL,
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
