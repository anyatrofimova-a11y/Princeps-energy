import React from "react";
import styles from "../TrackerLanding.module.css";

/**
 * PillarCard — one of three product pillars (Track · Forecast · Benchmark).
 * One verb per card, one CTA per card.
 *
 * Props
 * - verb: string                    — the single-word verb headline
 * - body: string                    — one sentence
 * - ctaLabel: string                — CTA text, e.g. "See the dataset"
 * - onCtaClick: () => void          — click handler (usually opens demo modal)
 */
export default function PillarCard({ verb, body, ctaLabel, onCtaClick }) {
  return (
    <div className={styles.pillar}>
      <h3 className={styles.pillarVerb}>{verb}</h3>
      <p className={styles.pillarBody}>{body}</p>
      <button type="button" className={styles.pillarCta} onClick={onCtaClick}>
        {ctaLabel}
        <span aria-hidden="true">→</span>
      </button>
    </div>
  );
}
