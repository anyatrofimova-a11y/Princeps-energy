// Substation Tracker — admin routes.
//
// Import this from main.jsx after Alerts frontend merge; wrap in
// <Route> inside <Routes>. Suggested splice:
//
//   import trackerRoutes from "./routes/trackerRoutes.jsx";
//   ...
//   <Routes>
//     {/* …existing app routes… */}
//     {trackerRoutes}
//   </Routes>
//
// Or spread the fragment element directly:
//
//   {trackerRoutes}
//
// The routes below cover:
//   /tracker-admin                  → TrackerDashboard
//   /tracker-admin/review/:id       → TrackerDashboard (deep-link detail)
//
// TODO (auth): if/when the app has an auth guard component
// (e.g. <RequireAuth role="admin">), wrap both <Route element=…>
// entries below. Until then we render the dashboard directly so
// local dev works.

import React from "react";
import { Route } from "react-router-dom";
import TrackerDashboard from "../pages/Tracker/TrackerDashboard";

// Placeholder — swap for the app's actual guard when it lands.
function AuthGuard({ children }) {
  // TODO: integrate with real auth. For now this is a pass-through so
  // /tracker-admin renders in dev and in mock mode.
  return children;
}

const trackerRoutes = (
  <>
    <Route
      path="/tracker-admin"
      element={
        <AuthGuard>
          <TrackerDashboard admin />
        </AuthGuard>
      }
    />
    <Route
      path="/tracker-admin/review/:id"
      element={
        <AuthGuard>
          <TrackerDashboard admin />
        </AuthGuard>
      }
    />
  </>
);

export default trackerRoutes;
