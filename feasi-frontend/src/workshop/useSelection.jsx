import {createContext, useCallback, useContext, useMemo, useState} from 'react';

/**
 * Workshop selection context — single source of truth for "what is the user
 * looking at right now". Cloned/table/3D/SLD components all read and write
 * here so that bidirectional linking just works.
 *
 * Surface (intentionally small):
 *   selectedAssetRid    — Princeps RID of the focused ontology object
 *   selectedTagId       — sub-asset tag (e.g. PnID tag, sensor id)
 *   highlightedRowIds   — multi-select for tables (Set<string>)
 *   focusedSeriesId     — trend-chart row that's currently highlighted
 *
 * If nothing is selected the value is null. Components must tolerate null —
 * the context is mounted at app root so the provider is always present.
 */

const SelectionContext = createContext(null);

export function SelectionProvider({children}) {
  const [selectedAssetRid, setSelectedAssetRidRaw] = useState(null);
  const [selectedTagId, setSelectedTagId] = useState(null);
  const [highlightedRowIds, setHighlightedRowIds] = useState(() => new Set());
  const [focusedSeriesId, setFocusedSeriesId] = useState(null);

  const setSelectedAssetRid = useCallback((rid) => {
    setSelectedAssetRidRaw(rid);
    setSelectedTagId(null);
  }, []);

  const toggleRow = useCallback((id) => {
    setHighlightedRowIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearRows = useCallback(() => setHighlightedRowIds(new Set()), []);

  const value = useMemo(() => ({
    selectedAssetRid,
    setSelectedAssetRid,
    selectedTagId,
    setSelectedTagId,
    highlightedRowIds,
    toggleRow,
    clearRows,
    focusedSeriesId,
    setFocusedSeriesId,
  }), [selectedAssetRid, setSelectedAssetRid, selectedTagId, highlightedRowIds, toggleRow, clearRows, focusedSeriesId]);

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) {
    throw new Error('useSelection must be used inside <SelectionProvider>');
  }
  return ctx;
}
