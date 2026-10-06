import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useLang } from "../LanguageContext";
import { PlanIcon } from "./icons";

/** A small accessible dialog: a bottom sheet on phones, a centred panel on wide screens. No library.
 *  Esc and the backdrop close it, focus moves in and is restored, the page behind does not scroll, Tab stays inside. */
export function Sheet({ title, onClose, children, testId }: { title: string; onClose: () => void; children: ReactNode; testId?: string }) {
  const { t } = useLang();
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const scrollY = window.scrollY;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = "";
      window.scrollTo({ top: scrollY });
      opener?.focus?.();
    };
  }, []);

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !panelRef.current) return;
    const f = [...panelRef.current.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])')].filter((x) => x.getClientRects().length);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" onKeyDown={onKey} data-testid={testId}>
      <div className="plan-fade absolute inset-0 bg-[#06150f]/60" onClick={onClose} data-testid="sheet-backdrop" aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="plan-sheet relative flex max-h-[85vh] w-full flex-col overflow-hidden rounded-t-[1.75rem] bg-[#0f3a28] text-white shadow-2xl sm:max-w-md sm:rounded-[1.75rem]"
      >
        <div className="flex items-center justify-between gap-3 px-5 pb-2 pt-4">
          <h2 className="text-lg font-bold">{title}</h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label={t.fpl.ui.close} className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-white/10 hover:bg-white/20" data-testid="sheet-close">
            <PlanIcon name="close" size={20} />
          </button>
        </div>
        <div className="overflow-y-auto px-5 pb-6 pt-1">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
