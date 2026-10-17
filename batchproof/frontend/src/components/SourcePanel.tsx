import { useState } from "react";
import { A, api, fileForm, useJob } from "../api";
import { Banner, Field, JobBar } from "../ui";

const TARGETS: [string, string, boolean][] = [
  ["name", "Recipient name", true], ["organisation", "Organisation / college (optional)", false],
  ["award", "Award / position (optional)", false], ["recipient_id", "Recipient ID (optional)", false],
];

export default function SourcePanel({ p, reload, allowManual = true }: { p: A; reload: () => void; allowManual?: boolean }) {
  const [tab, setTab] = useState<"file" | "paste" | "manual">("file");
  const [paste, setPaste] = useState("");
  const [rows, setRows] = useState<A[]>([{ name: "", organisation: "", award: "", recipient_id: "" }]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState<string>("");
  const [hdr, setHdr] = useState(1);
  const [draft, setDraft] = useState<A>(p.mapping || {});
  const [note, setNote] = useState("");
  const [method, setMethod] = useState<string>(p.mapping?.method || "manual");
  const [flags, setFlags] = useState<A>({});
  const mapJob = useJob((j) => {
    if (j.status === "completed") {
      applyProposal(j.result.proposal, "ai");
    } else {
      setNote(j.message + " Using the rule-based suggestion instead.");
      if (j.result?.fallback) applyProposal(j.result.fallback, "rule_based");
    }
  });
  const src = p.source;

  const applyProposal = (prop: A, m: string) => {
    const d: A = {};
    const f: A = {};
    for (const [t] of TARGETS) { d[t] = prop[t]?.column || null; f[t] = prop[t]?.uncertain; }
    setDraft(d); setFlags(f); setMethod(m);
  };
  const guard = async (fn: () => Promise<void>) => {
    setErr(""); setBusy(true);
    try { await fn(); await reload(); } catch (e: A) { setErr(e.message); } finally { setBusy(false); }
  };
  const upload = (file: File) => guard(async () => {
    await api(`/projects/${p.id}/recipients/import`, { form: fileForm(file, { header_row: String(hdr) }) });
    setDraft({});
  });
  const reparse = () => guard(async () => {
    const f = new FormData();
    if (sheet) f.append("sheet", sheet);
    f.append("header_row", String(hdr));
    await api(`/projects/${p.id}/recipients/import`, { form: f });
    setDraft({});
  });
  const suggestRules = () => guard(async () => {
    const r = await api(`/projects/${p.id}/mapping/propose`, { json: { use_ai: false } });
    applyProposal(r.proposal, "rule_based"); setNote("Rule-based suggestion (headings matched against a fixed word list). Review before confirming.");
  });
  const suggestAI = () => guard(async () => {
    const r = await api(`/projects/${p.id}/mapping/propose`, { json: { use_ai: true } });
    setNote(""); mapJob.watch(r.job_id);
  });
  const confirm = () => guard(async () => {
    await api(`/projects/${p.id}/mapping/confirm`, { method: "PUT", json: { ...draft, method } });
  });

  const needsConfirm = src.rows.length > 0 && (!p.mapping || TARGETS.some(([t]) => (draft[t] || null) !== (p.mapping?.[t] || null)));

  return (
    <div>
      {err && <Banner kind="bad">{err}</Banner>}
      <div className="tabs small">
        <button className={tab === "file" ? "on" : ""} onClick={() => setTab("file")}>Import CSV / XLSX</button>
        {allowManual && <button className={tab === "paste" ? "on" : ""} onClick={() => setTab("paste")}>Paste names</button>}
        {allowManual && <button className={tab === "manual" ? "on" : ""} onClick={() => setTab("manual")}>Type rows</button>}
      </div>

      {tab === "file" && (
        <div className="row gap">
          <Field label="Spreadsheet file" hint="UTF-8 CSV or .xlsx. Formulas and macros are never run.">
            <input type="file" accept=".csv,.xlsx,.txt" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </Field>
          {src.kind === "xlsx" && (
            <Field label="Worksheet">
              <select value={sheet || src.sheet} onChange={(e) => setSheet(e.target.value)}>{src.sheets.map((s: string) => <option key={s}>{s}</option>)}</select>
            </Field>
          )}
          {(src.kind === "xlsx" || src.kind === "csv") && (
            <>
              <Field label="Header row"><input type="number" min={1} value={hdr} onChange={(e) => setHdr(+e.target.value || 1)} style={{ width: 70 }} /></Field>
              <button className="btn" onClick={reparse} disabled={busy}>Re-read</button>
            </>
          )}
        </div>
      )}
      {tab === "paste" && (
        <div>
          <Field label="One name per line" hint="Names are kept exactly as typed — never auto-corrected or transliterated.">
            <textarea rows={6} value={paste} onChange={(e) => setPaste(e.target.value)} />
          </Field>
          <button className="btn primary" disabled={!paste.trim() || busy} onClick={() => guard(async () => { await api(`/projects/${p.id}/recipients`, { method: "PUT", json: { paste } }); })}>Use these names</button>
        </div>
      )}
      {tab === "manual" && (
        <div>
          <table className="tbl edit"><thead><tr><th>Name</th><th>Organisation</th><th>Award</th><th>ID</th><th /></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>{["name", "organisation", "award", "recipient_id"].map((k) => (
                <td key={k}><input value={r[k]} aria-label={k} onChange={(e) => setRows(rows.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x))} /></td>))}
                <td><button className="btn small" onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button></td></tr>))}
            </tbody></table>
          <button className="btn small" onClick={() => setRows([...rows, { name: "", organisation: "", award: "", recipient_id: "" }])}>+ Add row</button>{" "}
          <button className="btn primary" disabled={busy} onClick={() => guard(async () => { await api(`/projects/${p.id}/recipients`, { method: "PUT", json: { rows: rows.filter((r) => Object.values(r).some((v) => String(v).trim())) } }); })}>Save recipients</button>
        </div>
      )}

      {src.rows.length === 0 ? <p className="empty">No recipients yet.</p> : (
        <>
          <h3>Source data <small>{src.rows.length} rows · {src.filename}{src.kind === "xlsx" ? ` · sheet “${src.sheet}”` : ""}</small></h3>
          {src.warnings.map((w: string, i: number) => <Banner key={i} kind="warn">{w}</Banner>)}
          <div className="scroll"><table className="tbl dense">
            <thead><tr><th>Row</th>{src.headers.map((h: string) => <th key={h}>{h}</th>)}<th /></tr></thead>
            <tbody>{src.rows.slice(0, 100).map((r: A) => (
              <tr key={r.row_id}><td className="num">{r.row_index}</td>{src.headers.map((h: string) => <td key={h}>{r.cells[h]}</td>)}
                <td>{r.findings.map((f: string) => <span key={f} className="chip warn">{f.replace(/_/g, " ").toLowerCase()}</span>)}</td></tr>))}</tbody>
          </table></div>
          {src.rows.length > 100 && <p className="hint">Showing the first 100 rows. All {src.rows.length} rows are used.</p>}

          <h3>Column mapping</h3>
          <p className="hint">Matching and checking are deterministic after you confirm. A suggestion is never applied without confirmation.</p>
          <div className="row gap wrap">
            {TARGETS.map(([t, label, req]) => (
              <Field key={t} label={label + (req ? " *" : "")} hint={flags[t] ? "uncertain suggestion — please check" : undefined}>
                <select value={draft[t] || ""} onChange={(e) => setDraft({ ...draft, [t]: e.target.value || null })}>
                  <option value="">{req ? "— choose —" : "(none)"}</option>
                  {src.headers.map((h: string) => <option key={h} value={h}>{h}</option>)}
                </select>
              </Field>))}
          </div>
          <div className="row gap">
            <button className="btn" onClick={suggestRules} disabled={busy}>Suggest (rule-based)</button>
            <button className="btn" onClick={suggestAI} disabled={busy || mapJob.running}>Auto-suggest columns</button>
            <button className="btn primary" onClick={confirm} disabled={!draft.name || busy}>{needsConfirm ? "Confirm mapping" : "Mapping confirmed ✓"}</button>
          </div>
          {note && <Banner kind="info">{note}</Banner>}
          {mapJob.job && mapJob.running && <JobBar job={mapJob.job} onCancel={mapJob.cancel} />}
          {p.mapping && !needsConfirm && <Banner kind="ok">Mapping confirmed ({String(p.mapping.method).replace(/_/g, " ")}). Names are compared after Unicode NFC and whitespace normalisation only; accents, case and punctuation must match.</Banner>}
          {p.source_issues?.length > 0 && (
            <div><h3>Source checks</h3>
              {p.source_issues.slice(0, 20).map((i: A) => <div key={i.id} className={"issue " + i.severity}><code>{i.code}</code> {i.message}</div>)}</div>)}
        </>
      )}
    </div>
  );
}
