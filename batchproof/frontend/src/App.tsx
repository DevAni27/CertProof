import { useEffect, useState } from "react";
import { route } from "./api";
import Landing from "./pages/Landing";
import Dashboard from "./pages/Dashboard";
import ProjectPage from "./pages/ProjectPage";
import CheckPage from "./pages/CheckPage";
import { Header } from "./ui";

export default function App() {
  const [r, setR] = useState(route());
  useEffect(() => {
    const h = () => { setR(route()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  const page = r[0] === "p" && r[1] ? <ProjectPage id={r[1]} tab={r[2] || "design"} key={r[1]} />
    : r[0] === "check" && r[1] ? <CheckPage id={r[1]} key={r[1]} />
    : r[0] === "projects" ? <Dashboard />
    : <Landing />;
  const landing = !r[0];
  return (
    <div className="app">
      <Header current={r[0] || ""} />
      {landing ? page : <main className="wrap">{page}</main>}
      <footer className="foot">
        <div className="wrap">
          <span>© CertProof · Certificates you can check before you print.</span>
          <span>“Checked” means our checks passed against the inputs you confirmed. It does not verify identity, event facts or legal validity.</span>
        </div>
      </footer>
    </div>
  );
}
