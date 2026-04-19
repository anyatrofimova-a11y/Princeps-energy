/**
 * SettingsPanel — full-screen overlay that renders one of three tabs
 * (Team, Notifications, API Keys) with real data from /api/v1/settings/*.
 *
 * Controlled from Sidebar.jsx: pass `open` (boolean), `activeTab` (one of
 * "team" | "notifications" | "apikeys"), and `onClose`. Tab selection
 * stays in Sidebar so the nav highlight and panel stay in sync.
 *
 * Token handling — the POST /api-keys response returns `token` in
 * plaintext exactly once. We flash it in a banner at the top until the
 * user dismisses it; the token is never stored in React state past that.
 */

import React, { useEffect, useState } from "react";

const C = {
  gold: "#F5B731", goldDark: "#E8A012", goldSurface: "rgba(245,183,49,0.08)",
  goldBorder: "rgba(245,183,49,0.3)",
  ink: "#1A1714", secondary: "#6B6560", tertiary: "#9C9590",
  border: "#E8E5DF", card: "#FFFFFF", bg: "#F7F8FA",
  danger: "#D14545", dangerBg: "#FEF2F2",
  warn: "#D4850C", warnBg: "#FFF7E6",
  ok: "#16A34A", okBg: "#F0FDF4",
};

const api = {
  async get(path) {
    const r = await fetch(path, { credentials: "include" });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(path, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: "DELETE", credentials: "include" });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  },
};

/* ─────────────────────────────────────────────────────────────
   Team
   ───────────────────────────────────────────────────────────── */

function TeamTab() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [invite, setInvite] = useState({ email: "", name: "", role: "analyst" });
  const [tmpPw, setTmpPw] = useState(null);

  const load = async () => {
    setState(s => ({ ...s, loading: true }));
    try {
      const data = await api.get("/api/v1/settings/team");
      setState({ loading: false, data, error: null });
    } catch (e) {
      setState({ loading: false, data: null, error: e.message });
    }
  };

  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setTmpPw(null);
    try {
      const r = await api.post("/api/v1/settings/team/invite", invite);
      setTmpPw(r.tmp_password);
      setInvite({ email: "", name: "", role: "analyst" });
      load();
    } catch (e) {
      setState(s => ({ ...s, error: e.message }));
    }
  };

  if (state.loading) return <div style={{ color: C.tertiary, padding: 24 }}>Loading team…</div>;
  if (state.error) return <div style={{ color: C.danger, padding: 24 }}>Error: {state.error}</div>;

  const { members = [], me } = state.data || {};

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: "8px 0" }}>
      <section>
        <h3 style={S.h3}>Team members ({members.length})</h3>
        <table style={S.table}>
          <thead>
            <tr>
              <th style={S.th}>Email</th>
              <th style={S.th}>Name</th>
              <th style={S.th}>Role</th>
              <th style={S.th}>Last login</th>
              <th style={S.th}>Status</th>
            </tr>
          </thead>
          <tbody>
            {members.map(m => (
              <tr key={m.user_id}>
                <td style={S.td}>
                  {m.email}{me && me.user_id === m.user_id && <span style={S.tagMe}>you</span>}
                </td>
                <td style={S.td}>{m.name || <em style={{ color: C.tertiary }}>—</em>}</td>
                <td style={S.td}>
                  <span style={{ ...S.tag, background: m.role === "admin" ? C.goldSurface : C.bg, color: m.role === "admin" ? C.goldDark : C.secondary }}>
                    {m.role}
                  </span>
                </td>
                <td style={{ ...S.td, color: C.tertiary }}>
                  {m.last_login ? new Date(m.last_login).toLocaleDateString() : "never"}
                </td>
                <td style={S.td}>
                  {m.password_set
                    ? <span style={{ color: C.ok, fontSize: 12 }}>active</span>
                    : <span style={{ color: C.warn, fontSize: 12 }}>no password</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h3 style={S.h3}>Invite someone</h3>
        {tmpPw && (
          <div style={S.banner(C.okBg, C.ok)}>
            <strong>Temporary password:</strong> <code style={S.code}>{tmpPw}</code>
            <div style={{ fontSize: 11, color: C.secondary, marginTop: 4 }}>
              Send this to the new member. They'll be prompted to reset on first login. You won't see it again.
            </div>
          </div>
        )}
        <form onSubmit={submit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <label style={S.label}>Email</label>
            <input style={S.input} type="email" required
              value={invite.email}
              onChange={e => setInvite({ ...invite, email: e.target.value })} />
          </div>
          <div>
            <label style={S.label}>Name</label>
            <input style={S.input}
              value={invite.name}
              onChange={e => setInvite({ ...invite, name: e.target.value })} />
          </div>
          <div>
            <label style={S.label}>Role</label>
            <select style={S.input}
              value={invite.role}
              onChange={e => setInvite({ ...invite, role: e.target.value })}>
              <option value="analyst">Analyst</option>
              <option value="manager">Manager</option>
              <option value="admin">Admin</option>
              <option value="viewer">Viewer</option>
            </select>
          </div>
          <button type="submit" style={S.btnPrimary}>Invite</button>
        </form>
      </section>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Notifications
   ───────────────────────────────────────────────────────────── */

function NotificationsTab() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const load = async () => {
    setState(s => ({ ...s, loading: true }));
    try {
      const data = await api.get("/api/v1/settings/notifications?limit=50");
      setState({ loading: false, data, error: null });
    } catch (e) {
      setState({ loading: false, data: null, error: e.message });
    }
  };
  useEffect(() => { load(); }, []);

  const togglePref = async (key) => {
    const cur = state.data.prefs[key];
    await api.put("/api/v1/settings/notifications/prefs", { [key]: !cur });
    load();
  };

  const markRead = async (id) => {
    await api.post(`/api/v1/settings/notifications/${id}/read`, {});
    load();
  };

  if (state.loading) return <div style={{ color: C.tertiary, padding: 24 }}>Loading…</div>;
  if (state.error) return <div style={{ color: C.danger, padding: 24 }}>Error: {state.error}</div>;

  const { prefs, notifications, unread_count } = state.data;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: "8px 0" }}>
      <section>
        <h3 style={S.h3}>Delivery preferences</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Toggle label="Weekly portfolio report (email)"
            value={prefs.weekly_report_enabled}
            onChange={() => togglePref("weekly_report_enabled")} />
          <Toggle label="Slack direct messages for critical alerts"
            value={prefs.slack_dm_enabled}
            onChange={() => togglePref("slack_dm_enabled")} />
          <div style={{ fontSize: 12, color: C.tertiary, marginTop: 8 }}>
            Timezone: <strong>{prefs.timezone}</strong>
          </div>
        </div>
      </section>

      <section>
        <h3 style={S.h3}>
          Recent activity {unread_count > 0 && <span style={S.badge}>{unread_count}</span>}
        </h3>
        {notifications.length === 0 ? (
          <div style={{ color: C.tertiary, fontSize: 13, padding: 16, background: C.bg, borderRadius: 8 }}>
            No agent notifications yet. They'll land here when agents fire Slack / email / in-app alerts.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {notifications.map(n => (
              <div key={n.id} style={{
                padding: 12,
                background: n.read_at ? C.card : C.goldSurface,
                border: `1px solid ${n.read_at ? C.border : C.goldBorder}`,
                borderRadius: 8,
                fontSize: 13,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 2 }}>
                      <SeverityDot s={n.severity} />
                      <strong style={{ color: C.ink }}>{n.title}</strong>
                      <span style={S.metaPill}>{n.channel}</span>
                      {n.source_agent && <span style={S.metaPill}>{n.source_agent}</span>}
                    </div>
                    {n.body && <div style={{ color: C.secondary, fontSize: 12 }}>{n.body}</div>}
                    <div style={{ color: C.tertiary, fontSize: 11, marginTop: 4 }}>
                      {new Date(n.created_at).toLocaleString()}
                    </div>
                  </div>
                  {!n.read_at && (
                    <button style={S.btnGhost} onClick={() => markRead(n.id)}>Mark read</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   API Keys
   ───────────────────────────────────────────────────────────── */

function ApiKeysTab() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [newName, setNewName] = useState("");
  const [freshToken, setFreshToken] = useState(null);

  const load = async () => {
    setState(s => ({ ...s, loading: true }));
    try {
      const data = await api.get("/api/v1/settings/api-keys");
      setState({ loading: false, data, error: null });
    } catch (e) {
      setState({ loading: false, data: null, error: e.message });
    }
  };
  useEffect(() => { load(); }, []);

  const create = async (e) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setFreshToken(null);
    try {
      const r = await api.post("/api/v1/settings/api-keys", { name: newName.trim() });
      setFreshToken(r.token);
      setNewName("");
      load();
    } catch (e) {
      setState(s => ({ ...s, error: e.message }));
    }
  };

  const revoke = async (id) => {
    if (!confirm("Revoke this API key? This cannot be undone.")) return;
    await api.del(`/api/v1/settings/api-keys/${id}`);
    load();
  };

  if (state.loading) return <div style={{ color: C.tertiary, padding: 24 }}>Loading…</div>;
  if (state.error) return <div style={{ color: C.danger, padding: 24 }}>Error: {state.error}</div>;

  const { keys = [] } = state.data || {};
  const active = keys.filter(k => !k.revoked_at);
  const revoked = keys.filter(k => k.revoked_at);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: "8px 0" }}>
      <section>
        <h3 style={S.h3}>Create key</h3>
        {freshToken && (
          <div style={S.banner(C.warnBg, C.warn)}>
            <div style={{ fontSize: 12, color: C.secondary, marginBottom: 6 }}>
              Copy this token now. It will not be shown again.
            </div>
            <code style={S.code}>{freshToken}</code>
            <button style={{ ...S.btnGhost, marginLeft: 8 }}
              onClick={() => {
                navigator.clipboard.writeText(freshToken);
              }}>
              Copy
            </button>
          </div>
        )}
        <form onSubmit={create} style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label style={S.label}>Key name</label>
            <input style={S.input}
              placeholder="e.g. zapier-prod"
              value={newName}
              onChange={e => setNewName(e.target.value)} />
          </div>
          <button type="submit" style={S.btnPrimary}>Generate</button>
        </form>
      </section>

      <section>
        <h3 style={S.h3}>Active keys ({active.length})</h3>
        {active.length === 0 ? (
          <div style={{ color: C.tertiary, fontSize: 13, padding: 16, background: C.bg, borderRadius: 8 }}>
            No active API keys. Generate one above to start making authenticated requests.
          </div>
        ) : (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Name</th>
                <th style={S.th}>Prefix</th>
                <th style={S.th}>Scopes</th>
                <th style={S.th}>Created</th>
                <th style={S.th}>Last used</th>
                <th style={S.th} />
              </tr>
            </thead>
            <tbody>
              {active.map(k => (
                <tr key={k.id}>
                  <td style={S.td}>{k.name}</td>
                  <td style={{ ...S.td, fontFamily: "monospace", color: C.secondary }}>{k.prefix}…</td>
                  <td style={S.td}>
                    {(k.scopes || []).map(s => <span key={s} style={S.metaPill}>{s}</span>)}
                  </td>
                  <td style={{ ...S.td, color: C.tertiary }}>
                    {new Date(k.created_at).toLocaleDateString()}
                  </td>
                  <td style={{ ...S.td, color: C.tertiary }}>
                    {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : <em>never</em>}
                  </td>
                  <td style={S.td}>
                    <button style={S.btnDanger} onClick={() => revoke(k.id)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {revoked.length > 0 && (
        <section>
          <h3 style={{ ...S.h3, color: C.tertiary }}>Revoked ({revoked.length})</h3>
          <table style={S.table}>
            <thead><tr>
              <th style={S.th}>Name</th>
              <th style={S.th}>Prefix</th>
              <th style={S.th}>Revoked</th>
            </tr></thead>
            <tbody>
              {revoked.map(k => (
                <tr key={k.id} style={{ opacity: 0.6 }}>
                  <td style={S.td}>{k.name}</td>
                  <td style={{ ...S.td, fontFamily: "monospace" }}>{k.prefix}…</td>
                  <td style={{ ...S.td, color: C.tertiary }}>
                    {new Date(k.revoked_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Panel shell
   ───────────────────────────────────────────────────────────── */

const TABS = [
  { id: "team", label: "Team" },
  { id: "notifications", label: "Notifications" },
  { id: "apikeys", label: "API Keys" },
];

export default function SettingsPanel({ open, activeTab, onTabChange, onClose }) {
  if (!open) return null;
  const tab = activeTab || "team";

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 500,
      background: "rgba(26,23,20,0.45)",
      display: "flex", alignItems: "flex-start", justifyContent: "center",
      padding: "48px 32px",
    }} onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: "min(960px, 100%)",
          maxHeight: "calc(100vh - 96px)",
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: 12,
          boxShadow: "0 24px 64px rgba(0,0,0,0.18)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <header style={{
          padding: "18px 24px 0",
          borderBottom: `1px solid ${C.border}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 style={{
              margin: 0, fontSize: 18, fontWeight: 700, color: C.ink,
              fontFamily: "'DM Sans', sans-serif",
            }}>
              Settings
            </h2>
            <button onClick={onClose} style={{
              background: "none", border: "none", cursor: "pointer",
              color: C.tertiary, fontSize: 20, padding: 4,
            }}>×</button>
          </div>
          <div style={{ display: "flex", gap: 4, marginTop: 12 }}>
            {TABS.map(t => (
              <button key={t.id}
                onClick={() => onTabChange?.(t.id)}
                style={{
                  padding: "8px 14px",
                  background: "transparent",
                  border: "none",
                  borderBottom: `2px solid ${tab === t.id ? C.gold : "transparent"}`,
                  color: tab === t.id ? C.ink : C.secondary,
                  fontWeight: tab === t.id ? 600 : 500,
                  fontSize: 13,
                  fontFamily: "'DM Sans', sans-serif",
                  cursor: "pointer",
                }}>
                {t.label}
              </button>
            ))}
          </div>
        </header>

        <main style={{ padding: "16px 24px 24px", overflowY: "auto", flex: 1 }}>
          {tab === "team" && <TeamTab />}
          {tab === "notifications" && <NotificationsTab />}
          {tab === "apikeys" && <ApiKeysTab />}
        </main>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────
   Small atoms
   ───────────────────────────────────────────────────────────── */

function Toggle({ label, value, onChange }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", fontSize: 13 }}>
      <span style={{
        width: 36, height: 20, borderRadius: 10,
        background: value ? C.gold : C.border,
        position: "relative", transition: "background 0.15s",
      }}>
        <span style={{
          position: "absolute",
          top: 2, left: value ? 18 : 2,
          width: 16, height: 16, borderRadius: "50%",
          background: "#fff",
          transition: "left 0.15s",
          boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
        }} />
      </span>
      <input type="checkbox" checked={value} onChange={onChange} style={{ display: "none" }} />
      <span style={{ color: C.ink }}>{label}</span>
    </label>
  );
}

function SeverityDot({ s }) {
  const c = s === "alert" ? C.danger : s === "warn" ? C.warn : C.ok;
  return <span style={{ width: 8, height: 8, borderRadius: "50%", background: c, display: "inline-block" }} />;
}

const S = {
  h3: { margin: "0 0 12px", fontSize: 13, fontWeight: 700, color: C.ink, fontFamily: "'DM Sans', sans-serif", textTransform: "uppercase", letterSpacing: "0.06em" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", fontWeight: 600, color: C.tertiary, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.04em", borderBottom: `1px solid ${C.border}` },
  td: { padding: "10px", borderBottom: `1px solid ${C.border}`, color: C.ink, fontSize: 13 },
  tag: { padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600 },
  tagMe: { marginLeft: 8, padding: "1px 6px", borderRadius: 4, fontSize: 10, background: C.goldSurface, color: C.goldDark, fontWeight: 600 },
  metaPill: { marginLeft: 6, padding: "1px 6px", borderRadius: 4, fontSize: 10, background: C.bg, color: C.tertiary, fontWeight: 500 },
  badge: { marginLeft: 8, padding: "2px 8px", borderRadius: 10, fontSize: 11, background: C.goldSurface, color: C.goldDark, fontWeight: 700 },
  label: { display: "block", fontSize: 11, color: C.tertiary, fontWeight: 600, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.04em" },
  input: { padding: "8px 10px", border: `1px solid ${C.border}`, borderRadius: 6, fontSize: 13, minWidth: 160, fontFamily: "'DM Sans', sans-serif", color: C.ink },
  code: { fontFamily: "monospace", background: C.bg, padding: "3px 6px", borderRadius: 4, fontSize: 12, color: C.ink, wordBreak: "break-all" },
  btnPrimary: { padding: "8px 16px", background: C.gold, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" },
  btnGhost: { padding: "4px 10px", background: "transparent", color: C.secondary, border: `1px solid ${C.border}`, borderRadius: 4, fontSize: 11, cursor: "pointer" },
  btnDanger: { padding: "4px 10px", background: "transparent", color: C.danger, border: `1px solid ${C.danger}`, borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: "pointer" },
  banner: (bg, fg) => ({ padding: 12, background: bg, border: `1px solid ${fg}44`, borderRadius: 6, marginBottom: 12, fontSize: 13 }),
};
