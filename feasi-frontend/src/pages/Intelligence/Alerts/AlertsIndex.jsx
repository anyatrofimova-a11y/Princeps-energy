import React, { useMemo, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import useAlerts from "../../../hooks/useAlerts";
import AlertLibrary from "./AlertLibrary";
import DigestFeed from "./DigestFeed";
import DocRail from "./DocRail";
import QueryView from "./QueryView";
import StarterPacks from "./StarterPacks";
import SubscribeModal from "./SubscribeModal";
import PaywallModal from "./PaywallModal";

const C = {
  ivory: "#FBF8F2",
  border: "#E8EAED",
  ink: "#0F1318",
};

// Free-tier cap — trigger paywall on the 6th subscription attempt.
const FREE_CAP = 5;

export default function AlertsIndex() {
  const { alertId: routeAlertId } = useParams();
  const navigate = useNavigate();
  const { alerts, loading, subscribe, unsubscribe, subscribedCount } = useAlerts();

  const [selectedAlertId, setSelectedAlertId] = useState(routeAlertId || null);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [queryQuestion, setQueryQuestion] = useState(null);
  const [subscribeTarget, setSubscribeTarget] = useState(null); // { alert } | { pack }
  const [paywallOpen, setPaywallOpen] = useState(false);

  const subscribedAlerts = useMemo(
    () => alerts.filter((a) => a.subscribed),
    [alerts]
  );

  const hasAnySubs = subscribedAlerts.length > 0;

  // Empty-state gate — show starter packs if user has no subscriptions.
  const showEmptyState = !loading && !hasAnySubs;

  const onSelectAlert = useCallback((alertId) => {
    setSelectedAlertId(alertId);
    setSelectedDocId(null);
    setQueryQuestion(null);
    if (alertId) {
      navigate(`/intelligence/alerts/${alertId}`, { replace: true });
    } else {
      navigate("/intelligence/alerts", { replace: true });
    }
  }, [navigate]);

  const onToggleSubscribed = useCallback(async (alertId, nextVal) => {
    // Free-tier paywall check: block the 6th subscription.
    if (nextVal && subscribedCount >= FREE_CAP) {
      setPaywallOpen(true);
      return;
    }
    try {
      if (nextVal) await subscribe(alertId);
      else await unsubscribe(alertId);
    } catch (e) {
      console.warn("subscribe toggle failed:", e);
    }
  }, [subscribe, unsubscribe, subscribedCount]);

  const onCustomiseAlert = useCallback((alert) => {
    setSubscribeTarget({ alert });
  }, []);

  const onSubscribePack = useCallback(async (pack) => {
    // Check paywall up front — packs may push over the cap.
    if (subscribedCount + pack.alert_ids.length > FREE_CAP) {
      setPaywallOpen(true);
      return;
    }
    for (const id of pack.alert_ids) {
      try { await subscribe(id); } catch { /* continue */ }
    }
  }, [subscribe, subscribedCount]);

  const onCustomisePack = useCallback((pack) => {
    setSubscribeTarget({ pack });
  }, []);

  const onAskAcross = useCallback((question) => {
    setQueryQuestion(question);
  }, []);

  // ── Rendered content ─────────────────────────────────────────
  return (
    <div
      style={{
        flex: 1,
        minHeight: 0,
        display: "grid",
        gridTemplateColumns: "280px 1fr 360px",
        background: C.ivory,
        color: C.ink,
      }}
    >
      {/* Left rail — alert library */}
      <div
        style={{
          borderRight: `1px solid ${C.border}`,
          minHeight: 0,
          background: "#FFFFFF",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <AlertLibrary
          alerts={alerts}
          loading={loading}
          selectedAlertId={selectedAlertId}
          onSelect={onSelectAlert}
          onToggleSubscribed={onToggleSubscribed}
        />
      </div>

      {/* Middle column — feed or query results */}
      <div style={{ minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {showEmptyState ? (
          <StarterPacks
            onSubscribePack={onSubscribePack}
            onCustomisePack={onCustomisePack}
            onAskAnything={onAskAcross}
          />
        ) : queryQuestion ? (
          <QueryView
            question={queryQuestion}
            scope={{ alertId: selectedAlertId }}
            onBack={() => setQueryQuestion(null)}
            onSelectDoc={setSelectedDocId}
          />
        ) : (
          <DigestFeed
            alertId={selectedAlertId}
            onSelectDoc={setSelectedDocId}
            onAskAcross={onAskAcross}
          />
        )}
      </div>

      {/* Right rail — doc viewer / chat */}
      <div
        style={{
          borderLeft: `1px solid ${C.border}`,
          minHeight: 0,
          background: "#FFFFFF",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <DocRail
          docId={selectedDocId}
          alertId={selectedAlertId}
          onPickQuestion={onAskAcross}
        />
      </div>

      {/* Modals */}
      {subscribeTarget && (
        <SubscribeModal
          target={subscribeTarget}
          onClose={() => setSubscribeTarget(null)}
          onSubscribeAlert={async (id) => {
            await onToggleSubscribed(id, true);
            setSubscribeTarget(null);
          }}
          onSubscribeAll={async (ids) => {
            if (subscribedCount + ids.length > FREE_CAP) {
              setPaywallOpen(true);
              return;
            }
            for (const id of ids) {
              try { await subscribe(id); } catch { /* continue */ }
            }
            setSubscribeTarget(null);
          }}
        />
      )}

      {paywallOpen && <PaywallModal onClose={() => setPaywallOpen(false)} />}
    </div>
  );
}
