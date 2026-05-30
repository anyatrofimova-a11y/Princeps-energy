import {Outlet} from 'react-router-dom';
import {SelectionProvider} from '../workshop/useSelection.jsx';
import {SiteProvider} from '../SiteContext';
import {WorkspaceProvider} from '../contexts/WorkspaceContext';
import {SearchBar} from './SearchBar.jsx';
import {HierarchyExplorer} from './HierarchyExplorer.jsx';
import {Inspector} from './Inspector.jsx';
import {ConstellationBackdrop} from './ConstellationBackdrop.jsx';
import V2LiveTape from './V2LiveTape.jsx';
import V2AgentActivity from './V2AgentActivity.jsx';
// Princeps-AI chat rail — floating bottom-right card. Already wires the
// /chat/session + /chat/{sid}/message SSE stream and renders tool calls
// as spinning chips. Mounted globally in App.jsx for non-v2 routes; the
// v2 AppShell needs its own mount because /v2 sits on a parallel route
// tree (see main.jsx — /v2 mounts <AppShell>, not <App>).
import ChatRail from '../components/shell/ChatRail';
import './shell-v2.css';

/**
 * Princeps v2 shell — Foundry/Kognitwin three-column layout.
 *
 *   topbar (logo + search + user)
 *   ├─ explorer ── object-page (Outlet) ── inspector ─┤
 *   live tape (DEMAND / WIND / SOLAR / CARBON / FREQ / PRICE)
 *
 * No floating drawers, no overlay leakage. Inspector is always visible
 * (collapsible to spine on narrow screens). Explorer drives selection;
 * Object Page is whatever route resolved; Inspector mirrors selection.
 *
 * Wraps SiteProvider + WorkspaceProvider so legacy components used as
 * modules (MissionControl, Dashboard, etc.) have their context.
 */
export default function AppShell() {
  return (
    <SiteProvider>
      <WorkspaceProvider>
        <SelectionProvider>
          <div className="px2-shell">
            <ConstellationBackdrop />

            <header className="px2-topbar">
              <div className="px2-brand">
                <span className="px2-brand-mark">P</span>
                <span className="px2-brand-name">Princeps</span>
              </div>
              <SearchBar />
              <div className="px2-topbar-right">
                <span className="px2-user">A. Trofimova</span>
              </div>
            </header>

            <div className="px2-body">
              <aside className="px2-explorer">
                <HierarchyExplorer />
              </aside>
              <main className="px2-main">
                <Outlet />
              </main>
              <aside className="px2-inspector">
                <Inspector />
              </aside>
            </div>

            <footer className="px2-live-strip">
              <V2LiveTape />
              <V2AgentActivity />
            </footer>

            {/* Princeps AI — floating chat bubble. Renders bottom-right;
                an override below in shell-v2.css raises it above the live
                strip so it doesn't tuck under the footer. */}
            <ChatRail parcelId={null} projectId={null} />
          </div>
        </SelectionProvider>
      </WorkspaceProvider>
    </SiteProvider>
  );
}
