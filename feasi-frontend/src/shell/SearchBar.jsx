import {useState, useEffect, useRef} from 'react';
import {useNavigate} from 'react-router-dom';
import {useSelection} from '../workshop/useSelection.jsx';

/**
 * Top-bar ontology-wide search. Cmd-K from anywhere focuses it.
 * Calls /api/workshop/search?q=...; results dropdown navigates to
 * /v2/object/:type/:rid.
 */
export function SearchBar() {
  const [q, setQ] = useState('');
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();
  const {setSelectedAssetRid} = useSelection();

  // Cmd/Ctrl-K focuses the search.
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === 'Escape') {
        setOpen(false);
        inputRef.current?.blur();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Debounced fetch.
  useEffect(() => {
    if (q.trim().length < 2) {
      setResults(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`/api/workshop/search?q=${encodeURIComponent(q)}`);
        if (!r.ok) throw new Error(`search ${r.status}`);
        const data = await r.json();
        setResults(data);
      } catch (err) {
        setResults({error: String(err)});
      }
    }, 180);
    return () => clearTimeout(t);
  }, [q]);

  const pick = (item) => {
    setSelectedAssetRid(item.rid);
    navigate(`/v2/object/${item.type}/${ridLocator(item.rid)}`);
    setOpen(false);
    setQ('');
  };

  return (
    <div className="px2-search">
      <input
        ref={inputRef}
        type="text"
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => q && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        placeholder="Search ontology  (⌘K)"
        className="px2-search-input"
      />
      {open && results && (
        <div className="px2-search-dropdown">
          {results.error && <div className="px2-search-empty">{results.error}</div>}
          {!results.error && (results.items?.length ?? 0) === 0 && (
            <div className="px2-search-empty">no matches</div>
          )}
          {results.items?.map((it) => (
            <button key={it.rid} className="px2-search-item" onMouseDown={() => pick(it)}>
              <span className="px2-search-type">{it.type}</span>
              <span className="px2-search-name">{it.name}</span>
              {it.snippet && <span className="px2-search-snippet">{it.snippet}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ridLocator(rid) {
  if (!rid) return '';
  const parts = rid.split('.');
  return parts.length >= 5 ? parts.slice(4).join('.') : rid;
}
