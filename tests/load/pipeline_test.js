// MedScribe — k6 Load Test: Pipeline Trigger + Status Polling
//
// Tests the full strangler-fig path:
//   Go gateway -> Kafka -> Go consumer -> Python pipeline -> Redis status
//
// Install k6:
//   brew install k6            (macOS)
//   go install go.k6.io/k6@latest  (from source)
//
// Usage:
//   k6 run tests/load/pipeline_test.js                          # defaults
//   k6 run --env BASE_URL=http://localhost:8080 tests/load/pipeline_test.js
//   k6 run --env VUS=50 --env DURATION=2m tests/load/pipeline_test.js
//
// Environment variables:
//   BASE_URL   — Gateway base URL (default: http://localhost:8080)
//   VUS        — Max virtual users (default: 100)
//   DURATION   — Test duration (default: 3m)

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const pipelineTriggerDuration = new Trend("pipeline_trigger_duration", true);
const pipelineStatusDuration = new Trend("pipeline_status_duration", true);
const pipelinePollCount = new Counter("pipeline_poll_count");
const pipelineCompletedRate = new Rate("pipeline_completed_rate");
const pipelineErrorRate = new Rate("pipeline_error_rate");

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const MAX_VUS = parseInt(__ENV.VUS || "100", 10);
const DURATION = __ENV.DURATION || "3m";

export const options = {
  scenarios: {
    ramp_up: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "30s", target: Math.ceil(MAX_VUS * 0.1) },  // warm-up
        { duration: "30s", target: Math.ceil(MAX_VUS * 0.5) },  // ramp to 50%
        { duration: "1m", target: MAX_VUS },                     // full load
        { duration: "30s", target: MAX_VUS },                    // sustain
        { duration: "30s", target: 0 },                          // cool-down
      ],
      gracefulRampDown: "15s",
    },
  },
  thresholds: {
    // Go gateway p99 < 200ms for trigger (just enqueue to Kafka)
    "pipeline_trigger_duration{url:trigger}": ["p(99)<200"],
    // Status polling p95 < 100ms (Redis GET). p99 relaxed for Docker warm-up.
    "pipeline_status_duration{url:status}": ["p(95)<100", "p(99)<500"],
    // At least 80% of pipelines complete (rest may timeout during cool-down)
    pipeline_completed_rate: ["rate>0.8"],
    // Error rate under 5%
    pipeline_error_rate: ["rate<0.05"],
    // Standard k6 thresholds
    http_req_failed: ["rate<0.05"],
    http_req_duration: ["p(95)<500"],
  },
};

// ---------------------------------------------------------------------------
// Setup: create a shared test user and get a JWT token
// ---------------------------------------------------------------------------
export function setup() {
  const uniqueID = `loadtest_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
  const email = `${uniqueID}@test.local`;
  const password = "K6LoadTest!2024Secure";

  // Register
  const regRes = http.post(
    `${BASE_URL}/api/auth/register`,
    JSON.stringify({
      email: email,
      password: password,
      full_name: "K6 Load Tester",
      role: "doctor",
      occupation: "load_testing",
    }),
    { headers: { "Content-Type": "application/json" } }
  );

  check(regRes, {
    "register status 201": (r) => r.status === 201,
  });

  if (regRes.status !== 201) {
    console.error(`Registration failed: ${regRes.status} ${regRes.body}`);
    return { token: null };
  }

  // Login
  const loginRes = http.post(
    `${BASE_URL}/api/auth/login`,
    JSON.stringify({ email: email, password: password }),
    { headers: { "Content-Type": "application/json" } }
  );

  check(loginRes, {
    "login status 200": (r) => r.status === 200,
  });

  if (loginRes.status !== 200) {
    console.error(`Login failed: ${loginRes.status} ${loginRes.body}`);
    return { token: null };
  }

  const body = JSON.parse(loginRes.body);
  return { token: body.access_token };
}

// ---------------------------------------------------------------------------
// Helper: authenticated headers
// ---------------------------------------------------------------------------
function authHeaders(token) {
  return {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
  };
}

// ---------------------------------------------------------------------------
// Helper: generate realistic transcript segments
// ---------------------------------------------------------------------------
function mockSegments() {
  return [
    {
      start: 0.0,
      end: 5.2,
      speaker: "doctor",
      raw_text: "Good morning, how are you feeling today?",
      cleaned_text: "Good morning, how are you feeling today?",
      confidence: "0.95",
    },
    {
      start: 5.3,
      end: 12.1,
      speaker: "patient",
      raw_text:
        "I have been having headaches for the past week, mostly in the morning.",
      cleaned_text:
        "I have been having headaches for the past week, mostly in the morning.",
      confidence: "0.92",
    },
    {
      start: 12.2,
      end: 18.0,
      speaker: "doctor",
      raw_text:
        "Can you describe the pain? Is it throbbing, sharp, or dull?",
      cleaned_text:
        "Can you describe the pain? Is it throbbing, sharp, or dull?",
      confidence: "0.94",
    },
    {
      start: 18.1,
      end: 25.5,
      speaker: "patient",
      raw_text:
        "It is more of a dull ache. Sometimes I feel nauseous with it.",
      cleaned_text:
        "It is more of a dull ache. Sometimes I feel nauseous with it.",
      confidence: "0.91",
    },
    {
      start: 25.6,
      end: 32.0,
      speaker: "doctor",
      raw_text:
        "Any visual changes or sensitivity to light? Have you taken anything for it?",
      cleaned_text:
        "Any visual changes or sensitivity to light? Have you taken anything for it?",
      confidence: "0.93",
    },
  ];
}

// ---------------------------------------------------------------------------
// Main VU function
// ---------------------------------------------------------------------------
export default function (data) {
  if (!data.token) {
    console.error("No auth token available, skipping iteration");
    sleep(1);
    return;
  }

  const headers = authHeaders(data.token);

  group("pipeline_lifecycle", function () {
    // 1. Start a session
    const startRes = http.post(
      `${BASE_URL}/api/session/start`,
      null,
      headers
    );

    const sessionOK = check(startRes, {
      "session start 201": (r) => r.status === 201,
    });

    if (!sessionOK) {
      pipelineErrorRate.add(1);
      console.error(`Session start failed: ${startRes.status}`);
      sleep(1);
      return;
    }

    const sessionID = JSON.parse(startRes.body).session_id;

    // 2. Trigger pipeline
    const triggerPayload = JSON.stringify({
      session_id: sessionID,
      patient_id: `patient_${__VU}_${__ITER}`,
      doctor_id: `doctor_loadtest`,
      is_new_patient: true,
      segments: mockSegments(),
    });

    const triggerStart = Date.now();
    const triggerRes = http.post(
      `${BASE_URL}/api/session/${sessionID}/pipeline`,
      triggerPayload,
      headers
    );
    const triggerElapsed = Date.now() - triggerStart;

    pipelineTriggerDuration.add(triggerElapsed, { url: "trigger" });

    const triggerOK = check(triggerRes, {
      "pipeline trigger 202": (r) => r.status === 202,
    });

    if (!triggerOK) {
      pipelineErrorRate.add(1);
      console.error(
        `Pipeline trigger failed: ${triggerRes.status} ${triggerRes.body}`
      );
      sleep(1);
      return;
    }

    // 3. Poll pipeline status until completed/failed or timeout
    const maxPollTime = 180; // seconds — LLM pipeline can take 30-120s
    const pollInterval = 2; // seconds
    let elapsed = 0;
    let finalStatus = "unknown";

    while (elapsed < maxPollTime) {
      sleep(pollInterval);
      elapsed += pollInterval;

      const statusStart = Date.now();
      const statusRes = http.get(
        `${BASE_URL}/api/session/${sessionID}/pipeline/status`,
        headers
      );
      const statusElapsed = Date.now() - statusStart;

      pipelineStatusDuration.add(statusElapsed, { url: "status" });
      pipelinePollCount.add(1);

      check(statusRes, {
        "status poll 200": (r) => r.status === 200,
      });

      if (statusRes.status === 200) {
        const statusBody = JSON.parse(statusRes.body);
        finalStatus = statusBody.status;

        if (finalStatus === "completed" || finalStatus === "failed") {
          break;
        }
      }
    }

    // 4. Record outcome
    if (finalStatus === "completed") {
      pipelineCompletedRate.add(1);
      pipelineErrorRate.add(0);
    } else if (finalStatus === "failed") {
      pipelineCompletedRate.add(0);
      pipelineErrorRate.add(1);
    } else {
      // timeout
      pipelineCompletedRate.add(0);
      pipelineErrorRate.add(0);
    }
  });

  // Short pause between iterations to avoid pure spin
  sleep(1);
}

// ---------------------------------------------------------------------------
// Teardown: summary
// ---------------------------------------------------------------------------
export function teardown(data) {
  console.log("Load test complete.");
}
