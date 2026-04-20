import React from "react";

const C = {
  gold: "#F5B731",
  goldDark: "#B5912F",
  goldSoft: "#C9A64B",
  goldSurface: "rgba(245,183,49,0.10)",
  goldBorder: "rgba(245,183,49,0.32)",
  ink: "#0F1318",
  secondary: "#4B5563",
  tertiary: "#9C9590",
  border: "#E8EAED",
  ivory: "#FBF8F2",
};

// Placeholder Stripe checkout URLs — wire up real price IDs later.
const TIERS = [
  {
    id: "individual",
    name: "Individual",
    price: "£79",
    cadence: "/ month",
    tagline: "For solo developers and consultants",
    features: [
      "Unlimited alert subscriptions",
      "Daily + weekly digests",
      "Ask across all documents",
      "Pin to 5 projects",
    ],
    cta: "Start Individual",
    checkoutUrl: "https://buy.stripe.com/princeps_individual_placeholder",
  },
  {
    id: "team",
    name: "Team",
    price: "£299",
    cadence: "/ month",
    tagline: "5 seats, shared starter packs",
    features: [
      "Everything in Individual",
      "5 seats, shared subscriptions",
      "Slack + email digests",
      "Pin to unlimited projects",
      "Basic API access",
    ],
    cta: "Start Team",
    featured: true,
    checkoutUrl: "https://buy.stripe.com/princeps_team_placeholder",
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "£1,500",
    cadence: "/ month",
    tagline: "DNOs, consultancies, asset owners",
    features: [
      "Everything in Team",
      "Unlimited seats",
      "SSO + audit log",
      "Priority corpus refresh",
      "Dedicated success manager",
    ],
    cta: "Contact sales",
    checkoutUrl: "https://buy.stripe.com/princeps_enterprise_placeholder",
  },
];

function Tier({ tier }) {
  const featured = tier.featured;
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        padding: "16px 16px 18px",
        borderRadius: 10,
        border: `1px solid ${featured ? C.goldBorder : C.border}`,
        background: featured ? C.goldSurface : "#FFFFFF",
        position: "relative",
        display: "flex", flexDirection: "column", gap: 10,
      }}
    >
      {featured && (
        <div
          style={{
            position: "absolute", top: -10, left: 16,
            padding: "2px 8px",
            background: C.gold,
            color: C.ink,
            fontSize: 9, fontWeight: 800,
            fontFamily: "'JetBrains Mono', monospace",
            letterSpacing: "0.08em",
            borderRadius: 4,
          }}
        >
          MOST POPULAR
        </div>
      )}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.ink }}>{tier.name}</div>
        <div style={{ fontSize: 11, color: C.secondary, lineHeight: 1.4, marginTop: 2 }}>
          {tier.tagline}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
        <span style={{
          fontSize: 24, fontWeight: 800, color: C.ink, letterSpacing: "-0.02em",
        }}>
          {tier.price}
        </span>
        <span style={{ fontSize: 11, color: C.tertiary }}>{tier.cadence}</span>
      </div>

      <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 5 }}>
        {tier.features.map((f) => (
          <li
            key={f}
            style={{
              display: "flex", gap: 6, fontSize: 12, color: C.secondary, lineHeight: 1.5,
            }}
          >
            <span style={{ color: C.goldDark, flexShrink: 0 }}>✓</span>
            {f}
          </li>
        ))}
      </ul>

      <a
        href={tier.checkoutUrl}
        target="_blank"
        rel="noreferrer"
        style={{
          marginTop: "auto",
          display: "inline-flex",
          alignItems: "center", justifyContent: "center",
          padding: "8px 12px",
          fontSize: 12, fontWeight: 700,
          borderRadius: 6,
          border: featured ? "none" : `1px solid ${C.border}`,
          background: featured ? C.gold : "#FFFFFF",
          color: featured ? C.ink : C.ink,
          textDecoration: "none",
          fontFamily: "'DM Sans', sans-serif",
        }}
      >
        {tier.cta}
      </a>
    </div>
  );
}

export default function PaywallModal({ onClose }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15,19,24,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 1000,
        fontFamily: "'DM Sans', sans-serif",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(860px, 94vw)",
          maxHeight: "92vh",
          background: C.ivory,
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          boxShadow: "0 20px 60px rgba(15,19,24,0.25)",
          display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "20px 24px 16px",
          borderBottom: `1px solid ${C.border}`,
          background: "#FFFFFF",
          display: "flex", alignItems: "flex-start", gap: 16,
        }}>
          <div style={{ flex: 1 }}>
            <div style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 10, fontWeight: 700, color: C.goldSoft,
              letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4,
            }}>
              Upgrade required
            </div>
            <h3 style={{
              margin: "0 0 4px",
              fontSize: 18, fontWeight: 800, color: C.ink, letterSpacing: "-0.02em",
            }}>
              You've hit the free tier — 5 alerts
            </h3>
            <p style={{
              margin: 0, fontSize: 13, lineHeight: 1.5, color: C.secondary, maxWidth: 520,
            }}>
              Upgrade for unlimited subscriptions, cross-document queries, and pin-to-project. Cancel anytime.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: 28, height: 28, borderRadius: 6,
              border: `1px solid ${C.border}`,
              background: "#FFFFFF", color: C.tertiary,
              cursor: "pointer", fontSize: 14, lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        {/* Tier grid */}
        <div style={{
          flex: 1, overflowY: "auto",
          padding: 24,
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 14,
        }}>
          {TIERS.map((t) => <Tier key={t.id} tier={t} />)}
        </div>

        {/* Footer */}
        <div style={{
          padding: "12px 24px",
          borderTop: `1px solid ${C.border}`,
          background: "#FFFFFF",
          fontSize: 11, color: C.tertiary,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span>Secure checkout via Stripe · GBP · VAT added at checkout</span>
          <button
            onClick={onClose}
            style={{
              padding: "4px 10px",
              fontSize: 11, fontWeight: 600,
              border: `1px solid ${C.border}`,
              background: "#FFFFFF", color: C.secondary,
              borderRadius: 6, cursor: "pointer",
            }}
          >
            Continue free
          </button>
        </div>
      </div>
    </div>
  );
}
