// Load test for the API through the web app's proxy (what browsers use).
//
//   docker run --rm -i --network host -e BASE=http://localhost:3000 -e SESSION=<cookie> \
//     -e PROFILE=smoke grafana/k6:1.3.0 run - < scripts/load/k6-api.js
//
// SESSION is the value of the signed-in `vey_session` cookie (optional; without it only
// public endpoints run). PROFILE=smoke (20 users, 1 minute) or load (200 users, 10 minutes).
// Chat answers are not included: their latency is the model's, measured in Monitoring.
import http from "k6/http";
import { check } from "k6";

const BASE = __ENV.BASE || "http://localhost:3000";
const SESSION = __ENV.SESSION || "";
const PROFILES = {
  smoke: [
    { duration: "15s", target: 20 },
    { duration: "30s", target: 20 },
    { duration: "15s", target: 0 },
  ],
  load: [
    { duration: "2m", target: 200 },
    { duration: "6m", target: 200 },
    { duration: "2m", target: 0 },
  ],
};

export const options = {
  stages: PROFILES[__ENV.PROFILE || "smoke"],
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{kind:public}": ["p(95)<300"],
    "http_req_duration{kind:signed_in}": ["p(95)<500"],
  },
};

const headers = SESSION ? { Cookie: `vey_session=${SESSION}` } : {};

export default function () {
  const status = http.get(`${BASE}/api/v1/status`, { tags: { kind: "public" } });
  check(status, { "status 200": (r) => r.status === 200 });
  const info = http.get(`${BASE}/api/v1/public/info`, { tags: { kind: "public" } });
  check(info, { "info 200": (r) => r.status === 200 });
  if (SESSION) {
    for (const path of ["/api/v1/me", "/api/v1/me/chatbots", "/api/v1/chat/conversations?limit=8"]) {
      const res = http.get(`${BASE}${path}`, { headers, tags: { kind: "signed_in" } });
      check(res, { [`${path} 200`]: (r) => r.status === 200 });
    }
  }
}
