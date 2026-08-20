import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { api, ApiClientError } from "@/lib/api";
import { Loader2, Shield, KeyRound } from "lucide-react";

type Step = "credentials" | "mfa-enrol" | "mfa-verify";

export function LoginPage() {
  const { login, setMfaDone, needsMfa, needsMfaEnrolment } = useAuth();
  const [step, setStep] = useState<Step>("credentials");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await login(email, password);
      if (resp.mfaRequired) {
        if (resp.mfaEnrolmentRequired) {
          const enrol = await api.auth.mfaEnrol();
          setTotpSecret(enrol.secret);
          setStep("mfa-enrol");
        } else {
          setStep("mfa-verify");
        }
      }
    } catch (err) {
      setError(
        err instanceof ApiClientError
          ? err.message
          : "Login failed. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleMfaEnrolConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const resp = await api.auth.mfaConfirm(totpCode);
      setRecoveryCodes(resp.codes);
      setMfaDone();
    } catch (err) {
      setError(
        err instanceof ApiClientError ? err.message : "Invalid code."
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleMfaVerify(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.auth.mfaVerify(totpCode);
      setMfaDone();
    } catch (err) {
      setError(
        err instanceof ApiClientError ? err.message : "Invalid code."
      );
    } finally {
      setLoading(false);
    }
  }

  if (recoveryCodes.length > 0) {
    return (
      <LoginShell>
        <div className="space-y-4">
          <div className="text-center">
            <KeyRound
              size={40}
              className="mx-auto mb-3"
              style={{ color: "var(--color-success)" }}
            />
            <h2 className="text-lg font-bold">Recovery Codes</h2>
            <p
              className="text-sm mt-1"
              style={{ color: "var(--color-text-secondary)" }}
            >
              Save these codes securely. Each can be used once if you lose your
              authenticator.
            </p>
          </div>
          <div
            className="grid grid-cols-2 gap-2 p-4 rounded-lg font-mono text-sm"
            style={{ backgroundColor: "var(--color-bg-secondary)" }}
          >
            {recoveryCodes.map((code) => (
              <div key={code}>{code}</div>
            ))}
          </div>
          <button
            onClick={() => setRecoveryCodes([])}
            className="w-full py-2.5 rounded-lg font-medium text-sm transition-colors"
            style={{
              backgroundColor: "var(--color-accent)",
              color: "var(--color-text-inverse)",
            }}
          >
            I've saved these — continue
          </button>
        </div>
      </LoginShell>
    );
  }

  if (step === "mfa-enrol") {
    return (
      <LoginShell>
        <form onSubmit={handleMfaEnrolConfirm} className="space-y-4">
          <div className="text-center">
            <Shield
              size={40}
              className="mx-auto mb-3"
              style={{ color: "var(--color-accent)" }}
            />
            <h2 className="text-lg font-bold">Set Up Two-Factor Auth</h2>
            <p
              className="text-sm mt-1"
              style={{ color: "var(--color-text-secondary)" }}
            >
              Scan this secret in your authenticator app, then enter the code.
            </p>
          </div>
          <div
            className="p-3 rounded-lg text-center font-mono text-sm break-all select-all"
            style={{ backgroundColor: "var(--color-bg-secondary)" }}
          >
            {totpSecret}
          </div>
          {error && <ErrorMsg msg={error} />}
          <Input
            label="6-digit code"
            value={totpCode}
            onChange={setTotpCode}
            placeholder="000000"
            maxLength={6}
            autoFocus
          />
          <SubmitButton loading={loading} label="Confirm" />
        </form>
      </LoginShell>
    );
  }

  if (step === "mfa-verify") {
    return (
      <LoginShell>
        <form onSubmit={handleMfaVerify} className="space-y-4">
          <div className="text-center">
            <Shield
              size={40}
              className="mx-auto mb-3"
              style={{ color: "var(--color-accent)" }}
            />
            <h2 className="text-lg font-bold">Two-Factor Verification</h2>
            <p
              className="text-sm mt-1"
              style={{ color: "var(--color-text-secondary)" }}
            >
              Enter the code from your authenticator app.
            </p>
          </div>
          {error && <ErrorMsg msg={error} />}
          <Input
            label="6-digit code"
            value={totpCode}
            onChange={setTotpCode}
            placeholder="000000"
            maxLength={6}
            autoFocus
          />
          <SubmitButton loading={loading} label="Verify" />
        </form>
      </LoginShell>
    );
  }

  return (
    <LoginShell>
      <form onSubmit={handleLogin} className="space-y-4">
        <div className="text-center mb-6">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center text-xl font-bold mx-auto mb-4"
            style={{
              backgroundColor: "var(--color-accent)",
              color: "var(--color-text-inverse)",
            }}
          >
            H
          </div>
          <h1 className="text-xl font-bold">HCP Speaker Program</h1>
          <p
            className="text-sm mt-1"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Sign in to your account
          </p>
        </div>
        {error && <ErrorMsg msg={error} />}
        <Input
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          placeholder="admin@example.com"
          autoFocus
        />
        <Input
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          placeholder="Password"
        />
        <SubmitButton loading={loading} label="Sign In" />
      </form>
    </LoginShell>
  );
}

function LoginShell({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ backgroundColor: "var(--color-bg-secondary)" }}
    >
      <div
        className="w-full max-w-sm rounded-2xl border p-8 shadow-lg"
        style={{
          backgroundColor: "var(--color-bg-card)",
          borderColor: "var(--color-border-default)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

function Input({
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  autoFocus,
  maxLength,
}: {
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  maxLength?: number;
}) {
  return (
    <div>
      <label
        className="block text-sm font-medium mb-1.5"
        style={{ color: "var(--color-text-secondary)" }}
      >
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        maxLength={maxLength}
        className="w-full px-3 py-2.5 rounded-lg border text-sm outline-none transition-colors"
        style={{
          backgroundColor: "var(--color-bg-input)",
          borderColor: "var(--color-border-default)",
          color: "var(--color-text-primary)",
        }}
        onFocus={(e) =>
          (e.target.style.borderColor = "var(--color-border-focus)")
        }
        onBlur={(e) =>
          (e.target.style.borderColor = "var(--color-border-default)")
        }
      />
    </div>
  );
}

function SubmitButton({
  loading,
  label,
}: {
  loading: boolean;
  label: string;
}) {
  return (
    <button
      type="submit"
      disabled={loading}
      className="w-full py-2.5 rounded-lg font-medium text-sm transition-colors flex items-center justify-center gap-2 disabled:opacity-60"
      style={{
        backgroundColor: "var(--color-accent)",
        color: "var(--color-text-inverse)",
      }}
    >
      {loading && <Loader2 size={16} className="animate-spin" />}
      {label}
    </button>
  );
}

function ErrorMsg({ msg }: { msg: string }) {
  return (
    <div
      className="px-3 py-2 rounded-lg text-sm"
      style={{
        backgroundColor: "hsla(0, 84%, 60%, 0.1)",
        color: "var(--color-danger)",
      }}
    >
      {msg}
    </div>
  );
}
