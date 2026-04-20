import React from "react";
import styles from "../TrackerLanding.module.css";

/**
 * HeroTriplicate — Brickanta-style animated hero.
 *
 * Renders three staggered, bold lines. Exactly one word in the triplicate can
 * carry a gold underline accent (pass `accentIndex` as a [lineIdx, wordIdx]
 * tuple; defaults to line 0, first word).
 *
 * Props
 * - lines: [string, string, string]              — three verbs / phrases
 * - accent: { line: number, word: number }       — which word to underline
 */
export default function HeroTriplicate({
  lines = ["Track.", "Forecast.", "Benchmark."],
  accent = { line: 0, word: 0 },
}) {
  return (
    <div className={styles.triplicate} aria-label={lines.join(" ")}>
      {lines.slice(0, 3).map((line, lineIdx) => {
        const words = line.split(" ");
        return (
          <div key={lineIdx} className={styles.triplicateLine}>
            {words.map((word, wordIdx) => {
              const isAccent = lineIdx === accent.line && wordIdx === accent.word;
              return (
                <React.Fragment key={wordIdx}>
                  {isAccent ? <em>{word}</em> : word}
                  {wordIdx < words.length - 1 ? " " : ""}
                </React.Fragment>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}
