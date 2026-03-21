import React from "react";
import { createRoot } from "react-dom/client";
import { SiteProvider } from "./SiteContext";
import { WorkspaceProvider } from "./contexts/WorkspaceContext";
import App from "./App";
import "./styles.css";

class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null, info: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) {
    console.error("ErrorBoundary caught:", error, info);
    this.setState({ info });
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 20, fontFamily: "monospace", maxWidth: "90vw" }}>
          <h2>Something went wrong</h2>
          <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 12, color: "#dc2626" }}>{this.state.error.message}</pre>
          {this.state.info?.componentStack && (
            <details style={{ marginTop: 10 }}>
              <summary style={{ cursor: "pointer", fontSize: 12 }}>Component Stack</summary>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 10, color: "#6b7280", maxHeight: 300, overflow: "auto" }}>{this.state.info.componentStack}</pre>
            </details>
          )}
          <button onClick={() => this.setState({ error: null, info: null })} style={{ marginTop: 10, padding: "8px 16px", cursor: "pointer" }}>Retry</button>
          <button onClick={() => window.location.reload()} style={{ marginTop: 10, marginLeft: 8, padding: "8px 16px", cursor: "pointer" }}>Hard Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(
  <ErrorBoundary><SiteProvider><WorkspaceProvider><App /></WorkspaceProvider></SiteProvider></ErrorBoundary>
);
