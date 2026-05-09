/**
 * pages/
 * ------
 * Top-level screens (routes). Compose components here — avoid giant JSX blobs.
 */

import { useEffect, useState } from "react";
import { fetchHealth } from "../services/api.js";

export default function Dashboard() {
  const [health, setHealth] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((e) => setErr(String(e.message)));
  }, []);

  return (
    <div>
      <h1>Dashboard</h1>
      <p>Starter screen — replace with CPI integration health, incidents, and AI summaries.</p>

      <section style={{ marginTop: "1.5rem" }}>
        <h2 style={{ fontSize: "1.1rem" }}>Backend status</h2>
        {err && <p style={{ color: "#b91c1c" }}>Could not reach API: {err}</p>}
        {!err && !health && <p>Checking…</p>}
        {health && (
          <pre
            style={{
              background: "#fff",
              border: "1px solid #e2e8f0",
              padding: "1rem",
              borderRadius: "8px",
            }}
          >
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
      </section>
    </div>
  );
}
