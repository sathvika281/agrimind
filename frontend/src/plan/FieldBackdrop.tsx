/** An original, abstract aerial patchwork of crop plots (greens and soft ochres) behind the hero. It is a hand-built SVG:
 *  no photo, no external file, nothing to license, works offline. Purely decorative, so it is hidden from assistive tech. */
const PLOTS: [number, number, number, number, string][] = [
  [0, 0, 120, 90, "#2f6f46"], [120, 0, 90, 60, "#44854f"], [210, 0, 130, 110, "#7d8a3c"], [340, 0, 100, 70, "#2a6a45"], [440, 0, 160, 95, "#5e8f4a"],
  [0, 90, 80, 100, "#8c8f43"], [80, 90, 130, 70, "#2b6d48"], [120, 60, 90, 30, "#a39a46"], [210, 110, 100, 80, "#3c7d4d"], [310, 110, 120, 80, "#9a8f40"],
  [340, 70, 100, 40, "#2f7048"], [430, 95, 170, 95, "#336f49"], [0, 190, 140, 70, "#4f8a4d"], [140, 160, 70, 100, "#2a6844"], [210, 190, 100, 70, "#b09a47"],
  [310, 190, 130, 70, "#3a794c"], [440, 190, 160, 70, "#7a8b3f"],
];

export function FieldBackdrop({ photo }: { photo?: string }) {
  if (photo) return <img src={photo} alt="" aria-hidden="true" className="plan-photo" decoding="async" />;
  return (
    <svg className="plan-backdrop" viewBox="0 0 600 260" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
      <g>
        {PLOTS.map(([x, y, w, h, c], i) => (
          <rect key={i} x={x + 1.5} y={y + 1.5} width={w - 3} height={h - 3} rx="3" fill={c} />
        ))}
      </g>
      <g stroke="rgba(255,255,255,0.10)" strokeWidth="1" fill="none">
        {[18, 38, 58, 78].map((o) => <path key={o} d={`M${120 + o} 4v52M${210 + o} 114v72`} />)}
      </g>
    </svg>
  );
}
