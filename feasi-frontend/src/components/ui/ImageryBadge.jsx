import React from "react";

export default function ImageryBadge({ text = "detected from imagery" }) {
  return (
    <span className="imagery-badge">
      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" style={{ marginRight: 4, flexShrink: 0 }}>
        <path d="M8 1C4.7 1 2 3.7 2 7c0 1.5.6 2.9 1.5 4L8 15l4.5-4C13.4 9.9 14 8.5 14 7c0-3.3-2.7-6-6-6z" fill="none" stroke="currentColor" strokeWidth="1.5"/>
        <circle cx="8" cy="7" r="2.5" fill="none" stroke="currentColor" strokeWidth="1.5"/>
      </svg>
      {text}
    </span>
  );
}
