import { useLang } from "../LanguageContext";

/** UNDERSTAND (a result) -> LEARN (the farm over time) -> ACT (the plan). A small eyebrow so the three areas read as one system. */
export function LayerTag({ k, dark = false }: { k: "understand" | "learn" | "act" | "decide"; dark?: boolean }) {
  const { t } = useLang();
  const idx = k === "understand" ? 1 : k === "learn" ? 2 : k === "act" ? 3 : 4;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-widest ${dark ? "bg-white/15 text-white" : "bg-leaf-100 text-leaf-800"}`} data-testid={`layer-${k}`}>
      {idx} · {t.layer[k]}
    </span>
  );
}
