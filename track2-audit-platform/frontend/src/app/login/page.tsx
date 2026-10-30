"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import { setSession } from "@/lib/api";

export default function Page() {
  const router = useRouter();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin-password");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");

    if (!username.trim() || !password.trim()) {
      setError("Please enter both username and password.");
      setBusy(false);
      return;
    }

    setSession("demo-session-token", ["ADMIN"]);
    router.push("/dashboard/");
    setBusy(false);
  }

  return (
    <main className="login-page-shell">
      <div className="login-demo-card">
        <section className="login-form-panel">
          <a className="login-brand" href="/" aria-label="Finstack home">
            <span className="login-brand-icon"><ShieldCheck size={19} /></span>
            <span>Finstack</span>
          </a>

          <div className="login-intro">
            <span className="login-eyebrow">AUDIT OPERATIONS PORTAL</span>
            <h1>Welcome back</h1>
            <p>Sign in to your workspace to continue reviewing audit activity.</p>
          </div>

          <form onSubmit={handleSubmit} className="demo-login-form">
            <label className="demo-field">
              <span>Username</span>
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="Enter your username"
              />
            </label>

            <label className="demo-field">
              <span>Password</span>
              <span className="password-input-wrap">
                <input
                  autoComplete="current-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter your password"
                />
                <button
                  type="button"
                  className="password-toggle"
                  onClick={() => setShowPassword((visible) => !visible)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </span>
            </label>

            {error ? <p className="demo-login-error" role="alert">{error}</p> : null}

            <button type="submit" className="demo-login-button" disabled={busy}>
              <span>{busy ? "Signing in..." : "Sign in to workspace"}</span>
              {!busy ? <ArrowRight size={17} /> : null}
            </button>
          </form>

          <div className="demo-account-note">
            <span className="demo-note-indicator" />
            <span><strong>Demo mode</strong> · Any non-empty credentials will work.</span>
          </div>
          <p className="login-legal">Finstack Audit Platform <span>•</span> Secure review workspace</p>
        </section>
        <aside className="login-brand-panel">
          <div className="brand-panel-top">
            <span className="brand-panel-mark"><ShieldCheck size={17} /></span>
            <span>FINSTACK <b>/</b> AUDIT</span>
          </div>
          <div className="brand-panel-content">
            <span className="brand-panel-label">EVIDENCE FIRST. ALWAYS.</span>
            <h2>Clarity and control for every review.</h2>
            <p>Bring transactions, findings, and cases together in one trusted audit workspace.</p>
            <div className="brand-panel-rule" />
            <div className="brand-panel-footer">
              <div className="brand-panel-badge"><ShieldCheck size={18} /></div>
              <div><strong>Built for confident decisions</strong><span>Traceable. Deterministic. Human-reviewed.</span></div>
            </div>
          </div>
          <div className="brand-panel-decoration" aria-hidden="true">
            <span /><span /><span /><span /><span />
          </div>
        </aside>
      </div>
    </main>
  );
}
