import { useState, useEffect } from "react";

/* ─── Timer ──────────────────────────────────────────────────────────────── */
export default function useTimer() {
  const [s, setS] = useState(0);
  const [on, setOn] = useState(false);

  useEffect(() => {
    if (!on) return;
    const id = setInterval(() => setS((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, [on]);

  const fmt = (n) =>
    `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(
      2,
      "0"
    )}`;

  return {
    seconds: s,
    display: fmt(s),
    running: on,
    start: () => setOn(true),
    stop: () => setOn(false),
    toggle: () => setOn((r) => !r),
    reset: () => {
      setS(0);
      setOn(false);
    },
  };
}
