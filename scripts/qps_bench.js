// MedScribe -- k6 Ingestion QPS Benchmark
//
// Measures the raw request-acceptance rate of the Go gateway pipeline trigger
// endpoint (Go -> JWT validation -> Kafka produce -> Redis seed -> 202).
// Does NOT wait for pipeline completion -- this is purely ingestion throughput.
//
// Not invoked directly. Use scripts/bench-qps.sh which handles auth setup
// and passes the required environment variables.
//
// Environment variables (set by bench-qps.sh):
//   BASE_URL      Gateway base URL
//   AUTH_TOKEN     JWT bearer token
//   SESSIONS_FILE  Path to JSON file with pre-created session IDs
//   TARGET_QPS     Target requests per second (default: 500)
//   DURATION       Test duration (default: 30s)
//   MAX_VUS        Max virtual users (default: 200)

import http from "k6/http";
import { check } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import { SharedArray } from "k6/data";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const triggerLatency = new Trend("trigger_latency_ms", true);
const triggerSuccess = new Rate("trigger_success_rate");
const triggerAccepted = new Counter("trigger_accepted_total");
const triggerFailed = new Counter("trigger_failed_total");
const kafkaEnqueueRate = new Rate("kafka_enqueue_rate");

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";
const TOKEN = __ENV.AUTH_TOKEN;
const TARGET_QPS = parseInt(__ENV.TARGET_QPS || "500", 10);
const DURATION = __ENV.DURATION || "30s";
const MAX_VUS = parseInt(__ENV.MAX_VUS || "400", 10);

if (!TOKEN) {
  throw new Error("AUTH_TOKEN env var is required. Use scripts/bench-qps.sh.");
}

// Pre-created sessions loaded from JSON file
const sessions = new SharedArray("sessions", function () {
  const path = __ENV.SESSIONS_FILE;
  if (!path) {
    throw new Error("SESSIONS_FILE env var is required");
  }
  return JSON.parse(open(path));
});

// ---------------------------------------------------------------------------
// Scenarios
// ---------------------------------------------------------------------------
export const options = {
  scenarios: {
    // Phase 1: gentle warm-up at 20% of target. The heavy pre-warming
    // (cache + pool + Kafka) is done by bench-qps.sh before k6 starts.
    // This phase just eases VU allocation so the executor does not need to
    // allocate all VUs in a single tick when the sustained phase begins.
    warmup: {
      executor: "constant-arrival-rate",
      rate: Math.max(1, Math.ceil(TARGET_QPS * 0.2)),
      timeUnit: "1s",
      duration: "10s",
      preAllocatedVUs: Math.ceil(MAX_VUS * 0.3),
      maxVUs: Math.ceil(MAX_VUS * 0.6),
      startTime: "0s",
      exec: "triggerPipeline",
    },
    // Phase 2: full target QPS — sustained load
    sustained: {
      executor: "constant-arrival-rate",
      rate: TARGET_QPS,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: Math.ceil(MAX_VUS * 0.5),
      maxVUs: MAX_VUS,
      startTime: "10s",
      exec: "triggerPipeline",
    },
  },
  thresholds: {
    // Latency SLOs -- p95 at 150ms and p99 at 400ms account for Docker
    // Desktop network virtualization overhead on macOS. In a real K8s
    // cluster with host networking these would be tighter.
    trigger_latency_ms: ["p(50)<50", "p(95)<150", "p(99)<400"],
    // At least 99% of triggers accepted (202)
    trigger_success_rate: ["rate>0.99"],
    // Standard HTTP thresholds
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<200"],
  },
};

// ---------------------------------------------------------------------------
// Reusable request payload and headers
// ---------------------------------------------------------------------------
const headers = {
  "Content-Type": "application/json",
  Authorization: `Bearer ${TOKEN}`,
};

function makePayload(sessionID) {
  return JSON.stringify({
    session_id: sessionID,
    patient_id: `bench_patient_${__VU}_${__ITER}`,
    doctor_id: "bench_doctor",
    is_new_patient: true,
    segments: [
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
    ],
  });
}

// ---------------------------------------------------------------------------
// Main test function
// ---------------------------------------------------------------------------
export function triggerPipeline() {
  // Round-robin across pre-created sessions
  const idx = (__VU * 1000 + __ITER) % sessions.length;
  const sessionID = sessions[idx];

  const res = http.post(
    `${BASE_URL}/api/session/${sessionID}/pipeline`,
    makePayload(sessionID),
    { headers: headers, tags: { name: "trigger" } }
  );

  const latency = res.timings.duration;
  triggerLatency.add(latency);

  const accepted = check(res, {
    "status is 202": (r) => r.status === 202,
  });

  if (accepted) {
    triggerSuccess.add(1);
    triggerAccepted.add(1);
    kafkaEnqueueRate.add(1);
  } else {
    triggerSuccess.add(0);
    triggerFailed.add(1);
    kafkaEnqueueRate.add(0);

    // Log first few failures for debugging
    if (__ITER < 5) {
      console.error(
        `VU=${__VU} iter=${__ITER} status=${res.status} body=${res.body}`
      );
    }
  }
}
