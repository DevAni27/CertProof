import { useState } from "react";
import { startProject } from "../api";
import { Banner } from "../ui";

const STYLES = [["formal", "Heritage"], ["luxe", "Midnight"], ["academic", "Modern"], ["event", "Bold"]];
const FEATURES: [string, string, string][] = [
  ["✦", "Designer-grade styles", "Four finished looks with fine ornament, refined type and your own logo, signatures and colours. Pick one and see it instantly."],
  ["✎", "Blank-name mode", "Print everything except the name and write it by hand. Choose how many copies and the size of the writing area."],
  ["⇄", "Names that always fit", "Long names shrink to a readable size, or wrap to two lines. Names are never cut off or silently shortened."],
  ["✓", "Every page proof-read", "After the PDF is made, we read it back page by page and compare it to your list: missing, repeated, altered."],
  ["⌕", "Check a batch you already made", "Upload a spreadsheet and any searchable certificate PDF to find missing, duplicate and wrong certificates."],
  ["⤓", "A report you can keep", "Download the print-ready PDF plus a report of exactly what was checked, page by page."],
];

export default function Landing() {
  const [err, setErr] = useState("");
  const go = (k: "design" | "check" | "sample") => startProject(k).catch((e) => setErr(e.message));
  return (
    <div>
      <div className="wrap">
        <section className="hero">
          <div>
            <span className="eyebrow">✦ Certificate maker &amp; checker</span>
            <h1>Certificates worth framing. <span className="grad">Batches you can trust.</span></h1>
            <p className="lead">Design, personalise and check every certificate before you print. Pick a style, add your recipients, and CertProof reads every finished page back to prove each name is right.</p>
            <div className="cta-row">
              <button className="btn primary big" onClick={() => go("design")}>Create certificates →</button>
              <button className="btn big" onClick={() => go("sample")}>See a sample project</button>
            </div>
            {err && <Banner kind="bad">{err}</Banner>}
            <div className="trust"><span>Print-ready A4 PDF</span><span>Blank-name option</span><span>Page-by-page proof report</span></div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="glow" />
            <img className="a" src="/samples/formal.jpg" alt="" />
            <img className="b" src="/samples/luxe.jpg" alt="" />
          </div>
        </section>
      </div>

      <div className="wrap">
        <section className="section" id="how">
          <div className="kicker">How it works</div>
          <h2>From idea to proofed PDF in three steps</h2>
          <p className="intro">No design skills and no spreadsheet gymnastics. You always see the certificate as it will print.</p>
          <div className="steps3">
            <div className="s"><i>1</i><b>Design</b><p>Enter your event, add your logo and signatures, choose a style. The preview updates as you type.</p></div>
            <div className="s"><i>2</i><b>Add recipients</b><p>Upload a CSV or Excel file, paste names, or skip it and print blank certificates to fill by hand.</p></div>
            <div className="s"><i>3</i><b>Export &amp; proof</b><p>We build the PDF, read it back and report any page that doesn’t match your list.</p></div>
          </div>
        </section>

        <section className="section" id="styles">
          <div className="kicker">Styles</div>
          <h2>Pick a look, make it yours</h2>
          <p className="intro">Every style adapts to your colours, logo and number of signatories.</p>
          <div className="gallery">
            {STYLES.map(([k, l]) => <figure key={k}><img src={`/samples/${k}.jpg`} alt={`${l} certificate style`} loading="lazy" /><figcaption>{l}</figcaption></figure>)}
          </div>
          <p className="hint" style={{ marginTop: 14 }}>Sample certificates use fictional names and organisations.</p>
        </section>

        <section className="section" id="features">
          <div className="kicker">Why CertProof</div>
          <h2>Beautiful on paper. Correct on every page.</h2>
          <p className="intro">Most tools stop at “generate”. We also check the result.</p>
          <div className="features">
            {FEATURES.map(([ic, t, d]) => <div className="feat" key={t}><div className="ic">{ic}</div><b>{t}</b><p>{d}</p></div>)}
          </div>
        </section>

        <div className="band">
          <h2>Ready to make your first batch?</h2>
          <p>Start with a style, see the certificate update live, and export when it looks right.</p>
          <div className="cta-row" style={{ justifyContent: "center" }}>
            <button className="btn primary big" onClick={() => go("design")}>Create certificates →</button>
            <button className="btn big" onClick={() => go("check")}>Check an existing batch</button>
          </div>
        </div>
      </div>
    </div>
  );
}
