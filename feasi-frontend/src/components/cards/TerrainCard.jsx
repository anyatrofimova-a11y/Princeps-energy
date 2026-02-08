import React from "react";
import { useSite } from "../../SiteContext";
import MetricCard from "../ui/MetricCard";
import BarChart from "../ui/BarChart";
import ErrorBoundary from "../ErrorBoundary";
import ThreeView from "../ThreeView";
import LayoutEditor from "../LayoutEditor";
import LayoutControls from "../LayoutControls";

export default function TerrainCard() {
  const {
    slopeStats, heightmap,
    layoutMode, componentLayout, selectedLayoutItem,
    setSelectedLayoutItem, solarCatalogue,
  } = useSite();

  // These handlers need to use context setters
  const { setComponentLayout } = useSite();

  const handleComponentDrop = ({ component, x, y, z }) => {
    setComponentLayout(prev => [...prev, {
      id: crypto.randomUUID(),
      componentId: component.id,
      x, y, z,
      quantity: 1,
      rotation: 0,
    }]);
  };

  const handleUpdateLayoutItem = (id, updated) => {
    setComponentLayout(prev => prev.map(i => i.id === id ? updated : i));
  };

  const handleDeleteLayoutItem = (id) => {
    setComponentLayout(prev => prev.filter(i => i.id !== id));
    setSelectedLayoutItem(null);
  };

  if (!slopeStats?.stats) {
    return (
      <MetricCard title="Terrain" accentColor="#2196f3">
        <span className="muted">No terrain data</span>
      </MetricCard>
    );
  }

  return (
    <MetricCard
      title="Terrain"
      accentColor="#2196f3"
      headerValue={`${slopeStats.stats.mean?.toFixed(1)} avg`}
    >
      <div className="stat-grid three">
        <div>Mean: {slopeStats.stats.mean?.toFixed(1)}</div>
        <div>Min: {slopeStats.stats.min?.toFixed(1)}</div>
        <div>Max: {slopeStats.stats.max?.toFixed(1)}</div>
      </div>
      {slopeStats.histogram && (
        <BarChart
          data={slopeStats.histogram.map(b => b.count)}
          height="small"
          colors="#2196f3"
          tooltip={(_, i) => {
            const b = slopeStats.histogram[i];
            return `${b.min.toFixed(1)}-${b.max.toFixed(1)}: ${b.count} px`;
          }}
        />
      )}
      <ErrorBoundary name="3D View">
        {layoutMode ? (
          <LayoutEditor heightmap={heightmap} componentLayout={componentLayout}
            onDrop={handleComponentDrop} onSelectItem={setSelectedLayoutItem} selectedItem={selectedLayoutItem} />
        ) : (
          <ThreeView heightmap={heightmap} />
        )}
      </ErrorBoundary>
      {layoutMode && (
        <LayoutControls selectedItem={selectedLayoutItem} layout={componentLayout}
          onUpdate={handleUpdateLayoutItem} onDelete={handleDeleteLayoutItem} catalogue={solarCatalogue} />
      )}
    </MetricCard>
  );
}
