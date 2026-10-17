import { ReactNode } from "react";
import { A, startProject } from "./api";

export const STATUS_CLASS: Record<string, string> = {
  Checked: "ok", "Needs review": "warn", Blocked: "bad", "Not checked": "muted", "Not applicable": "muted",
};

export function Status({ s }: { s: string }) {
  return <span className={"chip " + (STATUS_CLASS[s] || "muted")}>{s}</span>;
}

export function completionLabel(c: string): string {
  return c === "checked" ? "Checked" : c === "needs_review" ? "Needs review" : c === "blocked" ? "Blocked" : "Not checked";
}

export function Banner({ kind, children }: { kind: "info" | "warn" | "bad" | "ok"; children: ReactNode }) {
  return <div className={"banner " + kind} role={kind === "bad" ? "alert" : "status"}>{children}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="lbl">{label}</span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function JobBar({ job, onCancel }: { job: A; onCancel?: () => void }) {
  if (!job) return null;
  const active = ["queued", "running"].includes(job.status);
  const measurable = active && job.progress > 0;
  return (
    <div className="jobbar" aria-live="polite">
      <div className="jobtxt">
        <strong>{job.status === "queued" ? "Queued" : active ? "Working" : job.status[0].toUpperCase() + job.status.slice(1)}</strong>
        <span> {job.message}</span>
      </div>
      {active && (
        <div className={"bar " + (measurable ? "" : "indet")}>
          <div style={{ width: measurable ? Math.round(job.progress * 100) + "%" : undefined }} />
        </div>
      )}
      {active && onCancel && <button className="btn small" onClick={onCancel}>Cancel</button>}
    </div>
  );
}

export function IssueCard({ i, onAck, onPick }: { i: A; onAck?: (id: string, note: string) => void; onPick?: (rowIdx: string) => void }) {
  return (
    <div className={"issue " + i.severity}>
      <div className="issue-head">
        <span className={"chip " + (i.severity === "error" ? "bad" : i.severity === "warning" ? "warn" : "muted")}>
          {i.severity === "error" ? "Blocked" : i.acknowledged ? "Acknowledged" : "Needs review"}
        </span>
        <code>{i.code}</code>
        {i.page ? <span className="where">page {i.page}</span> : null}
        {i.source_row_index ? <span className="where">source row {i.source_row_index}</span> : null}
        {i.field ? <span className="where">{i.field}</span> : null}
      </div>
      <p>{i.message}</p>
      {(i.expected != null || i.actual != null) && (
        <dl className="cmp">
          {i.expected != null && (<><dt>Expected</dt><dd>{i.expected || <em>(empty)</em>}</dd></>)}
          {i.actual != null && (<><dt>Found in PDF</dt><dd>{i.actual || <em>(empty)</em>}</dd></>)}
        </dl>
      )}
      {i.next_action && <p className="next"><strong>Next:</strong> {i.next_action}</p>}
      {i.candidates?.length > 0 && onPick && (
        <p className="next">Candidate source rows: {i.candidates.map((c: string) => (
          <button key={c} className="btn small" onClick={() => onPick(c)}>row {c}</button>))}</p>
      )}
      {i.acknowledged && <p className="hint">Audit note: {i.ack_note}</p>}
      {i.severity === "warning" && !i.acknowledged && onAck && <AckForm onAck={(n) => onAck(i.id, n)} />}
    </div>
  );
}

import { useState } from "react";
function AckForm({ onAck }: { onAck: (note: string) => void }) {
  const [n, setN] = useState("");
  return (
    <div className="ack">
      <input value={n} placeholder="Audit note (required) — why this is acceptable" onChange={(e) => setN(e.target.value)} />
      <button className="btn small" disabled={!n.trim()} onClick={() => onAck(n)}>Acknowledge</button>
    </div>
  );
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="drawer-wrap" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={title}>
        <header><h3>{title}</h3><button className="btn small" onClick={onClose} autoFocus>Close</button></header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

export function Header({ current }: { current: string }) {
  return (
    <header className="top">
      <div className="wrap">
        <a href="#/" className="brand"><span className="logo-mark">✓</span>CertProof<span className="descriptor">Certificate maker &amp; checker</span></a>
        <nav>
          <a href="#/" className={current === "" ? "on" : ""}>Home</a>
          <a href="#/projects" className={current === "projects" ? "on" : ""}>My projects</a>
          <button className="btn small" onClick={() => startProject("check")}>Check a batch</button>
          <button className="btn small primary" onClick={() => startProject("design")}>Create certificates</button>
        </nav>
      </div>
    </header>
  );
}
