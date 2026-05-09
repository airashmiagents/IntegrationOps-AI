/**
 * components/
 * ------------
 * Reusable UI pieces: nav bars, cards, tables, charts.
 *
 * Keep each file focused — easier to rearrange during the hackathon demo.
 */

export default function Header() {
  return (
    <header
      style={{
        background: "#0f172a",
        color: "#f8fafc",
        padding: "1rem 1.5rem",
      }}
    >
      <strong>IntegrationOps-AI</strong>
      <span style={{ marginLeft: "0.75rem", opacity: 0.85, fontSize: "0.9rem" }}>
        SAP CPI monitoring & incident analysis
      </span>
    </header>
  );
}
