import {useState, memo} from 'react';
import {useSelection} from './useSelection.jsx';

/**
 * Kognitwin-pattern asset hierarchy with rolled-up red/yellow/blue/green
 * issue badges per node.
 *
 * Props:
 *   nodes     [{rid, name, children, badges: {red,yellow,blue,green}}]
 *   defaultExpandDepth  number — open levels by default (default 1)
 *   onSelect  (rid) => void   — also fires the global selection context
 *
 * Counts are pre-rolled-up on the server (don't sum client-side; that costs
 * a render per badge change and gives wrong numbers under filtering).
 */
export function AssetHierarchyTree({nodes, defaultExpandDepth = 1, onSelect}) {
  return (
    <ul className="px-tree" role="tree">
      {nodes.map((n) => (
        <TreeNode
          key={n.rid}
          node={n}
          depth={0}
          defaultExpandDepth={defaultExpandDepth}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );
}

const TreeNode = memo(function TreeNode({node, depth, defaultExpandDepth, onSelect}) {
  const [open, setOpen] = useState(depth < defaultExpandDepth);
  const {selectedAssetRid, setSelectedAssetRid} = useSelection();
  const hasChildren = (node.children?.length ?? 0) > 0;
  const isSelected = selectedAssetRid === node.rid;

  const select = () => {
    // Group / header nodes (rid starts with "group:") are containers only —
    // expand/collapse but never become the focused selection. Prevents the
    // inspector from trying to render synthetic dtmi-grouping rids.
    if (typeof node.rid === 'string' && node.rid.startsWith('group:')) {
      setOpen((v) => !v);
      return;
    }
    setSelectedAssetRid(node.rid);
    onSelect?.(node.rid);
  };

  return (
    <li role="treeitem" aria-expanded={hasChildren ? open : undefined}>
      <div
        className={`px-tree-row${isSelected ? ' is-selected' : ''}`}
        style={{paddingLeft: 8 + depth * 14}}
      >
        {hasChildren ? (
          <button
            className="px-tree-disclosure"
            aria-label={open ? 'collapse' : 'expand'}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? '▾' : '▸'}
          </button>
        ) : (
          <span className="px-tree-disclosure-spacer" />
        )}
        <button className="px-tree-label" onClick={select}>
          {node.name}
        </button>
        <BadgeRow badges={node.badges} />
      </div>
      {open && hasChildren && (
        <ul role="group">
          {node.children.map((c) => (
            <TreeNode
              key={c.rid}
              node={c}
              depth={depth + 1}
              defaultExpandDepth={defaultExpandDepth}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

function BadgeRow({badges}) {
  if (!badges) return null;
  const order = ['red', 'yellow', 'blue', 'green'];
  return (
    <span className="px-badges">
      {order.map((k) => {
        const n = badges[k];
        if (!n) return null;
        return (
          <span key={k} className={`px-badge px-badge-${k}`} title={`${k}: ${n}`}>
            {n}
          </span>
        );
      })}
    </span>
  );
}
