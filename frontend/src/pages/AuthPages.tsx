import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../AuthContext";
import { ErrorBox, Page, Spinner } from "../components";
import { useLang } from "../LanguageContext";

function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { user, loading, login, register } = useAuth();
  const { t } = useLang();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);

  if (loading) return <Spinner />;
  if (user) return <Navigate to="/" replace />;

  const isLogin = mode === "login";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (!email.trim() || !password) return setError(t.auth.needBoth);
    setBusy(true);
    try {
      await (isLogin ? login(email, password) : register(email, password));
      nav("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t.err.generic);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title={isLogin ? t.auth.welcomeBack : t.auth.createTitle}>
      <p className="-mt-3 mb-4 text-lg text-gray-700">{t.auth.tagline}</p>
      <form onSubmit={submit} className="card space-y-4" noValidate>
        <ErrorBox message={error} />
        <div>
          <label htmlFor="email" className="label">{t.auth.email}</label>
          <input id="email" type="email" autoComplete="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password" className="label">{t.auth.password}{!isLogin && t.auth.passwordHint}</label>
          <input
            id="password"
            type={show ? "text" : "password"}
            autoComplete={isLogin ? "current-password" : "new-password"}
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button type="button" className="link-btn mt-1" onClick={() => setShow((s) => !s)} aria-pressed={show}>
            {show ? t.auth.hide : t.auth.show}
          </button>
        </div>
        <button className="btn-primary" disabled={busy}>
          {busy ? t.auth.wait : isLogin ? t.auth.logIn : t.auth.createBtn}
        </button>
      </form>
      <p className="mt-5 text-center text-lg">
        {isLogin ? t.auth.newHere : t.auth.haveAccount}
        <Link className="inline-flex min-h-[2.75rem] items-center font-semibold text-leaf-700 underline" to={isLogin ? "/register" : "/login"}>
          {isLogin ? t.auth.createLink : t.auth.logInLink}
        </Link>
      </p>
      <p className="mt-2 text-center">
        <Link to="/privacy" className="inline-flex min-h-[2.75rem] items-center text-base text-mute underline" data-testid="privacy-link">{t.ac.privacy}</Link>
      </p>
    </Page>
  );
}

export const LoginPage = () => <AuthForm mode="login" />;
export const RegisterPage = () => <AuthForm mode="register" />;
