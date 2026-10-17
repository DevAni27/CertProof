import { useCallback, useEffect, useState } from "react";
import { A, api, fileForm, useJob } from "../api";
import { Banner, Drawer, IssueCard, Status, completionLabel } from "../ui";
import SourcePanel from "../components/SourcePanel";

const ZT: [string, string][] = [["name", "Recipient name"], ["organisation", "Organisation"], ["award", "Award"], ["recipient_id", "ID"]];
const COLORS: A = { name: "#d33", organisation: "#27a", award: "#2a6", recipient_id: "#a2a" };
const band = (r: number[]) => { const h = r[3] - r[1]; return [0.04, Math.max(0, r[1] - 0.25 * h), 0.96, Math.min(1, r[3] + 0.25 * h)]; };

export default function CheckPage({ id }: { id: string }) {
  const [p, setP] = useState<A>(null);
  const [ins, setIns] = useState<A>(null);
  const [zones, setZones] = useState<A>({});
  const [target, setTarget] = useState("name");
  const [fixed, setFixed] = useState("");
  const [res, setRes] = useState<A>({});
  const [art, setArt] = useState<A>(null);
  const [err, setErr] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [imgv, setImgv] = useState(0);

  const reload = useCallback(async () => { try { setP(await api("/projects/" + id)); } catch (e: A) { setErr(e.message); } }, [id]);
  useEffect(() => { reload(); }, [reload]);
  const loadArt = async (aid: string) => setArt(await api(`/projects/${id}/artifacts/${aid}`));
  const job = useJob((j) => { if (j.status === "completed") loadArt(j.result.artifact_id); else setErr(j.message); });

  const upload = async (f: File) => {
    setErr(""); setArt(null); setIns(null);
    try {
      const r = await api(`/projects/${id}/verify-external/inspect`, { form: fileForm(f) });
      setIns(r); setZones(r.suggested_zones); setImgv((v) => v + 1);
    } catch (e: A) { setErr(e.message); }
  };
  const run = async (resolutions: A = res) => {
    setErr("");
    try {
      const r = await api(`/projects/${id}/verify-external`, { json: { zones, fixed_texts: fixed.split("\n").map((s) => s.trim()).filter(Boolean), resolutions } });
      job.watch(r.job_id);
    } catch (e: A) { setErr(e.message); }
  };
  const pick = (page: number, rowIdx: string) => {
    const row = p.source.rows.find((r: A) => String(r.row_index) === rowIdx);
    if (!row) return;
    const next = { ...res, [page]: row.row_id };
    setRes(next); run(next);
  };
  const ack = async (iid: string, note: string) => { await api(`/projects/${id}/acknowledge`, { json: { issue_id: iid, note } }); await loadArt(art.id); };

  if (!p) return err ? <Banner kind="bad">{err}</Banner> : <p>Loading…</p>;
  const rep = art?.report;
  const ready = p.mapping?.name && ins && zones.name;

  return (
    <section>
      <h1>Check an existing batch</h1>
      <p className="hint">Upload the spreadsheet and a separately produced <strong>searchable</strong> PDF (one certificate per page, one recipient name per certificate). Scanned PDFs are rejected — OCR is not supported.</p>
      {err && <Banner kind="bad">{err}</Banner>}
      <h2>1 · Source spreadsheet</h2>
      <SourcePanel p={p} reload={reload} allowManual={false} />

      <h2>2 · Certificate PDF</h2>
      <input type="file" accept="application/pdf,.pdf" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} aria-label="Certificate PDF" />
      {ins && (
        <>
          <Banner kind="info">{ins.pages} page(s). {ins.caveat}</Banner>
          {ins.pages_without_text.length > 0 && <Banner kind="warn">No readable text on page(s) {ins.pages_without_text.join(", ")} — those pages will show as Needs review.</Banner>}
          {ins.notes.map((n: string) => <Banner key={n} kind="warn">{n}</Banner>)}
          <p>Click a line on the sample page to mark where each field is. Choose the field first:</p>
          <div className="row gap wrap">
            {ZT.map(([k, l]) => <label key={k} className="check"><input type="radio" name="zt" checked={target === k} onChange={() => setTarget(k)} /> <span style={{ color: COLORS[k] }}>■</span> {l}{zones[k] ? " ✓" : ""}</label>)}
            <button className="btn small" onClick={() => setZones((z: A) => { const n = { ...z }; delete n[target]; return n; })}>Clear selected</button>
          </div>
          <div className="pagewrap small">
            <img className="cert" alt="Page 1 of the PDF" src={`/api/projects/${id}/external/page/1.png?scale=1.1&v=${imgv}`} />
            {ins.lines.map((l: A, i: number) => (
              <button key={i} className="line" title={l.text} style={{ left: l.rect[0] * 100 + "%", top: l.rect[1] * 100 + "%", width: (l.rect[2] - l.rect[0]) * 100 + "%", height: (l.rect[3] - l.rect[1]) * 100 + "%" }}
                onClick={() => setZones({ ...zones, [target]: band(l.rect) })} aria-label={`Use line: ${l.text}`} />))}
            {Object.entries(zones).map(([k, r]: A) => <div key={k} className="zone" style={{ borderColor: COLORS[k], left: r[0] * 100 + "%", top: r[1] * 100 + "%", width: (r[2] - r[0]) * 100 + "%", height: (r[3] - r[1]) * 100 + "%" }} />)}
          </div>
          <label className="field"><span className="lbl">Fixed text that must appear on every page (one per line, optional)</span>
            <textarea rows={3} value={fixed} onChange={(e) => setFixed(e.target.value)} placeholder="e.g. 12 October 2026" />
            <span className="hint">Whitespace is ignored when comparing these; each page is searched for the text.</span></label>
          <button className="btn primary big" disabled={!ready || job.running} onClick={() => run()}>Run checks</button>
          {!ready && <span className="hint"> Confirm the column mapping and mark the recipient-name line first.</span>}
        </>
      )}
      {job.job && <div className="jobbar">{job.job.status} — {job.job.message}</div>}

      {rep && (
        <>
          <h2>3 · Result</h2>
          {art.stale && <Banner kind="warn">The source, mapping, zones or PDF changed after this result. Run the checks again.</Banner>}
          <div className="summary">
            <div className="sum"><span className="big">{completionLabel(rep.completion)}</span><span>overall</span></div>
            <div className="sum"><span className="big">{rep.counts.source_rows}</span><span>source rows</span></div>
            <div className="sum"><span className="big">{rep.counts.pdf_pages}</span><span>PDF pages</span></div>
            <div className="sum bad"><span className="big">{rep.counts.rows_without_page}</span><span>rows without a page</span></div>
            <div className="sum bad"><span className="big">{rep.counts.unexpected_pages}</span><span>unexpected pages</span></div>
            <div className="sum warn"><span className="big">{rep.counts.ambiguous_pages}</span><span>ambiguous pages</span></div>
          </div>
          <Banner kind="info">Page-count equality is never treated as proof that every recipient exists. “Checked” does not certify identity or event facts.</Banner>
          <div className="row gap">
            <a className="btn" href={`/api/projects/${id}/artifacts/${art.id}/report.csv`}>Report (CSV)</a>
            <a className="btn" href={`/api/projects/${id}/artifacts/${art.id}/report.json`}>Report (JSON)</a>
          </div>
          <h3>Pages</h3>
          <div className="scroll"><table className="tbl dense"><thead><tr><th>Page</th><th>Status</th><th>Name read from PDF</th><th>Matched source row</th><th /></tr></thead>
            <tbody>{rep.page_statuses.map((s: A) => {
              const row = p.source.rows.find((r: A) => r.row_id === s.row_id);
              return (<tr key={s.page}><td>{s.page}</td><td><Status s={s.status} /></td><td>{s.extracted?.name}</td><td>{row ? `row ${row.row_index}` : s.state}</td>
                <td><button className="btn small" onClick={() => setOpen(s.page)}>Details</button></td></tr>);
            })}</tbody></table></div>
          <h3>Source rows</h3>
          <div className="scroll"><table className="tbl dense"><thead><tr><th>Row</th><th>Name</th><th>Status</th></tr></thead>
            <tbody>{rep.row_statuses.map((r: A) => <tr key={r.row_id}><td>{r.source_row_index}</td><td>{r.name}</td><td><Status s={r.status} /></td></tr>)}</tbody></table></div>
          <h3>All issues ({rep.issues.length})</h3>
          {rep.issues.map((i: A) => <IssueCard key={i.id} i={i} onAck={ack} onPick={i.code === "AMBIGUOUS_PAGE_MATCH" ? (r) => pick(i.page, r) : undefined} />)}
          {open && (
            <Drawer title={`Page ${open}`} onClose={() => setOpen(null)}>
              <div className="pagewrap">
                <img className="cert" alt={`Page ${open}`} src={`/api/projects/${id}/external/page/${open}.png?scale=1.3&v=${imgv}`} />
                {rep.issues.filter((i: A) => i.page === open && i.rect).map((i: A) => <div key={i.id} className="hl" style={{ left: i.rect[0] * 100 + "%", top: i.rect[1] * 100 + "%", width: (i.rect[2] - i.rect[0]) * 100 + "%", height: (i.rect[3] - i.rect[1]) * 100 + "%" }} />)}
              </div>
              {rep.issues.filter((i: A) => i.page === open).map((i: A) => <IssueCard key={i.id} i={i} onAck={ack} onPick={i.code === "AMBIGUOUS_PAGE_MATCH" ? (r) => pick(open, r) : undefined} />)}
            </Drawer>)}
        </>
      )}
    </section>
  );
}
