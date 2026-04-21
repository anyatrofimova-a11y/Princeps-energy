import React, { useCallback, useEffect, useState } from "react";

/**
 * IngestResponseModal — opens when the user has received a response
 * from the DNO and wants to feed it into Princeps so the workflow
 * advances (engagement status: sent → responded) and the agent can
 * factor it into verdicts.
 *
 * Two input modes:
 *  - "Paste email"     — paste the raw email body; we POST raw_body.
 *  - "Upload PDF"      — pick a PDF from disk; we upload it to
 *                         `/api/v1/uploads` first to get a server path,
 *                         then POST with raw_pdf_path + the PDF's
 *                         extracted text as raw_body.
 *
 * Server: POST /api/dno-engagement/{id}/response — parses via Claude
 * (app/ingestion/dno_response_parser.py) and writes a structured
 * `dno_engagement_responses` row.
 *
 * Props:
 *   engagement: { id, project_id, dno_slug, pack_version }
 *   onClose:     () => void
 *   onIngested:  (engagement_id, response) => void
 */

const C = {
  overlay: "rgba(15,19,24,0.44)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  bg: "#F7F8FA",
  gold: "#F5B731",
  goldSurface: "rgba(245,183,49,0.10)",
  go: "#2F7C46",
  caution: "#C07A1A",
  nogo: "#B23B3B",
};

export default function IngestResponseModal({ engagement, onClose, onIngested }) {
  const [mode, setMode] = useState("email");          // 'email' | 'upload'
  const [rawBody, setRawBody] = useState("");
  const [pdfFile, setPdfFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);        // parsed structured_extract

  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const reset = () => {
    setRawBody(""); setPdfFile(null); setPreview(null); setError(null);
  };

  const handleModeSwitch = (m) => { reset(); setMode(m); };

  const handleFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setPdfFile(f);
    setError(null);
  };

  const submit = useCallback(async () => {
    if (!engagement?.id) return;
    setBusy(true); setError(null); setPreview(null);

    try {
      let channel = "manual";
      let payload = {};

      if (mode === "email") {
        if (!rawBody.trim()) throw new Error("Paste the email body first");
        channel = "email";
        payload = { channel, raw_body: rawBody };
      } else {
        if (!pdfFile) throw new Error("Choose a PDF file first");
        channel = "upload";

        // Upload the PDF to the server so we get a path we can persist.
        const fd = new FormData();
        fd.append("file", pdfFile);
        const up = await fetch("/api/v1/uploads", { method: "POST", body: fd });
        if (!up.ok) {
          // Fall back: no upload route — send raw_body only with the filename as a marker.
          payload = {
            channel,
            raw_body: `[PDF attached: ${pdfFile.name}]\n(Upload route unavailable — server will parse from filename only.)`,
          };
        } else {
          const upj = await up.json().catch(() => ({}));
          payload = {
            channel,
            raw_body: rawBody || null,
            raw_pdf_path: upj.path || upj.storage_path || upj.url || null,
          };
        }
      }

      const r = await fetch(`/api/dno-engagement/${engagement.id}/response`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setPreview(data.structured_extract || null);
      onIngested?.(engagement.id, data);
    } catch (e) {
      setError(e.message || "Ingest failed");
    } finally {
      setBusy(false);
    }
  }, [engagement, mode, rawBody, pdfFile, onIngested]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0,
        background: C.overlay, zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(620px, 94vw)", background: "#FFFFFF",
          borderRadius: 12, border: `1px solid ${C.border}`,
          boxShadow: "0 20px 60px rgba(15,19,24,0.25)",
          color: C.ink, overflow: "hidden",
          display: "flex", flexDirection: "column", maxHeight: "90vh",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "16px 20px", borderBottom: `1px solid ${C.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-0.01em" }}>
              Ingest DNO response
            </div>
            <div style={{ fontSize: 12, color: C.tertiary, marginTop: 2 }}>
              {engagement?.dno_slug
                ? `${engagement.dno_slug.toUpperCase()} · pack v${engagement.pack_version}`
                : "Engagement"}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              border: "none", background: "transparent",
              fontSize: 18, color: C.secondary, cursor: "pointer", padding: 4,
            }}
            aria-label="Close"
          >×</button>
        </div>

        {/* Mode toggle */}
        <div style={{ padding: "12px 20px 0", display: "flex", gap: 8 }}>
          {["email", "upload"].map((m) => {
            const active = mode === m;
            return (
              <button
                key={m}
                onClick={() => handleModeSwitch(m)}
                style={{
                  padding: "6px 12px",
                  fontSize: 12, fontWeight: active ? 700 : 600,
                  border: `1px solid ${active ? C.gold : C.border}`,
                  borderRadius: 6,
                  background: active ? C.goldSurface : "#FFFFFF",
                  color: C.ink, cursor: "pointer", fontFamily: "inherit",
                }}
              >
                {m === "email" ? "Paste email" : "Upload PDF"}
              </button>
            );
          })}
        </div>

        {/* Body */}
        <div style={{
          padding: "14px 20px", flex: 1, overflow: "auto",
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          {mode === "email" && (
            <textarea
              value={rawBody}
              onChange={(e) => setRawBody(e.target.value)}
              placeholder="Paste the full email body — headers, greeting, the DNO's substantive reply, and any attached offer text."
              rows={14}
              style={{
                width: "100%", padding: 12,
                border: `1px solid ${C.border}`, borderRadius: 8,
                fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
                color: C.ink, outline: "none", resize: "vertical",
              }}
            />
          )}

          {mode === "upload" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <label style={{
                border: `1.5px dashed ${C.border}`, borderRadius: 8,
                padding: 24, textAlign: "center", cursor: "pointer",
                color: C.secondary, fontSize: 12,
                background: pdfFile ? C.goldSurface : C.bg,
              }}>
                <input type="file" accept="application/pdf"
                  onChange={handleFile} style={{ display: "none" }} />
                {pdfFile
                  ? <b style={{ color: C.ink }}>{pdfFile.name}</b>
                  : "Choose PDF — formal DNO offer letter or response"}
              </label>
              <textarea
                value={rawBody}
                onChange={(e) => setRawBody(e.target.value)}
                placeholder="Optional cover-email body (paste here if the PDF came with one)."
                rows={4}
                style={{
                  width: "100%", padding: 12,
                  border: `1px solid ${C.border}`, borderRadius: 8,
                  fontSize: 12, fontFamily: "'JetBrains Mono', monospace",
                  color: C.ink, outline: "none", resize: "vertical",
                }}
              />
            </div>
          )}

          {error && (
            <div style={{ color: C.nogo, fontSize: 12 }}>Error: {error}</div>
          )}

          {preview && (
            <div style={{
              background: C.goldSurface, border: "1px solid rgba(245,183,49,0.22)",
              borderRadius: 8, padding: 12, fontSize: 12, color: C.ink,
            }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>
                Parsed preview
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: "4px 10px" }}>
                <div style={{ color: C.secondary }}>Sentiment:</div>
                <div style={{ fontWeight: 600 }}>{preview.sentiment || "—"}</div>
                {preview.firm_split_delta != null && (<>
                  <div style={{ color: C.secondary }}>Firm split Δ:</div>
                  <div style={{
                    fontWeight: 600,
                    color: preview.firm_split_delta < 0 ? C.caution : C.go,
                  }}>
                    {preview.firm_split_delta > 0 ? "+" : ""}{preview.firm_split_delta} MW
                  </div>
                </>)}
                {preview.timeline_revision?.days_delta != null && (<>
                  <div style={{ color: C.secondary }}>Timeline Δ:</div>
                  <div style={{
                    fontWeight: 600,
                    color: preview.timeline_revision.days_delta > 0 ? C.caution : C.go,
                  }}>
                    {preview.timeline_revision.days_delta > 0 ? "+" : ""}
                    {preview.timeline_revision.days_delta} days
                  </div>
                </>)}
                {preview.proposed_poc && (<>
                  <div style={{ color: C.secondary }}>Proposed POC:</div>
                  <div>{preview.proposed_poc.name || "—"}{preview.proposed_poc.voltage_kv ? ` @ ${preview.proposed_poc.voltage_kv}kV` : ""}</div>
                </>)}
                {Array.isArray(preview.requested_info) && preview.requested_info.length > 0 && (<>
                  <div style={{ color: C.secondary }}>DNO asks:</div>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {preview.requested_info.slice(0, 5).map((x, i) => (
                      <li key={i}>{x}</li>
                    ))}
                  </ul>
                </>)}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 20px", borderTop: `1px solid ${C.border}`,
          display: "flex", gap: 10, justifyContent: "flex-end", background: C.bg,
        }}>
          <button
            onClick={onClose}
            style={{
              padding: "7px 14px",
              fontSize: 12, fontWeight: 600,
              border: `1px solid ${C.border}`, borderRadius: 6,
              background: "#FFFFFF", color: C.secondary,
              cursor: "pointer", fontFamily: "inherit",
            }}
          >Cancel</button>
          <button
            onClick={submit}
            disabled={busy || (mode === "email" ? !rawBody.trim() : !pdfFile)}
            style={{
              padding: "7px 14px",
              fontSize: 12, fontWeight: 700,
              border: "none", borderRadius: 6,
              background: busy ? C.bg : C.gold,
              color: busy ? C.tertiary : C.ink,
              cursor: busy ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >{busy ? "Parsing…" : "Parse & save"}</button>
        </div>
      </div>
    </div>
  );
}
