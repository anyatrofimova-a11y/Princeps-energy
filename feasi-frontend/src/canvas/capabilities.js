/**
 * Princeps Unified Canvas — Capability Registry (L1)
 *
 * Each capability describes a unit of functionality that can surface in the
 * right-rail CardStack, as a map overlay, or as a tool.
 *
 * Shape:
 *   {
 *     id:          string,                 // stable identifier
 *     label:       string,                 // human-readable title
 *     component:   React.ComponentType,    // receives { polygon, projectId, assetClass, siteId, onExpand }
 *     relevantFor: AssetClass[],           // which asset classes show this card
 *     priority:    number,                 // lower = shown higher in the stack
 *     group:       'verdict' | 'overlay' | 'tool',
 *   }
 */

import HelloCard from "./cards/HelloCard.jsx";
import GridCard from "./cards/GridCard.jsx";
import PlanningCard from "./cards/PlanningCard.jsx";
import LandCard from "./cards/LandCard.jsx";
import YieldCard from "./cards/YieldCard.jsx";
import FinanceCard from "./cards/FinanceCard.jsx";
import EnvironmentCard from "./cards/EnvironmentCard.jsx";

export const ASSET_CLASSES = ["solar", "wind", "bess", "dc", "hybrid"];
const ALL = ["solar", "wind", "bess", "dc", "hybrid"];

export const capabilities = [
  {
    id: "grid",
    label: "Grid Connection",
    component: GridCard,
    relevantFor: ALL,
    priority: 10,
    group: "verdict",
    color: "#caa24a",
    defaultLayers: ["substations", "dno_boundaries", "headroom"],
  },
  {
    id: "planning",
    label: "Planning",
    component: PlanningCard,
    relevantFor: ALL,
    priority: 20,
    group: "verdict",
    color: "#6a8caf",
    defaultLayers: ["lpa", "repd_similar"],
  },
  {
    id: "land",
    label: "Land & Ownership",
    component: LandCard,
    relevantFor: ALL,
    priority: 30,
    group: "verdict",
    color: "#7aa46a",
    defaultLayers: ["inspire", "alc", "protected_designations"],
  },
  {
    id: "yield",
    label: "Yield",
    component: YieldCard,
    relevantFor: ["solar", "wind", "hybrid"],
    priority: 40,
    group: "verdict",
    color: "#e2b64a",
    defaultLayers: ["irradiance"],
  },
  {
    id: "finance",
    label: "Finance",
    component: FinanceCard,
    relevantFor: ALL,
    priority: 50,
    group: "verdict",
    color: "#3a7a6b",
    defaultLayers: [],
  },
  {
    id: "environment",
    label: "Environment",
    component: EnvironmentCard,
    relevantFor: ALL,
    priority: 60,
    group: "verdict",
    color: "#8e5a5a",
    defaultLayers: ["flood_zones", "sssi", "aonb"],
  },
  {
    id: "hello",
    label: "Canvas",
    component: HelloCard,
    relevantFor: ALL,
    priority: 99,
    group: "tool",
  },
];

export const capabilitiesFor = (assetClass) =>
  capabilities
    .filter((c) => c.relevantFor.includes(assetClass))
    .sort((a, b) => a.priority - b.priority);

export const capabilitiesByGroup = (assetClass, group) =>
  capabilitiesFor(assetClass).filter((c) => c.group === group);
