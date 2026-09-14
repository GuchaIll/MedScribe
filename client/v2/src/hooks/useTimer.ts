import { useCallback, useEffect, useState } from "react";

const fmt = (n: number) =>
  `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;

/** Wall-clock seconds timer with start / stop / reset. */
export function useTimer() {
  const [seconds, setSeconds] = useState(0);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setSeconds((x) => x + 1), 1000);
    return () => clearInterval(id);
  }, [running]);

  const reset = useCallback(() => {
    setSeconds(0);
    setRunning(false);
  }, []);

  return {
    seconds,
    display: fmt(seconds),
    running,
    start: useCallback(() => setRunning(true), []),
    stop: useCallback(() => setRunning(false), []),
    toggle: useCallback(() => setRunning((r) => !r), []),
    reset,
  };
}
