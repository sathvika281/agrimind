import { Page } from "../components";
import { useLang } from "../LanguageContext";

// The operator sets this at build time (VITE_CONTACT_EMAIL). Until then the page says so instead of showing a fake address.
const CONTACT = (import.meta.env.VITE_CONTACT_EMAIL as string | undefined)?.trim();

export default function Privacy() {
  const { t } = useLang();
  const P = t.pv;
  return (
    <Page title={P.title} back="/">
      <p className="-mt-3 mb-4 text-base text-mute">{P.updated}</p>
      <div className="space-y-4" data-testid="privacy">
        {P.sections.map((s) => (
          <section key={s.h} className="card space-y-2">
            <h2 className="text-xl font-bold text-leaf-800">{s.h}</h2>
            {s.p.map((x) => <p key={x} className="text-base text-ink/90">{x}</p>)}
          </section>
        ))}
        <p className="text-base font-semibold" data-testid="privacy-contact">{CONTACT ? P.contact(CONTACT) : P.contactNone}</p>
      </div>
    </Page>
  );
}
