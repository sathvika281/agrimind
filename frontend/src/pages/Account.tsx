import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../AuthContext";
import { ErrorBox, Page, Spinner } from "../components";
import { useLang } from "../LanguageContext";

export default function Account() {
  const { t } = useLang();
  const A = t.ac;
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [sure, setSure] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  if (!user) return <Spinner />;

  async function download() {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await api.exportMyData();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "agrimind-data.json";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof ApiError ? e.message : A.exportError);
    } finally {
      setExporting(false);
    }
  }

  async function remove(e: FormEvent) {
    e.preventDefault();
    if (deleting) return;
    setDeleteError(null);
    if (!password || !sure) return setDeleteError(A.needBoth);
    setDeleting(true);
    try {
      await api.deleteAccount(password);
      await logout().catch(() => undefined); // the server already cleared the cookie; this clears the app's state
      nav("/login", { replace: true });
    } catch (err) {
      setDeleteError(err instanceof ApiError && err.status === 403 ? A.wrongPassword : err instanceof ApiError && err.status === 429 ? err.message : A.deleteError);
      setDeleting(false);
    }
  }

  return (
    <Page title={A.title} back="/">
      <p className="-mt-3 mb-4 text-base text-mute" data-testid="account-email">{A.email}: <span className="font-semibold text-ink">{user.email}</span></p>
      <div className="space-y-5">
        <section className="card space-y-3" aria-label={A.exportTitle}>
          <h2 className="text-xl font-bold text-leaf-800">{A.exportTitle}</h2>
          <p className="text-base text-mute">{A.exportNote}</p>
          <ErrorBox message={exportError} />
          <button type="button" className="btn-secondary" disabled={exporting} onClick={() => void download()} data-testid="export-button">
            {exporting ? A.exporting : A.exportBtn}
          </button>
        </section>

        <section className="card space-y-3 border-2 border-red-200" aria-label={A.deleteTitle}>
          <h2 className="text-xl font-bold text-red-900">{A.deleteTitle}</h2>
          <p className="text-base text-ink">{A.deleteWarn}</p>
          <form onSubmit={remove} className="space-y-3" noValidate data-testid="delete-form">
            <ErrorBox message={deleteError} />
            <div>
              <label htmlFor="del-password" className="label">{A.password}</label>
              <input id="del-password" type="password" autoComplete="current-password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} disabled={deleting} />
            </div>
            <label className="flex min-h-[2.75rem] items-center gap-3 text-base">
              <input type="checkbox" className="h-5 w-5" checked={sure} onChange={(e) => setSure(e.target.checked)} disabled={deleting} />
              {A.confirm}
            </label>
            <button className="btn-primary !bg-red-800 hover:!bg-red-900" disabled={deleting} data-testid="delete-button">{deleting ? A.deleting : A.deleteBtn}</button>
          </form>
        </section>

        <Link to="/privacy" className="link-btn inline-flex min-h-[2.75rem] items-center text-base">{A.privacy}</Link>
      </div>
    </Page>
  );
}
