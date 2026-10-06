// Small inline stroke icons (no icon library, no network). Decorative: always aria-hidden next to text.
import type { ReactNode } from "react";

function Svg({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
      {children}
    </svg>
  );
}

export const IconOverview = () => (<Svg><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></Svg>);
export const IconFarms = () => (<Svg><path d="M3 20h18M5 20V9l7-5 7 5v11" /><path d="M10 20v-6h4v6" /></Svg>);
export const IconCopilot = () => (<Svg><rect x="4" y="8" width="16" height="11" rx="2" /><path d="M12 8V4M9 13h.01M15 13h.01M9 16.5h6" /></Svg>);
export const IconChecks = () => (<Svg><path d="M9 6h11M9 12h11M9 18h11" /><path d="M3.5 6l1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2" /></Svg>);
export const IconWeather = () => (<Svg><path d="M7 18a4 4 0 1 1 .8-7.9A5.5 5.5 0 0 1 18.5 11 3.5 3.5 0 0 1 18 18H7z" /></Svg>);
export const IconSoil = () => (<Svg><path d="M12 3l9 5-9 5-9-5 9-5z" /><path d="M3 13l9 5 9-5M3 17.5l9 5 9-5" /></Svg>);
export const IconInsights = () => (<Svg><path d="M3 17l5-5 4 4 8-9" /><path d="M15 7h5v5" /></Svg>);
export const IconAnalytics = () => (<Svg><path d="M5 20V10M12 20V4M19 20v-7" /></Svg>);
export const IconLeaf = ({ size = 18 }: { size?: number }) => (<Svg size={size}><path d="M5 19c0-9 6-14 15-14 0 9-5 15-14 15" /><path d="M5 19c3-5 6-8 11-10" /></Svg>);
export const IconDrop = () => (<Svg><path d="M12 3c3 4 6 7 6 11a6 6 0 0 1-12 0c0-4 3-7 6-11z" /></Svg>);
export const IconMic = () => (<Svg><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></Svg>);
export const IconProfile = () => (<Svg><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" /></Svg>);
export const IconPlan = () => (<Svg><path d="M4 6h16M4 12h10M4 18h7" /><path d="M17 15l2 2 3-4" /></Svg>);
export const IconEconomics = () => (<Svg><path d="M6 4h12M6 9h12M9 4c4 0 6 2 6 5s-2 5-6 5h-1l8 6" /></Svg>);
export const IconDiary = () => (<Svg><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h4" /></Svg>);
