/**
 * services/
 * ---------
 * HTTP helpers and API wrappers — keeps fetch logic out of React components.
 *
 * Create `cpi.js`, `incidents.js`, etc. as you add endpoints on the FastAPI side.
 */

/**
 * API base URL:
 * - If ``VITE_API_URL`` is set → use it (direct calls; backend must allow this origin in CORS).
 * - In dev with no env → ``/api`` so Vite proxies to FastAPI (same origin, no CORS pain).
 * - Production build without env → localhost:8000 (override with VITE_API_URL in deploy).
 */
function apiBase() {
  const raw = import.meta.env.VITE_API_URL;
  if (raw != null && String(raw).trim() !== "") {
    return String(raw).replace(/\/$/, "");
  }
  if (import.meta.env.DEV) {
    return "/api";
  }
  return "http://localhost:8000";
}

const base = apiBase();

export async function fetchHealth() {
  const res = await fetch(`${base}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

/** Latest autonomous-monitor incidents (SQLite); newest first. */
export async function fetchIncidents(limit = 100) {
  const res = await fetch(`${base}/incidents?limit=${encodeURIComponent(limit)}`);
  if (!res.ok) throw new Error(`Incidents fetch failed: ${res.status}`);
  return res.json();
}

/** Scheduler config + next poll time (GET /monitor/status). */
export async function fetchMonitorStatus() {
  const res = await fetch(`${base}/monitor/status`);
  if (!res.ok) throw new Error(`Monitor status failed: ${res.status}`);
  return res.json();
}

/**
 * One immediate CPI FAILED-MPL poll + full agent + SQLite (POST /monitor/run-now).
 * Does not require SCHEDULER_ENABLED — needs CPI_USE_MOCK=false and MONITOR_IFLOW_IDS set.
 */
export async function postMonitorRunNow() {
  const res = await fetch(`${base}/monitor/run-now`, { method: "POST" });
  if (!res.ok) throw new Error(`Run-now failed: ${res.status}`);
  return res.json();
}

/**
 * Incidents joined with llm_exchange rows and in-memory monitor runs (GET /observability/lifecycles).
 */
export async function fetchObservabilityLifecycles(limit = 100, exchangeLimit = 30) {
  const q = new URLSearchParams({
    limit: String(limit),
    exchange_limit: String(exchangeLimit),
  });
  const res = await fetch(`${base}/observability/lifecycles?${q}`);
  if (!res.ok) throw new Error(`Observability lifecycles failed: ${res.status}`);
  return res.json();
}
