/**
 * Monitor lifecycle — incidents DB + canonical agent steps + LLM audit SQLite + recent monitor runs.
 */

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchObservabilityLifecycles } from "../services/api.js";

const preStyle = {
  background: "#fff",
  border: "1px solid #e2e8f0",
  padding: "0.75rem",
  borderRadius: "8px",
  fontSize: "0.78rem",
  overflow: "auto",
  maxHeight: "320px",
};

function JsonBlock({ value, title }) {
  let text = "";
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    text = String(value);
  }
  return (
    <details style={{ marginTop: "0.5rem" }}>
      <summary style={{ cursor: "pointer", fontSize: "0.82rem" }}>{title}</summary>
      <pre style={{ ...preStyle, marginTop: "0.35rem", maxHeight: "240px" }}>{text}</pre>
    </details>
  );
}

export default function MonitorLifecycle() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedMid, setSelectedMid] = useState(null);

  const load = useCallback(async () => {
    setErr(null);
    setLoading(true);
    try {
      const d = await fetchObservabilityLifecycles(150, 40);
      setData(d);
      const first = d?.incidents?.[0]?.message_id;
      setSelectedMid((prev) => {
        if (prev && d?.incidents?.some((i) => i.message_id === prev)) return prev;
        return first || null;
      });
    } catch (e) {
      setErr(String(e.message || e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const qMid = (searchParams.get("message_id") || "").trim();
  useEffect(() => {
    if (!qMid || !data?.incidents?.length) return;
    if (data.incidents.some((i) => i.message_id === qMid)) setSelectedMid(qMid);
  }, [qMid, data]);

  const incidents = data?.incidents ?? [];
  const selected = incidents.find((i) => i.message_id === selectedMid) || null;
  const steps = data?.agent_canonical_steps ?? [];

  const incidentRowOnly = selected
    ? (() => {
        const { llm_exchanges: _x, monitor_runs: _m, ...core } = selected;
        return core;
      })()
    : null;

  return (
    <div>
      <h1>Monitor &amp; agent lifecycle</h1>
      <p style={{ color: "#64748b", fontSize: "0.95rem", maxWidth: "52rem" }}>
        Each row is one persisted incident (MPL <code>MessageGuid</code>). The pipeline shows how the backend agent
        processed that failure; <code>llm_exchange</code> rows are the exact audit trail from{" "}
        <code>llm_audit.sqlite</code>. Matching rows from the in-process monitor buffer appear under monitor runs
        (cleared on uvicorn restart).
      </p>

      <p style={{ marginTop: "0.75rem" }}>
        <button
          type="button"
          onClick={() => load()}
          disabled={loading}
          style={{
            padding: "0.45rem 0.9rem",
            fontWeight: 600,
            borderRadius: "8px",
            border: "1px solid #334155",
            background: loading ? "#e2e8f0" : "#1e293b",
            color: "#fff",
            cursor: loading ? "not-allowed" : "pointer",
          }}
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
        {data && (
          <span style={{ marginLeft: "0.75rem", fontSize: "0.85rem", color: "#64748b" }}>
            incidents DB: {data.incidents_sqlite_enabled ? "on" : "off"} · LLM audit:{" "}
            {data.llm_audit_sqlite_enabled ? "on" : "off"}
          </span>
        )}
      </p>

      {err && <p style={{ color: "#b91c1c", marginTop: "1rem" }}>{err}</p>}

      {!err && loading && !data && <p style={{ marginTop: "1rem" }}>Loading…</p>}

      {!err && data && incidents.length === 0 && (
        <p style={{ marginTop: "1rem", color: "#64748b" }}>
          No incidents in SQLite yet. Run the CPI monitor with real <code>MONITOR_IFLOW_IDS</code> and a FAILED MPL
          row, then refresh.
        </p>
      )}

      {!err && incidents.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.35fr)",
            gap: "1.25rem",
            marginTop: "1.25rem",
            alignItems: "start",
          }}
          className="monitor-lifecycle-grid"
        >
          <section>
            <h2 style={{ fontSize: "1.05rem" }}>Incidents ({incidents.length})</h2>
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {incidents.map((inc) => {
                const active = inc.message_id === selectedMid;
                return (
                  <li key={inc.message_id} style={{ marginBottom: "0.35rem" }}>
                    <button
                      type="button"
                      onClick={() => setSelectedMid(inc.message_id)}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        padding: "0.6rem 0.75rem",
                        borderRadius: "8px",
                        border: active ? "2px solid #2563eb" : "1px solid #e2e8f0",
                        background: active ? "#eff6ff" : "#fff",
                        cursor: "pointer",
                        fontSize: "0.82rem",
                      }}
                    >
                      <div style={{ fontWeight: 600, wordBreak: "break-all" }}>{inc.message_id}</div>
                      <div style={{ color: "#64748b", marginTop: "0.2rem" }}>
                        {inc.iflow} · {inc.severity} · {inc.error_type} · {inc.llm_exchange_count ?? 0} LLM row(s)
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>

          {selected && (
            <section>
              <h2 style={{ fontSize: "1.05rem" }}>Detail</h2>

              <h3 style={{ fontSize: "0.95rem", marginTop: "1rem", marginBottom: "0.35rem" }}>SQLite incident row</h3>
              <pre style={preStyle}>{JSON.stringify(incidentRowOnly, null, 2)}</pre>

              <h3 style={{ fontSize: "0.95rem", marginTop: "1.25rem", marginBottom: "0.35rem" }}>
                Agent pipeline (canonical)
              </h3>
              <p style={{ fontSize: "0.82rem", color: "#64748b", marginTop: 0 }}>
                These four steps always run inside <code>run_investigation</code> before anything is written to{" "}
                <code>llm_exchange</code>.
              </p>
              <ol style={{ paddingLeft: "1.1rem", margin: "0.5rem 0 0", fontSize: "0.88rem" }}>
                {steps.map((s) => (
                  <li key={s.id} style={{ marginBottom: "0.5rem" }}>
                    <strong>{s.title}</strong> <code style={{ fontSize: "0.78rem" }}>({s.id})</code>
                    <div style={{ color: "#475569", marginTop: "0.15rem" }}>{s.detail}</div>
                  </li>
                ))}
              </ol>

              <h3 style={{ fontSize: "0.95rem", marginTop: "1.25rem", marginBottom: "0.35rem" }}>
                LLM audit (<code>llm_exchange</code>)
              </h3>
              {(selected.llm_exchanges || []).length === 0 ? (
                <p style={{ color: "#92400e", fontSize: "0.88rem" }}>
                  No matching audit rows (LLM disabled, or rows predate <code>message_id</code> linkage — re-run
                  investigation to capture new rows).
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                  {(selected.llm_exchanges || []).map((ex) => (
                    <article
                      key={ex.id}
                      style={{
                        border: "1px solid #cbd5e1",
                        borderRadius: "10px",
                        padding: "0.75rem 1rem",
                        background: "#f8fafc",
                      }}
                    >
                      <div style={{ fontSize: "0.8rem", color: "#475569" }}>
                        <strong>#{ex.id}</strong> · {ex.created_at} · <code>{ex.exchange_path}</code>
                      </div>
                      <div style={{ fontSize: "0.8rem", marginTop: "0.25rem" }}>
                        model: {ex.model || "—"} · HTTP: {ex.http_status ?? "—"}
                        {ex.error_note && (
                          <span style={{ color: "#b91c1c", display: "block", marginTop: "0.25rem" }}>
                            {ex.error_note}
                          </span>
                        )}
                      </div>
                      {ex.response_obj != null && (
                        <JsonBlock value={ex.response_obj} title="Parsed response_json (model output)" />
                      )}
                      <JsonBlock value={ex.request_messages} title="request_messages (system + user briefing)" />
                      {ex.raw_assistant_text && (
                        <JsonBlock value={ex.raw_assistant_text} title="raw_assistant_text" />
                      )}
                    </article>
                  ))}
                </div>
              )}

              <h3 style={{ fontSize: "0.95rem", marginTop: "1.25rem", marginBottom: "0.35rem" }}>
                Monitor runs (in-memory, this process)
              </h3>
              {(selected.monitor_runs || []).length === 0 ? (
                <p style={{ color: "#64748b", fontSize: "0.88rem" }}>No buffered runs with this message_guid.</p>
              ) : (
                <pre style={preStyle}>{JSON.stringify(selected.monitor_runs, null, 2)}</pre>
              )}
            </section>
          )}
        </div>
      )}

      <style>{`
        @media (max-width: 820px) {
          .monitor-lifecycle-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
