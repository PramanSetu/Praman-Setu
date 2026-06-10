import { useEffect, useState } from "react";

const API = "http://localhost:8000";

export function App() {
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setHealth(`ok · provider=${d.default_provider}`))
      .catch(() => setHealth("backend unreachable"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>Praman Setu</h1>
      <p>Code generation + debug assistant — scaffold is up.</p>
      <p>
        Backend health: <strong>{health}</strong>
      </p>
    </main>
  );
}
