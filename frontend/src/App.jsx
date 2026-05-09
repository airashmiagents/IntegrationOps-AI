import { Routes, Route } from "react-router-dom";
import Header from "./components/Header.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import MonitorLifecycle from "./pages/MonitorLifecycle.jsx";

export default function App() {
  return (
    <>
      <Header />
      <main style={{ maxWidth: "1100px", margin: "0 auto", padding: "1.5rem" }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/monitor/lifecycle" element={<MonitorLifecycle />} />
        </Routes>
      </main>
    </>
  );
}
