/**
 * Mock alert inbox — fake email client UI for hackathon demos (no SMTP).
 * Uses GET /incidents when rows exist; otherwise shows seeded sample alerts.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchHealth, fetchIncidents } from "../services/api.js";

const FROM = "IntegrationOps-AI Alerts <alerts-noreply@integrationops-demo.local>";

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return String(iso);
  }
}

function buildFromIncidents(rows, toEmail) {
  return rows.map((row) => ({
    id: `incident-${row.id}`,
    kind: "incident",
    subject: `[${row.severity}] CPI incident — ${row.iflow}`,
    from: FROM,
    to: toEmail,
    date: row.timestamp,
    preview:
      (row.root_cause || "No summary")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 100) + ((row.root_cause || "").length > 100 ? "…" : ""),
    body: {
      headline: "Autonomous monitor stored this investigation in SQLite.",
      iflow: row.iflow,
      message_id: row.message_id,
      severity: row.severity,
      error_type: row.error_type,
      confidence_score: row.confidence_score,
      investigation_status: row.investigation_status,
      jira_ticket_id: row.jira_ticket_id,
      root_cause: row.root_cause,
      recommendation: row.recommendation,
    },
  }));
}

function seedDemoEmails(toEmail) {
  return [
    {
      id: "demo-seed-1",
      kind: "demo",
      subject: "[HIGH] CPI incident — Sample_OrderToCash_IFlow",
      from: FROM,
      to: toEmail,
      date: new Date(Date.now() - 45 * 60 * 1000).toISOString(),
      preview: "TLS certificate validation failed at receiver HTTPS adapter — PKIX path building failed…",
      body: {
        headline: "Sample alert (no real CPI call — shown when the incidents table is empty).",
        iflow: "Sample_OrderToCash_IFlow",
        message_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        severity: "HIGH",
        error_type: "PKIX",
        confidence_score: 82,
        investigation_status: "completed",
        jira_ticket_id: null,
        root_cause:
          "TLS certificate validation failed — trust chain or hostname mismatch likely between CPI and the partner HTTPS endpoint.",
        recommendation:
          "Import partner root/intermediate into CPI keystore or fix server certificate; verify hostname/SNI matches the URL used in the adapter.",
      },
    },
    {
      id: "demo-seed-2",
      kind: "demo",
      subject: "[MEDIUM] CPI incident — Demo_HR_EmployeeSync",
      from: FROM,
      to: toEmail,
      date: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      preview: "Downstream latency caused HTTP receiver timeout after 120s; MPL shows adapter retry…",
      body: {
        headline: "Second sample alert for layout demos.",
        iflow: "Demo_HR_EmployeeSync",
        message_id: "11111111-2222-3333-4444-555555555555",
        severity: "MEDIUM",
        error_type: "TIMEOUT",
        confidence_score: 61,
        investigation_status: "completed",
        jira_ticket_id: null,
        root_cause:
          "Downstream latency or network blockage caused the HTTP adapter to exceed its configured timeout.",
        recommendation:
          "Increase HTTP timeout on the receiver channel, verify endpoint availability, and check firewall/DNS from the CPI runtime.",
      },
    },
  ];
}

export default function MockAlertInbox() {
  const [toEmail, setToEmail] = useState("integrationops-alerts@demo.example.com");
  const [emails, setEmails] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [err, setErr] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setErr(null);
    setLoading(true);
    try {
      const [h, inc] = await Promise.all([fetchHealth(), fetchIncidents(50)]);
      const rows = Array.isArray(inc) ? inc : inc?.incidents ?? [];
      const to = (h?.mock_alert_email || "integrationops-alerts@demo.example.com").trim();
      setToEmail(to);
      const fromDb = buildFromIncidents(rows, to);
      const list = fromDb.length ? fromDb : seedDemoEmails(to);
      setEmails(list);
      setSelectedId((prev) => {
        if (prev && list.some((e) => e.id === prev)) return prev;
        return list[0]?.id ?? null;
      });
    } catch (e) {
      setErr(String(e.message || e));
      const fallback = seedDemoEmails("integrationops-alerts@demo.example.com");
      setEmails(fallback);
      setSelectedId(fallback[0]?.id ?? null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selected = useMemo(() => emails.find((e) => e.id === selectedId) || null, [emails, selectedId]);

  return (
    <div>
      <h1 style={{ marginBottom: "0.35rem" }}>Mock alert inbox</h1>
      <p style={{ color: "#64748b", fontSize: "0.95rem", maxWidth: "42rem", marginTop: 0 }}>
        Preview-only email UI — no SMTP or mail server. Messages are built from{" "}
        <Link to="/">Dashboard</Link> incidents when available; otherwise sample CPI alerts are shown. Recipient
        address comes from <code>GET /health</code> (<code>mock_alert_email</code> / <code>MOCK_ALERT_EMAIL</code> in{" "}
        <code>backend/.env</code>).
      </p>
      <p style={{ marginTop: "0.5rem" }}>
        <button
          type="button"
          onClick={() => load()}
          disabled={loading}
          style={{
            padding: "0.4rem 0.85rem",
            borderRadius: "6px",
            border: "1px solid #cbd5e1",
            background: loading ? "#f1f5f9" : "#fff",
            cursor: loading ? "wait" : "pointer",
            fontSize: "0.88rem",
          }}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </p>

      {err && (
        <p style={{ color: "#b45309", fontSize: "0.88rem", marginTop: "0.75rem" }}>
          API unavailable — showing demo emails only. ({err})
        </p>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(200px, 280px) 1fr",
          gap: 0,
          marginTop: "1.25rem",
          border: "1px solid #cbd5e1",
          borderRadius: "12px",
          overflow: "hidden",
          minHeight: "420px",
          background: "#e2e8f0",
          boxShadow: "0 4px 24px rgba(15, 23, 42, 0.08)",
        }}
        className="mock-inbox-grid"
      >
        {/* List pane */}
        <aside style={{ background: "#f8fafc", borderRight: "1px solid #cbd5e1" }}>
          <div
            style={{
              padding: "0.65rem 1rem",
              fontSize: "0.75rem",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "#64748b",
              borderBottom: "1px solid #e2e8f0",
            }}
          >
            Inbox · {emails.length}{" "}
            {emails.some((e) => e.kind === "incident") ? "· from incidents SQLite" : "· demo samples only"}
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: "560px", overflowY: "auto" }}>
            {emails.map((m) => {
              const active = m.id === selectedId;
              return (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(m.id)}
                    style={{
                      width: "100%",
                      textAlign: "left",
                      padding: "0.65rem 1rem",
                      border: "none",
                      borderBottom: "1px solid #e2e8f0",
                      background: active ? "#fff" : "transparent",
                      cursor: "pointer",
                      borderLeft: active ? "3px solid #2563eb" : "3px solid transparent",
                    }}
                  >
                    <div
                      style={{
                        fontSize: "0.72rem",
                        color: m.kind === "demo" ? "#b45309" : "#15803d",
                        marginBottom: "0.2rem",
                      }}
                    >
                      {m.kind === "demo" ? "Demo" : "From monitor"}
                    </div>
                    <div style={{ fontWeight: 600, fontSize: "0.82rem", color: "#0f172a", lineHeight: 1.3 }}>
                      {m.subject}
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: "0.25rem" }}>{m.preview}</div>
                    <div style={{ fontSize: "0.7rem", color: "#94a3b8", marginTop: "0.35rem" }}>
                      {formatWhen(m.date)}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* Reading pane */}
        <div style={{ background: "#e8edf3", padding: "1rem 1.25rem" }}>
          {!selected ? (
            <p style={{ color: "#64748b" }}>No messages.</p>
          ) : (
            <article
              style={{
                background: "#fff",
                borderRadius: "8px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
                maxWidth: "720px",
                margin: "0 auto",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  padding: "0.5rem 1rem",
                  background: "linear-gradient(180deg, #fafafa 0%, #f4f4f5 100%)",
                  borderBottom: "1px solid #e4e4e7",
                  fontSize: "0.75rem",
                  color: "#71717a",
                }}
              >
                Mock client · Not sent
              </div>
              <div style={{ padding: "1.25rem 1.5rem 1.75rem" }}>
                <div style={{ fontSize: "0.8rem", color: "#52525b", marginBottom: "0.35rem" }}>
                  <strong>From</strong> {selected.from}
                </div>
                <div style={{ fontSize: "0.8rem", color: "#52525b", marginBottom: "0.35rem" }}>
                  <strong>To</strong> {selected.to}
                </div>
                <div style={{ fontSize: "0.8rem", color: "#52525b", marginBottom: "1rem" }}>
                  <strong>Date</strong> {formatWhen(selected.date)}
                </div>
                <h2 style={{ margin: "0 0 1rem", fontSize: "1.15rem", fontWeight: 600, color: "#18181b" }}>
                  {selected.subject}
                </h2>
                <p style={{ fontSize: "0.88rem", color: "#52525b", marginBottom: "1.25rem", lineHeight: 1.5 }}>
                  {selected.body.headline}
                </p>
                <table style={{ width: "100%", fontSize: "0.85rem", borderCollapse: "collapse" }}>
                  <tbody>
                    {[
                      ["Integration artifact (iFlow)", <code key="if">{selected.body.iflow}</code>],
                      ["Message ID (MPL)", <code key="mid">{selected.body.message_id}</code>],
                      ["Severity", selected.body.severity],
                      ["Error type", selected.body.error_type],
                      ["Confidence", `${selected.body.confidence_score}%`],
                      ["Status", selected.body.investigation_status],
                      ["Jira", selected.body.jira_ticket_id || "—"],
                    ].map(([label, val]) => (
                      <tr key={label} style={{ borderTop: "1px solid #f4f4f5" }}>
                        <td
                          style={{
                            width: "38%",
                            padding: "0.5rem 0",
                            color: "#71717a",
                            verticalAlign: "top",
                            fontWeight: 500,
                          }}
                        >
                          {label}
                        </td>
                        <td style={{ padding: "0.5rem 0", color: "#18181b", verticalAlign: "top" }}>{val}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ marginTop: "1.25rem" }}>
                  <div style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", color: "#71717a" }}>
                    Root cause
                  </div>
                  <p style={{ margin: "0.35rem 0 0", fontSize: "0.9rem", lineHeight: 1.55, color: "#27272a" }}>
                    {selected.body.root_cause}
                  </p>
                </div>
                <div style={{ marginTop: "1rem" }}>
                  <div style={{ fontSize: "0.72rem", fontWeight: 700, textTransform: "uppercase", color: "#71717a" }}>
                    Recommendation
                  </div>
                  <p style={{ margin: "0.35rem 0 0", fontSize: "0.9rem", lineHeight: 1.55, color: "#27272a" }}>
                    {selected.body.recommendation}
                  </p>
                </div>
                <div
                  style={{
                    marginTop: "1.5rem",
                    paddingTop: "1rem",
                    borderTop: "1px dashed #e4e4e7",
                    fontSize: "0.78rem",
                    color: "#a1a1aa",
                  }}
                >
                  In production you would wire this HTML to SendGrid, Amazon SES, or Microsoft Graph — this page is a
                  static preview only.
                </div>
              </div>
            </article>
          )}
        </div>
      </div>

      <style>{`
        @media (max-width: 720px) {
          .mock-inbox-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
