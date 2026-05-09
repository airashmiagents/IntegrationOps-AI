import { Routes, Route } from "react-router-dom";
import Header from "./components/Header.jsx";
import Dashboard from "./pages/Dashboard.jsx";

export default function App() {
  return (
    <>
      <Header />
      <main style={{ maxWidth: "960px", margin: "0 auto", padding: "1.5rem" }}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
        </Routes>
      </main>
    </>
  );
}
