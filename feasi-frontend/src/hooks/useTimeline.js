import { useEffect, useState } from "react";
import api from "../api/dockets";

export function useTimeline(docketId) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!docketId) return;
    let alive = true;
    setLoading(true);
    api.getTimeline(docketId).then((rows) => {
      if (!alive) return;
      setEvents(rows || []);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [docketId]);

  return { events, loading };
}
