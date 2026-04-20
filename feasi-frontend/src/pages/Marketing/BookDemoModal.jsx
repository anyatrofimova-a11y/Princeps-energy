import React, { useEffect, useRef, useState } from "react";
import styles from "./TrackerLanding.module.css";

/**
 * BookDemoModal — Cal.com iframe embed + email-fallback form.
 *
 * Behaviour
 * - Prefers iframe embed of Cal.com booking page (https://cal.com/princeps/demo).
 * - If the iframe fails to load within 6s, falls back to an email form that
 *   POSTs to /api/marketing/demo-request. The endpoint is not yet live; in
 *   development the submit handler logs to console and resolves optimistically.
 * - ESC key and backdrop click both close the modal.
 *
 * Props
 * - open: boolean
 * - onClose: () => void
 * - reason?: string    — optional context string ("track" | "forecast" | ...)
 */
const CAL_URL = "https://cal.com/princeps/demo"; // placeholder — replace when Cal handle is live.
const IFRAME_TIMEOUT_MS = 6000;

export default function BookDemoModal({ open, onClose, reason }) {
  const [iframeReady, setIframeReady] = useState(false);
  const [iframeFailed, setIframeFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [note, setNote] = useState("");
  const backdropRef = useRef(null);

  // Reset state when re-opened
  useEffect(() => {
    if (!open) return;
    setIframeReady(false);
    setIframeFailed(false);
    setSubmitted(false);
    const timer = setTimeout(() => {
      if (!iframeReady) setIframeFailed(true);
    }, IFRAME_TIMEOUT_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  const onBackdrop = (e) => {
    if (e.target === backdropRef.current) onClose?.();
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    const payload = {
      email,
      company,
      note,
      reason: reason || "tracker_landing",
      source: "marketing/tracker",
      ts: new Date().toISOString(),
    };
    try {
      // POST stub — /api/marketing/demo-request is not yet live. In dev the
      // request will 404; we still resolve the UI optimistically.
      await fetch("/api/marketing/demo-request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => { /* intentionally ignore; endpoint may be absent */ });
      // eslint-disable-next-line no-console
      console.log("[Princeps] demo request (stub)", payload);
      setSubmitted(true);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      ref={backdropRef}
      className={styles.modalBackdrop}
      onClick={onBackdrop}
      role="dialog"
      aria-modal="true"
      aria-label="Book a demo"
    >
      <div className={styles.modal}>
        <div className={styles.modalHeader}>
          <h3 className={styles.modalTitle}>Book a demo</h3>
          <button
            type="button"
            className={styles.modalClose}
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className={styles.modalBody}>
          {submitted ? (
            <div className={styles.modalSuccess}>
              <h4 className={styles.modalSuccessTitle}>Request received.</h4>
              <p className={styles.modalSuccessBody}>
                A Princeps engineer will reply within 1 UK business day with slots.
              </p>
              <button type="button" className={`${styles.btn} ${styles.btnSecondary}`} onClick={onClose}>
                Close
              </button>
            </div>
          ) : iframeFailed ? (
            <form className={styles.modalFallback} onSubmit={onSubmit}>
              <p>
                Calendar isn't loading — leave an email and we'll send slots directly.
              </p>
              <label htmlFor="demo-email">Work email</label>
              <input
                id="demo-email"
                className={styles.modalInput}
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
              />
              <label htmlFor="demo-company">Company</label>
              <input
                id="demo-company"
                className={styles.modalInput}
                type="text"
                value={company}
                onChange={(e) => setCompany(e.target.value)}
                placeholder="e.g. UKPN, Octopus Energy, Google"
              />
              <label htmlFor="demo-note">What do you want to see?</label>
              <textarea
                id="demo-note"
                className={`${styles.modalInput} ${styles.modalTextarea}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. 400 kV switching stations in East Anglia, RIIO-ED2 forecast uplift…"
              />
              <button
                type="submit"
                className={`${styles.btn} ${styles.btnPrimary} ${styles.modalSubmit}`}
                disabled={submitting}
              >
                {submitting ? "Sending…" : "Request slots"}
              </button>
            </form>
          ) : (
            <iframe
              title="Princeps demo booking"
              className={styles.modalIframe}
              src={CAL_URL}
              onLoad={() => setIframeReady(true)}
              onError={() => setIframeFailed(true)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
