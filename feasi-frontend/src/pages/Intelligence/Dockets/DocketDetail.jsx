import React, { useState, useRef, useEffect } from "react";
import { COLOURS, SANS } from "./tokens";
import DocketHeader from "./DocketHeader";
import AtAGlanceBand from "./AtAGlanceBand";
import ExecutiveSummary from "./ExecutiveSummary";
import QuestionCards from "./QuestionCards";
import StakeholderGraph from "./StakeholderGraph";
import Timeline from "./Timeline";
import DocumentList from "./DocumentList";
import ConsulteePanel from "./ConsulteePanel";
import ExposureStrip from "./ExposureStrip";
import WatchDocketModal from "./WatchDocketModal";
import ShareDocketModal from "./ShareDocketModal";
import { useDocket } from "../../../hooks/useDocket";
import { useStakeholders } from "../../../hooks/useStakeholders";
import { useTimeline } from "../../../hooks/useTimeline";
import api from "../../../api/dockets";

const SECTIONS = [
  { id: "summary",     label: "Summary" },
  { id: "stakeholders", label: "Stakeholders" },
  { id: "timeline",    label: "Timeline" },
  { id: "documents",   label: "Documents" },
  { id: "consultees",  label: "Consultees" },
  { id: "exposure",    label: "Exposure" },
];

// The detail router / page-level container for a single docket.
// Accepts either a `docket` prop (already loaded) or an `id` (fetches).
export default function DocketDetail({ id, docket: docketProp, onClose }) {
  const { docket: loadedDocket, refetch } = useDocket(!docketProp ? id : null);
  const docket = docketProp || loadedDocket;

  const { stakeholders } = useStakeholders(docket?.id);
  const { events } = useTimeline(docket?.id);

  const [activeSection, setActiveSection] = useState("summary");
  const [stakeholderFilter, setStakeholderFilter] = useState(null);
  const [watchOpen, setWatchOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);

  const scrollerRef = useRef(null);
  const sectionRefs = useRef({});

  // Scroll-spy — highlights the section in view.
  useEffect(() => {
    const sc = scrollerRef.current;
    if (!sc) return;
    const handler = () => {
      for (const s of SECTIONS) {
        const el = sectionRefs.current[s.id];
        if (!el) continue;
        const rect = el.getBoundingClientRect();
        const scRect = sc.getBoundingClientRect();
        if (rect.top - scRect.top > 120) break;
        setActiveSection(s.id);
      }
    };
    sc.addEventListener("scroll", handler);
    return () => sc.removeEventListener("scroll", handler);
  }, [docket]);

  const scrollTo = (id) => {
    const el = sectionRefs.current[id];
    if (el && scrollerRef.current) {
      scrollerRef.current.scrollTo({ top: el.offsetTop - 100, behavior: "smooth" });
    }
  };

  const togglePin = async () => {
    if (!docket) return;
    if (docket.pinned) await api.unpinDocket(docket.id);
    else await api.pinDocket(docket.id);
    refetch && refetch();
  };

  const toggleWatch = () => {
    if (!docket) return;
    if (docket.watched) {
      api.unwatchDocket(docket.id).then(() => refetch && refetch());
    } else {
      setWatchOpen(true);
    }
  };

  if (!docket) {
    return (
      <div style={{ padding: 40, color: COLOURS.muted, fontSize: 13, fontFamily: SANS }}>
        Loading docket…
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: COLOURS.bg,
        fontFamily: SANS,
        overflow: "hidden",
      }}
    >
      {/* Back button */}
      {onClose && (
        <div style={{ background: "#FFFFFF", padding: "8px 16px", borderBottom: `1px solid ${COLOURS.border}` }}>
          <button
            onClick={onClose}
            style={{
              padding: "4px 10px",
              fontSize: 12,
              fontWeight: 600,
              border: "none",
              background: "transparent",
              color: COLOURS.muted,
              cursor: "pointer",
              fontFamily: SANS,
            }}
          >
            ← Back to library
          </button>
        </div>
      )}

      <DocketHeader docket={docket} onPin={togglePin} onWatch={toggleWatch} onShare={() => setShareOpen(true)} />

      {/* Sticky sub-nav */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 5,
          display: "flex",
          gap: 4,
          padding: "6px 24px",
          background: "#FFFFFF",
          borderBottom: `1px solid ${COLOURS.border}`,
          overflowX: "auto",
        }}
      >
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => scrollTo(s.id)}
            style={{
              padding: "6px 12px",
              fontSize: 12.5,
              fontWeight: activeSection === s.id ? 700 : 500,
              border: "none",
              background: "transparent",
              color: activeSection === s.id ? COLOURS.ink : COLOURS.muted,
              cursor: "pointer",
              borderBottom: `2px solid ${activeSection === s.id ? COLOURS.gold : "transparent"}`,
              borderRadius: 0,
              fontFamily: SANS,
              whiteSpace: "nowrap",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div ref={scrollerRef} style={{ flex: 1, overflowY: "auto", padding: "20px 24px 60px" }}>
        <div style={{ maxWidth: 1024, margin: "0 auto", display: "flex", flexDirection: "column", gap: 16 }}>
          {/* At-a-glance */}
          <div ref={(el) => (sectionRefs.current.summary = el)}>
            <AtAGlanceBand docket={docket} />
          </div>

          {docket.pinned && <ExposureStrip docket={docket} />}

          <ExecutiveSummary docket={docket} />

          <QuestionCards docket={docket} />

          <div ref={(el) => (sectionRefs.current.stakeholders = el)}>
            <StakeholderGraph
              stakeholders={stakeholders}
              onSelect={(s) => setStakeholderFilter(s)}
              selectedId={stakeholderFilter?.id}
            />
          </div>

          <div ref={(el) => (sectionRefs.current.timeline = el)}>
            <Timeline events={events} docket={docket} />
          </div>

          <div ref={(el) => (sectionRefs.current.documents = el)}>
            <DocumentList
              documents={docket.documents || []}
              filterByStakeholderName={stakeholderFilter?.name}
            />
            {stakeholderFilter && (
              <button
                onClick={() => setStakeholderFilter(null)}
                style={{
                  marginTop: 8,
                  padding: "4px 10px",
                  fontSize: 11,
                  fontWeight: 600,
                  background: "#FFFFFF",
                  color: COLOURS.muted,
                  border: `1px solid ${COLOURS.border}`,
                  borderRadius: 4,
                  cursor: "pointer",
                  fontFamily: SANS,
                }}
              >
                Clear stakeholder filter
              </button>
            )}
          </div>

          <div ref={(el) => (sectionRefs.current.consultees = el)}>
            <ConsulteePanel docket={docket} />
          </div>

          <div ref={(el) => (sectionRefs.current.exposure = el)}>
            {docket.pinned ? (
              <ExposureStrip docket={docket} />
            ) : (
              <div
                style={{
                  background: "#FFFFFF",
                  border: `1px dashed ${COLOURS.border}`,
                  borderRadius: 8,
                  padding: 24,
                  textAlign: "center",
                  color: COLOURS.muted,
                  fontSize: 13,
                }}
              >
                Pin a project to see exposure (distance, DNO overlap, timeline impact, ΔIRR / ΔNPV).
              </div>
            )}
          </div>
        </div>
      </div>

      <WatchDocketModal
        open={watchOpen}
        docket={docket}
        onClose={(saved) => {
          setWatchOpen(false);
          if (saved) refetch && refetch();
        }}
      />
      <ShareDocketModal open={shareOpen} docket={docket} onClose={() => setShareOpen(false)} />
    </div>
  );
}
