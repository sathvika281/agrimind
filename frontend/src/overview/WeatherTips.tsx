import { api, type WeatherTips as Tips } from "../api";
import { useKeyedData } from "../insights/useFarmData";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "../plan/icons";

const GROUPS = ["protect", "water", "watch"] as const;
const GROUP_ICON = { protect: "warning", water: "drop", watch: "inspect" } as const;
const shown = (v: number) => String(Math.round(v * 10) / 10);

/** How to cope with the forecast for this farm: the real conditions first, then grouped, non-chemical tips.
 *  Only the Weather tab renders this; the numbers and the tips both come from the server's deterministic rules. */
export function WeatherTips({ farmId, version }: { farmId: number; version: string }) {
  const { t } = useLang();
  const W = t.wt;
  const { data } = useKeyedData<Tips>(String(farmId), version, (id) => api.farmWeatherTips(Number(id)));
  if (!data || data.tips.length === 0) return null;
  const known = data.conditions.filter((c) => W.cond[c.kind]);
  return (
    <details open className="rounded-2xl border border-line/70 bg-white" data-testid="weather-tips">
      <summary className="flex min-h-[2.75rem] cursor-pointer items-center px-4 py-2 text-base font-extrabold text-leaf-800">{W.title}</summary>
      <div className="space-y-3 px-3 pb-3">
        <p className="px-1 text-xs text-mute">{W.note}</p>
        <div>
          <h3 className="text-sm font-semibold">{W.conditionsTitle}</h3>
          {known.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1.5" data-testid="weather-conditions">
              {known.map((c) => <li key={c.kind} className="chip" data-kind={c.kind}>{W.cond[c.kind](Number(shown(c.value)))}</li>)}
            </ul>
          ) : (
            <p className="mt-1 text-sm" data-testid="weather-normal">{W.normal}</p>
          )}
        </div>
        {GROUPS.map((g) => {
          const items = data.tips.filter((x) => x.group === g && W.tips[x.kind]);
          if (items.length === 0) return null;
          return (
            <div key={g} data-group={g} className="rounded-2xl bg-leaf-50 p-3">
              <h3 className="flex items-center gap-2 text-sm font-extrabold text-leaf-800">
                <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-leaf-800 text-[#c8f169]"><PlanIcon name={GROUP_ICON[g]} size={18} /></span>
                {W.groups[g]}
              </h3>
              <ul className="mt-2 space-y-2 text-sm" data-testid={`weather-tips-${g}`}>
                {items.map((x) => <li key={x.kind} data-tip={x.kind} className="rounded-xl bg-white px-3 py-2 shadow-sm">{W.tips[x.kind]}</li>)}
              </ul>
            </div>
          );
        })}
      </div>
    </details>
  );
}
