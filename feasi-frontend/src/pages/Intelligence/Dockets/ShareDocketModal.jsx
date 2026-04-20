import React, { useState } from "react";
import { COLOURS, SANS, MONO } from "./tokens";
import api, { exportDocketURL } from "../../../api/dockets";
import { Overlay, ModalFrame, Group } from "./WatchDocketModal";

// Share modal — read-only link + export to PDF / CSV / JSON.
export default function ShareDocketModal({ open, docket, onClose }) {
  const [shareUrl, setShareUrl] = useState("");
  const [gen, setGen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!open || !docket) return null;

  const generate = async () => {
    setGen(true);
    const res = await api.shareDocket(docket.id, { scope: "read_only" });
    setShareUrl(res?.share_url || "");
    setGen(false);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  const download = (fmt) => {
    const url = exportDocketURL(docket.id, fmt);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${docket.docket_number}.${fmt}`;
    a.click();
  };

  return (
    <Overlay onClose={onClose}>
      <ModalFrame title="Share docket" subtitle={`${docket.docket_number} — ${docket.title}`} onClose={onClose}>
        <Group title="Read-only share link">
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={shareUrl}
              readOnly
              placeholder="Click Generate to create a link"
              style={{
                flex: 1,
                padding: "8px 10px",
                border: `1px solid ${COLOURS.border}`,
                borderRadius: 4,
                fontSize: 12,
                fontFamily: MONO,
                color: COLOURS.ink,
                outline: "none",
              }}
            />
            {!shareUrl ? (
              <button
                onClick={generate}
                disabled={gen}
                style={{
                  padding: "7px 14px",
                  fontSize: 12,
                  fontWeight: 700,
                  background: COLOURS.gold,
                  color: COLOURS.ink,
                  border: `1px solid ${COLOURS.gold}`,
                  borderRadius: 4,
                  cursor: gen ? "default" : "pointer",
                  fontFamily: SANS,
                }}
              >
                {gen ? "…" : "Generate"}
              </button>
            ) : (
              <button
                onClick={copy}
                style={{
                  padding: "7px 14px",
                  fontSize: 12,
                  fontWeight: 700,
                  background: "#FFFFFF",
                  color: COLOURS.ink,
                  border: `1px solid ${COLOURS.gold}`,
                  borderRadius: 4,
                  cursor: "pointer",
                  fontFamily: SANS,
                }}
              >
                {copied ? "Copied" : "Copy"}
              </button>
            )}
          </div>
          <div style={{ fontSize: 11, color: COLOURS.muted, marginTop: 6 }}>
            Anyone with the link can view. No editing, no watches.
          </div>
        </Group>

        <Group title="Exports">
          <div style={{ display: "flex", gap: 8 }}>
            <ExportBtn onClick={() => download("pdf")} label="PDF" />
            <ExportBtn onClick={() => download("csv")} label="CSV" />
            <ExportBtn onClick={() => download("json")} label="JSON" />
          </div>
        </Group>
      </ModalFrame>
    </Overlay>
  );
}

function ExportBtn({ onClick, label }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "7px 14px",
        fontSize: 12,
        fontWeight: 600,
        background: "#FFFFFF",
        color: COLOURS.ink,
        border: `1px solid ${COLOURS.border}`,
        borderRadius: 4,
        cursor: "pointer",
        fontFamily: SANS,
      }}
    >
      {label}
    </button>
  );
}
