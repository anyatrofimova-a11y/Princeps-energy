import React from "react";

/**
 * Octopus Energy-inspired half-hourly price grid.
 * Rows = dates, 48 columns = half-hour slots.
 * Color-coded: green (<10p) -> yellow (10-20p) -> orange (20-30p) -> red (>30p) -> dark red (>50p)
 */
function priceClass(p) {
  if (p == null) return "";
  if (p < 0) return "negative";
  if (p < 10) return "cheap";
  if (p < 20) return "moderate";
  if (p < 30) return "expensive";
  return "peak";
}

function isCurrent(dateStr, slot) {
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  if (dateStr !== today) return false;
  const currentSlot = now.getHours() * 2 + (now.getMinutes() >= 30 ? 1 : 0);
  return slot === currentSlot;
}

export default function AgileSlotGrid({ heatmap }) {
  if (!heatmap?.dates?.length || !heatmap?.grid?.length) return null;

  // Show hour labels every 4 slots (every 2 hours)
  const hourLabels = [];
  for (let i = 0; i < 48; i += 4) {
    hourLabels.push(`${String(Math.floor(i / 2)).padStart(2, "0")}`);
  }

  return (
    <div className="slot-grid-wrap">
      {heatmap.dates.map((date, di) => (
        <div key={date} className="slot-grid-row">
          <span className="slot-grid-label">{date.slice(5)}</span>
          <div className="slot-grid">
            {(heatmap.grid[di] || []).map((price, si) => (
              <div
                key={si}
                className={`slot-cell ${priceClass(price)} ${isCurrent(date, si) ? "current" : ""}`}
                title={`${date} ${String(Math.floor(si / 2)).padStart(2, "0")}:${si % 2 === 0 ? "00" : "30"} — ${price != null ? `${price}p/kWh` : "no data"}`}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="slot-grid-hours">
        {hourLabels.map((h, i) => (
          <span key={i} style={{ flex: 4 }}>{h}</span>
        ))}
      </div>
    </div>
  );
}
