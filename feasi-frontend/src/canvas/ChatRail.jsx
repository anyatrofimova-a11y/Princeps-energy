/**
 * ChatRail — bottom rail chat for the Unified Canvas.
 *
 * Uses the Vercel AI SDK (`@ai-sdk/react` v3 / AI SDK v6) with a
 * DefaultChatTransport pointing at `/api/canvas/chat`. If the endpoint does
 * not exist yet we degrade gracefully: a friendly "chat rail offline" banner
 * replaces the assistant reply but the input stays usable so that work can
 * be queued for when the backend comes online.
 *
 * Tool calls in the stream are rendered as small status chips.
 *
 * Imperative API (exposed via ref and via window "pc-chat-focus" event):
 *   .focus()   — focus the input.
 */
import React, {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  forwardRef,
} from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";

const CHAT_API = "/api/canvas/chat";

const ChatRail = forwardRef(function ChatRail(
  { projectId, assetClass, polygon },
  ref
) {
  const inputRef = useRef(null);
  const bodyRef = useRef(null);
  const [endpointOnline, setEndpointOnline] = useState(null); // null = unknown
  const [draft, setDraft] = useState("");

  // ── Probe the endpoint once on mount so we can show an offline hint. ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(CHAT_API, { method: "OPTIONS" });
        if (!cancelled) setEndpointOnline(res.status !== 404);
      } catch (_) {
        if (!cancelled) setEndpointOnline(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const transport = React.useMemo(
    () =>
      new DefaultChatTransport({
        api: CHAT_API,
        body: () => ({
          projectId: projectId || null,
          assetClass: assetClass || null,
          polygon: polygon || null,
        }),
      }),
    [projectId, assetClass, polygon]
  );

  const { messages, sendMessage, status, error } = useChat({
    transport,
  });

  // Scroll to bottom on new messages
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [messages, status]);

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
  }));

  // Listen for global "focus chat" events (from CommandPalette).
  useEffect(() => {
    const onFocus = () => inputRef.current?.focus();
    window.addEventListener("pc-chat-focus", onFocus);
    return () => window.removeEventListener("pc-chat-focus", onFocus);
  }, []);

  const submit = useCallback(
    (e) => {
      if (e) e.preventDefault();
      const text = draft.trim();
      if (!text) return;
      try {
        sendMessage({ text });
      } catch (err) {
        console.warn("[ChatRail] sendMessage failed:", err);
      }
      setDraft("");
    },
    [draft, sendMessage]
  );

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const offline = endpointOnline === false;
  const isStreaming = status === "streaming" || status === "submitted";

  return (
    <div className="pc-chat">
      <div className="pc-chat-header">
        <span>Canvas Chat</span>
        <span style={{ fontSize: 10, color: offline ? "var(--danger)" : "var(--ink-soft)" }}>
          {offline ? "offline" : isStreaming ? "streaming…" : ""}
        </span>
      </div>

      <div className="pc-chat-body" ref={bodyRef}>
        {offline && (
          <div style={{ fontSize: 12, color: "var(--ink-soft)", padding: "4px 0" }}>
            Chat rail offline — the backend agent will be wired in later. Messages
            typed here will not be sent until <code>{CHAT_API}</code> is online.
          </div>
        )}

        {error && !offline && (
          <div style={{ fontSize: 12, color: "var(--danger)", padding: "4px 0" }}>
            {String(error.message || error)}
          </div>
        )}

        {messages.map((m) => (
          <MessageRow key={m.id} message={m} />
        ))}

        {!messages.length && !offline && (
          <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>
            Ask about the current site, request a card, or describe what to
            build.
          </div>
        )}
      </div>

      <form className="pc-chat-input-row" onSubmit={submit}>
        <input
          ref={inputRef}
          className="pc-chat-input"
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={offline ? "Offline — queue a message…" : "Ask Princeps…"}
          aria-label="Chat input"
        />
        <button className="pc-chat-send" type="submit" disabled={!draft.trim() || isStreaming}>
          Send
        </button>
      </form>
    </div>
  );
});

function MessageRow({ message }) {
  const role = message.role;
  // AI SDK v6 uses `parts` arrays on UIMessage. Fall back to .content for safety.
  const parts = message.parts || (message.content ? [{ type: "text", text: message.content }] : []);
  return (
    <div className={`pc-chat-msg pc-chat-msg-${role}`}>
      <div className="pc-chat-msg-role">{role}</div>
      <div>
        {parts.map((p, i) => {
          if (!p) return null;
          if (p.type === "text") {
            return <span key={i}>{p.text}</span>;
          }
          if (typeof p.type === "string" && p.type.startsWith("tool-")) {
            const name = p.toolName || p.type.replace(/^tool-/, "");
            const state = p.state || "";
            return (
              <span key={i} className="pc-chat-tool-chip">
                {state === "output-available" ? "✓" : state === "input-streaming" ? "…" : "⚙"}
                &nbsp;{name}
              </span>
            );
          }
          if (p.type === "reasoning" && p.text) {
            return (
              <span key={i} style={{ fontStyle: "italic", color: "var(--ink-soft)" }}>
                {p.text}
              </span>
            );
          }
          return null;
        })}
      </div>
    </div>
  );
}

export default ChatRail;
