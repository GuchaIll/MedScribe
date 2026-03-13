import { useState, useCallback } from "react";

/* ─── Toast notification state ───────────────────────────────────────────── */
export default function useNotify() {
  const [toast, setToast] = useState(null);

  const notify = useCallback((message, type = "info") => {
    setToast({ message, type, key: Date.now() });
  }, []);

  const clearToast = useCallback(() => setToast(null), []);

  return { toast, notify, clearToast };
}
