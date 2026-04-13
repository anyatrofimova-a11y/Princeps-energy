import React from "react";
import { createRoot } from "react-dom/client";
import { SiteProvider } from "./SiteContext";
import { WorkspaceProvider } from "./contexts/WorkspaceContext";
import App from "./App";
import "normalize.css";
import "@blueprintjs/core/lib/css/blueprint.css";
import "@blueprintjs/icons/lib/css/blueprint-icons.css";
import "@blueprintjs/select/lib/css/blueprint-select.css";
import "@blueprintjs/table/lib/css/table.css";
import "./styles.css";

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("Princeps error:", error, info); }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          height: "100vh", fontFamily: "'Inter', 'DM Sans', -apple-system, sans-serif",
          background: "#F9FAFB", color: "#111827",
        }}>
          <img src="/logo-princeps.png" alt="Princeps" width="48" height="48" style={{ marginBottom: 24, objectFit: "contain" }} />
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 8px" }}>Something went wrong</h2>
          <p style={{ fontSize: 14, color: "#6B7280", margin: "0 0 24px", maxWidth: 400, textAlign: "center" }}>
            An unexpected error occurred. This has been logged. Please try refreshing the page.
          </p>
          <div style={{ display: "flex", gap: 12 }}>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                padding: "10px 24px", borderRadius: 8, border: "1px solid #E5E7EB",
                background: "white", color: "#374151", fontSize: 14, fontWeight: 500,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >Retry</button>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: "10px 24px", borderRadius: 8, border: "none",
                background: "#D4A018", color: "white", fontSize: 14, fontWeight: 600,
                cursor: "pointer", fontFamily: "inherit",
              }}
            >Reload Page</button>
          </div>
          {process.env.NODE_ENV === "development" && (
            <details style={{ marginTop: 24, maxWidth: 600, width: "100%" }}>
              <summary style={{ cursor: "pointer", fontSize: 11, color: "#9CA3AF" }}>Developer details</summary>
              <pre style={{ fontSize: 10, color: "#9CA3AF", whiteSpace: "pre-wrap", marginTop: 8, padding: 12, background: "#F3F4F6", borderRadius: 6, overflow: "auto", maxHeight: 200 }}>
                {this.state.error.message}
              </pre>
            </details>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary><SiteProvider><WorkspaceProvider><App /></WorkspaceProvider></SiteProvider></ErrorBoundary>
);
