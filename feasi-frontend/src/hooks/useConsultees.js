import { useEffect, useState } from "react";
import api from "../api/dockets";

export function useConsultees(params) {
  const [consultees, setConsultees] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.getConsultees(params || {}).then((rows) => {
      if (!alive) return;
      setConsultees(rows || []);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [JSON.stringify(params || {})]);

  return { consultees, loading };
}
