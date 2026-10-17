import { useCallback, useEffect, useState } from "react";
import { A, api, go } from "../api";
import { Banner } from "../ui";
import DesignTab from "../components/DesignTab";
import SourcePanel from "../components/SourcePanel";
import ExportTab from "../components/ExportTab";
import ReviewTab from "../components/ReviewTab";

const STEPS: [string, string, string][] = [["design", "Design", "Look & details"], ["recipients", "Recipients", "Who gets one"], ["export", "Export", "Make the PDF"], ["review", "Review", "Proof every page"]];

export default function ProjectPage({ id, tab }: { id: string; tab: string }) {
  const [p, setP] = useState<A>(null);
  const [err, setErr] = useState("");
  const reload = useCallback(async () => {
    try { setP(await api("/projects/" + id)); setErr(""); } catch (e: A) { setErr(e.message); }
  }, [id]);
  useEffect(() => { reload(); }, [reload, tab]);
  if (err) return <Banner kind="bad">{err}</Banner>;
  if (!p) return <p className="hint" style={{ padding: 40 }}>Loading…</p>;
  const cur = STEPS.findIndex(([k]) => k === tab);
  return (
    <section>
      <div className="proj-head">
        <h1>{p.title}</h1>
        {p.is_demo && <span className="chip muted">Sample data</span>}
      </div>
      <div className="stepper" role="tablist">
        {STEPS.map(([k, l, s], i) => (
          <button key={k} role="tab" aria-selected={tab === k} className={"step " + (tab === k ? "on " : "") + (i < cur ? "done" : "")} onClick={() => go(`p/${id}/${k}`)}>
            <span className="n">{i < cur ? "✓" : i + 1}</span><span><b>{l}</b><small>{s}</small></span>
          </button>
        ))}
      </div>
      {tab === "design" && <DesignTab p={p} reload={reload} />}
      {tab === "recipients" && <SourcePanel p={p} reload={reload} />}
      {tab === "export" && <ExportTab p={p} reload={reload} />}
      {tab === "review" && <ReviewTab p={p} reload={reload} />}
    </section>
  );
}
