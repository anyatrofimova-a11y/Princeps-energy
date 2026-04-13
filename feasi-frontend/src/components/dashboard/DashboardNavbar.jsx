import React from "react";
import AISearchBar from "./AISearchBar";

export default function DashboardNavbar({ onSearchSelect }) {
  return (
    <div className="pd2-navbar" style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "0 0 20px", marginBottom: 4,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <img src="/logo-princeps.png" alt="" style={{ width: 32, height: 32, objectFit: "contain" }} />
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--ink)", letterSpacing: "-0.02em" }}>Princeps</div>
          <div style={{ fontSize: 11, color: "var(--muted-light)", fontWeight: 500 }}>Energy Infrastructure Intelligence</div>
        </div>
      </div>
      <div className="pd2-search-wrap">
        <AISearchBar onSelect={onSearchSelect} />
      </div>
      <div style={{ display: "flex", gap: 8, color: "var(--muted)" }}>
        <span style={{ fontSize: 12, color: "var(--muted-light)" }}>
          {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
        </span>
      </div>
    </div>
  );
}
