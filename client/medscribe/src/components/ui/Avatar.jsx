/* ─── Avatar ─────────────────────────────────────────────────────────────── */
function Avatar({ src, online, size = 34 }) {
  return (
    <div style={{ position: "relative", flexShrink: 0 }}>
      <img
        src={src}
        alt=""
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          objectFit: "cover",
          border: "1.5px solid rgba(255,255,255,0.18)",
          display: "block",
        }}
      />
      {online && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            right: 0,
            width: 9,
            height: 9,
            borderRadius: "50%",
            background: "#4ade80",
            border: "2px solid rgba(30,32,36,0.9)",
          }}
        />
      )}
    </div>
  );
}

export default Avatar;
