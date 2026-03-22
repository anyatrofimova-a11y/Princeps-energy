import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// ── Mock mapbox-gl (needs canvas / WebGL which jsdom lacks) ──
vi.mock("mapbox-gl", () => ({
  default: {
    Map: vi.fn(),
    Marker: vi.fn(() => ({ setLngLat: vi.fn().mockReturnThis(), addTo: vi.fn() })),
    LngLatBounds: vi.fn(() => ({ extend: vi.fn(), isEmpty: vi.fn(() => true) })),
    accessToken: "",
  },
  Map: vi.fn(),
  Marker: vi.fn(() => ({ setLngLat: vi.fn().mockReturnThis(), addTo: vi.fn() })),
  LngLatBounds: vi.fn(() => ({ extend: vi.fn(), isEmpty: vi.fn(() => true) })),
}));

// ── Mock fetch globally ──
globalThis.fetch = vi.fn(() =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
);

// ── ErrorBoundary tests ──
import ErrorBoundary from "../components/ErrorBoundary";

function CrashingComponent() {
  throw new Error("Boom!");
}

function SafeComponent() {
  return <div data-testid="safe">Hello</div>;
}

describe("ErrorBoundary", () => {
  it("renders children when they do not crash", () => {
    render(
      <ErrorBoundary name="Test">
        <SafeComponent />
      </ErrorBoundary>
    );
    expect(screen.getByTestId("safe")).toBeTruthy();
  });

  it("renders fallback UI when a child crashes", () => {
    // Suppress console.error from React's error boundary logging
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary name="CrashTest">
        <CrashingComponent />
      </ErrorBoundary>
    );
    expect(screen.getByText(/CrashTest failed to render/)).toBeTruthy();
    expect(screen.getByText("Boom!")).toBeTruthy();
    spy.mockRestore();
  });

  it("renders nothing when fallback={null} and child crashes", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { container } = render(
      <ErrorBoundary name="Silent" fallback={null}>
        <CrashingComponent />
      </ErrorBoundary>
    );
    expect(container.innerHTML).toBe("");
    spy.mockRestore();
  });
});

// ── CopilotWidget smoke test (mock SiteContext + WorkspaceContext) ──
vi.mock("../SiteContext", () => ({
  useSite: () => ({
    parcelId: null,
    pickedLocation: null,
    samCapacity: 100,
    samDay: 172,
    loading: false,
    layers: {},
    chatLayers: [],
    setChatLayers: vi.fn(),
    workflowStage: "site",
    placedAssets: [],
    agentResult: null,
    gridContext: null,
    solarYield: null,
    activeIntent: null,
    setActiveTab: vi.fn(),
    setPanelOpen: vi.fn(),
  }),
}));

vi.mock("../contexts/WorkspaceContext", () => ({
  useWorkspace: () => ({
    activeWorkspace: "analyse",
    setActiveWorkspace: vi.fn(),
    navigateToIntent: vi.fn(),
  }),
  WORKSPACES: [],
}));

vi.mock("../services/api", () => ({
  default: {
    chat: { send: vi.fn(), history: vi.fn(() => Promise.resolve([])) },
    grid: { liveStatus: vi.fn(() => Promise.resolve(null)), demandForecast: vi.fn(() => Promise.resolve(null)), agilePricing: vi.fn(() => Promise.resolve(null)) },
    inventory: { catalogue: vi.fn(() => Promise.resolve(null)) },
    energy: { npv: vi.fn(() => Promise.resolve(null)) },
    site: { fromLocation: vi.fn(() => Promise.resolve(null)) },
  },
}));

import CopilotWidget from "../components/CopilotWidget";

describe("CopilotWidget", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <CopilotWidget
        onMapLayer={vi.fn()}
        onZoomTo={vi.fn()}
        onAction={vi.fn()}
      />
    );
    expect(container).toBeTruthy();
  });
});
