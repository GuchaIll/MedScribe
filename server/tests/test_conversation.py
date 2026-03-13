#!/usr/bin/env python3
"""
DEPRECATED — Manual agent intercept test script.

This is a **manual** test script, NOT part of the automated test suite (pytest).
It requires the server to already be running at http://localhost:3001.
Consider migrating this to a proper integration test.

Simulates a clinical conversation designed to trigger two specific alerts:
  1. Penicillin allergy + amoxicillin prescription (beta-lactam cross-reactivity)
  2. Warfarin (current med) + aspirin (new request) (bleeding-risk interaction)

Usage (from the server/ directory, with backend running):
    python tests/test_conversation.py
"""

import sys
import time
import requests

BASE = "http://localhost:3001"

# Conversation is structured so that alert-triggering utterances come AFTER
# the relevant context has been established (allergy declared before prescribing,
# existing med declared before new one is requested).
CONVERSATION = [
    ("Clinician", "Good morning. What brings you in today?"),
    ("Patient",   "I've had a sore throat and a fever for the past two days."),
    ("Clinician", "Before we proceed — do you have any known drug allergies?"),
    # Penicillin allergy established here
    ("Patient",   "Yes, I'm allergic to penicillin. I had a bad rash last time I took it."),
    ("Clinician", "Noted. Are you currently taking any medications regularly?"),
    # Warfarin established here
    ("Patient",   "I take warfarin every day for my atrial fibrillation."),
    # === ALERT 1 should fire here: amoxicillin + penicillin allergy ===
    ("Clinician", "I'd like to prescribe amoxicillin for the throat infection."),
    ("Patient",   "Alright. Also, can I take aspirin to help with the fever?"),
    # === ALERT 2 should fire here: warfarin + aspirin interaction ===
    ("Clinician", "Let me check that. Aspirin can interact with your warfarin."),
]


def run():
    print("=" * 62)
    print("  Medical Transcription — Agent Intercept Test")
    print("=" * 62)

    # Start session
    try:
        res = requests.post(f"{BASE}/api/session/start", timeout=10)
        res.raise_for_status()
    except Exception as exc:
        print(f"\n[ERROR] Could not connect to backend at {BASE}: {exc}")
        print("  Make sure the server is running:  uvicorn main:app --reload --port 3001")
        sys.exit(1)

    session_id = res.json()["session_id"]
    print(f"\nSession: {session_id}\n")

    agent_fire_count = 0

    for speaker, text in CONVERSATION:
        print(f"  {speaker:<12} {text}")
        try:
            res = requests.post(
                f"{BASE}/api/session/{session_id}/transcribe",
                json={"text": text, "speaker": speaker},
                timeout=10,
            )
            res.raise_for_status()
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            continue

        data = res.json()
        if data.get("agent_message"):
            agent_fire_count += 1
            print()
            print(f"  {'─' * 58}")
            print(f"  🤖  {data['agent_message']}")
            print(f"  {'─' * 58}")
            print()

        time.sleep(0.25)

    # End session
    try:
        requests.post(f"{BASE}/api/session/{session_id}/end", timeout=5)
    except Exception:
        pass

    print(f"\nSession ended.")
    print(f"\n{'─' * 62}")
    print(f"  Result: {agent_fire_count} agent intercept(s) fired")

    if agent_fire_count == 0:
        print()
        print("  No intercepts fired. Possible causes:")
        print("  - Clinical engine returned risk_level='low'")
        print("    (check that keyword extraction matched the drug names)")
        print("  - Exception in agent — check server logs")
        sys.exit(1)
    elif agent_fire_count >= 2:
        print("  ✓  Both allergy and interaction alerts detected correctly")
    else:
        print("  ~  Only one alert fired — partial pass")

    print(f"{'─' * 62}")


if __name__ == "__main__":
    run()
