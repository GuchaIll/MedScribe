Demo: “Contradictory Allergy + Medication Across Docs”
Inputs

Transcript says:

“Patient reports no allergies.”

Later: “Actually, I had a rash with penicillin years ago.”

PDF med list includes:

Amoxicillin prescribed last week

Discharge summary lists:

Allergy: Penicillin (rash)

Expected system behavior (what you show in UI/logs)
Outputs (artifacts)

Structured record

allergies: [penicillin -> rash]

medications: amoxicillin flagged with contraindication_warning = true

Conflict report

Conflict type: ALLERGY_CONTRADICTION

Evidence:

transcript span A (“no allergies”)

transcript span B (“rash with penicillin”)

discharge summary allergy section

Resolution:

pick “penicillin allergy (rash)” (higher confidence: discharge + later transcript)

Validation report

warning: Medication amoxicillin conflicts with penicillin allergy

status: needs_review = true OR “resolved but flagged” depending on policy

Human review gate

Generates one crisp question:

“Confirm whether amoxicillin is safe given penicillin rash history.”

Clinical note

Includes allergy and warning, with no hallucinated extras.