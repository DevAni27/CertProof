import { useEffect, useMemo, useState } from "react";
import { A, api } from "../api";
import { Banner, Drawer, IssueCard, Status, completionLabel } from "../ui";

export default function ReviewTab({ p, reload }: { p: A; reload: () => void }) {
  const [art, setArt] = useState<A>(null);
  const [none, setNone] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [code, setCode] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const list = await api(`/projects/${p.id}/artifacts`);
      const e = list.find((a: A) => a.kind === "export");
      if (!e) { setNone(true); return; }
      setArt(await api(`/projects/${p.id}/artifacts/${e.id}`));
    } catch (x: A) { setErr(x.message); }
  };
  useEffect(() => { load(); }, [p.id]);

  const rep = art?.report;
  const nameOf = (rowId: string | null, page: number) => {
    if (rep?.mode === "blank_name") return `Blank #${page}`;
    const r = p.source.rows.find((x: A) => x.row_id === rowId);
    return r ? r.cells[p.mapping?.name] : `Page ${page}`;
  };
  const rows = useMemo(() => {
    if (!rep) return [];
    return rep.page_statuses.map((s: A) => ({ ...s, name: nameOf(s.row_id, s.page), issues: rep.issues.filter((i: A) => i.page === s.page) }));
  }, [rep, p.source]);
  const shown = rows.filter((r: A) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (code && !r.issues.some((i: A) => i.code === code)) return false;
    if (q) { const t = q.toLowerCase(); if (!(String(r.name).toLowerCase().includes(t) || String(r.page) === t || r.issues.some((i: A) => String(i.source_row_index) === t))) return false; }
    return true;
  });
  const codes: string[] = rep ? Array.from(new Set<string>(rep.issues.map((i: A) => i.code))) : [];
  const other = rep ? rep.issues.filter((i: A) => !i.page) : [];

  const ack = async (id: string, note: string) => { await api(`/projects/${p.id}/acknowledge`, { json: { issue_id: id, note } }); await load(); };

  if (err) return <Banner kind="bad">{err}</Banner>;
  if (none) return <p className="empty">Nothing generated yet. Go to <a href={`#/p/${p.id}/export`}>Export</a> and run the checks.</p>;
  if (!rep) return <p>Loading…</p>;
  const counts = { Checked: 0, "Needs review": 0, Blocked: 0 } as A;
  rows.forEach((r: A) => counts[r.status]++);

  return (
    <div>
      {art.stale && <Banner kind="warn"><strong>Out of date.</strong> The design, recipients, mapping, event details or output mode changed after this was generated. Regenerate before printing or sending. (The files below still match what was checked at the time.)</Banner>}
      <div className="summary">
        <div className="sum"><span className="big">{rep.pdf_pages}</span><span>pages</span></div>
        <div className="sum"><span className="big">{completionLabel(rep.completion)}</span><span>overall</span></div>
        <div className="sum ok"><span className="big">{counts.Checked}</span><span>Checked</span></div>
        <div className="sum warn"><span className="big">{counts["Needs review"]}</span><span>Needs review</span></div>
        <div className="sum bad"><span className="big">{counts.Blocked}</span><span>Blocked</span></div>
      </div>
      {rep.mode === "blank_name"
        ? <Banner kind="info">Blank-name output. Recipient matching: <strong>Not applicable</strong>. Fixed details, page count, handwriting-area clearance, fonts and layout were checked. Repeated identical pages are intended.</Banner>
        : <Banner kind="info">Each page's text was read back from the finished PDF and compared with the source row. “Checked” does not certify identity, event facts or spelling supplied by the organiser.</Banner>}
      <div className="row gap wrap">
        <a className="btn primary" href={`/api/projects/${p.id}/artifacts/${art.id}/pdf`}>{rep.completion === "checked" ? "Download PDF" : "Download PDF (DRAFT — not fully checked)"}</a>
        <a className="btn" href={`/api/projects/${p.id}/artifacts/${art.id}/report.csv`}>Report (CSV)</a>
        <a className="btn" href={`/api/projects/${p.id}/artifacts/${art.id}/report.json`}>Report (JSON)</a>
      </div>

      <div className="row gap wrap filters">
        <input type="search" placeholder="Search name, page number or source row…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
        {["all", "Needs review", "Blocked"].map((f) => <button key={f} className={"btn small " + (filter === f ? "on" : "")} onClick={() => setFilter(f)}>{f === "all" ? "All pages" : f}</button>)}
        <select value={code} onChange={(e) => setCode(e.target.value)} aria-label="Issue type"><option value="">Any issue</option>{codes.map((c) => <option key={c}>{c}</option>)}</select>
      </div>
      <p className="hint">{shown.length} of {rows.length} pages shown</p>
      <div className="grid-thumbs">
        {shown.map((r: A) => (
          <button key={r.page} className={"thumb " + r.status.replace(" ", "-").toLowerCase()} onClick={() => setOpen(r.page)}>
            <img loading="lazy" src={`/api/projects/${p.id}/artifacts/${art.id}/thumb/${r.page}.png`} alt={`Page ${r.page}`} />
            <span className="cap"><span>{r.page}. {r.name}</span><Status s={r.status} /></span>
          </button>))}
      </div>

      {other.length > 0 && (<><h3>Issues not tied to one page</h3>{other.map((i: A) => <IssueCard key={i.id} i={i} onAck={ack} />)}</>)}

      {open && (
        <Drawer title={`Page ${open} — ${rows.find((r: A) => r.page === open)?.name}`} onClose={() => setOpen(null)}>
          <div className="pagewrap">
            <img className="cert" alt={`Page ${open}`} src={`/api/projects/${p.id}/artifacts/${art.id}/page/${open}.png?scale=1.3`} />
            {rep.issues.filter((i: A) => i.page === open && i.rect).map((i: A) => (
              <div key={i.id} className="hl" style={{ left: i.rect[0] * 100 + "%", top: i.rect[1] * 100 + "%", width: (i.rect[2] - i.rect[0]) * 100 + "%", height: (i.rect[3] - i.rect[1]) * 100 + "%" }} />))}
          </div>
          {rep.issues.filter((i: A) => i.page === open).length === 0 ? <Banner kind="ok">No issues found on this page by the implemented checks.</Banner>
            : rep.issues.filter((i: A) => i.page === open).map((i: A) => <IssueCard key={i.id} i={i} onAck={ack} />)}
        </Drawer>)}
    </div>
  );
}
