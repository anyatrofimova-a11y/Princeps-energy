import React, { useState, useCallback, useRef } from "react";
import { InputGroup, Icon, Menu, MenuItem, MenuDivider, Tag } from "@blueprintjs/core";

const COMMANDS = [
  { id: "new_site", label: "New site assessment", icon: "map-marker", category: "command" },
  { id: "grid_study", label: "Run grid study", icon: "flash", category: "command" },
  { id: "financial", label: "Financial model", icon: "bank-account", category: "command" },
  { id: "report", label: "Generate PDF report", icon: "document", category: "command" },
  { id: "parcel_search", label: "Search land parcels", icon: "search-around", category: "command" },
  { id: "optimizer", label: "System optimizer", icon: "settings", category: "command" },
];

export default function AISearchBar({ onSelect }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const timerRef = useRef(null);

  const handleChange = useCallback((e) => {
    const q = e.target.value;
    setQuery(q);
    if (!q.trim()) { setResults([]); setOpen(false); return; }

    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      const matched = COMMANDS.filter(c => c.label.toLowerCase().includes(q.toLowerCase()));
      // Try API search
      let apiResults = [];
      try {
        const r = await fetch(`/api/regulatory/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, limit: 3 }),
        });
        if (r.ok) {
          const data = await r.json();
          if (Array.isArray(data)) apiResults = data.map(d => ({ ...d, category: "regulatory" }));
        }
      } catch {}
      setResults([...matched, ...apiResults]);
      setOpen(true);
    }, 300);
  }, []);

  const handleSelect = useCallback((item) => {
    setOpen(false);
    setQuery("");
    onSelect?.(item);
  }, [onSelect]);

  return (
    <div style={{ position: "relative" }}>
      <InputGroup
        leftIcon="search"
        placeholder="Search sites, substations, regulations, or type a command..."
        value={query}
        onChange={handleChange}
        onFocus={() => query && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 200)}
        round
      />
      {open && results.length > 0 && (
        <div style={{
          position: "absolute", top: "100%", left: 0, right: 0, zIndex: 100,
          background: "#fff", border: "1px solid #E5E7EB", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(0,0,0,0.12)", marginTop: 4, maxHeight: 300, overflowY: "auto",
        }}>
          <Menu>
            {results.some(r => r.category === "command") && <MenuDivider title="Commands" />}
            {results.filter(r => r.category === "command").map(r => (
              <MenuItem key={r.id} icon={r.icon} text={r.label} onClick={() => handleSelect(r)} />
            ))}
            {results.some(r => r.category === "regulatory") && <MenuDivider title="Regulatory Docs" />}
            {results.filter(r => r.category === "regulatory").map((r, i) => (
              <MenuItem key={i} icon="document" text={r.title || r.chunk_text?.slice(0, 60)}
                labelElement={<Tag minimal small>{r.source}</Tag>}
                onClick={() => handleSelect(r)} />
            ))}
          </Menu>
        </div>
      )}
    </div>
  );
}
