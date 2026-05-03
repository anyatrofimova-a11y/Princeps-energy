/**
 * SsoButton — minimal "Sign in with SSO" button.
 *
 * Hits GET /api/auth/sso/config on mount; renders nothing until config
 * comes back. If `enabled === true`, shows a button that navigates the
 * full window to /api/auth/sso/login?return_to=<current path>. The
 * backend takes it from there: 302 to the IdP, then 302 back to the
 * callback, which sets a cookie and bounces to return_to.
 *
 * Tested against Auth0, Keycloak, Google, Microsoft Entra, Okta — the
 * flow is generic OIDC, so no provider branching is needed in the UI.
 */
import { useEffect, useState } from "react";

const CONFIG_URL = "/api/auth/sso/config";
const LOGIN_URL = "/api/auth/sso/login";

export default function SsoButton({ className = "", label = "Sign in with SSO" }) {
  const [config, setConfig] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetch(CONFIG_URL, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : { enabled: false, issuer: null }))
      .then((data) => {
        if (!cancelled) setConfig(data);
      })
      .catch(() => {
        if (!cancelled) setConfig({ enabled: false, issuer: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!config || !config.enabled) return null;

  const handleClick = () => {
    const returnTo = encodeURIComponent(
      window.location.pathname + window.location.search,
    );
    window.location.href = `${LOGIN_URL}?return_to=${returnTo}`;
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={className || "princeps-sso-button"}
      aria-label={label}
      style={
        className
          ? undefined
          : {
              padding: "0.6rem 1rem",
              fontSize: "0.95rem",
              border: "1px solid #c9a227",
              background: "#fffaf0",
              color: "#3a2f00",
              borderRadius: "0.4rem",
              cursor: "pointer",
              fontWeight: 600,
            }
      }
    >
      {label}
      {config.issuer ? ` (${new URL(config.issuer).hostname})` : ""}
    </button>
  );
}
