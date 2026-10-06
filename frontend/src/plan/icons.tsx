import type { ReactNode } from "react";

/** One consistent icon family for the Farm plan: 24 px grid, 1.8 stroke, currentColor. Decorative (aria-hidden): the text next to
 *  every icon says the same thing, so nothing relies on the picture alone and nothing depends on platform emoji. */
function Svg({ children, size = 24 }: { children: ReactNode; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

const CLOUD = "M7 17h10a3.8 3.8 0 0 0 .4-7.58A5.4 5.4 0 0 0 7 8.9 4.05 4.05 0 0 0 7 17z";
const ICONS: Record<string, ReactNode> = {
  sun: (<><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6" /></>),
  partly: (<><circle cx="8" cy="8" r="2.8" /><path d="M8 2.6v1.2M2.6 8h1.2M4.2 4.2l.9.9M11.8 4.2l-.9.9" /><path d="M9 19h8.2a3.4 3.4 0 0 0 .3-6.8 4.8 4.8 0 0 0-9 .8A3.1 3.1 0 0 0 9 19z" /></>),
  rain: (<><path d={CLOUD} transform="translate(0 -2)" /><path d="M8.5 17.5l-1 2.5M12.5 17.5l-1 2.5M16.5 17.5l-1 2.5" /></>),
  wind: (<><path d="M3 9h10a2.6 2.6 0 1 0-2.5-3.3M3 14h14a2.8 2.8 0 1 1-2.6 3.8M3 19h6" /></>),
  storm: (<><path d={CLOUD} transform="translate(0 -2)" /><path d="M12.8 14l-2.6 3.6h2.8L11.2 21" /></>),
  sow: (<><path d="M12 21v-8.5" /><path d="M12 12.5c0-3.6-2.6-5.6-6.3-5.6 0 3.6 2.6 5.6 6.3 5.6z" /><path d="M12 15c0-3 2.2-5 5.8-5 0 3-2.2 5-5.8 5z" /></>),
  water: (<path d="M12 3.2s5.8 5.9 5.8 10.2A5.8 5.8 0 0 1 6.2 13.4C6.2 9.1 12 3.2 12 3.2z" />),
  weed: (<path d="M5.5 20.5c0-5 1-9 3-12.5M12 20.5c0-6 0-10.5 0-14.5M18.5 20.5c0-5-1-9-3-12.5" />),
  harvest: (<><path d="M4 10.5h16l-1.5 8.2a2 2 0 0 1-2 1.6h-9a2 2 0 0 1-2-1.6L4 10.5z" /><path d="M8 10.5l3.2-5.5M16 10.5L12.8 5" /></>),
  other: (<path d="M12 5v14M5 12h14" />),
  hold: (<><circle cx="12" cy="12" r="9" /><path d="M10 9v6M14 9v6" /></>),
  inspect: (<><circle cx="10.5" cy="10.5" r="6" /><path d="M15 15l5.5 5.5" /></>),
  warn: (<><path d="M12 3.5l9.2 16H2.8L12 3.5z" /><path d="M12 10v4.2M12 17.2h.01" /></>),
  check: (<path d="M5 12.5l4.5 4.5L19 7.5" />),
  refresh: (<><path d="M20 12a8 8 0 1 1-2.4-5.7" /><path d="M20 4.5v4.8h-4.8" /></>),
  history: (<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.2 2" /></>),
  info: (<><circle cx="12" cy="12" r="9" /><path d="M12 11v5.2M12 7.8h.01" /></>),
  crop: (<><path d="M5 19c0-8 5-13 14-14 0 9-5 14-14 14z" /><path d="M5 19c3-4 6-7 10-9" /></>),
  chevron: (<path d="M9 6l6 6-6 6" />),
  down: (<path d="M6 9l6 6 6-6" />),
  close: (<path d="M6 6l12 12M18 6L6 18" />),
  left: (<path d="M15 6l-6 6 6 6" />),
  right: (<path d="M9 6l6 6-6 6" />),
  temp: (<path d="M14 14.4V5.5a2 2 0 0 0-4 0v8.9a4 4 0 1 0 4 0z" />),
  drop: (<path d="M12 3.2s5.8 5.9 5.8 10.2A5.8 5.8 0 0 1 6.2 13.4C6.2 9.1 12 3.2 12 3.2z" />),
  chance: (<><path d={CLOUD} transform="translate(0 -2)" /><path d="M9 18.5h6" /></>),
  link: (<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>),
  arrow: (<path d="M5 12h14M13 6l6 6-6 6" />),
};

export function PlanIcon({ name, size = 24 }: { name: string; size?: number }) {
  return <Svg size={size}>{ICONS[name] ?? ICONS.info}</Svg>;
}

/** Which icon each plan step, activity and weather kind uses. */
export const KIND_ICON: Record<string, string> = {
  inspect_plants: "inspect", watch_spread: "inspect", recheck_crop: "history", ask_expert: "warn", add_detail: "info", monitor_routine: "check",
  drain_field: "water", dry_field: "water", irrigation_hold: "hold", reassess_after_rain: "history", irrigation_plan: "water", planting_window: "sow",
  if_rain_arrives: "rain", if_forecast_changes: "refresh", if_heat_arrives: "sun", if_symptoms_spread: "inspect",
};
export const ACTIVITY_ICON: Record<string, string> = { sowing: "sow", transplanting: "sow", irrigation: "water", weeding: "weed", harvest: "harvest", other: "other" };
