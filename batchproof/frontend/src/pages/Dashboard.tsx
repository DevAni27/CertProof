import { useEffect, useState } from "react";
import { A, api, startProject } from "../api";
import { Banner } from "../ui";

export default function Dashboard() {
  const [projects, setProjects] = useState<A[] | null>(null);
  const [err, setErr] = useState("");
  const load = () => api("/projects").then(setProjects).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const go = (k: "design" | "check" | "sample") => startProject(k).catch((e) => setErr(e.message));
  const del = async (p: A) => {
    if (!confirm(`Delete "${p.title}" and all its files (recipients, images, PDFs)? This cannot be undone.`)) return;
    await api("/projects/" + p.id, { method: "DELETE" });
    load();
  };
  return (
    <section>
      <div className="proj-head"><h1 style={{ margin: 0 }}>My projects</h1>
        <div className="row gap">
          <button className="btn" onClick={() => go("check")}>Check a batch</button>
          <button className="btn primary" onClick={() => go("design")}>+ New certificate project</button>
        </div></div>
      {err && <Banner kind="bad">{err}</Banner>}
      {projects && projects.length === 0 ? (
        <div className="panel" style={{ textAlign: "center", padding: 44 }}>
          <h2>No projects yet</h2>
          <p className="hint">Create your first certificate batch, or explore a sample project with fictional data.</p>
          <div className="row gap" style={{ justifyContent: "center" }}>
            <button className="btn primary" onClick={() => go("design")}>Create certificates</button>
            <button className="btn" onClick={() => go("sample")}>Open sample project</button>
          </div>
        </div>
      ) : projects && (
        <table className="tbl">
          <thead><tr><th>Project</th><th>Type</th><th>Recipients</th><th>Updated</th><th /></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td><a href={p.kind === "check" ? `#/check/${p.id}` : `#/p/${p.id}/design`}>{p.title}</a> {p.is_demo && <span className="chip muted">Sample</span>}</td>
                <td>{p.kind === "check" ? "Batch check" : "Certificates"}</td>
                <td>{p.recipients}</td>
                <td>{new Date(p.updated_at).toLocaleString()}</td>
                <td><button className="btn small danger" onClick={() => del(p)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
