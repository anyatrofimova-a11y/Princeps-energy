import { useEffect, useState } from "react";
import api from "../api/dockets";

export function useStakeholders(docketId) {
  const [stakeholders, setStakeholders] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!docketId) return;
    let alive = true;
    setLoading(true);
    api.getStakeholders(docketId).then((rows) => {
      if (!alive) return;
      setStakeholders(rows || []);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [docketId]);

  return { stakeholders, loading };
}
