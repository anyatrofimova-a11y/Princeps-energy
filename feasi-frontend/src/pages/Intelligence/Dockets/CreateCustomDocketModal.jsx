import React, { useState } from "react";
import { COLOURS, SANS } from "./tokens";
import api from "../../../api/dockets";
import { Overlay, ModalFrame, Group, Pill, Check } from "./WatchDocketModal";

// 3-step wizard: Basis → Seed → Automation.
export default function CreateCustomDocketModal({ open, onClose, onCreated }) {
  const [step, setStep] = useState(0);
  const [basis, setBasis] = useState({ name: "", visibility: "private" });
  const [seed, setSeed] = useState({ docs: "", stakeholders: "", geometry: "" });
  const [auto, setAuto] = useState({ auto_ingest: true, cadence: "daily" });
  const [saving, setSaving] = useState(false);

  if (!open) return null;

  const titles = ["Basis", "Seed", "Automation"];

  const submit = async () => {
    setSaving(true);
    const res = await api.createCustomDocket({
      ...basis,
      seed: {
        docs: seed.docs.split("\n").map((s) => s.trim()).filter(Boolean),
        stakeholders: seed.stakeholders.split("\n").map((s) => s.trim()).filter(Boolean),
        geometry: seed.geometry || null,
      },
      automation: auto,
    });
    setSaving(false);
    onCreated && onCreated(res);
    onClose && onClose();
  };

  return (
    <Overlay onClose={onClose}>
      <ModalFrame title="New custom docket" subtitle="3 steps — create a portfolio-specific intelligence feed" onClose={onClose}>
        {/* Stepper */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, paddingBottom: 10, borderBottom: `1px solid ${COLOURS.border}` }}>
          {titles.map((t, i) => (
            <React.Fragment key={t}>
              <div
                onClick={() => setStep(i)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  color: i === step ? COLOURS.ink : COLOURS.muted,
                  cursor: "pointer",
                }}
              >
                <span
                  style={{
                    width: 22,
                    height: 22,
                    borderRadius: 11,
                    background: i <= step ? COLOURS.gold : COLOURS.border,
                    color: COLOURS.ink,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 11,
                    fontWeight: 700,
                  }}
                >
                  {i + 1}
                </span>
                {t}
              </div>
              {i < titles.length - 1 && <div style={{ flex: 1, height: 1, background: COLOURS.border }} />}
            </React.Fragment>
          ))}
        </div>

        {step === 0 && (
          <>
            <Group title="Docket name">
              <input
                value={basis.name}
                onChange={(e) => setBasis({ ...basis, name: e.target.value })}
                placeholder="e.g. East of England solar + BESS cluster"
                style={inputStyle}
              />
            </Group>
            <Group title="Visibility">
              <div style={{ display: "flex", gap: 6 }}>
                {[
                  { v: "private", l: "Private" },
                  { v: "team",    l: "Team" },
                  { v: "workspace", l: "Workspace" },
                ].map((o) => (
                  <Pill key={o.v} active={basis.visibility === o.v} onClick={() => setBasis({ ...basis, visibility: o.v })}>
                    {o.l}
                  </Pill>
                ))}
              </div>
            </Group>
          </>
        )}

        {step === 1 && (
          <>
            <Group title="Seed documents (one URL per line)">
              <textarea
                value={seed.docs}
                onChange={(e) => setSeed({ ...seed, docs: e.target.value })}
                rows={4}
                placeholder="https://infrastructure.planninginspectorate.gov.uk/projects/…"
                style={{ ...inputStyle, resize: "vertical", fontFamily: SANS }}
              />
            </Group>
            <Group title="Seed stakeholders (one per line)">
              <textarea
                value={seed.stakeholders}
                onChange={(e) => setSeed({ ...seed, stakeholders: e.target.value })}
                rows={3}
                placeholder="NGET&#10;UK Power Networks&#10;Natural England"
                style={{ ...inputStyle, resize: "vertical", fontFamily: SANS }}
              />
            </Group>
            <Group title="Geometry (GeoJSON or postcode)">
              <input
                value={seed.geometry}
                onChange={(e) => setSeed({ ...seed, geometry: e.target.value })}
                placeholder="CB8 — or paste GeoJSON"
                style={inputStyle}
              />
            </Group>
          </>
        )}

        {step === 2 && (
          <>
            <Group title="Automation">
              <Check
                label="Auto-ingest new PINS / Ofgem / NESO / LPA publications"
                value={auto.auto_ingest}
                onChange={(v) => setAuto({ ...auto, auto_ingest: v })}
              />
            </Group>
            <Group title="Cadence">
              <div style={{ display: "flex", gap: 6 }}>
                {[
                  { v: "realtime", l: "Realtime" },
                  { v: "daily",    l: "Daily" },
                  { v: "weekly",   l: "Weekly" },
                ].map((o) => (
                  <Pill key={o.v} active={auto.cadence === o.v} onClick={() => setAuto({ ...auto, cadence: o.v })}>
                    {o.l}
                  </Pill>
                ))}
              </div>
            </Group>
          </>
        )}

        {/* Footer nav */}
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginTop: 12 }}>
          <button
            onClick={() => setStep(Math.max(0, step - 1))}
            disabled={step === 0}
            style={{
              padding: "7px 14px",
              fontSize: 12,
              fontWeight: 600,
              background: "#FFFFFF",
              color: step === 0 ? COLOURS.muted : COLOURS.ink,
              border: `1px solid ${COLOURS.border}`,
              borderRadius: 4,
              cursor: step === 0 ? "default" : "pointer",
              fontFamily: SANS,
            }}
          >
            Back
          </button>
          {step < 2 ? (
            <button
              onClick={() => setStep(step + 1)}
              disabled={step === 0 && !basis.name.trim()}
              style={{
                padding: "7px 14px",
                fontSize: 12,
                fontWeight: 700,
                background: COLOURS.gold,
                color: COLOURS.ink,
                border: `1px solid ${COLOURS.gold}`,
                borderRadius: 4,
                cursor: step === 0 && !basis.name.trim() ? "default" : "pointer",
                opacity: step === 0 && !basis.name.trim() ? 0.5 : 1,
                fontFamily: SANS,
              }}
            >
              Next
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={saving}
              style={{
                padding: "7px 14px",
                fontSize: 12,
                fontWeight: 700,
                background: COLOURS.gold,
                color: COLOURS.ink,
                border: `1px solid ${COLOURS.gold}`,
                borderRadius: 4,
                cursor: saving ? "default" : "pointer",
                fontFamily: SANS,
              }}
            >
              {saving ? "Creating…" : "Create docket"}
            </button>
          )}
        </div>
      </ModalFrame>
    </Overlay>
  );
}

const inputStyle = {
  width: "100%",
  padding: "8px 10px",
  border: `1px solid ${COLOURS.border}`,
  borderRadius: 4,
  fontSize: 13,
  outline: "none",
  fontFamily: SANS,
  color: COLOURS.ink,
};
