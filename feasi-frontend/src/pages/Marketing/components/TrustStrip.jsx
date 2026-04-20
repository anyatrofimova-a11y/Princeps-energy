import React from "react";
import styles from "../TrackerLanding.module.css";

/**
 * TrustStrip — compliance + provenance pills for footer placement.
 * Honest wording: ISO 27001 is in-progress, not certified.
 */
const BADGES = [
  { label: "ISO 27001 — in progress" },
  { label: "GDPR compliant" },
  { label: "Based in London" },
  { label: "Source-cited at the row level" },
];

export default function TrustStrip() {
  return (
    <section className={styles.trustStrip} aria-label="Trust and compliance">
      <div className={styles.trustInner}>
        {BADGES.map((b) => (
          <span key={b.label} className={styles.trustBadge}>
            <span className={styles.trustBadgeDot} aria-hidden="true" />
            {b.label}
          </span>
        ))}
      </div>
    </section>
  );
}
