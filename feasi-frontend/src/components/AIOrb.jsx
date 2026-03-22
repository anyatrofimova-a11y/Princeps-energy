/**
 * AIOrb — Siri-inspired floating AI assistant orb.
 *
 * - Draggable gold orb that can be moved anywhere on screen
 * - Pulsing glow when AI has a suggestion
 * - Click to expand into chat panel
 * - Proactive suggestion bubbles pop up near the orb
 * - Minimises back to orb when chat is closed
 */
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSite } from "../SiteContext";

const PROACTIVE_SUGGESTIONS = [
  { trigger: "site_picked", text: "I can run a full feasibility assessment on this site", delay: 2000 },
  { trigger: "idle", text: "Try asking me to find sites with >20MW headroom", delay: 15000 },
  { trigger: "constraint", text: "I found environmental constraints nearby — want me to scope an ESA?", delay: 3000 },
  { trigger: "price_spike", text: "Wholesale price is high — shall I calculate BESS dispatch revenue?", delay: 1000 },
];

export default function AIOrb({ onOpenChat, chatOpen }) {
  const { pickedLocation, selectedEntity } = useSite();
  const [position, setPosition] = useState({ x: null, y: null }); // null = use CSS default
  const [dragging, setDragging] = useState(false);
  const [suggestion, setSuggestion] = useState(null);
  const [pulse, setPulse] = useState(false);
  const [hovered, setHovered] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });
  const suggestionTimer = useRef(null);

  // Proactive suggestion on site pick
  useEffect(() => {
    if (!pickedLocation) return;
    clearTimeout(suggestionTimer.current);
    suggestionTimer.current = setTimeout(() => {
      setSuggestion("I can analyse this site — grid, environmental, financial. Click me.");
      setPulse(true);
      setTimeout(() => { setSuggestion(null); setPulse(false); }, 8000);
    }, 2000);
    return () => clearTimeout(suggestionTimer.current);
  }, [pickedLocation]);

  // Proactive suggestion on entity selection
  useEffect(() => {
    if (!selectedEntity) return;
    clearTimeout(suggestionTimer.current);
    const type = selectedEntity.type;
    const name = selectedEntity.data?.name || "";
    suggestionTimer.current = setTimeout(() => {
      if (type === "substation") {
        setSuggestion(`${name} — I can check headroom, queue depth, and connection cost.`);
      } else {
        setSuggestion(`Want me to run a detailed assessment?`);
      }
      setPulse(true);
      setTimeout(() => { setSuggestion(null); setPulse(false); }, 8000);
    }, 1500);
    return () => clearTimeout(suggestionTimer.current);
  }, [selectedEntity]);

  // Idle suggestion
  useEffect(() => {
    if (chatOpen) return;
    const idle = setTimeout(() => {
      if (!pickedLocation && !selectedEntity) {
        setSuggestion("Click anywhere on the map, or ask me to find optimal sites.");
        setPulse(true);
        setTimeout(() => { setSuggestion(null); setPulse(false); }, 10000);
      }
    }, 20000);
    return () => clearTimeout(idle);
  }, [chatOpen, pickedLocation, selectedEntity]);

  // ── Drag handling ──
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    dragOffset.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    setDragging(true);
    e.preventDefault();
  }, []);

  useEffect(() => {
    if (!dragging) return;
    const handleMove = (e) => {
      setPosition({
        x: e.clientX - dragOffset.current.x,
        y: e.clientY - dragOffset.current.y,
      });
    };
    const handleUp = () => setDragging(false);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [dragging]);

  const handleClick = useCallback(() => {
    if (!dragging) {
      setSuggestion(null);
      setPulse(false);
      onOpenChat?.();
    }
  }, [dragging, onOpenChat]);

  // Don't show orb when chat is open
  if (chatOpen) return null;

  const style = position.x != null
    ? { left: position.x, top: position.y, right: "auto", bottom: "auto" }
    : {};

  return (
    <>
      {/* Suggestion bubble */}
      {suggestion && (
        <div
          className="ai-orb-suggestion"
          style={position.x != null ? { left: position.x - 220, top: position.y - 10 } : {}}
          onClick={handleClick}
        >
          <div className="ai-orb-suggestion-text">{suggestion}</div>
          <div className="ai-orb-suggestion-arrow" />
        </div>
      )}

      {/* Orb */}
      <div
        className={`ai-orb ${pulse ? "ai-orb-pulse" : ""} ${hovered ? "ai-orb-hover" : ""} ${dragging ? "ai-orb-dragging" : ""}`}
        style={style}
        onMouseDown={handleMouseDown}
        onClick={handleClick}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        title="Princeps AI — click to chat, drag to move"
      >
        <div className="ai-orb-inner">
          <svg width="22" height="22" viewBox="0 0 48 48" fill="none">
            <polygon points="4,4 36,4 28,16 12,16" fill="#fff" opacity="0.9"/>
            <polygon points="12,20 28,20 36,32 4,32" fill="#fff" opacity="0.9"/>
            <rect x="28" y="14" width="16" height="8" fill="#fff" opacity="0.7"/>
            <rect x="4" y="36" width="24" height="8" fill="#fff" opacity="0.7"/>
          </svg>
        </div>
      </div>
    </>
  );
}
