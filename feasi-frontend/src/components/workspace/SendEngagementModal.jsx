import React, { useCallback, useEffect, useMemo, useState } from "react";

/**
 * SendEngagementModal — opens from an engagement card / pipeline cell /
 * agent "Send Pack" action. Lets the user type the DNO's recipient
 * email, preview the attached PDF filename, and hand off to the user's
 * own mail client via a `mailto:` link.
 *
 * Council decision (Task #20): Princeps is NOT the sender. This modal
 * never hits an outbound SMTP relay — it only composes a `mailto:`
 * URL that the OS hands to Mail.app / Outlook / Gmail.
 *
 * Scaffolding for future SMTP OAuth: the "Use Princeps mail (Pro)"
 * toggle is wired to a no-op `oauthFlowStub` that the user can see
 * but can't activate. Phase 7f will light it up.
 *
 * After the user confirms they've sent the email, we POST
 * `/api/dno-engagement/{engagement_id}/mark-sent` (handled by the
 * sibling engine package — NOT this router) which flips the row to
 * status='sent' and stamps sent_at/sent_by/recipient_email.
 *
 * Props:
 *   engagement: { id, project_id, dno_slug, pack_version, pdf_path, pdf_sha256 }
 *   onClose:   () => void
 *   onSent:    (engagement_id) => void     // called after the POST succeeds
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
};

function buildMailto({ to, subject, body }) {
  const params = new URLSearchParams();
  params.set("subject", subject);
  params.set("body", body);
  return `mailto:${encodeURIComponent(to)}?${params.toString()
    .replace(/\+/g, "%20")}`;
}

function defaultEmailBody({ dno_slug, project_id, pack_version, pdf_path }) {
  return [
    "Hello,",
    "",
    `Please find attached the connection engagement pack (v${pack_version}) for our project ${project_id}. `,
    "It summarises the load profile, requested POC, firm/non-firm split, and target energisation date.",
    "",
    `We'd welcome your initial view on feasibility and would appreciate a response within the 90-day SLC-15 window.`,
    "",
    `Pack PDF: ${pdf_path || "(attach locally before sending)"}`,
    "",
    "Kind regards,",
    "",
    `(Sent via Princeps — for tracking, please reply to this thread)`,
  ].join("\n");
}

export default function SendEngagementModal({ engagement, onClose, onSent }) {
  const [recipient, setRecipient] = useState("");
  const [useProMail, setUseProMail] = useState(false);  // scaffolded; no-op
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState(null);

  // Escape key = close.
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const subject = useMemo(() => (
    `Princeps engagement pack v${engagement?.pack_version ?? "?"} — project ${engagement?.project_id ?? ""}`
  ), [engagement]);

  const body = useMemo(() => defaultEmailBody({
    dno_slug:     engagement?.dno_slug,
    project_id:   engagement?.project_id,
    pack_version: engagement?.pack_version,
    pdf_path:     engagement?.pdf_path,
  }), [engagement]);

  const mailto = useMemo(
    () => recipient ? buildMailto({ to: recipient, subject, body }) : null,
    [recipient, subject, body],
  );

  const handleOpenMail = useCallback(() => {
    if (!mailto) return;
    window.location.href = mailto;
  }, [mailto]);

  const handleConfirmSent = useCallback(async () => {
    if (!engagement?.id) return;
    setConfirming(true);
    setError(null);
    try {
      // Owned by utils/dno_engagement/ engine package — NOT this router.
      const r = await fetch(`/api/dno-engagement/${engagement.id}/mark-sent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipient_email: recipient }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onSent?.(engagement.id);
      onClose?.();
    } catch (e) {
      setError(e.message || "Could not record send");
    } finally {
      setConfirming(false);
    }
  }, [engagement, recipient, onSent, onClose]);

  const oauthFlowStub = () => {
    // Phase 7f — wire Gmail/Outlook OAuth + send-on-behalf. Today, just nudge.
    alert("Princeps mail (Pro) — available in a later release. For now, use your own mail client via mailto:.");
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: C.overlay,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(560px, 94vw)",
          background: "#FFFFFF",
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          boxShadow: "0 20px 60px rgba(15,19,24,0.25)",
          color: C.ink,
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "16px 20px",
          borderBottom: `1px solid ${C.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-0.01em" }}>
              Send engagement pack
            </div>
            <div style={{ fontSize: 12, color: C.tertiary, marginTop: 2 }}>
              {engagement?.dno_slug
                ? `${engagement.dno_slug.toUpperCase()} · pack v${engagement.pack_version}`
                : "Draft pack"}
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

        {/* Body */}
        <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
          {/* Pack summary */}
          <div style={{
            background: C.bg, border: `1px solid ${C.border}`,
            borderRadius: 8, padding: 12, fontSize: 12, color: C.secondary,
          }}>
            <div><b style={{ color: C.ink }}>PDF:</b> {engagement?.pdf_path || "(not yet rendered)"}</div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: C.tertiary, marginTop: 4 }}>
              sha256 · {engagement?.pdf_sha256 || "—"}
            </div>
          </div>

          {/* Recipient field */}
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.secondary }}>
              Recipient email
            </span>
            <input
              type="email"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              placeholder="connections@ukpn.co.uk"
              style={{
                padding: "8px 12px",
                border: `1px solid ${C.border}`,
                borderRadius: 6,
                fontSize: 13,
                fontFamily: "inherit",
                color: C.ink,
                outline: "none",
              }}
            />
          </label>

          {/* Pro mail toggle — scaffolded, not wired */}
          <label style={{
            display: "flex", alignItems: "center", gap: 8,
            fontSize: 12, color: C.tertiary,
            cursor: "not-allowed",
          }}>
            <input
              type="checkbox"
              checked={useProMail}
              onChange={() => { setUseProMail(false); oauthFlowStub(); }}
              disabled
            />
            Use Princeps mail (Pro) — coming soon
          </label>

          {/* Copy-paste body preview (read-only) */}
          <details style={{ fontSize: 12 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600, color: C.secondary }}>
              Preview email body
            </summary>
            <pre style={{
              whiteSpace: "pre-wrap",
              background: C.bg, border: `1px solid ${C.border}`,
              borderRadius: 6, padding: 10, marginTop: 8,
              fontSize: 11, fontFamily: "'DM Sans', sans-serif",
              color: C.secondary, maxHeight: 200, overflow: "auto",
            }}>{body}</pre>
          </details>

          {error && (
            <div style={{ color: C.caution, fontSize: 12 }}>{error}</div>
          )}

          <div style={{
            fontSize: 11, color: C.tertiary,
            background: C.goldSurface,
            padding: "8px 10px", borderRadius: 6,
            border: `1px solid rgba(245,183,49,0.22)`,
          }}>
            Princeps does not send email directly. Your own mail client will open with the
            recipient and body pre-filled. Attach the pack PDF, send, then come back and
            hit "Mark as sent".
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 20px",
          borderTop: `1px solid ${C.border}`,
          display: "flex",
          gap: 10,
          justifyContent: "flex-end",
          background: C.bg,
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
            onClick={handleOpenMail}
            disabled={!recipient}
            style={{
              padding: "7px 14px",
              fontSize: 12, fontWeight: 700,
              border: `1px solid ${C.border}`, borderRadius: 6,
              background: !recipient ? C.bg : "#FFFFFF",
              color: !recipient ? C.tertiary : C.ink,
              cursor: !recipient ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >Open mail client</button>
          <button
            onClick={handleConfirmSent}
            disabled={!recipient || confirming}
            style={{
              padding: "7px 14px",
              fontSize: 12, fontWeight: 700,
              border: "none", borderRadius: 6,
              background: !recipient ? C.bg : C.gold,
              color: !recipient ? C.tertiary : C.ink,
              cursor: !recipient || confirming ? "default" : "pointer",
              fontFamily: "inherit",
            }}
          >{confirming ? "Recording…" : "Mark as sent"}</button>
        </div>
      </div>
    </div>
  );
}
