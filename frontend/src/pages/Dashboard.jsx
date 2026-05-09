/**
 * Dashboard — backend health + autonomous monitor incidents (30s auto-refresh).
 */

import { useCallback, useEffect, useState } from "react";
import { fetchHealth, fetchIncidents } from "../services/api.js";

const REFRESH_MS = 30_000;

function severityStyle(sev) {
  const s = (sev || "").toUpperCase();
  if (s === "CRITICAL") return { bg: "#450a0a", fg: "#fecaca", label: "CRITICAL" };
  if (s === "HIGH") return { bg: "#7c2d12", fg: "#ffedd5", label: "HIGH" };
  if (s === "MEDIUM") return { bg: "#854d0e", fg: "#fef9c3", label: "MEDIUM" };
  if (s === "LOW") return { bg: "#334155", fg: "#e2e8f0", label: "LOW" };
  return { bg: "#475569", fg: "#f8fafc", label: s || "—" };
}

function statusStyle(st) {
  const s = (st || "").toLowerCase();
  if (s === "completed") return { bg: "#14532d", fg: "#bbf7d0", label: "completed" };
  if (s === "failed") return { bg: "#7f1d1d", fg: "#fecaca", label: "failed" };
  return { bg: "#1e3a5f", fg: "#bfdbfe", label: st || "—" };
}

export default function Dashboard() {
  const [health, setHealth] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [err, setErr] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [h, inc] = await Promise.all([fetchHealth(), fetchIncidents(100)]);
      setHealth(h);
      const rows = Array.isArray(inc) ? inc : inc?.incidents ?? [];
      setIncidents(rows);
      setLastRefresh(new Date().toISOString());
    } catch (e) {
      setErr(String(e.message || e));
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div>
      <h1>IntegrationOps-AI</h1>
      <p style={{ color: "#64748b", fontSize: "0.95rem" }}>
        Incidents auto-refresh every {REFRESH_MS / 1000}s from <code>GET /incidents</code>
        {lastRefresh && (
          <>
            {" "}
            · last fetch: {lastRefresh}
          </>
        )}
      </p>

      <section style={{ marginTop: "1.25rem" }}>
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
              fontSize: "0.85rem",
            }}
          >
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.1rem" }}>Latest incidents</h2>
        {!err && incidents.length === 0 && <p style={{ color: "#64748b" }}>No stored incidents yet (run the CPI monitor or POST /monitor/run-now).</p>}
        {incidents.length > 0 && (
          <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: "8px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.88rem" }}>
              <thead>
                <tr style={{ background: "#f8fafc", textAlign: "left" }}>
                  <th style={{ padding: "0.6rem 0.75rem" }}>When</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>iFlow</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>Severity</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>Type</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>Confidence</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>Jira</th>
                  <th style={{ padding: "0.6rem 0.75rem" }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((row) => {
                  const sev = severityStyle(row.severity);
                  const st = statusStyle(row.investigation_status);
                  return (
                    <tr key={row.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                      <td style={{ padding: "0.55rem 0.75rem", whiteSpace: "nowrap" }}>{row.timestamp}</td>
                      <td style={{ padding: "0.55rem 0.75rem" }}>
                        <code>{row.iflow}</code>
                        <div style={{ fontSize: "0.75rem", color: "#64748b" }} title={row.message_id}>
                          msg {String(row.message_id || "").slice(0, 12)}…
                        </div>
                      </td>
                      <td style={{ padding: "0.55rem 0.75rem" }}>
                        <span
                          style={{
                            display: "inline-block",
                            padding: "0.15rem 0.5rem",
                            borderRadius: "6px",
                            fontWeight: 600,
                            fontSize: "0.75rem",
                            background: sev.bg,
                            color: sev.fg,
                          }}
                        >
                          {sev.label}
                        </span>
                      </td>
                      <td style={{ padding: "0.55rem 0.75rem" }}>{row.error_type}</td>
                      <td style={{ padding: "0.55rem 0.75rem" }}>{row.confidence_score}</td>
                      <td style={{ padding: "0.55rem 0.75rem", fontFamily: "monospace", fontSize: "0.8rem" }}>
                        {row.jira_ticket_id || "—"}
                      </td>
                      <td style={{ padding: "0.55rem 0.75rem" }}>
                        <span
                          style={{
                            display: "inline-block",
                            padding: "0.15rem 0.45rem",
                            borderRadius: "6px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            background: st.bg,
                            color: st.fg,
                          }}
                        >
                          {st.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {incidents.length > 0 && (
          <details style={{ marginTop: "1rem" }}>
            <summary style={{ cursor: "pointer", color: "#475569" }}>Root cause & recommendation (first row)</summary>
            <pre
              style={{
                marginTop: "0.5rem",
                background: "#0f172a",
                color: "#e2e8f0",
                padding: "1rem",
                borderRadius: "8px",
                fontSize: "0.8rem",
                whiteSpace: "pre-wrap",
              }}
            >
              {JSON.stringify(
                {
                  root_cause: incidents[0]?.root_cause,
                  recommendation: incidents[0]?.recommendation,
                },
                null,
                2
              )}
            </pre>
          </details>
        )}
      </section>
    </div>
  );
}
