import { api, type WeatherTips as Tips } from "../api";
import { useKeyedData } from "../insights/useFarmData";
import { useLang } from "../LanguageContext";

const GROUPS = ["protect", "water", "watch"] as const;
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
    <details open className="rounded-md border border-line bg-white" data-testid="weather-tips">
      <summary className="flex min-h-[2.5rem] cursor-pointer items-center px-3 py-2 text-sm font-bold text-leaf-800">{W.title}</summary>
      <div className="space-y-3 px-3 pb-3">
        <p className="text-sm text-mute">{W.note}</p>
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
            <div key={g} data-group={g}>
              <h3 className="text-sm font-semibold text-leaf-800">{W.groups[g]}</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-sm" data-testid={`weather-tips-${g}`}>
                {items.map((x) => <li key={x.kind} data-tip={x.kind}>{W.tips[x.kind]}</li>)}
              </ul>
            </div>
          );
        })}
      </div>
    </details>
  );
}
