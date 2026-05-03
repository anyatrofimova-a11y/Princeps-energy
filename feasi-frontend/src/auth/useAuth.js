/**
 * useAuth — thin localStorage-backed auth hook for Princeps.
 *
 * Reads/writes:
 *   - princeps.auth.token      (presence => authenticated)
 *   - princeps.user.email
 *   - princeps.user.firstName
 *   - princeps.user.role
 *
 * Exposes: { isAuthenticated, user, login, logout }
 *
 * login/logout fire a CustomEvent `princeps-auth-changed` so other tabs /
 * components can react without prop drilling. Also listens to the "storage"
 * event so cross-tab logout takes effect instantly.
 */
import { useCallback, useEffect, useState } from "react";

const TOKEN_KEY = "princeps.auth.token";
const EMAIL_KEY = "princeps.user.email";
const FIRST_NAME_KEY = "princeps.user.firstName";
const ROLE_KEY = "princeps.user.role";

const AUTH_EVENT = "princeps-auth-changed";

function readToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

function readUser() {
  try {
    return {
      email: localStorage.getItem(EMAIL_KEY) || "",
      firstName: localStorage.getItem(FIRST_NAME_KEY) || "",
      role: localStorage.getItem(ROLE_KEY) || "",
    };
  } catch {
    return { email: "", firstName: "", role: "" };
  }
}

export function useAuth() {
  const [token, setToken] = useState(() => readToken());
  const [user, setUser] = useState(() => readUser());

  useEffect(() => {
    const refresh = () => {
      setToken(readToken());
      setUser(readUser());
    };
    window.addEventListener(AUTH_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(AUTH_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  const login = useCallback(({ email, firstName, token: newToken, role }) => {
    try {
      if (newToken) localStorage.setItem(TOKEN_KEY, String(newToken));
      if (email) localStorage.setItem(EMAIL_KEY, String(email));
      if (firstName) localStorage.setItem(FIRST_NAME_KEY, String(firstName));
      if (role) localStorage.setItem(ROLE_KEY, String(role));
    } catch (err) {
      console.warn("[useAuth] localStorage write failed:", err);
    }
    setToken(newToken || "");
    setUser({ email: email || "", firstName: firstName || "", role: role || "" });
    try {
      window.dispatchEvent(new CustomEvent(AUTH_EVENT, {
        detail: { type: "login", email, firstName, role },
      }));
    } catch {}
  }, []);

  const logout = useCallback(() => {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(EMAIL_KEY);
      localStorage.removeItem(FIRST_NAME_KEY);
      localStorage.removeItem(ROLE_KEY);
    } catch (err) {
      console.warn("[useAuth] localStorage clear failed:", err);
    }
    setToken("");
    setUser({ email: "", firstName: "", role: "" });
    try {
      window.dispatchEvent(new CustomEvent(AUTH_EVENT, { detail: { type: "logout" } }));
    } catch {}
  }, []);

  return {
    isAuthenticated: Boolean(token && token.length > 0),
    user,
    login,
    logout,
  };
}

export default useAuth;
