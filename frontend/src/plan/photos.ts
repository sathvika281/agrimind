/** Free-license photos (Pexels), stored in public/img and served from this site: no external request. Credits: public/img/CREDITS.md */
const BY_PREFIX: [string, string][] = [
  ["/weather", "weather"], ["/analyze", "analyze-greens"], ["/analyses", "result"], ["/history", "history"], ["/farms", "farms"],
  ["/diary", "diary"], ["/profile", "profile"], ["/plan", "plan"], ["/economics", "economics-market"], ["/insights", "insights"], ["/account", "farms"],
];

/** The header photo for a route (every main page has its own). */
export function photoFor(pathname: string): string {
  if (pathname === "/") return "/img/overview.jpg";
  const hit = BY_PREFIX.find(([p]) => pathname === p || pathname.startsWith(p + "/"));
  return `/img/${hit ? hit[1] : "insights"}.jpg`;
}
