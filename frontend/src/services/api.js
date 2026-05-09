/**
 * services/
 * ---------
 * HTTP helpers and API wrappers — keeps fetch logic out of React components.
 *
 * Create `cpi.js`, `incidents.js`, etc. as you add endpoints on the FastAPI side.
 */

const base =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export async function fetchHealth() {
  const res = await fetch(`${base}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
