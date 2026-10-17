import { useEffect, useRef, useState } from "react";

export type A = any;

export class ApiError extends Error {
  status: number;
  detail: A;
  constructor(status: number, detail: A) {
    super(formatDetail(detail));
    this.status = status;
    this.detail = detail;
  }
}

function formatDetail(d: A): string {
  if (!d) return "Request failed";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  if (d.message) return d.message + (d.blocking ? ": " + d.blocking.join(" ") : "");
  return JSON.stringify(d);
}

export async function api<T = A>(path: string, opts: { method?: string; json?: A; form?: FormData } = {}): Promise<T> {
  const init: RequestInit = { method: opts.method || (opts.json || opts.form ? "POST" : "GET") };
  if (opts.json !== undefined) {
    init.body = JSON.stringify(opts.json);
    init.headers = { "Content-Type": "application/json" };
  } else if (opts.form) init.body = opts.form;
  const r = await fetch("/api" + path, init);
  if (!r.ok) {
    let d: A = null;
    try {
      d = (await r.json()).detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(r.status, d);
  }
  return r.json();
}

export function fileForm(file: File, extra: Record<string, string> = {}): FormData {
  const f = new FormData();
  f.append("file", file);
  Object.entries(extra).forEach(([k, v]) => f.append(k, v));
  return f;
}

/** Polls a job until it reaches a terminal state. Progress is only the measurable fraction of completed work units. */
export function useJob(onDone?: (job: A) => void) {
  const [job, setJob] = useState<A | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const cb = useRef(onDone);
  cb.current = onDone;

  const stop = () => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);

  const watch = (jobId: string) => {
    stop();
    setError(null);
    setJob({ id: jobId, status: "queued", progress: 0, message: "Queued" });
    timer.current = window.setInterval(async () => {
      try {
        const j = await api("/jobs/" + jobId);
        setJob(j);
        if (["completed", "failed", "cancelled", "interrupted"].includes(j.status)) {
          stop();
          cb.current?.(j);
        }
      } catch (e: A) {
        stop();
        setError(e.message);
      }
    }, 600);
  };
  const cancel = async () => {
    if (job) await api(`/jobs/${job.id}/cancel`, { method: "POST" });
  };
  const running = !!job && ["queued", "running"].includes(job.status);
  return { job, watch, cancel, running, error, clear: () => setJob(null) };
}

export function route(): string[] {
  return (location.hash.replace(/^#\/?/, "") || "").split("/").filter(Boolean);
}
export function go(path: string) {
  location.hash = "#/" + path;
}

/** Creates a project and opens it. */
export async function startProject(kind: "design" | "check" | "sample"): Promise<void> {
  const body = kind === "check" ? { title: "Check an existing batch", kind: "check" }
    : kind === "sample" ? { title: "Sample project", sample: true } : { title: "New certificate project" };
  const p = await api("/projects", { json: body });
  go(kind === "check" ? `check/${p.id}` : `p/${p.id}/design`);
}
