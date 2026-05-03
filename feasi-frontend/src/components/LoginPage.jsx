/**
 * LoginPage — initial auth gate for Princeps.
 *
 * - Full-bleed animated GridCanvas background (same as Mission Control)
 * - Centered card with email/password, SSO stubs, demo-mode fallback
 * - Calls POST /api/auth/login — on 401/400 shakes card + inline error
 * - On 200, stores token + user via useAuth.login(), fades the card,
 *   then App.jsx re-renders into the main shell
 *
 * Companion: BOT-LOG-AUTH owns /api/auth/login | /me | /logout.
 * If the endpoint 404s (backend not landed yet), we fall back to demo login
 * so the UI is never a dead-end.
 */
import React, { useEffect, useRef, useState } from "react";
import GridCanvas from "./GridCanvas";
import useAuth from "../auth/useAuth";

const PKG_VERSION = "0.1.0"; // mirrors package.json; bumped when it is

export default function LoginPage({ onLoginSuccess }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [shake, setShake] = useState(0);
  const [toast, setToast] = useState("");
  const [fadingOut, setFadingOut] = useState(false);
  const toastTimer = useRef(null);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const flashToast = (msg, ms = 2200) => {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), ms);
  };

  const triggerShake = () => setShake((n) => n + 1);

  const finishLogin = (payload) => {
    login(payload);
    setFadingOut(true);
    setTimeout(() => {
      if (typeof onLoginSuccess === "function") onLoginSuccess();
      // hook state already flipped isAuthenticated; App.jsx gate re-renders
    }, 300);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError("");
    if (!email || !password || password.length < 4) {
      setError("Enter a valid email and at least 4 characters.");
      triggerShake();
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (res.status === 404) {
        // Auth endpoint not landed yet — graceful demo fallback.
        flashToast("Auth service unavailable — continuing in demo mode.");
        finishLogin({
          email,
          firstName: email.split("@")[0],
          token: "demo-" + Date.now(),
          role: "member",
        });
        return;
      }
      if (!res.ok) {
        setError("Invalid email or password.");
        triggerShake();
        return;
      }
      const data = await res.json().catch(() => ({}));
      const u = data.user || {};
      finishLogin({
        email: u.email || email,
        firstName: u.first_name || u.firstName || (u.email || email).split("@")[0],
        token: data.token || data.access_token || "",
        role: u.role || "member",
      });
    } catch (err) {
      // Network/abort — treat like endpoint unavailable, demo-fallback.
      console.warn("[LoginPage] login fetch failed, falling back to demo:", err);
      flashToast("Network error — continuing in demo mode.");
      finishLogin({
        email,
        firstName: email.split("@")[0],
        token: "demo-" + Date.now(),
        role: "member",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleSSO = (provider) => {
    console.log(`[LoginPage] SSO stub clicked: ${provider}`);
    flashToast("SSO coming soon");
  };

  const handleDemo = () => {
    finishLogin({
      email: "anya.trofimova@yahoo.com",
      firstName: "Anya",
      token: "demo-" + Date.now(),
      role: "owner",
    });
  };

  // Clear inline error on next keystroke
  const onEmailChange = (e) => {
    setEmail(e.target.value);
    if (error) setError("");
  };
  const onPasswordChange = (e) => {
    setPassword(e.target.value);
    if (error) setError("");
  };

  return (
    <div className="login-root">
      <GridCanvas className="login-bg-canvas" />

      <div className={`login-card ${fadingOut ? "login-card--fade" : ""}`} data-shake={shake}>
        <div className="login-header">
          <img src="/logo-princeps.png" alt="Princeps" className="login-logo" width={32} height={32} />
          <span className="login-wordmark">PRINCEPS</span>
        </div>
        <div className="login-subtitle">UK energy infrastructure feasibility</div>

        <form className="login-form" onSubmit={handleSubmit} autoComplete="on">
          <label className="login-field">
            <span className="login-label">Email</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={onEmailChange}
              placeholder="you@company.com"
              required
              disabled={submitting || fadingOut}
            />
          </label>
          <label className="login-field">
            <span className="login-label">Password</span>
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={onPasswordChange}
              placeholder="••••••••"
              required
              minLength={4}
              disabled={submitting || fadingOut}
            />
            {error && <div className="login-error" role="alert">{error}</div>}
          </label>
          <button
            type="submit"
            className="login-submit"
            disabled={submitting || fadingOut}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="login-divider"><span>or</span></div>

        <div className="login-sso">
          <button
            type="button"
            className="login-ghost"
            onClick={() => handleSSO("google")}
            disabled={submitting || fadingOut}
          >
            Continue with Google
          </button>
          <button
            type="button"
            className="login-ghost"
            onClick={() => handleSSO("github")}
            disabled={submitting || fadingOut}
          >
            Continue with GitHub
          </button>
        </div>

        <button
          type="button"
          className="login-demo"
          onClick={handleDemo}
          disabled={submitting || fadingOut}
        >
          Demo mode — continue as Anya T.
        </button>

        <div className="login-footer">© 2026 Princeps · v{PKG_VERSION}</div>
      </div>

      {toast && <div className="login-toast" role="status">{toast}</div>}

      <style>{`
        .login-root {
          position: fixed;
          inset: 0;
          width: 100vw;
          height: 100vh;
          background: #F7F8FA;
          font-family: "DM Sans", -apple-system, BlinkMacSystemFont, sans-serif;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          z-index: 0;
        }
        .login-bg-canvas {
          position: fixed !important;
          inset: 0 !important;
          pointer-events: none !important;
          z-index: 0 !important;
        }
        .login-card {
          position: relative;
          z-index: 2;
          width: 100%;
          max-width: 380px;
          background: #fff;
          border: 1px solid rgba(0,0,0,0.08);
          border-radius: 16px;
          box-shadow: 0 20px 60px rgba(0,0,0,0.08);
          padding: 32px;
          transition: opacity 300ms ease, transform 300ms ease;
        }
        .login-card--fade {
          opacity: 0;
          transform: translateY(-4px) scale(0.98);
          pointer-events: none;
        }
        .login-card[data-shake="0"] { animation: none; }
        .login-card[data-shake]:not([data-shake="0"]) {
          animation: login-shake 420ms cubic-bezier(.36,.07,.19,.97) both;
        }
        @keyframes login-shake {
          10%, 90% { transform: translateX(-1px); }
          20%, 80% { transform: translateX(2px); }
          30%, 50%, 70% { transform: translateX(-5px); }
          40%, 60% { transform: translateX(5px); }
        }
        .login-header {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 6px;
        }
        .login-logo {
          width: 32px;
          height: 32px;
          object-fit: contain;
          display: block;
        }
        .login-wordmark {
          font-weight: 700;
          letter-spacing: 0.18em;
          font-size: 15px;
          color: #0F1318;
        }
        .login-subtitle {
          font-size: 12px;
          color: #6B7280;
          margin-bottom: 22px;
        }
        .login-form {
          display: flex;
          flex-direction: column;
          gap: 14px;
          margin-bottom: 18px;
        }
        .login-field {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .login-label {
          font-size: 11px;
          font-weight: 600;
          color: #374151;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }
        .login-field input {
          width: 100%;
          box-sizing: border-box;
          height: 40px;
          padding: 0 12px;
          font-size: 14px;
          font-family: inherit;
          color: #0F1318;
          background: #fff;
          border: 1px solid rgba(0,0,0,0.12);
          border-radius: 8px;
          outline: none;
          transition: border-color 120ms ease, box-shadow 120ms ease;
        }
        .login-field input:focus {
          border-color: var(--gold, #E7B425);
          box-shadow: 0 0 0 3px rgba(231,180,37,0.18);
        }
        .login-field input:disabled {
          background: #F9FAFB;
          color: #9CA3AF;
        }
        .login-error {
          margin-top: 4px;
          font-size: 12px;
          color: #DC2626;
        }
        .login-submit {
          height: 42px;
          border-radius: 8px;
          background: var(--gold, #E7B425);
          border: 1px solid var(--gold, #E7B425);
          color: #0F1318;
          font-size: 14px;
          font-weight: 600;
          font-family: inherit;
          cursor: pointer;
          transition: transform 120ms ease, box-shadow 120ms ease, opacity 120ms ease;
        }
        .login-submit:hover:not(:disabled) {
          transform: translateY(-1px);
          box-shadow: 0 6px 16px rgba(231,180,37,0.32);
        }
        .login-submit:active:not(:disabled) {
          transform: translateY(0);
        }
        .login-submit:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .login-divider {
          display: flex;
          align-items: center;
          gap: 12px;
          margin: 6px 0 14px;
          color: #9CA3AF;
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }
        .login-divider::before,
        .login-divider::after {
          content: "";
          flex: 1;
          height: 1px;
          background: rgba(0,0,0,0.08);
        }
        .login-sso {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 14px;
        }
        .login-ghost {
          height: 40px;
          border-radius: 8px;
          background: #fff;
          border: 1px solid rgba(0,0,0,0.12);
          color: #0F1318;
          font-size: 13px;
          font-weight: 500;
          font-family: inherit;
          cursor: pointer;
          transition: background 120ms ease, border-color 120ms ease;
        }
        .login-ghost:hover:not(:disabled) {
          background: #F9FAFB;
          border-color: rgba(0,0,0,0.2);
        }
        .login-ghost:disabled {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .login-demo {
          display: block;
          width: 100%;
          background: transparent;
          border: none;
          color: #6B7280;
          font-size: 12px;
          font-family: inherit;
          cursor: pointer;
          padding: 6px 0;
          text-align: center;
          text-decoration: underline dotted;
          text-underline-offset: 3px;
          transition: color 120ms ease;
        }
        .login-demo:hover:not(:disabled) { color: #0F1318; }
        .login-demo:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .login-footer {
          margin-top: 18px;
          text-align: center;
          font-size: 10px;
          color: #9CA3AF;
          letter-spacing: 0.04em;
        }
        .login-toast {
          position: fixed;
          bottom: 28px;
          left: 50%;
          transform: translateX(-50%);
          z-index: 10;
          background: #0F1318;
          color: #fff;
          padding: 10px 16px;
          border-radius: 8px;
          font-size: 13px;
          box-shadow: 0 10px 30px rgba(0,0,0,0.2);
          animation: login-toast-in 180ms ease-out;
        }
        @keyframes login-toast-in {
          from { opacity: 0; transform: translate(-50%, 8px); }
          to   { opacity: 1; transform: translate(-50%, 0); }
        }
      `}</style>
    </div>
  );
}
