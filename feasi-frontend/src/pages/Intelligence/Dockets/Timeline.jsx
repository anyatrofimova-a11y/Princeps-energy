import React, { useMemo } from "react";
import { COLOURS, MONO, SANS, formatDate, countdownStyle, daysFromNow } from "./tokens";

// Vertical spine timeline — upper forward, lower past.
export default function Timeline({ events = [], docket }) {
  const sorted = useMemo(() => {
    const copy = [...events];
    copy.sort((a, b) => new Date(a.date) - new Date(b.date));
    return copy;
  }, [events]);

  const upcoming = sorted.filter((e) => e.type === "upcoming");
  const past = sorted.filter((e) => e.type !== "upcoming");

  const exportICS = () => {
    const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Princeps//Dockets//EN"];
    for (const e of upcoming) {
      const d = new Date(e.date);
      const dtStart =
        d.getUTCFullYear().toString() +
        String(d.getUTCMonth() + 1).padStart(2, "0") +
        String(d.getUTCDate()).padStart(2, "0");
      lines.push(
        "BEGIN:VEVENT",
        `UID:${e.id}@princeps.app`,
        `DTSTAMP:${dtStart}T000000Z`,
        `DTSTART;VALUE=DATE:${dtStart}`,
        `SUMMARY:[${docket?.docket_number || ""}] ${e.label}`,
        `DESCRIPTION:${docket?.title || ""} — stage ${e.stage}`,
        "END:VEVENT"
      );
    }
    lines.push("END:VCALENDAR");
    const blob = new Blob([lines.join("\r\n")], { type: "text/calendar" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${docket?.docket_number || "docket"}.ics`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const addToGantt = () => {
    // Dispatch an app-level event; the pipeline/Gantt view can listen.
    window.dispatchEvent(
      new CustomEvent("princeps-add-to-gantt", {
        detail: { docket_id: docket?.id, events: upcoming },
      })
    );
  };

  return (
    <section
      style={{
        background: "#FFFFFF",
        border: `1px solid ${COLOURS.border}`,
        borderRadius: 8,
        padding: 20,
        fontFamily: SANS,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: COLOURS.ink, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Timeline
        </h3>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={exportICS}
            style={{
              padding: "5px 10px",
              fontSize: 11.5,
              fontWeight: 600,
              border: `1px solid ${COLOURS.border}`,
              background: "#FFFFFF",
              color: COLOURS.ink,
              borderRadius: 4,
              cursor: "pointer",
              fontFamily: SANS,
            }}
          >
            Export .ics
          </button>
          <button
            onClick={addToGantt}
            style={{
              padding: "5px 10px",
              fontSize: 11.5,
              fontWeight: 600,
              border: `1px solid ${COLOURS.gold}`,
              background: "#FFFFFF",
              color: COLOURS.ink,
              borderRadius: 4,
              cursor: "pointer",
              fontFamily: SANS,
            }}
          >
            Add to project Gantt
          </button>
        </div>
      </div>

      <div style={{ position: "relative", paddingLeft: 20 }}>
        <div
          style={{
            position: "absolute",
            left: 8,
            top: 0,
            bottom: 0,
            width: 2,
            background: `linear-gradient(${COLOURS.gold} 0 ${upcomingFraction(upcoming, past) * 100}%, ${COLOURS.border} ${upcomingFraction(upcoming, past) * 100}% 100%)`,
          }}
        />

        {/* Upper — forward-looking (deadlines) */}
        {upcoming.length > 0 && (
          <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 10.5, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
              Upcoming
            </div>
            {upcoming.map((e) => (
              <TimelineRow key={e.id} event={e} mode="upcoming" />
            ))}
          </div>
        )}

        {/* Lower — past */}
        <div>
          <div style={{ fontSize: 10.5, color: COLOURS.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8 }}>
            Past events
          </div>
          {past
            .slice()
            .reverse()
            .map((e) => (
              <TimelineRow key={e.id} event={e} mode="past" />
            ))}
        </div>
      </div>
    </section>
  );
}

function upcomingFraction(upcoming, past) {
  const total = upcoming.length + past.length;
  if (total === 0) return 0;
  return upcoming.length / total;
}

function TimelineRow({ event, mode }) {
  const dLeft = mode === "upcoming" ? daysFromNow(event.date) : null;
  const cd = mode === "upcoming" ? countdownStyle(dLeft) : null;

  return (
    <div style={{ position: "relative", display: "flex", alignItems: "flex-start", gap: 12, padding: "8px 0" }}>
      <div
        style={{
          position: "absolute",
          left: -16,
          top: 12,
          width: 10,
          height: 10,
          borderRadius: "50%",
          background: mode === "upcoming" ? COLOURS.gold : COLOURS.ivory,
          border: `2px solid ${mode === "upcoming" ? COLOURS.gold : COLOURS.border}`,
        }}
      />
      <div style={{ fontFamily: MONO, fontSize: 11, color: COLOURS.muted, width: 96, flexShrink: 0 }}>
        {formatDate(event.date)}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: mode === "upcoming" ? 600 : 500, color: COLOURS.ink }}>
          {event.label}
        </div>
        <div style={{ fontSize: 11, color: COLOURS.muted, marginTop: 2 }}>{event.stage}</div>
      </div>
      {cd && dLeft != null && (
        <span
          style={{
            padding: "2px 8px",
            fontFamily: MONO,
            fontSize: 10.5,
            fontWeight: 700,
            color: cd.fg,
            background: cd.bg,
            border: `1.5px solid ${cd.border}`,
            borderRadius: 10,
            boxShadow: cd.boxShadow || "none",
            animation: cd.animation || "none",
            flexShrink: 0,
          }}
        >
          {dLeft > 0 ? `${dLeft}d` : dLeft === 0 ? "today" : `${-dLeft}d past`}
        </span>
      )}
    </div>
  );
}
