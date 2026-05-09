/**
 * components/
 * ------------
 * Reusable UI pieces: nav bars, cards, tables, charts.
 *
 * Keep each file focused — easier to rearrange during the hackathon demo.
 */

import { Link, NavLink } from "react-router-dom";

const linkStyle = { color: "#e2e8f0", textDecoration: "none", marginRight: "1rem", fontSize: "0.9rem" };
const activeStyle = { fontWeight: 700, borderBottom: "2px solid #38bdf8", paddingBottom: "2px" };

export default function Header() {
  return (
    <header
      style={{
        background: "#0f172a",
        color: "#f8fafc",
        padding: "1rem 1.5rem",
        display: "flex",
        flexWrap: "wrap",
        alignItems: "baseline",
        gap: "0.5rem 1rem",
      }}
    >
      <Link to="/" style={{ color: "#f8fafc", textDecoration: "none" }}>
        <strong>IntegrationOps-AI</strong>
      </Link>
      <span style={{ opacity: 0.85, fontSize: "0.9rem" }}>SAP CPI monitoring & incident analysis</span>
      <nav style={{ marginLeft: "auto", display: "flex", flexWrap: "wrap", alignItems: "center" }}>
        <NavLink to="/" end style={({ isActive }) => ({ ...linkStyle, ...(isActive ? activeStyle : {}) })}>
          Dashboard
        </NavLink>
        <NavLink
          to="/monitor/lifecycle"
          style={({ isActive }) => ({ ...linkStyle, ...(isActive ? activeStyle : {}) })}
        >
          Monitor lifecycle
        </NavLink>
      </nav>
    </header>
  );
}
