import React from "react";
import styles from "../TrackerLanding.module.css";

/**
 * PersonaCard — one buyer persona (icon + title + 1-line pitch).
 *
 * Icons are rendered as short text glyphs (2 letters) in the repo's existing
 * logo-less style; swap for SVG later if design supplies a glyph set.
 *
 * Props
 * - icon: string           — 1-2 char glyph
 * - title: string          — persona name
 * - pitch: string          — one-line value pitch
 */
export default function PersonaCard({ icon, title, pitch }) {
  return (
    <article className={styles.persona}>
      <div className={styles.personaIcon} aria-hidden="true">{icon}</div>
      <h4 className={styles.personaTitle}>{title}</h4>
      <p className={styles.personaPitch}>{pitch}</p>
    </article>
  );
}
