import type { ReactNode } from "react";
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { SEVERITY_STYLE, friendlyDate } from "./copy";
import { useFarms } from "./FarmContext";
import { IconChecks, IconCopilot, IconDiary, IconFarms, IconInsights, IconLeaf, IconOverview, IconProfile, IconWeather } from "./icons";
import { LANGS, type Lang } from "./i18n";
import { useLang } from "./LanguageContext";
import { rainOutlook } from "./overview/derive";
import { useStatus } from "./overview/StatusContext";

export function Spinner({ label }: { label?: string }) {
  const { t } = useLang();
  return (
    <div className="flex items-center justify-center gap-3 py-10 text-lg text-leaf-700" role="status" aria-live="polite">
      <span aria-hidden className="h-6 w-6 animate-spin rounded-full border-4 border-leaf-200 border-t-leaf-600" />
      {label ?? t.loadingGeneric}
    </div>
  );
}

export function ErrorBox({ message, requestId }: { message: string | null; requestId?: string }) {
  const { t } = useLang();
  if (!message) return null;
  return (
    <div role="alert" className="mb-4 rounded-lg border-2 border-red-300 bg-red-50 px-4 py-3 text-base text-red-900">
      <span aria-hidden className="mr-1">⚠</span>
      {message}
      {requestId && (
        <details className="mt-2 text-sm text-red-800">
          <summary>{t.analyze.support}</summary>
          <p className="mt-1 break-all">{t.analyze.reference}: {requestId}</p>
        </details>
      )}
    </div>
  );
}

export function Page({ title, back, children }: { title: string; back?: string; children: ReactNode }) {
  const { t } = useLang();
  return (
    <div>
      {back && (
        <Link to={back} className="link-btn mb-1">
          {t.addFarm.back}
        </Link>
      )}
      <h1 className="mb-5 text-3xl font-bold text-leaf-800">{title}</h1>
      {children}
    </div>
  );
}

export function EmptyState({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="card space-y-4 text-center">
      <p className="text-xl font-semibold text-ink">{title}</p>
      {action}
    </div>
  );
}

export function SeverityBadge({ severity }: { severity?: string }) {
  const { t } = useLang();
  const s = severity ? SEVERITY_STYLE[severity] : undefined;
  const label = severity ? t.severity[severity] : undefined;
  if (!s || !label) return null; // "unknown" shows nothing
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm font-bold ${s.cls}`}>
      <span aria-hidden>{s.icon}</span>
      {label}
    </span>
  );
}

/** Compact two-button language switcher. Each option is written in its own language. */
function LanguageSwitcher() {
  const { lang, t, setLang } = useLang();
  return (
    <div role="group" aria-label={t.lang.label} className="inline-flex overflow-hidden rounded-md border border-leaf-800">
      {LANGS.map((l: Lang) => (
        <button
          key={l}
          type="button"
          lang={l}
          aria-pressed={lang === l}
          onClick={() => setLang(l)}
          className={`min-h-[2.75rem] px-3 text-sm font-semibold ${lang === l ? "bg-leaf-800 text-white" : "bg-white text-leaf-800 hover:bg-leaf-50"}`}
        >
          {l === "en" ? t.lang.en : t.lang.te}
        </button>
      ))}
    </div>
  );
}

function Brand({ compact = false, dark = false }: { compact?: boolean; dark?: boolean }) {
  const { t } = useLang();
  return (
    <Link to="/" className="flex min-h-[2.75rem] items-center gap-2">
      <span aria-hidden className={`grid h-9 w-9 shrink-0 place-items-center rounded-md ${dark ? "bg-mint-100 text-leaf-900" : "bg-leaf-800 text-mint-100"}`}>
        <IconLeaf size={20} />
      </span>
      <span className="min-w-0 leading-tight">
        <span className={`block text-base font-extrabold ${dark ? "text-white" : "text-ink"}`}>AgriMind</span>
        <span className={`micro block truncate ${compact ? "max-w-[9rem]" : ""} ${dark ? "text-white/65" : ""}`}>{t.shell.brandSub}</span>
      </span>
    </Link>
  );
}

/** Farm selector (real farms). `id` differs between the sidebar and the phone header (ids must be unique). */
function FarmSelector({ id, card = false, dark = false }: { id: string; card?: boolean; dark?: boolean }) {
  const { t } = useLang();
  const { farms, selected, select } = useFarms();
  if (!farms || !selected) return null;
  return (
    <div className={card ? (dark ? "rounded-md border border-white/15 bg-white/10 p-2" : "rounded-md border border-line bg-ground p-2") : "flex items-center gap-2 rounded-md border border-line bg-white px-2"}>
      {card && <div className={`micro mb-1 ${dark ? "text-white/65" : ""}`}>{t.shell.farm}</div>}
      <div className="flex items-center gap-2">
        <span aria-hidden className={`h-2 w-2 shrink-0 rounded-full ${dark ? "bg-mint-200" : "bg-green-600"}`} />
        <label htmlFor={id} className="sr-only">{t.shell.farm}</label>
        <select
          id={id}
          value={selected.id}
          onChange={(e) => select(Number(e.target.value))}
          className={`min-h-[2.75rem] min-w-0 flex-1 truncate bg-transparent text-sm font-semibold focus:outline-none ${dark ? "text-white [&>option]:text-ink" : "text-ink"}`}
        >
          {farms.map((f) => (
            <option key={f.id} value={f.id}>{f.name}</option>
          ))}
        </select>
      </div>
      {card && (
        <div className={`micro mt-0.5 ${dark ? "text-white/65" : ""}`}>
          {t.ov.farmsCount(farms.length)} · {t.shell.active}
        </div>
      )}
    </div>
  );
}

/** Small REAL status chips: from your latest checks and the selected farm's weather. */
function StatusChips() {
  const { t } = useLang();
  const { selected } = useFarms();
  const { summary, weatherByFarm } = useStatus();
  const fw = selected ? weatherByFarm[selected.id] : undefined;
  const out = rainOutlook(fw?.weather);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="chip"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-green-600" />{t.shell.healthy(summary.ok)}</span>
      <span className="chip"><span aria-hidden className="h-1.5 w-1.5 rounded-full bg-stress" />{t.shell.attention(summary.needsAttention)}</span>
      {summary.unrated > 0 && <span className="chip hidden xl:inline-flex">{t.shell.notRated(summary.unrated)}</span>}
      <span className="chip">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-water" />
        {out.kind === "rain" ? t.shell.rain(String(out.mm)) : out.kind === "dry" ? t.shell.dry : t.shell.noWeather}
      </span>
    </div>
  );
}

const sideLight = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-[2.75rem] shrink-0 items-center gap-2 rounded-md px-3 text-sm font-semibold whitespace-nowrap ${
    isActive ? "bg-leaf-800 text-white" : "text-ink hover:bg-leaf-100"
  }`;
const sideDark = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-[2.75rem] min-w-0 items-center gap-3 rounded-md px-3 text-[15px] font-semibold whitespace-nowrap ${
    isActive ? "bg-white/15 text-white" : "text-white/80 hover:bg-white/10 hover:text-white"
  }`;

/** The section links: a vertical list in the dark sidebar (md+) or a horizontally scrolling tab bar on phones. */
function NavItems({ vertical }: { vertical: boolean }) {
  const { t } = useLang();
  const side = vertical ? sideDark : sideLight;
  const label = (text: string) => <span className="min-w-0 truncate">{text}</span>;
  return (
    <nav
      aria-label={t.nav.label}
      className={vertical ? "flex min-h-0 flex-col gap-1 overflow-x-hidden" : "flex gap-1 overflow-x-auto border-b border-line bg-white px-2 py-1"}
    >
      <NavLink to="/" end className={side}><IconOverview />{label(t.nav.home)}</NavLink>
      <NavLink to="/farms" className={side}><IconFarms />{label(t.nav.farms)}</NavLink>
      <NavLink to="/analyze" className={side}><IconCopilot />{label(t.nav.check)}</NavLink>
      <NavLink to="/history" className={side}><IconChecks />{label(t.nav.checks)}</NavLink>
      <NavLink to="/weather" className={side}><IconWeather />{label(t.shell.nav.weather)}</NavLink>
      <NavLink to="/insights" className={side}><IconInsights />{label(t.shell.nav.insights)}</NavLink>
      <NavLink to="/diary" className={side}><IconDiary />{label(t.nav.diary)}</NavLink>
      <NavLink to="/profile" className={side}><IconProfile />{label(t.prof.editLink)}</NavLink>
    </nav>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const { t } = useLang();
  const { selected } = useFarms();
  const nav = useNavigate();
  const { pathname } = useLocation();

  // Signed-out pages (login/register): the same header language, no sidebar.
  if (!user) {
    return (
      <div className="min-h-screen bg-ground">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-3">{t.skip}</a>
        <header className="flex items-center justify-between gap-2 border-b border-line bg-white px-4 py-2">
          <Brand />
          <LanguageSwitcher />
        </header>
        <main id="main" tabIndex={-1} className="mx-auto max-w-md px-4 py-6"><Outlet /></main>
      </div>
    );
  }

  const wide = pathname === "/" || pathname === "/insights";
  const doLogout = async () => {
    await logout();
    nav("/login");
  };
  const initial = (user.email[0] ?? "?").toUpperCase();

  return (
    <div className="min-h-screen bg-ground md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:p-3">{t.skip}</a>

      {/* Sidebar (md+): brand, farm card, sections. Full page height; the inner block stays in view while scrolling. */}
      <aside className="hidden w-60 shrink-0 bg-leaf-900 md:block">
        <div className="sticky top-0 flex h-screen flex-col gap-3 overflow-x-hidden overflow-y-auto p-2">
          <Brand dark />
          <FarmSelector id="farm-switch" card dark />
          <NavItems vertical />
          {/* Account block: the signed-in email and Log out (no display name is stored, so none is shown or guessed). */}
          <div className="mt-auto border-t border-white/10 pt-2" data-testid="sidebar-account">
            <Link to="/account" className="micro flex min-h-[2.5rem] items-center truncate px-1 !text-white/80 underline-offset-2 hover:underline" title={user.email} aria-label={t.ac.title} data-testid="sidebar-email"><span className="truncate">{user.email}</span></Link>
            <button type="button" className="mt-1 flex min-h-[2.75rem] w-full items-center rounded-md px-3 text-sm font-semibold text-white/85 hover:bg-white/10 hover:text-white" onClick={doLogout}>{t.nav.logout}</button>
          </div>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        {/* Phone header: brand + switcher + logout, then farm + chips, then the scrolling section tabs. */}
        <div className="md:hidden">
          <header className="border-b border-line bg-white px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <Brand compact />
              <button className="link-btn shrink-0 text-sm" onClick={doLogout}>{t.nav.logout}</button>
            </div>
            <div className="mt-2 flex items-center gap-2">
              <div className="min-w-0 flex-1"><FarmSelector id="farm-switch-m" /></div>
              <LanguageSwitcher />
            </div>
            <div className="mt-2"><StatusChips /></div>
          </header>
          <NavItems vertical={false} />
        </div>

        {/* Desktop top bar: ONE slim row. */}
        <header className="hidden items-center gap-3 border-b border-line bg-white px-4 py-1.5 md:flex">
          <div className="hidden min-w-0 lg:block">
            <div className="micro">{t.ov.welcomeBack}</div>
            <div className="max-w-[14rem] truncate text-sm font-bold leading-tight text-ink">{selected?.name ?? "AgriMind"}</div>
          </div>
          <StatusChips />
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitcher />
            <span aria-hidden title={user.email} className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-leaf-800 text-xs font-bold text-white">{initial}</span>
          </div>
        </header>

        <main id="main" tabIndex={-1} className={`min-w-0 px-3 py-3 pb-16 md:px-4 ${wide ? "" : "mx-auto max-w-3xl"}`}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  return user ? <Outlet /> : <Navigate to="/login" replace />;
}

export function formatDate(iso: string): string {
  return friendlyDate(iso);
}
