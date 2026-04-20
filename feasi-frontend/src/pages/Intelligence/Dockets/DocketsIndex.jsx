import React, { useMemo, useState } from "react";
import { COLOURS, SANS, CASE_TYPE_CHIP } from "./tokens";
import DocketLibrary from "./DocketLibrary";
import DocketCardGrid from "./DocketCardGrid";
import DocketDetail from "./DocketDetail";
import CreateCustomDocketModal from "./CreateCustomDocketModal";
import { useDocketList } from "../../../hooks/useDocket";
import api from "../../../api/dockets";

/**
 * /intelligence/dockets — three-column shell.
 *
 *   ┌──────────────────────────────────────────────────────────────┐
 *   │  Library (320)    │  Card Grid (fluid)    │  Preview (360)    │
 *   │                   │                       │                   │
 *   └──────────────────────────────────────────────────────────────┘
 *
 *  - Clicking a card selects it: the 360-preview shows a lightweight
 *    summary + "Open docket" CTA.
 *  - "Open docket" expands into the full DocketDetail view as an
 *    overlay inside the same tab.
 */
export default function DocketsIndex() {
  const [filters, setFilters] = useState({});
  const [savedView, setSavedView] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [fullDetail, setFullDetail] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);

  const { rows, loading, refetch } = useDocketList(filters);

  const dockets = useMemo(() => {
    if (!savedView) return rows;
    if (savedView === "watched")      return rows.filter((d) => d.watched);
    if (savedView === "pinned")       return rows.filter((d) => d.pinned);
    if (savedView === "next14") {
      return rows.filter((d) => {
        const left = d.next_deadline?.days_left;
        return left != null && left <= 14;
      });
    }
    if (savedView === "nsip_in_exam") {
      return rows.filter((d) => d.case_type === "NSIP_DCO" && d.stage === "Examination");
    }
    return rows;
  }, [rows, savedView]);

  const selected = dockets.find((d) => d.id === selectedId) || null;

  const togglePin = async (d) => {
    if (d.pinned) await api.unpinDocket(d.id);
    else await api.pinDocket(d.id);
    refetch();
  };
  const toggleWatch = async (d) => {
    if (d.watched) await api.unwatchDocket(d.id);
    else await api.watchDocket(d.id, { cadence: "daily" });
    refetch();
  };

  // ── Full detail overlay within the tab ─────────────────────
  if (fullDetail) {
    return (
      <DocketDetail
        id={fullDetail}
        onClose={() => {
          setFullDetail(null);
          refetch();
        }}
      />
    );
  }

  return (
    <div
      style={{
        display: "flex",
        width: "100%",
        height: "100%",
        background: COLOURS.bg,
        fontFamily: SANS,
        overflow: "hidden",
      }}
    >
      <DocketLibrary
        filters={filters}
        onChange={(f) => {
          setFilters(f);
          setSavedView(null);
        }}
        onSavedView={(id) => {
          setSavedView((curr) => (curr === id ? null : id));
        }}
        onCreate={() => setCreateOpen(true)}
      />

      <DocketCardGrid
        dockets={dockets}
        loading={loading}
        selectedId={selectedId}
        onSelect={(d) => setSelectedId(d.id)}
        onTogglePin={togglePin}
        onToggleWatch={toggleWatch}
      />

      <PreviewPane
        docket={selected}
        onOpen={() => selected && setFullDetail(selected.id)}
      />

      <CreateCustomDocketModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => refetch()}
      />
    </div>
  );
}

// ── Right-hand preview (360 px) ────────────────────────────────
function PreviewPane({ docket, onOpen }) {
  if (!docket) {
    return (
      <aside
        style={{
          width: 360,
          minWidth: 360,
          borderLeft: `1px solid ${COLOURS.border}`,
          background: "#FFFFFF",
          padding: 20,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: COLOURS.muted,
          fontSize: 13,
          textAlign: "center",
        }}
      >
        Select a docket to preview.
      </aside>
    );
  }

  const chip = CASE_TYPE_CHIP[docket.case_type] || CASE_TYPE_CHIP.LPA_PLANNING;

  return (
    <aside
      style={{
        width: 360,
        minWidth: 360,
        borderLeft: `1px solid ${COLOURS.border}`,
        background: "#FFFFFF",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div style={{ padding: "16px 20px", borderBottom: `1px solid ${COLOURS.border}` }}>
        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <span
            style={{
              padding: "3px 8px",
              fontSize: 10.5,
              fontWeight: 600,
              color: chip.fg,
              background: chip.bg,
              border: `1px solid ${chip.border}`,
              borderRadius: 4,
              letterSpacing: 0.3,
              textTransform: "uppercase",
            }}
          >
            {chip.label}
          </span>
        </div>
        <div style={{ fontSize: 11, color: COLOURS.muted, marginBottom: 2 }}>
          {docket.docket_number}
        </div>
        <div style={{ fontSize: 17, fontWeight: 700, color: COLOURS.ink, lineHeight: 1.3 }}>
          {docket.title}
        </div>
        <div style={{ fontSize: 12, color: COLOURS.muted, marginTop: 4 }}>
          {docket.publisher} · {docket.applicant}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "14px 20px", display: "flex", flexDirection: "column", gap: 14 }}>
        <PreviewField label="Site" value={docket.site} />
        <PreviewField label="Stage" value={docket.stage} />
        {docket.capacity_mw != null && <PreviewField label="Capacity" value={`${docket.capacity_mw} MW`} />}
        <PreviewField
          label="Next deadline"
          value={
            docket.next_deadline
              ? `${docket.next_deadline.label} · ${docket.next_deadline.date}`
              : "—"
          }
        />
        <PreviewField
          label="Stakeholders / documents"
          value={`${docket.n_stakeholders} · ${docket.n_documents}`}
        />

        <div>
          <div style={{ fontSize: 10.5, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6, fontWeight: 600 }}>
            Summary
          </div>
          <p style={{ margin: 0, fontSize: 12.5, color: COLOURS.ink, lineHeight: 1.5 }}>
            {docket.summary}
          </p>
        </div>
      </div>

      <div style={{ padding: "12px 20px", borderTop: `1px solid ${COLOURS.border}` }}>
        <button
          onClick={onOpen}
          style={{
            width: "100%",
            padding: "10px 14px",
            fontSize: 13,
            fontWeight: 700,
            background: COLOURS.gold,
            color: COLOURS.ink,
            border: `1px solid ${COLOURS.gold}`,
            borderRadius: 6,
            cursor: "pointer",
            fontFamily: SANS,
          }}
        >
          Open docket →
        </button>
      </div>
    </aside>
  );
}

function PreviewField({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 12.5, color: COLOURS.ink }}>{value || "—"}</div>
    </div>
  );
}
