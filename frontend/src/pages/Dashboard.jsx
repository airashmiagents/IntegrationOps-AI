/**
 * Dashboard — backend health + autonomous monitor incidents (30s auto-refresh).
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchHealth, fetchIncidents, fetchMonitorStatus, postMonitorRunNow } from "../services/api.js";

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
  const [monitorStatus, setMonitorStatus] = useState(null);
  const [err, setErr] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [runBusy, setRunBusy] = useState(false);
  const [runSummary, setRunSummary] = useState(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [h, inc] = await Promise.all([fetchHealth(), fetchIncidents(100)]);
      setHealth(h);
      const rows = Array.isArray(inc) ? inc : inc?.incidents ?? [];
      setIncidents(rows);
      try {
        setMonitorStatus(await fetchMonitorStatus());
      } catch {
        setMonitorStatus(null);
      }
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

      <p style={{ marginTop: "0.65rem", fontSize: "0.9rem" }}>
        <Link to="/alerts/mock-inbox">Open mock alert inbox</Link> — preview how CPI incident emails would look (no
        mail server).
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

      <section style={{ marginTop: "1.5rem", padding: "1rem", background: "#f0fdf4", border: "1px solid #86efac", borderRadius: "8px" }}>
        <h2 style={{ fontSize: "1.1rem", marginTop: 0 }}>Demo: run CPI monitor now</h2>
        <p style={{ margin: "0.5rem 0 1rem", color: "#166534", fontSize: "0.9rem" }}>
          Triggers <code>POST /monitor/run-now</code> — same path as the scheduler: FAILED MPL → full agent →
          <code> incidents</code> SQLite. Backend must stay running; this does not replace uvicorn.
        </p>

        {monitorStatus && (
          <div
            style={{
              marginBottom: "1rem",
              padding: "0.75rem 1rem",
              background: "#fff",
              border: "1px solid #bbf7d0",
              borderRadius: "8px",
              fontSize: "0.88rem",
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: "0.35rem", color: "#14532d" }}>Live config (GET /monitor/status)</div>
            <div style={{ color: "#166534" }}>
              <strong>MONITOR_IFLOW_IDS</strong> →{" "}
              {(monitorStatus.monitored_artifact_ids || []).length ? (
                <code>{(monitorStatus.monitored_artifact_ids || []).join(", ")}</code>
              ) : (
                <span style={{ color: "#b45309" }}>none (empty list — run-now cannot poll CPI yet)</span>
              )}
            </div>
            <div style={{ marginTop: "0.35rem", color: "#166534" }}>
              <strong>CPI_USE_MOCK</strong>: {String(monitorStatus.cpi_use_mock)} · <strong>lookback</strong>:{" "}
              {monitorStatus.lookback_minutes ?? "—"} min
            </div>
            {(monitorStatus.monitored_artifact_ids || []).length === 0 && (
              <p style={{ margin: "0.5rem 0 0", color: "#92400e", lineHeight: 1.45 }}>
                Edit <code>backend/.env</code>, set <code>MONITOR_IFLOW_IDS=&lt;IntegrationArtifact.Id&gt;</code> (comma-separated if
                several), save, then restart uvicorn from the <code>backend</code> folder. If you already set it, a restart was
                still required — pydantic-settings reads <code>.env</code> at process start only.
              </p>
            )}
            {monitorStatus.cpi_use_mock && (
              <p style={{ margin: "0.5rem 0 0", color: "#92400e", lineHeight: 1.45 }}>
                With <code>CPI_USE_MOCK=true</code>, the monitor never calls your tenant; run-now returns{" "}
                <code>skipped: cpi_use_mock</code> until you use real CPI settings.
              </p>
            )}
          </div>
        )}

        <button
          type="button"
          disabled={runBusy || !!err}
          onClick={async () => {
            setRunSummary(null);
            setRunBusy(true);
            try {
              const out = await postMonitorRunNow();
              setRunSummary(out);
              await load();
            } catch (e) {
              setRunSummary({ ok: false, error: String(e.message || e) });
            } finally {
              setRunBusy(false);
            }
          }}
          style={{
            padding: "0.5rem 1rem",
            fontWeight: 600,
            borderRadius: "8px",
            border: "1px solid #16a34a",
            background: runBusy ? "#cbd5e1" : "#22c55e",
            color: "#fff",
            cursor: runBusy || err ? "not-allowed" : "pointer",
          }}
        >
          {runBusy ? "Running…" : "Run CPI monitor now"}
        </button>
        {runSummary && (
          <div style={{ marginTop: "0.75rem" }}>
            {runSummary.error ? (
              <p style={{ color: "#b91c1c", fontSize: "0.9rem" }}>{runSummary.error}</p>
            ) : (
              <>
                <p style={{ fontSize: "0.9rem", margin: "0 0 0.5rem" }}>{runSummary.message || "OK"}</p>
                {runSummary.skipped && (
                  <p
                    style={{
                      margin: "0.5rem 0 0",
                      padding: "0.5rem 0.75rem",
                      background: "#fffbeb",
                      border: "1px solid #fcd34d",
                      borderRadius: "6px",
                      fontSize: "0.88rem",
                      color: "#92400e",
                    }}
                  >
                    <strong style={{ fontFamily: "monospace", fontSize: "0.82rem" }}>{runSummary.skipped}</strong>
                    <br />
                    {runSummary.hint || "See README and backend/.env.example."}
                  </p>
                )}
                {Array.isArray(runSummary.outcomes) && runSummary.outcomes.length > 0 && (
                  <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem", fontSize: "0.86rem", color: "#14532d" }}>
                    {runSummary.outcomes.map((o, idx) => (
                      <li key={`${o.artifact_id}-${idx}-${o.result}`}>
                        <code>{o.artifact_id}</code> → {o.result}
                        {o.detail ? (
                          <span style={{ color: "#64748b" }}>
                            {" "}
                            ({String(o.detail).length > 120 ? `${String(o.detail).slice(0, 120)}…` : o.detail})
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )}
                {"incidents_stored" in runSummary && (
                  <p
                    style={{
                      margin: "0.5rem 0 0",
                      fontSize: "0.88rem",
                      color: runSummary.skipped ? "#64748b" : "#166534",
                    }}
                  >
                    Incidents inserted this cycle: <strong>{runSummary.incidents_stored}</strong>
                    {runSummary.skipped
                      ? " — expected when the cycle did not run investigations (see reason above)."
                      : runSummary.incidents_stored === 0 &&
                          (runSummary.outcomes || []).some((o) => o.result && String(o.result).startsWith("skipped_"))
                        ? " — MPL had no new failures to analyze, or duplicate message_id, for each artifact."
                        : null}
                  </p>
                )}
                <details style={{ marginTop: "0.75rem" }}>
                  <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>Full API response</summary>
                  <pre
                    style={{
                      marginTop: "0.5rem",
                      background: "#fff",
                      border: "1px solid #e2e8f0",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      fontSize: "0.78rem",
                      overflow: "auto",
                    }}
                  >
                    {JSON.stringify(runSummary, null, 2)}
                  </pre>
                </details>
              </>
            )}
          </div>
        )}
        {monitorStatus && (
          <details style={{ marginTop: "1rem" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.85rem", color: "#475569" }}>
              Raw GET /monitor/status JSON
            </summary>
            <pre
              style={{
                marginTop: "0.5rem",
                background: "#fff",
                border: "1px solid #e2e8f0",
                padding: "0.75rem",
                borderRadius: "8px",
                fontSize: "0.78rem",
                overflow: "auto",
              }}
            >
              {JSON.stringify(monitorStatus, null, 2)}
            </pre>
          </details>
        )}
      </section>

      <section style={{ marginTop: "2rem" }}>
        <h2 style={{ fontSize: "1.1rem" }}>Latest incidents</h2>
        {!err && incidents.length === 0 && (
          <p style={{ color: "#64748b" }}>
            No stored incidents yet — configure <code>MONITOR_IFLOW_IDS</code> and real CPI (see demo box above), then run the
            monitor. For DB + LLM audit drill-down after rows exist, open{" "}
            <Link to="/monitor/lifecycle">Monitor lifecycle</Link>.
          </p>
        )}
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
