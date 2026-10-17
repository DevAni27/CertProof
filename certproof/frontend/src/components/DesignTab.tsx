import { useEffect, useRef, useState } from "react";
import { A, api, fileForm, go, useJob } from "../api";
import { Banner, Field } from "../ui";

const FONTS = [["lora", "Lora (serif)"], ["inter", "Inter (sans)"], ["poppins", "Poppins (display)"]];
const STYLES = [
  { id: "formal", name: "Heritage", desc: "Classic double border, gold flourishes" },
  { id: "luxe", name: "Midnight", desc: "Deep dark page with gold detail" },
  { id: "academic", name: "Modern", desc: "Calm, clean, side band" },
  { id: "event", name: "Bold", desc: "Confident corners, strong type" },
];
const MAX_SIG = 4;
const OPTS: Record<string, [string, string][]> = {
  frame: [["none", "None"], ["single", "Single line"], ["double", "Double line"], ["triple", "Triple line"], ["rounded", "Rounded"], ["thick_thin", "Thick + thin"]],
  corners: [["none", "None"], ["flourish", "Flourish"], ["triangles", "Triangles"], ["quarter_circles", "Quarter circles"], ["rings", "Rings"], ["brackets", "Brackets"]],
  band: [["none", "None"], ["left", "Left"], ["right", "Right"], ["top", "Top"], ["bottom", "Bottom"], ["top_bottom", "Top + bottom"], ["left_right", "Left + right"]],
  pattern: [["none", "None"], ["rosette", "Rosette"], ["dots", "Dots"], ["stripes", "Stripes"], ["arcs", "Arcs"], ["grid", "Grid"], ["waves", "Waves"]],
  divider: [["none", "None"], ["line", "Line"], ["diamond", "Diamond"], ["dots", "Dots"], ["double", "Double line"]],
};
const realSig = (s: A) => !!(s.name?.trim() || s.title?.trim() || s.signature_asset_id);

export default function DesignTab({ p, reload }: { p: A; reload: () => void }) {
  const [ev, setEv] = useState<A>(p.event);
  const [brand, setBrand] = useState<A>(p.brand);
  const [spec, setSpec] = useState<A | null>(p.design);
  const [previewRow, setPreviewRow] = useState<string>("");
  const [img, setImg] = useState<string>("");
  const [pvMsg, setPvMsg] = useState<string>("");
  const [state, setState] = useState<"saved" | "saving" | "error">("saved");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<A>(null);
  const [aiFail, setAiFail] = useState("");

  const touched = useRef(false);
  const latest = useRef({ ev, brand, spec, previewRow });
  latest.current = { ev, brand, spec, previewRow };
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const seq = useRef(0);

  const touch = () => { touched.current = true; };
  const setE = (patch: A) => { touch(); setEv((e: A) => ({ ...e, ...patch })); };
  const setB = (patch: A) => { touch(); setBrand((b: A) => ({ ...b, ...patch })); };
  const edit = (patch: A) => { touch(); setSpec((s: A) => ({ ...s, ...patch, source: "manual" })); };

  /** Saves everything, then re-renders the preview. Calls are serialised so they never race. */
  const persist = () => {
    chain.current = chain.current.then(async () => {
      const { ev, brand, spec, previewRow } = latest.current;
      const mine = ++seq.current;
      try {
        await api("/projects/" + p.id, { method: "PATCH", json: { event: { ...ev, signatories: ev.signatories.filter(realSig) }, brand } });
        if (spec) await api(`/projects/${p.id}/design`, { method: "PUT", json: spec });
        setState("saved");
        if (!ev.event_name.trim() || !ev.organisation.trim()) { setImg(""); setPvMsg("Add your event name and organisation to see the certificate."); return; }
        setPvMsg("");
        const pv = await api(`/projects/${p.id}/preview`, { json: { row_id: previewRow || null } });
        if (mine === seq.current) setImg(`/api/projects/${p.id}/artifacts/${pv.artifact_id}/preview.png`);
      } catch (e: A) {
        setState("error");
        if (e.status === 422 || e.status === 409) setPvMsg(e.message);
        else setPvMsg("Couldn't update the preview: " + e.message);
      }
    });
    return chain.current;
  };

  // Debounced autosave + live preview on any edit.
  useEffect(() => {
    if (!touched.current) return;
    setState("saving");
    const t = window.setTimeout(persist, 700);
    return () => window.clearTimeout(t);
  }, [ev, brand, spec, previewRow]); // eslint-disable-line

  // First visit: start from the first style so there is always something to look at.
  useEffect(() => {
    (async () => {
      if (!p.design) {
        const d = await api(`/projects/${p.id}/design/fallback`, { json: { layout: "formal" } });
        touch(); setSpec(d);
      } else persist();
    })().catch((e) => setNote({ kind: "bad", t: e.message }));
  }, []); // eslint-disable-line

  const job = useJob((j) => {
    if (j.status === "completed") { touch(); setSpec(j.result.design); setAiFail(""); setNote({ kind: "ok", t: "Design suggestion applied. Tweak anything — the preview updates as you go." }); }
    else setAiFail(j.message || "The suggestion did not finish.");
  });
  const suggest = async () => {
    setAiFail(""); setNote(null);
    await persist();
    try { const r = await api(`/projects/${p.id}/design/propose`, { json: { brief: brand.brief } }); job.watch(r.job_id); }
    catch (e: A) { setAiFail(e.message); }
  };

  const chooseStyle = async (layout: string) => {
    const d = await api(`/projects/${p.id}/design/fallback`, { json: { layout } });
    const keep = spec ? { preamble_text: spec.preamble_text, body_text: spec.body_text, name_font_max_pt: spec.name_font_max_pt, name_font_min_pt: spec.name_font_min_pt, allow_two_lines: spec.allow_two_lines } : {};
    touch(); setSpec({ ...d, ...keep, palette: spec && (brand.primary || brand.accent) ? { ...d.palette, ...spec.palette } : d.palette, warnings: [] });
  };
  const editComp = (patch: A) => edit({ composition: { ...spec!.composition, ...patch } });
  const setColour = (k: "primary" | "accent", v: string) => { touch(); setSpec((s: A) => ({ ...s, palette: { ...s.palette, [k]: v }, source: "manual" })); setBrand((b: A) => ({ ...b, [k]: v })); };

  // ---- signatories ----
  const sigs: A[] = ev.signatories || [];
  const setSig = (i: number, patch: A) => { const s = [...sigs]; s[i] = { ...s[i], ...patch }; setE({ signatories: s }); };
  const addSig = () => sigs.length < MAX_SIG && setE({ signatories: [...sigs, { name: "", title: "" }] });
  const delSig = (i: number) => setE({ signatories: sigs.filter((_, k) => k !== i) });

  const upload = async (file: File, role: "logo" | "signature", i = 0) => {
    setBusy(true);
    try {
      await persist();                                   // make sure the server list matches what is on screen
      const { ev: cur } = latest.current;
      const idx = role === "signature" ? cur.signatories.slice(0, i).filter(realSig).length : 0;
      const a = await api(`/projects/${p.id}/assets`, { form: fileForm(file, { role, signatory_index: String(idx) }) });
      if (role === "logo") setE({ logo_asset_id: a.id });
      else setSig(i, { signature_asset_id: a.id });
    } catch (e: A) { setNote({ kind: "bad", t: e.message }); } finally { setBusy(false); }
  };

  const next = async () => { await persist(); go(`p/${p.id}/recipients`); };
  const label = (t: string) => <span className="lbl">{t}</span>;
  const cur = spec?.layout_id;

  return (
    <div className="split">
      <div className="col">
        {note && <Banner kind={note.kind}>{note.t}</Banner>}

        <div className="sect">
          <h2><span className="num-badge">1</span>Choose a style</h2>
          <p className="sub">Click a style — your certificate on the right updates straight away.</p>
          {cur === "custom" && <div className="banner ok" style={{ marginTop: 0 }}>✦ This is a custom design made from your brief. Pick a style below to switch, or fine-tune it at the bottom.</div>}
          <div className="styles">
            {STYLES.map((s) => (
              <button key={s.id} className={"style-card " + (cur === s.id ? "on" : "")} onClick={() => chooseStyle(s.id)} aria-pressed={cur === s.id}>
                <img src={`/samples/${s.id}.jpg`} alt="" loading="lazy" />
                <b>{s.name}</b><span>{s.desc}</span>
              </button>
            ))}
          </div>
          <details className="adv" style={{ marginTop: 14 }}>
            <summary>Not sure? Describe the look you want</summary>
            <Field label="Style brief" hint="A few words, e.g. “calm, premium, deep green and gold”.">
              <textarea rows={2} value={brand.brief} onChange={(e) => setB({ brief: e.target.value })} />
            </Field>
            <div className="row gap wrap" style={{ marginBottom: 10 }}>
              <button className="btn" onClick={suggest} disabled={job.running || !ev.event_name || !ev.organisation}>{cur === "custom" ? "✦ Try another design" : "✦ Suggest a design"}</button>
              {job.running ? <span className="hint">Designing — this can take a minute…</span> : <span className="hint">Each click creates a new design from your words.</span>}
            </div>
            {aiFail && <Banner kind="warn">We couldn’t generate a suggestion this time — choose one of the styles above instead.
              <details><summary className="hint">Details</summary><span className="hint">{aiFail}</span></details></Banner>}
          </details>
        </div>

        <div className="sect">
          <h2><span className="num-badge">2</span>Event details</h2>
          <p className="sub">Exactly what should print. We never invent or change your wording.</p>
          <div className="grid2">
            <Field label="Event name"><input value={ev.event_name} onChange={(e) => setE({ event_name: e.target.value })} placeholder="Northlight Design Summit 2026" /></Field>
            <Field label="Organisation"><input value={ev.organisation} onChange={(e) => setE({ organisation: e.target.value })} placeholder="Northlight Collective" /></Field>
            <Field label="Certificate title"><input value={ev.cert_type} onChange={(e) => setE({ cert_type: e.target.value })} /></Field>
            <Field label="Date (prints as typed)"><input value={ev.event_date} onChange={(e) => setE({ event_date: e.target.value })} placeholder="12 October 2026" /></Field>
          </div>
          <Field label="Opening line" hint="Appears above the name.">
            <input value={spec?.preamble_text ?? ""} onChange={(e) => edit({ preamble_text: e.target.value })} />
          </Field>
          <Field label="Wording below the name" hint="You can use {event_name}, {organisation} and {event_date}.">
            <textarea rows={2} value={ev.wording || spec?.body_text || ""} onChange={(e) => setE({ wording: e.target.value })} />
          </Field>
        </div>

        <div className="sect">
          <h2><span className="num-badge">3</span>Logo &amp; colours</h2>
          <p className="sub">Optional. Your logo is placed as-is and never stretched.</p>
          <div className="row gap wrap" style={{ alignItems: "flex-start" }}>
            <Field label="Logo (PNG or JPEG)">
              <input type="file" accept="image/png,image/jpeg" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "logo")} />
              {ev.logo_asset_id && <><img className="thumb-logo" src={`/api/projects/${p.id}/assets/${ev.logo_asset_id}`} alt="logo" />
                <button className="btn small ghost" style={{ alignSelf: "flex-start" }} onClick={() => setE({ logo_asset_id: null })}>Remove logo</button></>}
            </Field>
          </div>
          <div className="colors">
            <Field label="Main colour"><input type="color" value={spec?.palette.primary || "#1f3a5f"} onChange={(e) => setColour("primary", e.target.value)} /></Field>
            <Field label="Accent colour"><input type="color" value={spec?.palette.accent || "#c8963e"} onChange={(e) => setColour("accent", e.target.value)} /></Field>
          </div>
        </div>

        <div className="sect">
          <h2><span className="num-badge">4</span>Signatures</h2>
          <p className="sub">Add as many as you need — or none. Up to {MAX_SIG}.</p>
          {sigs.length === 0 && <p className="hint" style={{ margin: "0 0 12px" }}>No signature lines on this certificate.</p>}
          {sigs.map((s, i) => (
            <div className="sig-card" key={i}>
              <div className="head"><span>Signature {i + 1}</span><button className="btn small ghost danger" onClick={() => delSig(i)}>Remove</button></div>
              <div className="grid2">
                <Field label="Name"><input value={s.name || ""} onChange={(e) => setSig(i, { name: e.target.value })} placeholder="Full name" /></Field>
                <Field label="Role"><input value={s.title || ""} onChange={(e) => setSig(i, { title: e.target.value })} placeholder="e.g. Programme Director" /></Field>
              </div>
              <Field label="Signature image (optional)" hint={s.name?.trim() ? undefined : "Enter a name first."}>
                <input type="file" accept="image/png,image/jpeg" disabled={busy || !s.name?.trim()} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0], "signature", i)} />
                {s.signature_asset_id && <><img className="thumb-sig" src={`/api/projects/${p.id}/assets/${s.signature_asset_id}`} alt="signature" />
                  <button className="btn small ghost" style={{ alignSelf: "flex-start" }} onClick={() => setSig(i, { signature_asset_id: null })}>Remove image</button></>}
              </Field>
            </div>
          ))}
          {sigs.length < MAX_SIG && <button className="btn" onClick={addSig}>+ Add a signature</button>}
        </div>

        {spec && (
          <details className="adv">
            <summary>Fine-tune typography &amp; layout</summary>
            {spec.layout_id === "custom" && (
              <>
                <div className="grid3">
                  {(["frame", "corners", "band", "pattern", "divider"] as const).map((k) => (
                    <Field key={k} label={k[0].toUpperCase() + k.slice(1)}>
                      <select value={spec.composition[k]} onChange={(e) => editComp({ [k]: e.target.value })}>{OPTS[k].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
                    </Field>))}
                  <Field label="Page style"><select value={spec.composition.background} onChange={(e) => editComp({ background: e.target.value })}><option value="solid">Solid</option><option value="gradient">Gradient</option></select></Field>
                </div>
                <div className="grid3">
                  <Field label="Page colour"><input type="color" value={spec.palette.background} onChange={(e) => edit({ palette: { ...spec.palette, background: e.target.value } })} /></Field>
                  {spec.composition.background === "gradient" && <Field label="Gradient to"><input type="color" value={spec.composition.background_color2} onChange={(e) => editComp({ background_color2: e.target.value })} /></Field>}
                  <Field label="Text colour"><input type="color" value={spec.palette.text} onChange={(e) => edit({ palette: { ...spec.palette, text: e.target.value } })} /></Field>
                  <Field label="Italic names (Lora)"><input type="checkbox" checked={spec.composition.name_italic} onChange={(e) => editComp({ name_italic: e.target.checked })} /></Field>
                  <Field label={`Title spacing ${spec.composition.title_tracking_em}`}><input type="range" min={0} max={0.3} step={0.01} value={spec.composition.title_tracking_em} onChange={(e) => editComp({ title_tracking_em: +e.target.value })} /></Field>
                  <Field label={`Texture strength ${spec.composition.pattern_opacity}`}><input type="range" min={0.03} max={0.2} step={0.01} value={spec.composition.pattern_opacity} onChange={(e) => editComp({ pattern_opacity: +e.target.value })} /></Field>
                </div>
              </>)}
            <div className="grid3">
              {spec.layout_id !== "custom" && <Field label="Ornament"><select value={spec.ornament} onChange={(e) => edit({ ornament: e.target.value })}>{[["corners", "Corner flourishes"], ["rule", "Divider only"], ["band", "Accent band"], ["none", "None"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>}
              <Field label="Heading font"><select value={spec.fonts.heading} onChange={(e) => edit({ fonts: { ...spec.fonts, heading: e.target.value } })}>{FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <Field label="Body font"><select value={spec.fonts.body} onChange={(e) => edit({ fonts: { ...spec.fonts, body: e.target.value } })}>{FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <Field label="Name font"><select value={spec.fonts.name} onChange={(e) => edit({ fonts: { ...spec.fonts, name: e.target.value } })}>{FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <Field label={`Spacing ${spec.density}`}><input type="range" min={0.85} max={1.15} step={0.01} value={spec.density} onChange={(e) => edit({ density: +e.target.value })} /></Field>
              <Field label={`Border ${spec.border_mm} mm`}><input type="range" min={0} max={4} step={0.1} value={spec.border_mm} onChange={(e) => edit({ border_mm: +e.target.value })} /></Field>
              <Field label="Name size max (pt)"><input type="number" min={28} max={60} value={spec.name_font_max_pt} onChange={(e) => edit({ name_font_max_pt: +e.target.value })} /></Field>
              <Field label="Name size min (pt)" hint="Names never shrink below this."><input type="number" min={18} max={40} value={spec.name_font_min_pt} onChange={(e) => edit({ name_font_min_pt: +e.target.value })} /></Field>
              <Field label="Two-line names"><input type="checkbox" checked={spec.allow_two_lines} onChange={(e) => edit({ allow_two_lines: e.target.checked })} /></Field>
            </div>
          </details>
        )}
        {spec?.warnings?.length > 0 && <Banner kind="info">{spec.warnings.map((w: string, i: number) => <div key={i}>{w}</div>)}</Banner>}

        <div className="sticky-cta">
          <button className="btn primary big" onClick={next}>Continue to recipients →</button>
        </div>
      </div>

      <div className="col preview">
        <div className="row between" style={{ marginBottom: 10 }}>
          <h2 style={{ margin: 0 }}>Live preview</h2>
          {p.source.rows.length > 0 && p.output_mode === "personalised" && (
            <select value={previewRow} onChange={(e) => setPreviewRow(e.target.value)} aria-label="Preview recipient">
              <option value="">First recipient</option>
              {p.source.rows.map((r: A) => <option key={r.row_id} value={r.row_id}>{r.cells[p.mapping?.name] ?? Object.values(r.cells)[0]}</option>)}
            </select>)}
        </div>
        <div className={"stage " + (state === "saving" ? "busy" : "")}>
          {img ? <img className="cert" alt="Certificate preview" src={img} /> : <div className="ph">{pvMsg || "Preparing your preview…"}</div>}
          {state === "saving" && img && <span className="overlay">Updating…</span>}
        </div>
        {img && pvMsg && <Banner kind="warn">{pvMsg}</Banner>}
        <div className="savebar">
          <span><span className={"dot " + (state === "saving" ? "saving" : state === "error" ? "err" : "")} />{state === "saving" ? "Saving…" : state === "error" ? "Couldn’t save — check the details" : "All changes saved"}</span>
          <span>{p.output_mode === "blank_name" ? "Blank-name mode: the name area is left empty." : (p.source.rows.length ? "Shown with your first recipient’s name." : "A sample name is shown until you add recipients.")}</span>
        </div>
      </div>
    </div>
  );
}
