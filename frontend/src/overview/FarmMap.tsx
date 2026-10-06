import type { KeyboardEvent } from "react";
import type { Analysis, Farm } from "../api";
import { friendlyDate } from "../copy";
import { useLang } from "../LanguageContext";
import { MAP_H, MAP_W, MAX_FIELDS, fieldGeometry, levelOf, rainOutlook, type Level } from "./derive";
import type { FarmWeather } from "./StatusContext";

export type Layer = "health" | "risk" | "weather";
export const LAYERS: Layer[] = ["health", "risk", "weather"]; // every layer is built from real checks or the real forecast

// Polygon fills per REAL level (radial gradients defined below) + a text-safe colour for the legend squares.
const LEVEL_GRAD: Record<Level, string> = { ok: "url(#g-ok)", attention: "url(#g-attn)", critical: "url(#g-crit)", unrated: "url(#g-unr)", none: "url(#g-none)" };
export const LEVEL_SWATCH: Record<Level, string> = { ok: "#2f8a58", attention: "#e58f3d", critical: "#b4443a", unrated: "#8fae9a", none: "#c4cbc4" };
const LEVEL_ICON: Record<Level, string> = { ok: "✔", attention: "!", critical: "⚠", unrated: "•", none: "–" };

function mix(a: string, b: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [r1, g1, b1] = p(a);
  const [r2, g2, b2] = p(b);
  const c = (x: number, y: number) => Math.round(x + (y - x) * Math.max(0, Math.min(1, t)));
  return `rgb(${c(r1, r2)},${c(g1, g2)},${c(b1, b2)})`;
}

interface Props {
  farms: Farm[];
  latest: Map<number, Analysis>;
  selectedId: number | null;
  onSelect: (id: number) => void;
  layer: Layer;
  onLayer: (l: Layer) => void;
  weatherByFarm: Record<number, FarmWeather | undefined>;
}

export function FarmMap({ farms, latest, selectedId, onSelect, layer, onLayer, weatherByFarm }: Props) {
  const { t, lang } = useLang();
  const O = t.ov;
  const shown = farms.slice(0, MAX_FIELDS);
  const lastCheck = [...latest.values()].sort((a, b) => b.id - a.id)[0];

  const fillFor = (f: Farm): string => {
    const lv = levelOf(latest.get(f.id));
    if (layer === "weather") {
      const w = weatherByFarm[f.id]?.weather;
      if (!w) return "url(#g-none)";
      const mm = w.next_3d_rain_mm ?? 0;
      return mix("#e5e9e2", "#3a82a8", mm / 25); // REAL forecast rain
    }
    return LEVEL_GRAD[lv];
  };

  const valueLine = (f: Farm): string => {
    const a = latest.get(f.id);
    const lv = levelOf(a);
    if (layer === "weather") {
      const w = weatherByFarm[f.id]?.weather;
      if (!w) return O.unavailable;
      const out = rainOutlook(w);
      return out.kind === "rain" ? t.shell.rain(String(out.mm)) : out.kind === "dry" ? t.shell.dry : O.unavailable;
    }
    return O.legend[lv];
  };

  const onKey = (e: KeyboardEvent, id: number) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onSelect(id);
    }
  };

  const sel = shown.find((f) => f.id === selectedId) ?? shown[0];
  const selIdx = sel ? shown.indexOf(sel) : -1;
  const g = sel ? fieldGeometry(sel.id, selIdx) : null;
  const selCrop = sel ? latest.get(sel.id)?.crop : undefined;

  return (
    <section className="panel min-w-0" aria-label={O.mapTitle}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="flex items-center gap-2 text-sm font-bold">
          {O.mapTitle}
          <span className="tag-mint">{O.mapSource}</span>
        </h2>
      </div>
      <div role="tablist" aria-label={O.mapTitle} className="flex gap-1 overflow-x-auto border-b border-line px-2 py-1.5">
        {LAYERS.map((l) => (
          <button
            key={l}
            role="tab"
            type="button"
            aria-selected={layer === l}
            onClick={() => onLayer(l)}
            className={`flex min-h-[2.75rem] shrink-0 items-center gap-1.5 rounded-md border px-3 text-xs font-semibold ${layer === l ? "border-leaf-800 bg-leaf-800 text-white" : "border-line bg-white text-ink hover:bg-leaf-50"}`}
          >
            {O.layers[l]}
                      </button>
        ))}
      </div>

      <div className="relative m-3 aspect-[16/8] rounded-2xl overflow-hidden rounded-md border border-line bg-[#ece9df]">
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} className="absolute inset-0 h-full w-full" role="group" aria-label={O.mapTitle}>
          <defs>
            <radialGradient id="g-ok"><stop offset="0" stopColor="#58a876" /><stop offset="1" stopColor="#1f6a45" /></radialGradient>
            <radialGradient id="g-attn"><stop offset="0" stopColor="#f2a65e" /><stop offset="1" stopColor="#d9822f" /></radialGradient>
            <radialGradient id="g-crit"><stop offset="0" stopColor="#d27468" /><stop offset="1" stopColor="#a63a30" /></radialGradient>
            <radialGradient id="g-unr"><stop offset="0" stopColor="#a6c2b0" /><stop offset="1" stopColor="#6f917d" /></radialGradient>
            <radialGradient id="g-none"><stop offset="0" stopColor="#d9ded8" /><stop offset="1" stopColor="#b6beb6" /></radialGradient>
            <pattern id="rows" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(32)"><line x1="0" y1="0" x2="0" y2="9" stroke="#000" strokeOpacity="0.10" strokeWidth="2" /></pattern>
            <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="8" stroke="#fff" strokeOpacity="0.55" strokeWidth="2" /></pattern>
          </defs>
          {/* tracks between fields */}
          <g stroke="#fff" strokeOpacity="0.9" strokeWidth="9" strokeLinecap="round">
            <line x1={MAP_W / 3} y1="0" x2={MAP_W / 3} y2={MAP_H} />
            <line x1={(MAP_W * 2) / 3} y1="0" x2={(MAP_W * 2) / 3} y2={MAP_H} />
            <line x1="0" y1={MAP_H / 2} x2={MAP_W} y2={MAP_H / 2} />
          </g>
          {shown.map((f, i) => {
            const geo = fieldGeometry(f.id, i);
            const a = latest.get(f.id);
            const lv = levelOf(a);
            const active = sel?.id === f.id;
            const uncertain = layer === "risk" && a?.result.uncertainty_level === "high";
            return (
              <g
                key={f.id}
                role="button"
                tabIndex={0}
                aria-pressed={active}
                aria-label={O.fieldAria(f.name, `${O.legend[lv]}`)}
                onClick={() => onSelect(f.id)}
                onKeyDown={(e) => onKey(e, f.id)}
                className="cursor-pointer outline-none [&:focus-visible_polygon]:stroke-amber-500"
              >
                <polygon points={geo.points} fill={fillFor(f)} stroke={active ? "#0d2d21" : "#fff"} strokeWidth={active ? 3.5 : 2} strokeLinejoin="round" />
                <polygon points={geo.points} fill="url(#rows)" pointerEvents="none" />
                {uncertain && <polygon points={geo.points} fill="url(#hatch)" pointerEvents="none" />}
                <text x={geo.cx} y={geo.cy + 4} textAnchor="middle" fontSize="14" fontWeight="700" fill={lv === "none" && layer === "health" ? "#2b3a32" : "#fff"} stroke={lv === "none" && layer === "health" ? "none" : "#0007"} strokeWidth="3" paintOrder="stroke" pointerEvents="none">
                  {f.name.length > 16 ? `${f.name.slice(0, 15)}…` : f.name}
                </text>
                <text x={geo.cx} y={geo.cy + 22} textAnchor="middle" fontSize="12" fill={lv === "none" && layer === "health" ? "#2b3a32" : "#fff"} stroke={lv === "none" && layer === "health" ? "none" : "#0007"} strokeWidth="3" paintOrder="stroke" pointerEvents="none" aria-hidden="true">
                  {layer === "health" || layer === "risk" ? LEVEL_ICON[lv] : ""}
                </text>
              </g>
            );
          })}
        </svg>


        {sel && g && (
          <div
            className="pointer-events-none absolute z-10 w-max max-w-[60%] rounded bg-leaf-900 px-2 py-1 text-xs text-white shadow"
            // Anchored by grid column so the label can never be cut off at the map edge on a phone:
            // left column -> left-aligned, right column -> right-aligned, middle -> centred.
            style={{
              top: `${(g.cy / MAP_H) * 100}%`,
              ...(selIdx % 3 === 0
                ? { left: "2%" }
                : selIdx % 3 === 2
                  ? { right: "2%" }
                  : { left: `${(g.cx / MAP_W) * 100}%` }),
              transform: `translate(${selIdx % 3 === 1 ? "-50%" : "0"}, ${g.cy < MAP_H * 0.3 ? "38%" : "-135%"})`,
            }}
          >
            <span className="font-bold">{sel.name}</span>
            {selCrop ? ` · ${selCrop}` : ""}
            <span className="block font-mono text-xs text-mint-200">{valueLine(sel)}</span>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-3 py-2 text-xs text-mute">
        {(["ok", "attention", "critical", "unrated", "none"] as Level[]).map((lv) => (
          <span key={lv} className="inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-3 w-3 rounded-sm" style={{ background: LEVEL_SWATCH[lv] }} />
            {O.legend[lv]}
          </span>
        ))}
      </div>
      {/* Field list: the same real data as the map, as plain buttons (also the keyboard / screen-reader route). */}
      <details className="border-t border-line">
      <summary className="flex min-h-[2.75rem] cursor-pointer items-center px-3 text-sm font-semibold">{O.fieldList}</summary>
      <ul className="divide-y divide-line border-t border-line" aria-label={O.fieldList}>
        {shown.map((f) => {
          const a = latest.get(f.id);
          const lv = levelOf(a);
          const active = sel?.id === f.id;
          return (
            <li key={f.id}>
              <button
                type="button"
                aria-pressed={active}
                onClick={() => onSelect(f.id)}
                className={`flex min-h-[2.75rem] w-full items-center gap-2 px-3 text-left text-sm ${active ? "bg-leaf-50 font-semibold" : "hover:bg-ground"}`}
              >
                <span aria-hidden className="h-3 w-3 shrink-0 rounded-sm" style={{ background: LEVEL_SWATCH[lv] }} />
                <span className="min-w-0 flex-1 truncate">{f.name}{a ? ` · ${a.crop}` : ""}</span>
                <span className="hidden shrink-0 text-xs text-mute sm:inline">{O.legend[lv]}</span>
                <span className="micro shrink-0">{a ? friendlyDate(a.created_at) : "—"}</span>
              </button>
            </li>
          );
        })}
      </ul>
      </details>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-3 py-2 text-xs text-mute">
        <span className="micro">{lastCheck ? O.mapFoot(friendlyDate(lastCheck.created_at)) : O.noChecksYet}</span>
        <span>{farms.length > MAX_FIELDS ? O.moreFarms(farms.length - MAX_FIELDS) : O.mapHint}</span>
      </div>
      <span className="sr-only" lang={lang}>{O.mapHint}</span>
    </section>
  );
}
