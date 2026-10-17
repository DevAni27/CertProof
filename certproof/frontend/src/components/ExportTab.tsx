import { useRef, useState } from "react";
import { A, api, go, useJob } from "../api";
import { Banner, Field, JobBar } from "../ui";

export default function ExportTab({ p, reload }: { p: A; reload: () => void }) {
  const [err, setErr] = useState("");
  // Local copy of the blank options so rapid edits never race the server round-trip; saves are serialised.
  const [b, setB] = useState<A>(p.blank);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const mode = p.output_mode;
  const job = useJob((j) => { if (j.status === "completed") { reload(); go(`p/${p.id}/review`); } else if (j.status === "failed") setErr(j.message + " " + (j.result?.blocking || []).join(" ")); });

  const patch = async (body: A) => {
    try { await api("/projects/" + p.id, { method: "PATCH", json: body }); await reload(); setErr(""); } catch (e: A) { setErr(e.message); }
  };
  const bref = useRef<A>(p.blank);
  const setBlank = (next: A) => {
    bref.current = { ...bref.current, ...next };
    setB(bref.current);
    const snapshot = bref.current;
    chain.current = chain.current.then(() => patch({ blank: snapshot }));
  };
  const setPolicy = (fld: string, pol: A) => setBlank({ optional_fields: { ...bref.current.optional_fields, [fld]: { mode: "omit", fixed_text: "", ...(bref.current.optional_fields[fld] || {}), ...pol } } });

  const start = async () => {
    setErr("");
    try { const r = await api(`/projects/${p.id}/export`, { json: {} }); job.watch(r.job_id); }
    catch (e: A) { setErr(e.message); }
  };
  const namesCount = p.source.rows.length;

  return (
    <div>
      {err && <Banner kind="bad">{err}</Banner>}
      <h2>What do you want to print?</h2>
      <div className="modes" role="radiogroup" aria-label="Output mode">
        <button role="radio" aria-checked={mode === "personalised"} className={"mode " + (mode === "personalised" ? "on" : "")} onClick={() => mode !== "personalised" && patch({ output_mode: "personalised" })}>
          <strong>Personalised names</strong><span>One certificate per recipient from your list. Names are checked against the source.</span>
        </button>
        <button role="radio" aria-checked={mode === "blank_name"} className={"mode " + (mode === "blank_name" ? "on" : "")} onClick={() => mode !== "blank_name" && patch({ output_mode: "blank_name" })}>
          <strong>Blank name — fill by hand</strong><span>Everything printed except the recipient name. No recipient list needed.</span>
        </button>
      </div>
      <p className="hint">Switching mode keeps your recipient data but marks earlier previews and exports as out of date.</p>

      {mode === "personalised" ? (
        <div className="panel">
          <p>{namesCount} recipient row(s) in the source. {p.mapping ? "Mapping confirmed." : <strong>Mapping not confirmed yet — go to Recipients.</strong>}</p>
        </div>
      ) : (
        <div className="panel">
          <div className="row gap wrap">
            <Field label="How many blank certificates? (1–100)">
              <input type="number" min={1} max={100} value={b.copies} onChange={(e) => setBlank({ copies: Math.max(1, Math.min(100, +e.target.value || 1)), confirmed_copies: null })} style={{ width: 90 }} />
            </Field>
            <label className="check"><input type="checkbox" checked={b.confirmed_copies === b.copies} onChange={(e) => setBlank({ confirmed_copies: e.target.checked ? b.copies : null })} /> I confirm: export exactly <strong>{b.copies}</strong> certificate{b.copies > 1 ? "s" : ""}</label>
          </div>
          <div className="row gap wrap">
            <label className="check"><input type="checkbox" checked={b.line} onChange={(e) => setBlank({ line: e.target.checked })} /> Print a handwriting line</label>
            <Field label="Writing area width (mm)"><input type="number" min={60} max={220} value={b.width_mm} onChange={(e) => setBlank({ width_mm: +e.target.value })} style={{ width: 90 }} /></Field>
            <Field label="Writing area height (mm)"><input type="number" min={10} max={30} value={b.height_mm} onChange={(e) => setBlank({ height_mm: +e.target.value })} style={{ width: 90 }} /></Field>
          </div>
          <div className="hw-demo-wrap">
            <div className="hw-demo" style={{ width: `${b.width_mm}mm`, height: `${b.height_mm}mm`, borderBottom: b.line ? "0.4mm solid #222" : "none" }} aria-label="Handwriting area preview" />
            <p className="hint">Approximate on-screen size. Print the PDF at <strong>Actual size / 100%</strong> (not “fit to page”) to keep these dimensions.</p>
          </div>
          {p.mapping && ["organisation", "award"].filter((f) => p.mapping[f]).map((f) => {
            const pol = b.optional_fields[f] || { mode: "", fixed_text: "" };
            return (
              <div className="row gap" key={f}>
                <Field label={`Per-recipient “${f}” field`} hint="Never taken from a recipient. Choose explicitly.">
                  <select value={pol.mode} onChange={(e) => setPolicy(f, { mode: e.target.value })}>
                    <option value="" disabled>— choose —</option>
                    <option value="omit">Leave it out</option><option value="fixed">Same fixed text on every certificate</option><option value="handwriting">Extra handwriting area</option>
                  </select></Field>
                {pol.mode === "fixed" && <Field label="Fixed text"><input value={pol.fixed_text} onChange={(e) => setPolicy(f, { fixed_text: e.target.value })} /></Field>}
              </div>);
          })}
          <Banner kind="info">A blank certificate is not linked to any verified recipient. CertProof cannot check a name that is written in later.</Banner>
        </div>
      )}

      {p.readiness.length > 0 && (
        <Banner kind="warn"><strong>Before you can export:</strong><ul>{p.readiness.map((m: string) => <li key={m}>{m}</li>)}</ul></Banner>)}
      <div className="row gap">
        <button className="btn primary big" disabled={job.running || p.readiness.length > 0} onClick={start}>Generate PDF and run checks</button>
      </div>
      {job.job && <JobBar job={job.job} onCancel={job.cancel} />}
      {job.job?.status === "cancelled" && <Banner kind="info">Cancelled. No PDF was kept and nothing was marked as exported.</Banner>}
    </div>
  );
}
