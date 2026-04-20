import React from "react";
import styles from "../TrackerLanding.module.css";

/**
 * OtherProductsRow — sibling data products teaser.
 *
 * The substations tracker is the first SKU in a family; this row signals
 * that the pipeline-level datasets (GB BESS, UK DC, AR7 allocation) are
 * on the same data spine. "Waitlist" status keeps expectations honest.
 */
const SIBLINGS = [
  {
    tag: "Dataset",
    title: "GB BESS Pipeline",
    pitch: "All grid-connected battery projects across GB: capacity, queue position, contracted TNUoS zone, revenue stack.",
    status: "Available Q3 2026",
  },
  {
    tag: "Dataset",
    title: "UK DC Pipeline",
    pitch: "Every permitted, planned and rumoured data centre in the UK with MW intent, water draw, cooling profile and operator.",
    status: "Available Q4 2026",
  },
  {
    tag: "Dataset",
    title: "AR7 Allocation Tracker",
    pitch: "CfD AR7 window (opens Jan 2026): strike price sweeps, budget pot split, delivery body metering, lot-level awards.",
    status: "Live",
  },
];

export default function OtherProductsRow() {
  return (
    <div className={styles.otherGrid}>
      {SIBLINGS.map((s) => (
        <article key={s.title} className={styles.otherCard}>
          <span className={styles.otherCardTag}>{s.tag}</span>
          <h3 className={styles.otherCardTitle}>{s.title}</h3>
          <p className={styles.otherCardPitch}>{s.pitch}</p>
          <span className={styles.otherCardStatus}>{s.status}</span>
        </article>
      ))}
    </div>
  );
}
