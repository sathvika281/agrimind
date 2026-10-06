import { useLang } from "../LanguageContext";
import { PlanIcon } from "./icons";

const FIELDS = [["none", "check"], ["waterlogged", "water"], ["dry", "sun"], ["pests_seen", "inspect"], ["wilting", "weed"]] as const;

/** How is the field right now? One tap sets it; the selected chip is filled and carries a check mark. */
export function FieldChips({ value, onChange, busy }: { value: string; onChange: (v: string) => void; busy: boolean }) {
  const { t } = useLang();
  const U = t.fpl.ui;
  return (
    <section aria-label={U.fieldLabel} data-testid="field-chips">
      <h2 className="mb-1.5 text-xs font-bold uppercase tracking-widest text-mute">{U.fieldLabel}</h2>
      <div role="radiogroup" aria-label={U.fieldLabel} className="flex flex-wrap gap-2">
        {FIELDS.map(([k, icon]) => {
          const on = (value || "none") === k;
          return (
            <button key={k} type="button" role="radio" aria-checked={on} disabled={busy} onClick={() => !on && onChange(k)} data-testid={`field-${k}`} data-on={on}
              className={`inline-flex min-h-[2.75rem] items-center gap-1.5 rounded-full border px-4 text-sm font-semibold transition ${on ? "border-transparent bg-leaf-800 text-white shadow" : "border-leaf-200 bg-white text-leaf-800 hover:border-leaf-500"}`}>
              <PlanIcon name={on ? "check" : icon} size={18} />{U.fields[k]}
            </button>
          );
        })}
      </div>
    </section>
  );
}
