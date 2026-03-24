import React, { useState, useEffect, useCallback } from "react";

/**
 * UsageMeter — floating usage indicator + pricing modal for Princeps freemium.
 *
 * Bottom-left pill showing tier badge, usage bar, and upgrade CTA.
 * Minimisable. Pricing modal on "Upgrade" click.
 *
 * Brand: white pill, gold accent (#D4A018), JetBrains Mono for numbers.
 */

const API_BASE = "/api";

/* ── Tier config ─────────────────────────────────────────────────────────── */

const TIER_META = {
  free:         { label: "FREE",       color: "#8A857D", badge: "#F5F0E8" },
  professional: { label: "PRO",        color: "#D4A018", badge: "#FFF8E7" },
  enterprise:   { label: "ENTERPRISE", color: "#1A1A2E", badge: "#E8E8F0" },
};

const PRICING_TIERS = [
  {
    id: "free",
    name: "Free",
    price: "£0",
    period: "forever",
    color: "#8A857D",
    features: [
      "5 site assessments / month",
      "10 map views / month",
      "Basic grid data",
      "Community support",
    ],
    limits: [
      "No PDF exports",
      "No API access",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    price: "£500",
    period: "/ month",
    color: "#D4A018",
    popular: true,
    features: [
      "Unlimited assessments",
      "Unlimited map views",
      "50 PDF reports / month",
      "1,000 API calls / month",
      "All data layers",
      "Priority email support",
    ],
    limits: [],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "£5-10k",
    period: "/ month",
    color: "#1A1A2E",
    features: [
      "Everything in Professional",
      "Unlimited PDF & API",
      "MCP integration",
      "Custom data pipelines",
      "White-label option",
      "Dedicated account manager",
      "SLA & priority support",
    ],
    limits: [],
  },
];

/* ── Styles ──────────────────────────────────────────────────────────────── */

const styles = {
  /* Floating pill — bottom left */
  container: {
    position: "fixed",
    bottom: 20,
    left: 20,
    zIndex: 9000,
    fontFamily: "'Inter', -apple-system, sans-serif",
    userSelect: "none",
  },

  pill: {
    background: "#FFFFFF",
    borderRadius: 16,
    boxShadow: "0 2px 16px rgba(0,0,0,0.10), 0 0 0 1px rgba(0,0,0,0.04)",
    padding: "10px 16px",
    display: "flex",
    alignItems: "center",
    gap: 10,
    cursor: "pointer",
    transition: "box-shadow 0.2s, transform 0.15s",
    minWidth: 200,
  },

  pillMinimised: {
    background: "#FFFFFF",
    borderRadius: 12,
    boxShadow: "0 2px 12px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04)",
    padding: "6px 12px",
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
    transition: "box-shadow 0.2s, transform 0.15s",
  },

  badge: (bg, color) => ({
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 6,
    fontSize: 10,
    fontWeight: 700,
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    letterSpacing: "0.05em",
    background: bg,
    color: color,
    lineHeight: "16px",
    whiteSpace: "nowrap",
  }),

  usageSection: {
    flex: 1,
    minWidth: 0,
  },

  usageLabel: {
    fontSize: 11,
    color: "#6B6560",
    lineHeight: "14px",
    marginBottom: 4,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },

  usageNumbers: {
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    fontSize: 12,
    fontWeight: 600,
    color: "#2A2520",
  },

  barTrack: {
    height: 4,
    borderRadius: 2,
    background: "#F0EDE8",
    marginTop: 3,
    overflow: "hidden",
  },

  barFill: (pct, color) => ({
    height: "100%",
    borderRadius: 2,
    background: color,
    width: `${Math.min(100, pct)}%`,
    transition: "width 0.4s ease",
  }),

  upgradeBtn: {
    padding: "4px 10px",
    borderRadius: 8,
    border: "none",
    background: "linear-gradient(135deg, #D4A018 0%, #B8860B 100%)",
    color: "#FFF",
    fontSize: 10,
    fontWeight: 700,
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    letterSpacing: "0.04em",
    cursor: "pointer",
    whiteSpace: "nowrap",
    transition: "opacity 0.15s",
    lineHeight: "18px",
  },

  minimiseBtn: {
    background: "none",
    border: "none",
    color: "#C0BBB4",
    fontSize: 14,
    cursor: "pointer",
    padding: "0 0 0 4px",
    lineHeight: 1,
  },

  /* Pricing Modal */
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.45)",
    zIndex: 10000,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "'Inter', -apple-system, sans-serif",
  },

  modal: {
    background: "#FFFFFF",
    borderRadius: 20,
    boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
    maxWidth: 860,
    width: "92vw",
    maxHeight: "88vh",
    overflow: "auto",
    padding: "36px 32px 28px",
  },

  modalTitle: {
    textAlign: "center",
    fontSize: 22,
    fontWeight: 700,
    color: "#1A1A2E",
    marginBottom: 4,
  },

  modalSubtitle: {
    textAlign: "center",
    fontSize: 13,
    color: "#8A857D",
    marginBottom: 28,
  },

  tiersRow: {
    display: "flex",
    gap: 16,
    justifyContent: "center",
    flexWrap: "wrap",
  },

  tierCard: (color, popular) => ({
    flex: "1 1 240px",
    maxWidth: 280,
    border: popular ? `2px solid ${color}` : "1px solid #E8E4DE",
    borderRadius: 16,
    padding: "24px 20px",
    position: "relative",
    background: popular ? "#FFFDF7" : "#FFF",
    transition: "transform 0.15s, box-shadow 0.15s",
  }),

  popularTag: (color) => ({
    position: "absolute",
    top: -11,
    left: "50%",
    transform: "translateX(-50%)",
    background: color,
    color: "#FFF",
    fontSize: 10,
    fontWeight: 700,
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    padding: "2px 12px",
    borderRadius: 6,
    letterSpacing: "0.06em",
  }),

  tierName: (color) => ({
    fontSize: 16,
    fontWeight: 700,
    color: color,
    marginBottom: 4,
  }),

  tierPrice: {
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    fontSize: 28,
    fontWeight: 700,
    color: "#1A1A2E",
    lineHeight: 1.1,
  },

  tierPeriod: {
    fontSize: 13,
    fontWeight: 400,
    color: "#8A857D",
    marginLeft: 2,
  },

  featureList: {
    listStyle: "none",
    padding: 0,
    margin: "16px 0 0",
    fontSize: 12.5,
    lineHeight: "22px",
    color: "#3A3530",
  },

  featureItem: {
    paddingLeft: 18,
    position: "relative",
  },

  featureCheck: {
    position: "absolute",
    left: 0,
    color: "#16a34a",
    fontWeight: 700,
  },

  limitItem: {
    paddingLeft: 18,
    position: "relative",
    color: "#B0AAA0",
  },

  limitX: {
    position: "absolute",
    left: 0,
    color: "#D4A018",
    fontWeight: 700,
  },

  tierBtn: (color) => ({
    display: "block",
    width: "100%",
    marginTop: 18,
    padding: "10px 0",
    borderRadius: 10,
    border: `1.5px solid ${color}`,
    background: "transparent",
    color: color,
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
    fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
    transition: "background 0.15s, color 0.15s",
  }),

  closeBtn: {
    position: "absolute",
    top: 14,
    right: 18,
    background: "none",
    border: "none",
    fontSize: 20,
    color: "#B0AAA0",
    cursor: "pointer",
    lineHeight: 1,
  },
};

/* ── Pricing Modal component ─────────────────────────────────────────────── */

function PricingModal({ currentTier, onClose, onSelect }) {
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div
        style={{ ...styles.modal, position: "relative" }}
        onClick={(e) => e.stopPropagation()}
      >
        <button style={styles.closeBtn} onClick={onClose} title="Close">
          &times;
        </button>
        <div style={styles.modalTitle}>Princeps Plans</div>
        <div style={styles.modalSubtitle}>
          Site feasibility intelligence for energy infrastructure
        </div>

        <div style={styles.tiersRow}>
          {PRICING_TIERS.map((t) => (
            <div
              key={t.id}
              style={styles.tierCard(t.color, t.popular)}
              onMouseEnter={(e) => {
                e.currentTarget.style.transform = "translateY(-2px)";
                e.currentTarget.style.boxShadow =
                  "0 6px 24px rgba(0,0,0,0.10)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.transform = "none";
                e.currentTarget.style.boxShadow = "none";
              }}
            >
              {t.popular && (
                <span style={styles.popularTag(t.color)}>MOST POPULAR</span>
              )}
              <div style={styles.tierName(t.color)}>{t.name}</div>
              <div>
                <span style={styles.tierPrice}>{t.price}</span>
                <span style={styles.tierPeriod}>{t.period}</span>
              </div>
              <ul style={styles.featureList}>
                {t.features.map((f, i) => (
                  <li key={i} style={styles.featureItem}>
                    <span style={styles.featureCheck}>&#10003;</span>
                    {f}
                  </li>
                ))}
                {t.limits.map((l, i) => (
                  <li key={`l${i}`} style={styles.limitItem}>
                    <span style={styles.limitX}>&mdash;</span>
                    {l}
                  </li>
                ))}
              </ul>
              <button
                style={styles.tierBtn(t.color)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = t.color;
                  e.currentTarget.style.color = "#FFF";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = t.color;
                }}
                onClick={() => onSelect(t.id)}
              >
                {t.id === currentTier
                  ? "Current Plan"
                  : t.id === "enterprise"
                  ? "Contact Sales"
                  : "Upgrade"}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Main UsageMeter component ───────────────────────────────────────────── */

export default function UsageMeter({ userId = "default" }) {
  const [usage, setUsage] = useState(null);
  const [minimised, setMinimised] = useState(false);
  const [showPricing, setShowPricing] = useState(false);
  const [hovered, setHovered] = useState(false);

  const fetchUsage = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/usage/summary?user_id=${userId}`);
      if (res.ok) {
        setUsage(await res.json());
      }
    } catch {
      // Fallback: show free tier defaults when backend is unavailable
      setUsage({
        tier: "free",
        tier_label: "Free",
        current: {
          assessment: { used: 0, limit: 5, pct: 0 },
          map_view:   { used: 0, limit: 10, pct: 0 },
          pdf_export: { used: 0, limit: 0, pct: 0 },
          api_call:   { used: 0, limit: 0, pct: 0 },
        },
      });
    }
  }, [userId]);

  useEffect(() => {
    fetchUsage();
    const interval = setInterval(fetchUsage, 60_000);
    return () => clearInterval(interval);
  }, [fetchUsage]);

  if (!usage) return null;

  const tier = usage.tier || "free";
  const meta = TIER_META[tier] || TIER_META.free;
  const assess = usage.current?.assessment || { used: 0, limit: 5, pct: 0 };
  const isUnlimited = assess.limit === "unlimited";
  const pct = isUnlimited ? 15 : assess.pct || 0;
  const barColor =
    pct >= 90 ? "#B33A3A" : pct >= 70 ? "#D4A018" : meta.color;

  const usageText = isUnlimited
    ? `${assess.used} assessments`
    : `${assess.used}/${assess.limit} assessments`;

  /* ── Minimised view ──────────────────────────────────────────────────── */

  if (minimised) {
    return (
      <div style={styles.container}>
        <div
          style={styles.pillMinimised}
          onClick={() => setMinimised(false)}
          title="Expand usage meter"
        >
          <span style={styles.badge(meta.badge, meta.color)}>
            {meta.label}
          </span>
          <span
            style={{
              fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
              fontSize: 11,
              color: barColor,
              fontWeight: 600,
            }}
          >
            {isUnlimited ? "\u221E" : `${assess.used}/${assess.limit}`}
          </span>
        </div>
      </div>
    );
  }

  /* ── Full view ───────────────────────────────────────────────────────── */

  return (
    <div style={styles.container}>
      <div
        style={{
          ...styles.pill,
          ...(hovered
            ? {
                boxShadow:
                  "0 4px 20px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.06)",
              }
            : {}),
        }}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Tier badge */}
        <span style={styles.badge(meta.badge, meta.color)}>{meta.label}</span>

        {/* Usage info */}
        <div style={styles.usageSection}>
          <div style={styles.usageLabel}>
            <span style={styles.usageNumbers}>{usageText}</span>
            {" this month"}
          </div>
          <div style={styles.barTrack}>
            <div style={styles.barFill(pct, barColor)} />
          </div>
        </div>

        {/* Upgrade button (free tier only) */}
        {tier === "free" && (
          <button
            style={styles.upgradeBtn}
            onClick={(e) => {
              e.stopPropagation();
              setShowPricing(true);
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = 0.85)}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = 1)}
          >
            Upgrade
          </button>
        )}

        {/* Minimise */}
        <button
          style={styles.minimiseBtn}
          onClick={(e) => {
            e.stopPropagation();
            setMinimised(true);
          }}
          title="Minimise"
        >
          &#8722;
        </button>
      </div>

      {/* Pricing modal */}
      {showPricing && (
        <PricingModal
          currentTier={tier}
          onClose={() => setShowPricing(false)}
          onSelect={(selected) => {
            setShowPricing(false);
            if (selected === "enterprise") {
              window.open("mailto:sales@princeps.energy?subject=Enterprise%20Inquiry", "_blank");
            } else if (selected !== tier) {
              // In production, this would redirect to Stripe checkout
              console.log(`[Princeps] Upgrade requested: ${tier} -> ${selected}`);
              window.open("/pricing", "_blank");
            }
          }}
        />
      )}
    </div>
  );
}
