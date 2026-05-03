# Login Page Spec — COUNCIL-LOG audit

Author: COUNCIL-LOG · 2026-04-21 · Target bots: BOT-LOG-UI + BOT-LOG-AUTH.

## A. Current state (file:line)

Auth is already scaffolded but never gated on the frontend:

- Backend router mounted at `/api/v1/auth` — `app/routers/auth.py:15` — endpoints `POST /register`, `POST /login`, `POST /refresh`, `GET /me`, `POST /api-key` (`app/routers/auth.py:30,63,95,106,120`).
- JWT + password helpers — `app/auth.py:20-100` (HS256, `JWT_SECRET` env, bcrypt with SHA-256 fallback, `JWT_EXPIRY_SECONDS` default 86400).
- DB — `users` table with `user_id uuid, email, name, org_name, password_hash, role, api_key, created_at, last_login` at `sql/migrate_auth.sql:4-14`.
- Auth dependency `get_current_user` — `app/deps.py:78` — but `PRINCEPS_DEMO_MODE=true` short-circuits to a hardcoded demo user (`app/deps.py:15-26, 46`). In production all protected routes currently pass without a token.
- Router registered via name list in `app/main.py:238` (`"auth"`).
- Frontend has **no login page, no auth gate, no auth client**. No grep hits for `/api/v1/auth`, no `Authorization: Bearer` header wiring in `feasi-frontend/src/services/api*`. Dashboard reads `localStorage.getItem("princeps.user.firstName")` / `princeps.user.email` (`feasi-frontend/src/components/Dashboard.jsx:369,371`) but nothing writes those keys. Settings team members live only in `localStorage` under `princeps_settings` (`feasi-frontend/src/SiteContext.jsx:25,39`) — no backend persistence for `teamMembers[]` (`app/routers/settings.py` has no team endpoints — confirmed by grep).
- GridCanvas component — `feasi-frontend/src/components/GridCanvas.jsx:19` — props `{ className, style, dark }`, auto-sizes to parent via `ResizeObserver`; Dashboard mounts it at `Dashboard.jsx:420` with `.mc-bg-canvas` CSS at `Dashboard.jsx:488` (`position:absolute; inset:0; z-index:0; pointer-events:none`) and lifts siblings to `z-index:2` at `Dashboard.jsx:496-499`.
- App entry — `feasi-frontend/src/main.jsx:115` renders `<BrowserRouter>` with routes; the legacy catch-all `*` mounts `<LegacyApp />` wrapping `<App />` at `main.jsx:276`. `App.jsx:771` unconditionally returns `<AppShell>`. **This is where the gate goes.**

## B. Visual / UX spec

Full-bleed GridCanvas background (reuse, do not reimplement):

- Root `<div className="login-root">` — `position:relative; min-height:100vh; background:var(--bg)` (the `#F2F3F5` GridCanvas paints over).
- `<GridCanvas className="login-bg-canvas" />` — same CSS pattern as Mission Control: `position:absolute; inset:0; pointer-events:none; z-index:0`. Do not wrap or re-style the canvas element — GridCanvas already measures its parent.
- All card content sits in `<main className="login-card">` with `position:relative; z-index:2`.

Centered card:
- `width:380px; padding:32px 28px 24px; border:1px solid rgba(15,19,24,0.08); border-radius:14px; background:#FFFFFF; box-shadow:0 24px 56px -28px rgba(15,19,24,0.28), 0 2px 6px rgba(15,19,24,0.05); font-family:"DM Sans",-apple-system,sans-serif`.
- Centered via flex on `.login-root`: `display:flex; align-items:center; justify-content:center`.

Card contents (top to bottom):
1. Princeps wordmark — `<img src="/logo-princeps.png" width=32 height=32>` + `<span>PRINCEPS</span>` (letter-spacing 0.18em, weight 600, 13px).
2. Tagline — "Energy infrastructure, engineered." — 12px, `color:#6B7280`.
3. Form: `email` (type=email, autocomplete=username), `password` (type=password, autocomplete=current-password). Inputs: 40px height, 1px border, 8px radius, DM Sans 13px.
4. Primary button — "Sign in" — full-width, 40px, background `#D4A018` (gold), `#FFFFFF` text, weight 600. Disabled state while request pending.
5. Divider — thin rule + centered "or" label.
6. SSO buttons — "Continue with Google" and "Continue with GitHub" — full-width ghost buttons with 16px provider glyph on the left. Wired to `onClick={() => window.alert("SSO coming soon")}` stubs for v1 (track via `data-stub="true"`).
7. Demo row — only rendered when `localStorage.getItem("princeps.demoMode") !== "off"`. Text-button "Demo mode — continue as Anya T." at 12px, `#6B7280`. Calls `loginAsDemo()` (see state below).
8. Footer — 11px, `#9CA3AF` — "v{import.meta.env.VITE_APP_VERSION ?? 'dev'} · © 2026 Princeps".

Interaction:
- Invalid credentials (HTTP 401): add `.login-card--shake` class for 420ms (CSS keyframes `translateX -6px/+6px 3 cycles`), surface inline error "Invalid email or password" in red 12px under the password field. Clear error on next keystroke.
- Success: fade card opacity 1 → 0 over 280ms, emit a custom event `window.dispatchEvent(new CustomEvent("princeps:login-pulse"))` that GridCanvas ignores (it auto-spawns anyway). After 280ms `setIsAuthenticated(true)` and re-render → Mission Control takes over. No hard `window.location` reload.
- Keyboard: Enter submits form; Esc clears the current input.
- Accessibility: `<form role="form" aria-label="Sign in">`, label-for on every input, `aria-live="polite"` on error text.

## C. Routing & gate

Insert gate in `feasi-frontend/src/App.jsx` immediately above the existing return at `App.jsx:771`:

```
const [isAuthenticated, setIsAuthenticated] = useState(() => !!localStorage.getItem("princeps.auth.token"));
useEffect(() => {
  const onLogin = () => setIsAuthenticated(true);
  const onLogout = () => setIsAuthenticated(false);
  window.addEventListener("princeps:login", onLogin);
  window.addEventListener("princeps:logout", onLogout);
  return () => { window.removeEventListener("princeps:login", onLogin); window.removeEventListener("princeps:logout", onLogout); };
}, []);
if (!isAuthenticated) return <LoginPage onAuthenticated={() => setIsAuthenticated(true)} />;
```

Placement: lines 770–771 of `App.jsx`. `<LoginPage />` is imported at top of the file alongside the other eager components (it is small; no lazy). The gate sits in `App.jsx` (not `main.jsx`) so `/canvas/*`, `/design/*`, `/intelligence/*` routes defined in `main.jsx:122-275` remain reachable for deep-link demos without the gate — if full-app gating is later required, move the gate into `main.jsx` above the `<Routes>`. Document this choice in the PR description.

## D. State (localStorage keys)

On successful login write (all as strings):
- `princeps.auth.token` — JWT from `POST /api/v1/auth/login`.
- `princeps.user.email` — from response `user.email`.
- `princeps.user.firstName` — derived: `display_name?.split(" ")[0] || name?.split(" ")[0] || email.split("@")[0]` (capitalised).
- `princeps.workspaceName` — from `user.org_name` (fallback `"Princeps Workspace"`).

Keep the existing `princeps_settings` key untouched — Settings/Team already uses it (`SiteContext.jsx:25`). Dashboard's greeting logic at `Dashboard.jsx:367-377` already reads `princeps.user.firstName` then falls back to `princeps.user.email` then `"Anya"`, so these four keys are sufficient.

Logout handler: clear the four keys, dispatch `window.dispatchEvent(new Event("princeps:logout"))`.

`api.js` interceptor (new, shared with BOT-LOG-AUTH contract): read `princeps.auth.token` and set `Authorization: Bearer ${token}` on every outbound request. On 401 response clear the four keys and dispatch `princeps:logout`.

## E. Backend

Reuse the existing router at `app/routers/auth.py:15` (prefix `/api/v1/auth`). **Do not** create a second `/api/auth` — normalise the frontend to `/api/v1/auth/...`.

Minimum viable contract (already implemented; only v1 demo-rule additions needed):
- `POST /api/v1/auth/login {email, password}` → `{token, user: {user_id, email, name, org_name, role}}`. Extend response to include `display_name` (alias of `name`) and `first_name` (server-derived) — one-line change in `auth.py:83-92`.
- `GET /api/v1/auth/me` → current user from JWT — already exists (`auth.py:106`).
- `POST /api/v1/auth/logout` → `{ok: true}` — **new**; server-side it is a no-op (JWT is stateless) but gives the frontend a clean hook and a place to hang future token-revocation.

Demo rule (v1 only, behind `PRINCEPS_DEMO_MODE` env, default **on** in dev, **off** in prod):

In `auth.py:login()` before the password check, if `DEMO_MODE`:
1. Accept password matching `^.{4,}$` for any email in the workspace's `settingsForm.teamMembers[]` (read from `princeps_settings` via a new read-only helper — but team members are frontend-only today, so for v1 accept any email matching `@princeps\.app$` OR the hardcoded owner `anya.trofimova@yahoo.com`).
2. Auto-provision the user row (INSERT IF NOT EXISTS) on first demo login so `/me` works.

Token: HS256 JWT with 7-day expiry. Change `JWT_EXPIRY_SECONDS` default in `app/auth.py:22` from 86400 to 604800. Secret from env `PRINCEPS_JWT_SECRET` with dev fallback (currently called `JWT_SECRET` at `app/auth.py:20` — rename with a one-line `os.environ.get("PRINCEPS_JWT_SECRET") or os.environ.get("JWT_SECRET") or secrets.token_hex(32)` to support both).

**No new DB tables.** `users` table at `sql/migrate_auth.sql:4` is sufficient. Team-member persistence is deferred to a later story.

## F. File plan — two execution bots, no overlap

**BOT-LOG-UI** owns:
- `feasi-frontend/src/components/LoginPage.jsx` (new)
- `feasi-frontend/src/components/LoginPage.css` (new, OR inline `<style>` block matching Dashboard pattern — pick inline for consistency with `Dashboard.jsx:474`)
- Gate mount in `feasi-frontend/src/App.jsx` at line 771 (≤ 15 line change)
- `feasi-frontend/src/services/api.js` Authorization header interceptor (≤ 10 line change)

BOT-LOG-UI **forbidden** to touch: any file under `app/`, any `sql/*.sql`, any `utils/*.py`, `main.py`, `main.jsx` routing.

**BOT-LOG-AUTH** owns:
- `app/routers/auth.py` — add `POST /logout`, extend login response with `display_name`/`first_name`, add demo-mode email allowlist (≤ 40 line change)
- `app/auth.py` — rename/alias `JWT_SECRET` → `PRINCEPS_JWT_SECRET`, bump default expiry to 604800 (≤ 6 line change)
- `utils/auth.py` (new, optional) — tiny JWT helper wrappers if any util/script needs them; otherwise skip the file
- **No** router-mount change in `app/main.py` — `"auth"` is already in the list at `main.py:238`.

BOT-LOG-AUTH **forbidden** to touch: any file under `feasi-frontend/`, any other router, `deps.py` (keep demo-mode semantics identical), any DB migration (no schema change).

## G. Acceptance criteria

1. **Gate blocks** — visit `/` with `localStorage.princeps.auth.token` cleared → LoginPage renders, Mission Control DOM not mounted. Verify via DevTools: no `.mc-root` in the tree, only `.login-root`.
2. **Valid login redirects** — submit `anya.trofimova@yahoo.com` + any 4+ char password → `POST /api/v1/auth/login` returns 200, four localStorage keys populated, card fades, Mission Control appears, top-bar shows `Good {greeting}, Anya`.
3. **Demo button works** — with `localStorage.princeps.demoMode` unset (or any value other than `"off"`) the demo row is visible; clicking it sets the four keys with `anya.trofimova@yahoo.com` / first-name `Anya` and skips network call; with `princeps.demoMode=="off"` the row is absent.
4. **Refresh keeps you in** — after login, hard reload → still on Mission Control (gate sees the token). `GET /api/v1/auth/me` optionally called on mount to verify the token is still valid; 401 → clear keys + show LoginPage.
5. **Logout returns to login** — dispatch `princeps:logout` (or click the Settings logout button, whichever ships) → LoginPage renders, keys cleared, no Mission Control flash.
6. **GridCanvas parity** — LoginPage and Mission Control both mount the **same** `GridCanvas` component from `feasi-frontend/src/components/GridCanvas.jsx`; visual diff between the two backgrounds at 1440×900 shows only the card overlay differing, the animated node/edge/pulse layer is pixel-equivalent within one animation frame.
7. **Invalid credentials** — wrong password → 401 response, `.login-card--shake` class applied for 420ms, error text "Invalid email or password" rendered, inputs not cleared, next keystroke clears the error.
8. **Bot collision check** — `git diff --name-only` for the two PRs shows zero overlapping files.
