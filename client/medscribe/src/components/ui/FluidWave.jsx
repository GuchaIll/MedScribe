import { useEffect, useRef } from "react";

/* ─── Fluid Wave ─────────────────────────────────────────────────────────── */
function FluidWave({ active }) {
  const canvasRef = useRef(null);
  const frameRef = useRef(null);
  const tRef = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = canvas.offsetWidth * dpr;
      canvas.height = canvas.offsetHeight * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = () => {
      const W = canvas.offsetWidth;
      const H = canvas.offsetHeight;
      ctx.clearRect(0, 0, W, H);

      if (!active) {
        ctx.beginPath();
        ctx.moveTo(0, H / 2);
        ctx.lineTo(W, H / 2);
        ctx.strokeStyle = "rgba(255,255,255,0.12)";
        ctx.lineWidth = 1;
        ctx.stroke();
        frameRef.current = requestAnimationFrame(draw);
        return;
      }

      tRef.current += 0.016;
      const t = tRef.current;
      const CY = H / 2;
      const STEPS = 320;

      const waves = [
        {
          amp: 0.44,
          freq: 1.35,
          phase: 0,
          cTop: "100,200,255",
          cBot: "80,130,240",
          glow: 22,
          lw: 2.2,
        },
        {
          amp: 0.36,
          freq: 1.75,
          phase: Math.PI * 0.55,
          cTop: "180,100,255",
          cBot: "200,80,230",
          glow: 17,
          lw: 1.9,
        },
        {
          amp: 0.24,
          freq: 2.3,
          phase: Math.PI * 1.25,
          cTop: "220,180,255",
          cBot: "150,80,210",
          glow: 12,
          lw: 1.4,
        },
      ];

      waves.forEach(({ amp, freq, phase, cTop, cBot, glow, lw }) => {
        ctx.beginPath();
        for (let i = 0; i <= STEPS; i++) {
          const x = (i / STEPS) * W;
          const env = Math.sin((i / STEPS) * Math.PI);
          const y =
            CY -
            env *
              amp *
              CY *
              Math.sin(freq * Math.PI * 2 * (i / STEPS) - t + phase);
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = `rgba(${cTop},0.82)`;
        ctx.lineWidth = lw;
        ctx.shadowColor = `rgba(${cTop},0.5)`;
        ctx.shadowBlur = glow;
        ctx.stroke();

        ctx.beginPath();
        for (let i = 0; i <= STEPS; i++) {
          const x = (i / STEPS) * W;
          const env = Math.sin((i / STEPS) * Math.PI);
          const y =
            CY +
            env *
              amp *
              CY *
              Math.sin(
                freq * Math.PI * 2 * (i / STEPS) - t + phase + 0.22
              );
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.strokeStyle = `rgba(${cBot},0.58)`;
        ctx.lineWidth = lw * 0.8;
        ctx.shadowColor = `rgba(${cBot},0.35)`;
        ctx.shadowBlur = glow * 0.65;
        ctx.stroke();
        ctx.shadowBlur = 0;
      });

      frameRef.current = requestAnimationFrame(draw);
    };

    frameRef.current = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frameRef.current);
      window.removeEventListener("resize", resize);
    };
  }, [active]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "100%", height: "100%", display: "block" }}
    />
  );
}

export default FluidWave;
