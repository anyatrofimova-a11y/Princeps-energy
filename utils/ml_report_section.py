"""
ML-enhanced report sections for Princeps site assessment reports.

Generates standalone HTML blocks (inline CSS, no external dependencies) that
visualise ML verdict, SHAP explanations, ensemble comparison, and multi-site
comparison tables.  Designed to be embedded in Jinja2 report templates or
returned directly as HTML responses.
"""

from __future__ import annotations

import html as _html
import logging
from typing import Any

log = logging.getLogger("princeps.ml_report_section")

# ---------------------------------------------------------------------------
# Princeps brand palette
# ---------------------------------------------------------------------------
_P = {
    "primary": "#7c5cfc",
    "primary_light": "#a78bfa",
    "go": "#16a34a",
    "go_light": "#bbf7d0",
    "caution": "#f59e0b",
    "caution_light": "#fef3c7",
    "nogo": "#dc2626",
    "nogo_light": "#fecaca",
    "bg": "#f8fafc",
    "text": "#1f2937",
    "text_muted": "#6b7280",
    "border": "#e5e7eb",
    "white": "#ffffff",
    "bar_pos": "#16a34a",
    "bar_neg": "#dc2626",
}

# UK average defaults (same as ml_site_classifier defaults)
UK_AVERAGES: dict[str, tuple[float, str]] = {
    "ghi_kwh_m2_yr":    (1000.0, "kWh/m\u00b2/yr"),
    "wind_speed_ms":    (6.0,    "m/s"),
    "slope_mean_deg":   (5.0,    "\u00b0"),
    "slope_p90_deg":    (8.0,    "\u00b0"),
    "south_facing_pct": (40.0,   "%"),
    "elevation_m":      (100.0,  "m"),
    "developable_pct":  (55.0,   "%"),
    "built_pct":        (12.0,   "%"),
    "trees_pct":        (13.0,   "%"),
    "water_pct":        (3.0,    "%"),
    "grid_distance_km": (5.0,    "km"),
    "grid_headroom_mw": (5.0,    "MW"),
    "flood_risk_score": (10.0,   ""),
    "ndvi_mean":        (0.45,   ""),
    "ndvi_trend_slope": (0.0,    ""),
    "sar_vv_mean_db":   (-12.0,  "dB"),
    "cloud_clear_pct":  (42.0,   "%"),
}

FEATURE_LABELS: dict[str, str] = {
    "ghi_kwh_m2_yr":    "Solar Resource (GHI)",
    "wind_speed_ms":    "Wind Speed",
    "slope_mean_deg":   "Mean Slope",
    "slope_p90_deg":    "P90 Slope",
    "south_facing_pct": "South-Facing %",
    "elevation_m":      "Elevation",
    "developable_pct":  "Developable Land %",
    "built_pct":        "Built-Up %",
    "trees_pct":        "Tree Cover %",
    "water_pct":        "Water Coverage %",
    "grid_distance_km": "Grid Distance",
    "grid_headroom_mw": "Grid Headroom",
    "flood_risk_score": "Flood Risk",
    "ndvi_mean":        "NDVI",
    "ndvi_trend_slope": "NDVI Trend",
    "sar_vv_mean_db":   "SAR Backscatter",
    "cloud_clear_pct":  "Cloud-Free %",
}


def _esc(val: Any) -> str:
    return _html.escape(str(val))


def _verdict_colour(verdict: str) -> str:
    v = verdict.upper().replace("-", "")
    if v == "GO":
        return _P["go"]
    if v == "NOGO":
        return _P["nogo"]
    return _P["caution"]


def _verdict_bg(verdict: str) -> str:
    v = verdict.upper().replace("-", "")
    if v == "GO":
        return _P["go_light"]
    if v == "NOGO":
        return _P["nogo_light"]
    return _P["caution_light"]


def _score_colour(score: float) -> str:
    """Return a colour along red-amber-green for 0-100 score."""
    if score >= 65:
        return _P["go"]
    if score >= 40:
        return _P["caution"]
    return _P["nogo"]


# ===================================================================
# 1. ML Verdict Section
# ===================================================================

def render_ml_verdict_section(ml_result: dict) -> str:
    """
    Render a full ML insights HTML block.

    Parameters
    ----------
    ml_result : dict
        Output from ``ml_site_classifier.predict_site()``.
        Expected keys: verdict, score, confidence, class_probabilities,
        shap_values, top_factors.

    Returns
    -------
    str  — self-contained HTML with inline CSS.
    """
    verdict = ml_result.get("verdict", "CAUTION")
    score = ml_result.get("score", 50.0)
    confidence = ml_result.get("confidence", 0.0)
    class_probs = ml_result.get("class_probabilities", {})
    shap_values = ml_result.get("shap_values", {})
    top_factors = ml_result.get("top_factors", [])

    parts: list[str] = []

    # --- wrapper ---
    parts.append(f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: {_P['text']}; background: {_P['bg']}; padding: 28px; border-radius: 12px;
                border: 1px solid {_P['border']}; margin: 24px 0;">
      <h2 style="margin: 0 0 24px 0; font-size: 22px; color: {_P['primary']};">
        ML Site Viability Assessment
      </h2>
    """)

    # --- verdict badge + confidence ---
    parts.append(f"""
      <div style="display: flex; align-items: center; gap: 24px; margin-bottom: 24px; flex-wrap: wrap;">
        <div style="background: {_verdict_bg(verdict)}; border: 2px solid {_verdict_colour(verdict)};
                    border-radius: 10px; padding: 16px 32px; text-align: center; min-width: 160px;">
          <div style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;
                      color: {_P['text_muted']}; margin-bottom: 4px;">ML Verdict</div>
          <div style="font-size: 32px; font-weight: 800; color: {_verdict_colour(verdict)};">
            {_esc(verdict)}
          </div>
        </div>
        <div style="flex: 1; min-width: 200px;">
          <div style="font-size: 13px; color: {_P['text_muted']}; margin-bottom: 6px;">
            Model Confidence</div>
          <div style="background: {_P['border']}; border-radius: 6px; height: 22px;
                      overflow: hidden; position: relative;">
            <div style="width: {confidence}%; height: 100%;
                        background: {_verdict_colour(verdict)};
                        border-radius: 6px; transition: width 0.5s;"></div>
            <span style="position: absolute; right: 8px; top: 2px; font-size: 12px;
                         font-weight: 600; color: {_P['text']};">{confidence:.1f}%</span>
          </div>
          <div style="display: flex; gap: 16px; margin-top: 8px; font-size: 12px;
                      color: {_P['text_muted']};">
    """)
    for label in ("GO", "CAUTION", "NO-GO"):
        pct = class_probs.get(label, 0)
        parts.append(f'<span>{label}: {pct:.1f}%</span>')
    parts.append("</div></div></div>")

    # --- score gauge ---
    parts.append(_render_score_gauge(score))

    # --- SHAP top factors bar chart ---
    if top_factors and any("feature" in f for f in top_factors):
        parts.append(_render_shap_bars(top_factors))

    # --- feature waterfall ---
    if shap_values:
        parts.append(_render_waterfall(shap_values, ml_result))

    # --- UK average comparison ---
    if top_factors and any("feature" in f for f in top_factors):
        parts.append(_render_uk_comparison(top_factors))

    parts.append("</div>")
    return "\n".join(parts)


def _render_score_gauge(score: float) -> str:
    colour = _score_colour(score)
    # Gradient background: red -> amber -> green
    return f"""
    <div style="margin-bottom: 28px;">
      <div style="font-size: 13px; text-transform: uppercase; letter-spacing: 1px;
                  color: {_P['text_muted']}; margin-bottom: 8px;">Viability Score</div>
      <div style="position: relative; height: 32px; border-radius: 8px; overflow: hidden;
                  background: linear-gradient(90deg, {_P['nogo']} 0%, {_P['caution']} 40%,
                              {_P['caution']} 60%, {_P['go']} 100%);">
        <div style="position: absolute; left: {score}%; top: -2px; transform: translateX(-50%);
                    width: 4px; height: 36px; background: {_P['text']}; border-radius: 2px;"></div>
      </div>
      <div style="display: flex; justify-content: space-between; margin-top: 4px;
                  font-size: 11px; color: {_P['text_muted']};">
        <span>0 — No-Go</span>
        <span style="font-weight: 700; font-size: 16px; color: {colour};">{score:.1f}</span>
        <span>100 — Go</span>
      </div>
    </div>
    """


def _render_shap_bars(top_factors: list[dict]) -> str:
    """Horizontal bar chart showing top SHAP factors."""
    factors = [f for f in top_factors if "feature" in f][:5]
    if not factors:
        return ""

    max_abs = max(abs(f.get("shap_impact", 0)) for f in factors) or 1.0

    rows = []
    for f in factors:
        impact = f.get("shap_impact", 0)
        label = FEATURE_LABELS.get(f["feature"], f["feature"])
        colour = _P["bar_pos"] if impact >= 0 else _P["bar_neg"]
        pct = abs(impact) / max_abs * 100
        sign = "+" if impact >= 0 else ""
        explanation = _esc(f.get("explanation", ""))

        # Bar is drawn from centre (50%) outward
        if impact >= 0:
            bar_style = f"left: 50%; width: {pct / 2}%;"
        else:
            bar_style = f"right: 50%; width: {pct / 2}%;"

        rows.append(f"""
        <div style="display: flex; align-items: center; margin-bottom: 8px; gap: 12px;">
          <div style="width: 140px; text-align: right; font-size: 12px; font-weight: 600;
                      flex-shrink: 0;">{_esc(label)}</div>
          <div style="flex: 1; position: relative; height: 24px; background: {_P['bg']};
                      border-radius: 4px; overflow: hidden;">
            <div style="position: absolute; left: 50%; top: 0; width: 1px; height: 100%;
                        background: {_P['border']};"></div>
            <div style="position: absolute; {bar_style} height: 100%;
                        background: {colour}; border-radius: 3px; opacity: 0.75;"></div>
          </div>
          <div style="width: 60px; font-size: 12px; font-weight: 600;
                      color: {colour}; flex-shrink: 0;">{sign}{impact:+.3f}</div>
        </div>
        <div style="margin: -4px 0 10px 152px; font-size: 11px; color: {_P['text_muted']};">
          {explanation}
        </div>
        """)

    return f"""
    <div style="margin-bottom: 28px;">
      <div style="font-size: 14px; font-weight: 700; margin-bottom: 12px;
                  color: {_P['text']};">Top 5 SHAP Impact Factors</div>
      <div style="padding: 16px; background: {_P['white']}; border-radius: 8px;
                  border: 1px solid {_P['border']};">
        {"".join(rows)}
        <div style="display: flex; justify-content: center; gap: 24px; margin-top: 8px;
                    font-size: 11px; color: {_P['text_muted']};">
          <span><span style="display: inline-block; width: 10px; height: 10px;
                             background: {_P['bar_neg']}; border-radius: 2px;
                             margin-right: 4px;"></span>Hurts viability</span>
          <span><span style="display: inline-block; width: 10px; height: 10px;
                             background: {_P['bar_pos']}; border-radius: 2px;
                             margin-right: 4px;"></span>Helps viability</span>
        </div>
      </div>
    </div>
    """


def _render_waterfall(shap_values: dict[str, float], ml_result: dict) -> str:
    """Feature-importance waterfall showing cumulative push/pull on score."""
    if not shap_values:
        return ""

    # Sort by absolute impact descending
    sorted_feats = sorted(shap_values.items(), key=lambda x: abs(x[1]), reverse=True)

    base_score = ml_result.get("score", 50.0)
    # Approximate base value (score minus sum of SHAP = expected value)
    total_shap = sum(shap_values.values())
    base_val = base_score - total_shap

    rows = []
    running = base_val
    for feat, val in sorted_feats:
        label = FEATURE_LABELS.get(feat, feat)
        colour = _P["bar_pos"] if val >= 0 else _P["bar_neg"]
        arrow = "\u2191" if val >= 0 else "\u2193"
        sign = "+" if val >= 0 else ""
        old_running = running
        running += val

        rows.append(f"""
        <tr>
          <td style="padding: 6px 10px; font-size: 12px; border-bottom: 1px solid {_P['border']};">
            {_esc(label)}</td>
          <td style="padding: 6px 10px; font-size: 12px; font-weight: 600;
                     color: {colour}; border-bottom: 1px solid {_P['border']}; text-align: right;">
            {arrow} {sign}{val:.3f}</td>
          <td style="padding: 6px 10px; font-size: 12px;
                     border-bottom: 1px solid {_P['border']}; text-align: right;
                     color: {_P['text_muted']};">{running:.1f}</td>
        </tr>
        """)

    return f"""
    <div style="margin-bottom: 28px;">
      <div style="font-size: 14px; font-weight: 700; margin-bottom: 12px;
                  color: {_P['text']};">Feature Importance Waterfall</div>
      <div style="max-height: 420px; overflow-y: auto; background: {_P['white']};
                  border-radius: 8px; border: 1px solid {_P['border']};">
        <table style="width: 100%; border-collapse: collapse;">
          <thead>
            <tr style="background: {_P['bg']};">
              <th style="padding: 8px 10px; text-align: left; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                Feature</th>
              <th style="padding: 8px 10px; text-align: right; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                SHAP Impact</th>
              <th style="padding: 8px 10px; text-align: right; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                Cumulative</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style="padding: 6px 10px; font-size: 12px; font-style: italic;
                         border-bottom: 1px solid {_P['border']}; color: {_P['text_muted']};">
                Base value</td>
              <td style="padding: 6px 10px; border-bottom: 1px solid {_P['border']};"></td>
              <td style="padding: 6px 10px; font-size: 12px; text-align: right;
                         border-bottom: 1px solid {_P['border']}; color: {_P['text_muted']};">
                {base_val:.1f}</td>
            </tr>
            {"".join(rows)}
            <tr style="background: {_P['bg']};">
              <td style="padding: 8px 10px; font-size: 12px; font-weight: 700;">
                Final Score</td>
              <td style="padding: 8px 10px;"></td>
              <td style="padding: 8px 10px; font-size: 14px; font-weight: 700;
                         text-align: right; color: {_score_colour(base_score)};">
                {base_score:.1f}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    """


def _render_uk_comparison(top_factors: list[dict]) -> str:
    """Compare top factor values against UK averages."""
    factors = [f for f in top_factors if "feature" in f][:5]
    if not factors:
        return ""

    rows = []
    for f in factors:
        feat = f["feature"]
        val = f.get("value", 0)
        uk_avg, unit = UK_AVERAGES.get(feat, (0, ""))
        label = FEATURE_LABELS.get(feat, feat)

        if uk_avg != 0:
            diff_pct = ((val - uk_avg) / abs(uk_avg)) * 100
        else:
            diff_pct = 0

        if abs(diff_pct) < 5:
            diff_colour = _P["text_muted"]
            diff_label = "Near average"
        elif diff_pct > 0:
            # Whether "above average" is good depends on feature
            neg_features = {"slope_mean_deg", "slope_p90_deg", "built_pct",
                            "trees_pct", "water_pct", "grid_distance_km",
                            "flood_risk_score"}
            if feat in neg_features:
                diff_colour = _P["nogo"]
                diff_label = f"+{diff_pct:.0f}% above avg"
            else:
                diff_colour = _P["go"]
                diff_label = f"+{diff_pct:.0f}% above avg"
        else:
            neg_features = {"slope_mean_deg", "slope_p90_deg", "built_pct",
                            "trees_pct", "water_pct", "grid_distance_km",
                            "flood_risk_score"}
            if feat in neg_features:
                diff_colour = _P["go"]
                diff_label = f"{diff_pct:.0f}% below avg"
            else:
                diff_colour = _P["nogo"]
                diff_label = f"{diff_pct:.0f}% below avg"

        rows.append(f"""
        <tr>
          <td style="padding: 8px 10px; font-size: 12px; font-weight: 600;
                     border-bottom: 1px solid {_P['border']};">{_esc(label)}</td>
          <td style="padding: 8px 10px; font-size: 12px; text-align: right;
                     border-bottom: 1px solid {_P['border']};">{val:.2f} {_esc(unit)}</td>
          <td style="padding: 8px 10px; font-size: 12px; text-align: right;
                     color: {_P['text_muted']};
                     border-bottom: 1px solid {_P['border']};">{uk_avg:.2f} {_esc(unit)}</td>
          <td style="padding: 8px 10px; font-size: 12px; text-align: right;
                     font-weight: 600; color: {diff_colour};
                     border-bottom: 1px solid {_P['border']};">{diff_label}</td>
        </tr>
        """)

    return f"""
    <div style="margin-bottom: 12px;">
      <div style="font-size: 14px; font-weight: 700; margin-bottom: 12px;
                  color: {_P['text']};">Comparison to UK Average</div>
      <div style="background: {_P['white']}; border-radius: 8px;
                  border: 1px solid {_P['border']}; overflow: hidden;">
        <table style="width: 100%; border-collapse: collapse;">
          <thead>
            <tr style="background: {_P['bg']};">
              <th style="padding: 8px 10px; text-align: left; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                Factor</th>
              <th style="padding: 8px 10px; text-align: right; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                Site Value</th>
              <th style="padding: 8px 10px; text-align: right; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                UK Average</th>
              <th style="padding: 8px 10px; text-align: right; font-size: 11px;
                         text-transform: uppercase; letter-spacing: 0.5px;
                         color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};">
                Difference</th>
            </tr>
          </thead>
          <tbody>
            {"".join(rows)}
          </tbody>
        </table>
      </div>
    </div>
    """


# ===================================================================
# 2. Ensemble Section
# ===================================================================

def render_ensemble_section(ensemble: dict) -> str:
    """
    Render an ensemble comparison HTML block.

    Parameters
    ----------
    ensemble : dict
        Output from ``ml_site_classifier.ensemble_score()``.
        Expected keys: final_score, final_verdict, component_scores,
        weights_used, disagreement, ml_shap_top.

    Returns
    -------
    str  — self-contained HTML with inline CSS.
    """
    final_score = ensemble.get("final_score", 50.0)
    final_verdict = ensemble.get("final_verdict", "CAUTION")
    components = ensemble.get("component_scores", {})
    weights = ensemble.get("weights_used", {})
    disagreement = ensemble.get("disagreement")

    # Derive per-source verdicts
    source_labels = {"rule": "Rule-Based", "ml": "ML Model", "agent": "Agent AI"}
    source_rows = []
    for key in ("rule", "ml", "agent"):
        sc = components.get(key)
        if sc is None:
            continue
        w = weights.get(key, 0)
        v = "GO" if sc >= 65 else ("CAUTION" if sc >= 40 else "NO-GO")
        source_rows.append(f"""
        <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 10px;">
          <div style="width: 110px; font-size: 13px; font-weight: 600;">
            {source_labels.get(key, key)}</div>
          <div style="flex: 1; position: relative; height: 20px; background: {_P['border']};
                      border-radius: 4px; overflow: hidden;">
            <div style="width: {sc}%; height: 100%; background: {_verdict_colour(v)};
                        border-radius: 4px; opacity: 0.7;"></div>
          </div>
          <div style="width: 45px; text-align: right; font-size: 12px; font-weight: 600;
                      color: {_verdict_colour(v)};">{sc:.1f}</div>
          <div style="width: 80px; text-align: center; font-size: 11px; font-weight: 700;
                      padding: 2px 8px; border-radius: 4px;
                      background: {_verdict_bg(v)}; color: {_verdict_colour(v)};">{v}</div>
          <div style="width: 50px; text-align: right; font-size: 11px;
                      color: {_P['text_muted']};">{w:.0%}</div>
        </div>
        """)

    disagreement_html = ""
    if disagreement:
        disagreement_html = f"""
        <div style="background: {_P['caution_light']}; border: 1px solid {_P['caution']};
                    border-radius: 8px; padding: 12px 16px; margin-top: 16px;
                    display: flex; align-items: flex-start; gap: 10px;">
          <span style="font-size: 18px; flex-shrink: 0;">&#9888;</span>
          <div>
            <div style="font-size: 13px; font-weight: 700; color: {_P['text']};">
              Source Disagreement Detected</div>
            <div style="font-size: 12px; color: {_P['text_muted']}; margin-top: 4px;">
              Rule-based says <strong>{_esc(disagreement.get('rule_says', ''))}</strong>,
              ML says <strong>{_esc(disagreement.get('ml_says', ''))}</strong>.
              {_esc(disagreement.get('note', ''))}
            </div>
          </div>
        </div>
        """

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: {_P['text']}; background: {_P['bg']}; padding: 28px; border-radius: 12px;
                border: 1px solid {_P['border']}; margin: 24px 0;">
      <h2 style="margin: 0 0 20px 0; font-size: 22px; color: {_P['primary']};">
        Ensemble Assessment
      </h2>

      <div style="display: flex; align-items: center; gap: 20px; margin-bottom: 24px; flex-wrap: wrap;">
        <div style="background: {_verdict_bg(final_verdict)};
                    border: 2px solid {_verdict_colour(final_verdict)};
                    border-radius: 10px; padding: 14px 28px; text-align: center;">
          <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
                      color: {_P['text_muted']}; margin-bottom: 2px;">Blended Verdict</div>
          <div style="font-size: 28px; font-weight: 800;
                      color: {_verdict_colour(final_verdict)};">{_esc(final_verdict)}</div>
        </div>
        <div>
          <div style="font-size: 36px; font-weight: 800;
                      color: {_score_colour(final_score)};">{final_score:.1f}</div>
          <div style="font-size: 12px; color: {_P['text_muted']};">Weighted Score</div>
        </div>
      </div>

      <div style="font-size: 13px; font-weight: 700; margin-bottom: 10px;">
        Source Comparison</div>
      <div style="padding: 16px; background: {_P['white']}; border-radius: 8px;
                  border: 1px solid {_P['border']};">
        {"".join(source_rows)}
      </div>

      {disagreement_html}
    </div>
    """


# ===================================================================
# 3. Site Comparison Table
# ===================================================================

def render_site_comparison_table(sites: list[dict]) -> str:
    """
    Render a side-by-side comparison table for up to 5 sites.

    Parameters
    ----------
    sites : list[dict]
        Each dict should contain: name, score, verdict, irr (%), grid_distance_km,
        capacity_factor (%).  Missing keys get "N/A".

    Returns
    -------
    str  — self-contained HTML table with inline CSS.
    """
    sites = sites[:5]
    if not sites:
        return ""

    metrics = [
        ("score",           "Viability Score",   "{:.1f}",  True),   # higher=better
        ("verdict",         "Verdict",           "{}",      None),   # special
        ("irr",             "IRR (%)",           "{:.1f}%", True),
        ("grid_distance_km","Grid Distance (km)","{:.1f}",  False),  # lower=better
        ("capacity_factor", "Capacity Factor (%)","{:.1f}%",True),
    ]

    # --- header ---
    header_cells = [f"""
    <th style="padding: 10px 14px; text-align: left; font-size: 11px;
               text-transform: uppercase; letter-spacing: 0.5px;
               color: {_P['text_muted']}; border-bottom: 2px solid {_P['border']};
               background: {_P['bg']};">Metric</th>
    """]
    for s in sites:
        header_cells.append(f"""
        <th style="padding: 10px 14px; text-align: center; font-size: 13px;
                   font-weight: 700; border-bottom: 2px solid {_P['border']};
                   background: {_P['bg']}; color: {_P['primary']};">
          {_esc(s.get('name', 'Site'))}
        </th>
        """)

    # --- body rows ---
    body_rows = []
    for key, label, fmt, higher_is_better in metrics:
        cells = [f"""
        <td style="padding: 10px 14px; font-size: 12px; font-weight: 600;
                   border-bottom: 1px solid {_P['border']}; background: {_P['bg']};">
          {_esc(label)}</td>
        """]

        # Find best value for highlighting
        vals = []
        for s in sites:
            v = s.get(key)
            if v is not None and higher_is_better is not None:
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    pass
        if vals:
            best = max(vals) if higher_is_better else min(vals)
        else:
            best = None

        for s in sites:
            v = s.get(key)
            if key == "verdict":
                if v:
                    bg = _verdict_bg(v)
                    col = _verdict_colour(v)
                    cells.append(f"""
                    <td style="padding: 10px 14px; text-align: center; font-size: 13px;
                               font-weight: 700; border-bottom: 1px solid {_P['border']};
                               background: {bg}; color: {col};">{_esc(v)}</td>
                    """)
                else:
                    cells.append(f"""
                    <td style="padding: 10px 14px; text-align: center;
                               border-bottom: 1px solid {_P['border']};
                               color: {_P['text_muted']};">N/A</td>
                    """)
            elif v is not None:
                try:
                    fv = float(v)
                    display = fmt.format(fv)
                    is_best = (best is not None and abs(fv - best) < 0.001)
                except (ValueError, TypeError):
                    display = str(v)
                    is_best = False

                bg = _P["go_light"] if is_best else _P["white"]
                fw = "700" if is_best else "400"
                cells.append(f"""
                <td style="padding: 10px 14px; text-align: center; font-size: 13px;
                           font-weight: {fw};
                           border-bottom: 1px solid {_P['border']};
                           background: {bg};">{_esc(display)}</td>
                """)
            else:
                cells.append(f"""
                <td style="padding: 10px 14px; text-align: center;
                           border-bottom: 1px solid {_P['border']};
                           color: {_P['text_muted']};">N/A</td>
                """)

        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: {_P['text']}; background: {_P['bg']}; padding: 28px; border-radius: 12px;
                border: 1px solid {_P['border']}; margin: 24px 0;">
      <h2 style="margin: 0 0 20px 0; font-size: 22px; color: {_P['primary']};">
        Site Comparison
      </h2>
      <div style="overflow-x: auto; background: {_P['white']}; border-radius: 8px;
                  border: 1px solid {_P['border']};">
        <table style="width: 100%; border-collapse: collapse; min-width: 500px;">
          <thead><tr>{''.join(header_cells)}</tr></thead>
          <tbody>{''.join(body_rows)}</tbody>
        </table>
      </div>
      <div style="margin-top: 8px; font-size: 11px; color: {_P['text_muted']};">
        Best-in-class values highlighted in green.
      </div>
    </div>
    """


# ===================================================================
# 4. Full ML-Enhanced Report HTML
# ===================================================================

def render_ml_enhanced_report(
    site_name: str,
    ml_result: dict,
    ensemble: dict | None = None,
    comparison_sites: list[dict] | None = None,
) -> str:
    """
    Generate a complete standalone HTML document with all ML sections.

    This wraps the individual section renderers in a full HTML page suitable
    for PDF conversion via Playwright or direct browser viewing.
    """
    from datetime import datetime

    sections = []
    sections.append(render_ml_verdict_section(ml_result))
    if ensemble:
        sections.append(render_ensemble_section(ensemble))
    if comparison_sites:
        sections.append(render_site_comparison_table(comparison_sites))

    body = "\n".join(sections)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Princeps ML-Enhanced Site Assessment — {_esc(site_name)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      margin: 0; padding: 0;
      background: {_P['white']};
      color: {_P['text']};
    }}
    @media print {{
      body {{ padding: 0; }}
      .page-break {{ page-break-before: always; }}
    }}
  </style>
</head>
<body>
  <!-- Header -->
  <div style="background: linear-gradient(135deg, {_P['primary']} 0%, #5b3fd4 100%);
              color: white; padding: 32px 40px; margin-bottom: 8px;">
    <div style="font-size: 14px; text-transform: uppercase; letter-spacing: 2px;
                opacity: 0.8; margin-bottom: 4px;">Princeps</div>
    <div style="font-size: 26px; font-weight: 800;">
      ML-Enhanced Site Assessment</div>
    <div style="font-size: 16px; margin-top: 4px; opacity: 0.9;">
      {_esc(site_name)}</div>
    <div style="font-size: 12px; margin-top: 12px; opacity: 0.7;">
      Generated {now}</div>
  </div>

  <!-- Content -->
  <div style="max-width: 900px; margin: 0 auto; padding: 16px 32px 48px;">
    {body}
  </div>

  <!-- Footer -->
  <div style="text-align: center; padding: 20px; font-size: 11px;
              color: {_P['text_muted']}; border-top: 1px solid {_P['border']};">
    Princeps &mdash; Energy Infrastructure Site Intelligence &mdash; Confidential
  </div>
</body>
</html>"""
