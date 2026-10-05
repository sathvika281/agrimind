import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Farm, InsightEvidence, Insights as InsightsData, Sev } from "../api";
import { ErrorBox, Spinner } from "../components";
import { useFarms } from "../FarmContext";
import { answer, profileAnswer, PROFILE_QUESTIONS, QUESTIONS, trendObservation, type ProfileQuestionId, type QuestionId } from "../insights/answers";
import { DecisionCard } from "../insights/DecisionPanel";
import { DECISION_QUESTIONS, decisionAnswer, type DecisionQuestionId } from "../insights/decision";
import { useDecision } from "../insights/useDecision";
import { ProactiveSection } from "../insights/ProactiveSection";
import { proactiveAnswer } from "../insights/proactive";
import { useProactive } from "../insights/useProactive";
import { useInsights } from "../insights/useInsights";
import { useEvents } from "./Diary";
import type { Decision, Proactive } from "../api";
import { useLang } from "../LanguageContext";
import { useStatus } from "../overview/StatusContext";

const SEV_ORDER: Sev[] = ["high", "medium", "low", "unknown"];
const SEV_BAR: Record<Sev, string> = { high: "bg-[#a63a30]", medium: "bg-[#d9822f]", low: "bg-[#1f6a45]", unknown: "bg-[#b6beb6]" };
const SEV_ICON: Record<Sev, string> = { high: "⚠", medium: "!", low: "✓", unknown: "–" };

function useDateFmt() {
  const { t } = useLang();
  return (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short" });
}

function Evidence({ items }: { items: InsightEvidence[] }) {
  const { t } = useLang();
  const fmt = useDateFmt();
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="micro">{t.ins.evidence}</span>
      {items.map((e) => (
        <Link key={e.analysis_id} to={`/analyses/${e.analysis_id}`} aria-label={`${t.ins.open}: ${fmt(e.at)}`} className="chip flex min-h-[2.5rem] items-center hover:bg-leaf-50">
          {fmt(e.at)}
        </Link>
      ))}
    </div>
  );
}

function Panel({ title, tag, children }: { title: string; tag?: boolean; children: React.ReactNode }) {
  const { t } = useLang();
  return (
    <section className="panel" aria-label={title}>
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <h2 className="text-sm font-bold">{title}</h2>
        {tag && <span className="tag-mint">{t.ins.fromChecks}</span>}
      </div>
      <div className="space-y-3 p-3">{children}</div>
    </section>
  );
}

function Summary({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  const fmt = useDateFmt();
  const msg = d.level === "none" ? I.levelNone : d.level === "one" ? I.levelOne : d.level === "limited" ? I.levelLimited : I.levelEnough(d.total);
  return (
    <section className="panel" aria-label={I.title}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-3">
        <div className="min-w-[8rem]">
          <div className="micro">{I.title}</div>
          <div className="text-2xl font-extrabold">{I.checksCount(d.total)}</div>
        </div>
        {d.last_at && (
          <div>
            <div className="micro">{I.lastCheck}</div>
            <div className="text-sm font-semibold">{fmt(d.last_at)}</div>
          </div>
        )}
        {d.first_at && d.total > 1 && (
          <div>
            <div className="micro">{I.firstCheck}</div>
            <div className="text-sm font-semibold">{fmt(d.first_at)}</div>
          </div>
        )}
        <p className="min-w-[14rem] flex-1 text-sm text-mute" data-testid="ins-level" data-level={d.level}>{msg}</p>
        {d.total === 0 && <Link to="/analyze" className="btn-sm-dark">📷 {I.startCheck}</Link>}
      </div>
    </section>
  );
}

function Trends({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  if (d.total < 4) return null; // below this, the level message above is the honest answer; no trend is claimed
  return (
    <Panel title={I.trendsTitle} tag>
      {d.trends.length === 0 && <p className="text-sm text-mute" data-testid="ins-nopattern">{I.noPattern}</p>}
      {d.trends.map((tr, i) => (
        <article key={`${tr.kind}-${i}`} className="space-y-1.5 rounded-md border border-line bg-ground p-3" data-testid="ins-trend" data-kind={tr.kind}>
          <div><span className="micro">{I.observation}</span><p className="text-sm font-semibold">{trendObservation(I, tr)}</p></div>
          <div><span className="micro">{I.interpretation}</span><p className="text-sm">{I.interp[tr.kind]}</p></div>
          <div><span className="micro">{I.recommendation}</span><p className="text-sm">{I.reco[tr.kind]}</p></div>
          <Evidence items={tr.evidence} />
        </article>
      ))}
    </Panel>
  );
}

function Comparison({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  const fmt = useDateFmt();
  const c = d.comparison;
  if (!c) return null;
  const a = answer(I, d, "changed", fmt);
  return (
    <Panel title={I.comparisonTitle} tag>
      {a.lines.map((l, i) => <p key={i} className="text-sm">{l}</p>)}
      <Evidence items={a.evidence} />
    </Panel>
  );
}

function Frequency({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  const max = Math.max(1, ...d.issues.map((g) => g.count));
  return (
    <Panel title={I.freqTitle} tag>
      {d.total < 2 ? (
        <p className="text-sm text-mute">{I.freqNeed}</p>
      ) : d.issues.length === 0 || d.issues[0].count < 2 ? (
        <p className="text-sm text-mute">{I.freqNone}</p>
      ) : (
        <ul className="space-y-2">
          {d.issues.filter((g) => g.count >= 2).slice(0, 5).map((g) => (
            <li key={g.label}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="min-w-0 flex-1 break-words">{g.label}</span>
                <span className="shrink-0 font-mono text-xs font-semibold">{I.freqCount(g.count)}</span>
              </div>
              <div className="mt-1 h-2 rounded bg-line" aria-hidden><div className="h-2 rounded bg-leaf-700" style={{ width: `${(g.count / max) * 100}%` }} /></div>
            </li>
          ))}
        </ul>
      )}
      {d.unclear_count > 0 && <p className="text-xs text-mute">{I.unclearNote(d.unclear_count)}</p>}
    </Panel>
  );
}

function Severity({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  if (d.total === 0) return null;
  return (
    <Panel title={I.sevTitle} tag>
      <div className="flex h-3 overflow-hidden rounded bg-line" role="img" aria-label={SEV_ORDER.map((s) => `${I.sev[s]}: ${d.severity_counts[s]}`).join(", ")}>
        {SEV_ORDER.filter((s) => d.severity_counts[s] > 0).map((s) => (
          <div key={s} className={SEV_BAR[s]} style={{ width: `${(d.severity_counts[s] / d.total) * 100}%` }} />
        ))}
      </div>
      <ul className="space-y-1 text-sm">
        {SEV_ORDER.map((s) => (
          <li key={s} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-2"><span aria-hidden className={`inline-block h-3 w-3 rounded-sm ${SEV_BAR[s]}`} /><span aria-hidden>{SEV_ICON[s]}</span>{I.sev[s]}</span>
            <span className="font-mono text-xs font-semibold">{d.severity_counts[s]}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-mute">{I.sevNote}</p>
    </Panel>
  );
}

function Recent({ d }: { d: InsightsData }) {
  const { t } = useLang();
  const I = t.ins;
  const fmt = useDateFmt();
  return (
    <Panel title={I.recentTitle} tag>
      {d.recent.length === 0 ? (
        <p className="text-sm text-mute">{I.recentNone}</p>
      ) : (
        <ol className="divide-y divide-line">
          {d.recent.map((c) => (
            <li key={c.analysis_id}>
              <Link to={`/analyses/${c.analysis_id}`} className="block min-h-[2.75rem] py-1.5 hover:bg-ground">
                <span className="micro">{fmt(c.at)} · {c.crop} · {I.sev[c.severity]}</span>
                <span className="block text-sm">{c.issue || "—"}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}

function ProfileStrip({ farm, d }: { farm: Farm; d: InsightsData | null }) {
  const { t } = useLang();
  const I = t.ins;
  const P = t.prof;
  const long = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" });
  // Only what the farmer actually entered; nothing is inferred or filled in.
  const parts = [
    farm.primary_crop && I.profileCrop(farm.primary_crop),
    farm.irrigation_method && I.profileIrrigation(P.irrigationOpts[farm.irrigation_method] ?? farm.irrigation_method),
    farm.season && I.profileSeason(P.seasonOpts[farm.season] ?? farm.season),
    farm.planting_date && I.planted(long(farm.planting_date)),
  ].filter(Boolean) as string[];
  // Checks stored BEFORE the profile was recorded were not made with it; say so instead of implying they were.
  const later = !!(farm.context_updated_at && d?.first_at && new Date(d.first_at) < new Date(farm.context_updated_at));
  return (
    <section className="panel" aria-label={I.profileTitle} data-testid="ins-profile">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="micro">{I.profileTitle}</div>
          <p className="text-sm" data-testid="ins-profile-text">{parts.length ? I.profileLine(parts.join(" · ")) : I.profileNone}</p>
          {parts.length > 0 && later && farm.context_updated_at && <p className="mt-0.5 text-xs text-mute" data-testid="ins-profile-later">{I.profileLater(long(farm.context_updated_at))}</p>}
        </div>
        <Link to="/profile" className="btn-sm-light">{I.profileOpen}</Link>
      </div>
    </section>
  );
}

function Ask({ d, farm, decision, proactive }: { d: InsightsData; farm: Farm; decision: Decision | null; proactive: Proactive | null }) {
  const { t } = useLang();
  const I = t.ins;
  const fmt = useDateFmt();
  const [q, setQ] = useState<QuestionId | ProfileQuestionId | DecisionQuestionId | "needs" | null>(null);
  const a = useMemo(() => {
    if (!q) return null;
    const long = (iso: string) => new Date(iso).toLocaleDateString(t.locale, { day: "numeric", month: "long", year: "numeric" });
    if (q === "needs") return proactive ? proactiveAnswer(t.pi, t.ds, proactive, fmt) : { lines: [t.pi.ans.none], evidence: [], insufficient: false };
    if ((DECISION_QUESTIONS as string[]).includes(q))
      return decision ? decisionAnswer(t.ds, t.prof, decision, q as DecisionQuestionId, fmt, long) : { lines: [t.ds.noneNext], evidence: [], insufficient: true };
    return (PROFILE_QUESTIONS as string[]).includes(q) ? profileAnswer(I, t.prof, d, farm, q as ProfileQuestionId, fmt, long) : answer(I, d, q as QuestionId, fmt);
  }, [q, I, d, farm, decision, proactive]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel title={I.askTitle}>
      <p className="text-xs text-mute">{I.askNote}</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label={I.askTitle}>
        {[...QUESTIONS, ...PROFILE_QUESTIONS, ...DECISION_QUESTIONS, "needs" as const].map((id) => (
          <button key={id} type="button" aria-pressed={q === id} onClick={() => setQ(id)} className={`min-h-[2.75rem] rounded-md border px-3 text-left text-sm font-semibold ${q === id ? "border-leaf-800 bg-leaf-800 text-white" : "border-line bg-white text-ink hover:bg-leaf-50"}`}>
            {I.q[id]}
          </button>
        ))}
      </div>
      {a && (
        <div role="status" aria-live="polite" className="space-y-1.5 rounded-md border border-line bg-ground p-3" data-testid="ins-answer" data-insufficient={a.insufficient}>
          {a.lines.map((l, i) => <p key={i} className="text-sm">{l}</p>)}
          <Evidence items={a.evidence} />
          <p className="text-xs text-mute">{I.ans.basis}</p>
        </div>
      )}
    </Panel>
  );
}

export default function Insights() {
  const { t } = useLang();
  const I = t.ins;
  const { selected, loading: farmsLoading, error: farmError } = useFarms();
  const { analyses } = useStatus();
  // Changes only when a check for THIS farm is added, so the page refetches then (and on farm change), not on every navigation.
  const version = useMemo(() => {
    const mine = (analyses ?? []).filter((a) => a.farm_id === selected?.id);
    return `${mine.length}:${mine[0]?.id ?? 0}`;
  }, [analyses, selected?.id]);
  const { data, error, loading, retry } = useInsights(selected?.id ?? null, version);
  const decision = useDecision(selected?.id ?? null, null, version);
  const diary = useEvents(selected?.id ?? null);
  const proactive = useProactive(selected?.id ?? null, version);

  if (farmError) return <ErrorBox message={farmError} />;
  if (farmsLoading) return <Spinner />;
  if (!selected)
    return (
      <div className="mx-auto max-w-xl space-y-4 py-6">
        <h1 className="text-2xl font-extrabold">{I.title}</h1>
        <p className="text-mute">{t.dash.noFarm}</p>
        <Link to="/farms/new" className="btn-hero">{t.dash.addFarm}</Link>
      </div>
    );

  return (
    <div className="mx-auto max-w-[1100px] space-y-3">
      <div>
        <Link to="/" className="link-btn text-sm">{I.back}</Link>
        <h1 className="text-2xl font-extrabold text-ink sm:text-3xl">{I.title}</h1>
        <p className="text-sm text-mute">{I.sub} · {I.forFarm(selected.name)}</p>
      </div>
      {error && (
        <div>
          <ErrorBox message={error || I.loadError} />
          <button type="button" className="btn-secondary" onClick={retry}>{I.retry}</button>
        </div>
      )}
      {loading && <Spinner />}
      {data && (
        <>
          <ProactiveSection data={proactive.data} loading={proactive.loading} error={proactive.error} retry={proactive.retry} farmName={selected.name} />
          <ProfileStrip farm={selected} d={data} />
          <Summary d={data} />
          <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="min-w-0 space-y-3">
              <DecisionCard data={decision.data} loading={decision.loading} error={decision.error} retry={decision.retry} />
              <Trends d={data} />
              <Comparison d={data} />
              <Ask d={data} farm={selected} decision={decision.data} proactive={proactive.data} />
              {diary.items && diary.items.length > 0 && (
                <section className="panel" aria-label={t.dy.recent} data-testid="insights-diary">
                  <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
                    <div className="flex items-center gap-2"><h2 className="text-sm font-bold">{t.dy.recent}</h2><span className="tag-mint">{t.dy.insightsNote}</span></div>
                    <Link to="/diary" className="link-btn flex min-h-[2.5rem] items-center text-sm">{t.dy.title}</Link>
                  </div>
                  <ul className="divide-y divide-line">
                    {diary.items.slice(0, 5).map((ev) => (
                      <li key={ev.id} className="px-3 py-2 text-sm"><span className="font-semibold">{t.dy.kinds[ev.kind] ?? ev.kind}</span> <span className="micro">· {new Date(ev.event_date + "T00:00:00").toLocaleDateString(t.locale, { day: "numeric", month: "short", year: "numeric" })}</span>{ev.note && <span className="block break-words text-ink/80">{ev.note}</span>}</li>
                    ))}
                  </ul>
                </section>
              )}
              <Panel title={I.unknownTitle}>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {I.unknown.map((u) => <li key={u}>{u}</li>)}
                </ul>
              </Panel>
            </div>
            <div className="min-w-0 space-y-3">
              {data.total > 0 && <Frequency d={data} />}
              <Severity d={data} />
              <Recent d={data} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
