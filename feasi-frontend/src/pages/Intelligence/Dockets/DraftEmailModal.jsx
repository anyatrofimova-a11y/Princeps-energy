import React, { useEffect, useState } from "react";
import { COLOURS, SANS } from "./tokens";
import api from "../../../api/dockets";

// Claude-drafted consultation letter modal. SSE-streamed content.
export default function DraftEmailModal({ open, consultee, docket, onClose }) {
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open || !consultee) return;
    setText("");
    setStreaming(true);
    const cancel = api.streamDraftLetter(
      consultee.id,
      {
        project_name: docket?.title || docket?.applicant || "Project",
        case_type: docket?.case_type || "LPA_PLANNING",
      },
      {
        onToken: (tk) => setText((p) => p + tk),
        onDone: () => setStreaming(false),
        onError: () => setStreaming(false),
      }
    );
    return () => cancel && cancel();
  }, [open, consultee, docket]);

  if (!open || !consultee) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  return (
    <div
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose && onClose();
      }}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,19,24,.45)",
        zIndex: 300,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        fontFamily: SANS,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 720,
          background: "#FFFFFF",
          borderRadius: 10,
          boxShadow: "0 20px 60px rgba(0,0,0,.25)",
          display: "flex",
          flexDirection: "column",
          maxHeight: "85vh",
        }}
      >
        <div
          style={{
            padding: "14px 20px",
            borderBottom: `1px solid ${COLOURS.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div>
            <div style={{ fontSize: 11, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Consultation letter
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: COLOURS.ink }}>
              To: {consultee.name}
            </div>
            <div style={{ fontSize: 11, color: COLOURS.muted, marginTop: 2 }}>
              Statutory hook: <strong style={{ color: COLOURS.ink }}>{consultee.statutory_hook}</strong>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              width: 28,
              height: 28,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              background: "transparent",
              border: `1px solid ${COLOURS.border}`,
              borderRadius: 4,
              cursor: "pointer",
              color: COLOURS.muted,
              fontSize: 16,
            }}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div style={{ padding: 20, overflowY: "auto", flex: 1 }}>
          {consultee.contact_email && (
            <div style={{ marginBottom: 12, fontSize: 12, color: COLOURS.inkSoft }}>
              <strong>To:</strong> {consultee.contact_email}
            </div>
          )}
          <pre
            style={{
              fontFamily: SANS,
              fontSize: 13,
              lineHeight: 1.6,
              color: COLOURS.ink,
              whiteSpace: "pre-wrap",
              margin: 0,
              background: COLOURS.ivory,
              padding: 16,
              borderRadius: 6,
              border: `1px solid ${COLOURS.border}`,
              minHeight: 300,
            }}
          >
            {text}
            {streaming && <span style={{ color: COLOURS.gold }}>▋</span>}
          </pre>
        </div>

        <div
          style={{
            padding: "12px 20px",
            borderTop: `1px solid ${COLOURS.border}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ fontSize: 11, color: COLOURS.muted }}>
            {streaming ? "Drafting…" : "Draft ready — review before sending."}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={copy}
              disabled={streaming}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                border: `1px solid ${COLOURS.border}`,
                background: "#FFFFFF",
                color: COLOURS.ink,
                borderRadius: 4,
                cursor: streaming ? "default" : "pointer",
                fontFamily: SANS,
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              disabled={streaming}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 700,
                border: `1px solid ${COLOURS.gold}`,
                background: COLOURS.gold,
                color: COLOURS.ink,
                borderRadius: 4,
                cursor: streaming ? "default" : "pointer",
                fontFamily: SANS,
              }}
            >
              Send email
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
