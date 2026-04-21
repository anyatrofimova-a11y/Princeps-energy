/**
 * Princeps 3D Twin — Onboarding
 * ----------------------------------------------------------------------
 * Three dismissable cards sequenced on first load. Persists the seen
 * flag to `localStorage.princeps.twinOnboardingSeen`. Skippable at any
 * point.
 *
 * Cards:
 *   1. Orbit / zoom controls
 *   2. Click any asset for spec
 *   3. Press E to export GA
 *
 * Renders nothing once dismissed. Shell re-shows on a fresh install.
 */

import React, { useState, useEffect } from 'react';

const GOLD = '#F5B731';
const IVORY = '#FBF8F2';
const INK = '#0F1318';
const MUTED = '#6B7280';
const BORDER = 'rgba(15, 19, 24, 0.08)';

const STORAGE_KEY = 'princeps.twinOnboardingSeen';

const CARDS = [
  {
    key: 'controls',
    title: 'Navigate the twin',
    body: (
      <>
        <Row>Orbit</Row>
        <Row>Left-drag on the canvas.</Row>
        <Row>Pan</Row>
        <Row>Right-drag or Shift + left-drag.</Row>
        <Row>Zoom</Row>
        <Row>Scroll wheel or pinch.</Row>
      </>
    ),
  },
  {
    key: 'select',
    title: 'Inspect any asset',
    body: (
      <>
        <Row>Click a Megapack, inverter, or pylon to open the spec drawer.</Row>
        <Row>It carries spec, cost, install, and compliance in four tabs.</Row>
      </>
    ),
  },
  {
    key: 'export',
    title: 'Export a GA drawing',
    body: (
      <>
        <Row>Press <Kbd>E</Kbd> at any time to download a general-arrangement PDF of the current view.</Row>
        <Row>Use the left toolbar for measure, annotate, section, and sun study.</Row>
      </>
    ),
  },
];

function hasSeen() {
  if (typeof window === 'undefined') return true;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function markSeen() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, 'true');
  } catch {}
}

export default function Onboarding({ forceShow }) {
  const [visible, setVisible] = useState(() => (forceShow ? true : !hasSeen()));
  const [index, setIndex] = useState(0);

  // Allow the app shell to replay onboarding by dispatching this event.
  useEffect(() => {
    const handler = () => {
      setIndex(0);
      setVisible(true);
    };
    window.addEventListener('princeps:twin:replayOnboarding', handler);
    return () => window.removeEventListener('princeps:twin:replayOnboarding', handler);
  }, []);

  const finish = () => {
    markSeen();
    setVisible(false);
  };

  const next = () => {
    if (index >= CARDS.length - 1) {
      finish();
      return;
    }
    setIndex((i) => i + 1);
  };

  if (!visible) return null;

  const card = CARDS[index];
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="twin-onboarding-title"
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(15, 19, 24, 0.32)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
        fontFamily: "'DM Sans', system-ui, sans-serif",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) finish(); }}
    >
      <div
        style={{
          width: 360,
          background: IVORY,
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
          boxShadow: '0 8px 32px rgba(15, 19, 24, 0.24)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '14px 18px 10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: MUTED, fontSize: 10, letterSpacing: 1, textTransform: 'uppercase' }}>
            <span>Princeps 3D</span>
            <span>{'\u00B7'}</span>
            <span style={{ fontFamily: "'JetBrains Mono', ui-monospace, monospace" }}>
              {index + 1} / {CARDS.length}
            </span>
          </div>
          <button
            aria-label="Skip"
            onClick={finish}
            style={{
              border: 'none',
              background: 'transparent',
              cursor: 'pointer',
              fontSize: 11,
              color: MUTED,
            }}
          >
            Skip
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '0 18px 18px', color: INK }}>
          <h3
            id="twin-onboarding-title"
            style={{ margin: 0, fontSize: 16, fontWeight: 600, marginBottom: 10 }}
          >
            {card.title}
          </h3>
          <div style={{ fontSize: 12, lineHeight: 1.6, color: INK }}>{card.body}</div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: 14,
            borderTop: `1px solid ${BORDER}`,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          {CARDS.map((_, i) => (
            <span
              key={i}
              style={{
                width: i === index ? 18 : 6,
                height: 6,
                borderRadius: 3,
                background: i === index ? GOLD : 'rgba(15,19,24,0.15)',
                transition: 'width 180ms, background 180ms',
              }}
            />
          ))}
          <div style={{ flex: 1 }} />
          <button
            onClick={next}
            style={{
              height: 32,
              padding: '0 14px',
              borderRadius: 999,
              border: 'none',
              cursor: 'pointer',
              background: GOLD,
              color: INK,
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "'DM Sans', system-ui, sans-serif",
            }}
          >
            {index >= CARDS.length - 1 ? 'Start exploring' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ children }) {
  return (
    <div style={{ marginBottom: 6 }}>{children}</div>
  );
}

function Kbd({ children }) {
  return (
    <kbd
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: 4,
        border: `1px solid ${BORDER}`,
        background: '#FFFFFF',
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 10,
        color: INK,
      }}
    >
      {children}
    </kbd>
  );
}
