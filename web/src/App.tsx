import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";
import ProjectWorkspace, { type ProjectSummary } from "./ProjectWorkspace";

type Role = "admin" | "user";

type User = {
  id: string;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
};

type CsrfResponse = { csrf_token: string };
type SessionResponse = { user: User; csrf_token?: string };
type PageState = "loading" | "anonymous" | "authenticated" | "unavailable";
type ResetPasswordResult = { ok: boolean; message: string };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function TextField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  maxLength,
  required = true,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  maxLength?: number;
  required?: boolean;
}) {
  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-foreground" htmlFor={id}>
        {label}
      </label>
      <input
        autoComplete={autoComplete}
        className="min-h-11 w-full rounded-lg border border-input-border bg-canvas px-3 py-2 text-sm text-foreground outline-none placeholder:text-copy-muted/70 focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        id={id}
        maxLength={maxLength}
        name={id}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
      />
    </div>
  );
}

function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  minLength,
  maxLength = 256,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: string;
  minLength?: number;
  maxLength?: number;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="grid gap-2">
      <label className="text-sm font-medium text-foreground" htmlFor={id}>
        {label}
      </label>
      <div className="flex min-w-0 gap-2">
        <input
          autoComplete={autoComplete}
          className="min-h-11 min-w-0 flex-1 rounded-lg border border-input-border bg-canvas px-3 py-2 text-sm text-foreground outline-none placeholder:text-copy-muted/70 focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          id={id}
          maxLength={maxLength}
          minLength={minLength}
          name={id}
          onChange={(event) => onChange(event.target.value)}
          required
          type={visible ? "text" : "password"}
          value={value}
        />
        <button
          aria-controls={id}
          aria-pressed={visible}
          className="min-h-11 min-w-16 rounded-lg border border-line bg-surface-raised px-3 text-xs font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          onClick={() => setVisible((current) => !current)}
          type="button"
        >
          {visible ? "Hide" : "Show"}
        </button>
      </div>
    </div>
  );
}

function ResetPasswordForm({
  account,
  busy,
  onReset,
}: {
  account: User;
  busy: boolean;
  onReset: (account: User, password: string) => Promise<ResetPasswordResult>;
}) {
  const [password, setPassword] = useState("");
  const [feedback, setFeedback] = useState<ResetPasswordResult | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const result = await onReset(account, password);
    setFeedback(result);
    if (result.ok) {
      setPassword("");
    }
  }

  return (
    <details className="rounded-lg border border-line bg-canvas px-3 py-2">
      <summary className="min-h-8 cursor-pointer py-1 text-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        Reset password for {account.username}
      </summary>
      <form className="mt-3 grid gap-4" onSubmit={(event) => void submit(event)}>
        <p className="text-xs leading-5 text-copy-muted">
          This immediately changes {account.username}&apos;s password and revokes their active
          sessions. Share the temporary password through an approved secure channel.
        </p>
        <PasswordField
          autoComplete="new-password"
          id={`reset-password-${account.id}`}
          label={`Temporary password for ${account.username}`}
          minLength={12}
          onChange={(value) => {
            setPassword(value);
            setFeedback(null);
          }}
          value={password}
        />
        <button
          className="min-h-11 w-full rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 sm:w-fit"
          disabled={busy}
          type="submit"
        >
          {busy ? "Saving…" : `Set temporary password for ${account.username}`}
        </button>
        {feedback ? (
          <p
            aria-live={feedback.ok ? "polite" : "assertive"}
            className={`text-sm ${feedback.ok ? "text-accent" : "text-red-300"}`}
            role={feedback.ok ? "status" : "alert"}
          >
            {feedback.message}
          </p>
        ) : null}
      </form>
    </details>
  );
}

export default function App() {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [sessionGeneration, setSessionGeneration] = useState(0);
  const [user, setUser] = useState<User | null>(null);
  const [csrfToken, setCsrfToken] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [sessionCheckNumber, setSessionCheckNumber] = useState(0);
  const [workspaceRefreshNumber, setWorkspaceRefreshNumber] = useState(0);
  const [userOffset, setUserOffset] = useState(0);
  const [projectOffset, setProjectOffset] = useState(0);
  const [workspaceHasEdits, setWorkspaceHasEdits] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [accounts, setAccounts] = useState<User[]>([]);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [deactivationTarget, setDeactivationTarget] = useState<User | null>(null);
  const deactivationDialogRef = useRef<HTMLDialogElement>(null);
  const deactivationCancelRef = useRef<HTMLButtonElement>(null);
  const deactivationTriggerRef = useRef<HTMLButtonElement | null>(null);
  const accountsHeadingRef = useRef<HTMLHeadingElement>(null);
  const deactivationDialogWasOpen = useRef(false);
  const sessionGenerationRef = useRef(0);

  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [createUsername, setCreateUsername] = useState("");
  const [createPassword, setCreatePassword] = useState("");
  const [createRole, setCreateRole] = useState<Role>("user");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const clearSensitiveFormValues = useCallback((): void => {
    setLoginPassword("");
    setCreatePassword("");
    setCurrentPassword("");
    setNewPassword("");
  }, []);

  const clearWorkspaceState = useCallback((): void => {
    setProjects([]);
    setAccounts([]);
    setProjectOffset(0);
    setUserOffset(0);
    setWorkspaceHasEdits(false);
    setWorkspaceLoading(false);
    setWorkspaceError("");
  }, []);

  const advanceSessionGeneration = useCallback((): void => {
    const nextGeneration = sessionGenerationRef.current + 1;
    sessionGenerationRef.current = nextGeneration;
    setSessionGeneration(nextGeneration);
  }, []);

  const refreshCsrf = useCallback(async (): Promise<void> => {
    const csrf = await apiRequest<CsrfResponse>("/api/auth/csrf");
    setCsrfToken(csrf.csrf_token);
  }, []);

  const recoverExpiredSession = useCallback((): void => {
    advanceSessionGeneration();
    clearWorkspaceState();
    setUser(null);
    setCsrfToken("");
    setPageState("anonymous");
    setError("Your session has expired. Sign in again.");
    setNotice("");
    clearSensitiveFormValues();
    setDeactivationTarget(null);
    void refreshCsrf().catch((csrfError: unknown) => {
      setPageState("unavailable");
      setError(errorMessage(csrfError));
    });
  }, [advanceSessionGeneration, clearSensitiveFormValues, clearWorkspaceState, refreshCsrf]);

  const handleWorkspaceSessionExpired = useCallback((): void => {
    if (sessionGenerationRef.current !== sessionGeneration) return;
    recoverExpiredSession();
  }, [recoverExpiredSession, sessionGeneration]);

  const addCreatedProject = useCallback(
    (created: ProjectSummary): void => {
      const currentUserId = user?.id;
      if (
        sessionGenerationRef.current !== sessionGeneration ||
        currentUserId === undefined ||
        created.owner_user_id !== currentUserId
      ) {
        return;
      }
      setProjects((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    },
    [sessionGeneration, user?.id],
  );

  const reportWorkspacePending = useCallback(
    (pending: boolean): void => {
      if (sessionGenerationRef.current === sessionGeneration) setWorkspaceHasEdits(pending);
    },
    [sessionGeneration],
  );

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    async function restoreSession(): Promise<void> {
      setPageState("loading");
      try {
        const csrf = await apiRequest<CsrfResponse>("/api/auth/csrf", {
          signal: controller.signal,
        });
        if (!active) return;
        setCsrfToken(csrf.csrf_token);

        const response = await fetch("/api/auth/session", {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (response.status === 401) {
          if (!active) return;
          advanceSessionGeneration();
          clearWorkspaceState();
          clearSensitiveFormValues();
          setUser(null);
          setPageState("anonymous");
          setError("");
          return;
        }
        if (!response.ok) {
          throw new ApiError("Could not restore the sign-in session.", response.status);
        }
        const payload = (await response.json()) as SessionResponse;
        if (!active) return;
        advanceSessionGeneration();
        clearWorkspaceState();
        setUser(payload.user);
        setPageState("authenticated");
        setError("");
      } catch (restoreError) {
        if (!active || controller.signal.aborted) return;
        advanceSessionGeneration();
        clearWorkspaceState();
        clearSensitiveFormValues();
        setUser(null);
        setPageState("unavailable");
        setError(errorMessage(restoreError));
      }
    }

    void restoreSession();
    return () => {
      active = false;
      controller.abort();
    };
  }, [advanceSessionGeneration, clearSensitiveFormValues, clearWorkspaceState, sessionCheckNumber]);

  useEffect(() => {
    if (pageState !== "authenticated" || user === null) return;
    const currentUser = user;
    const currentSessionGeneration = sessionGeneration;
    const controller = new AbortController();
    let active = true;

    async function loadWorkspace(): Promise<void> {
      setWorkspaceLoading(true);
      setWorkspaceError("");
      try {
        const projectPromise = apiRequest<ProjectSummary[]>(
          projectOffset === 0 ? "/api/projects" : `/api/projects?limit=100&offset=${projectOffset}`,
          {
            signal: controller.signal,
          },
        );
        const accountPromise =
          currentUser.role === "admin"
            ? apiRequest<User[]>(`/api/admin/users?limit=100&offset=${userOffset}`, {
                signal: controller.signal,
              })
            : Promise.resolve([]);
        const [nextProjects, nextAccounts] = await Promise.all([projectPromise, accountPromise]);
        if (!active || sessionGenerationRef.current !== currentSessionGeneration) return;
        setProjects(nextProjects);
        setAccounts(nextAccounts);
      } catch (loadError) {
        if (
          !active ||
          controller.signal.aborted ||
          sessionGenerationRef.current !== currentSessionGeneration
        ) {
          return;
        }
        if (loadError instanceof ApiError && loadError.status === 401) {
          recoverExpiredSession();
        } else {
          setWorkspaceError(errorMessage(loadError));
        }
      } finally {
        if (active && sessionGenerationRef.current === currentSessionGeneration) {
          setWorkspaceLoading(false);
        }
      }
    }

    void loadWorkspace();
    return () => {
      active = false;
      controller.abort();
    };
  }, [
    pageState,
    projectOffset,
    recoverExpiredSession,
    sessionGeneration,
    user,
    userOffset,
    workspaceRefreshNumber,
  ]);

  useEffect(() => {
    const dialog = deactivationDialogRef.current;
    if (deactivationTarget !== null) {
      if (!dialog) return;
      if (!dialog.open) {
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        } else {
          dialog.setAttribute("open", "");
        }
      }
      deactivationDialogWasOpen.current = true;
      deactivationCancelRef.current?.focus();
      return;
    }

    if (!dialog || !deactivationDialogWasOpen.current) return;
    if (dialog.open) {
      if (typeof dialog.close === "function") {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    }
    deactivationDialogWasOpen.current = false;
    const trigger = deactivationTriggerRef.current;
    if (trigger?.isConnected) {
      trigger.focus();
    } else {
      accountsHeadingRef.current?.focus();
    }
    deactivationTriggerRef.current = null;
  }, [deactivationTarget]);

  function presentActionError(actionError: unknown): void {
    if (actionError instanceof ApiError && actionError.status === 401) {
      recoverExpiredSession();
      return;
    }
    setError(errorMessage(actionError));
  }

  async function submitLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusyAction("login");
    setError("");
    setNotice("");
    try {
      const response = await apiRequest<SessionResponse>("/api/auth/login", {
        method: "POST",
        csrfToken,
        body: { username: loginUsername, password: loginPassword },
      });
      if (!response.csrf_token) {
        throw new ApiError("The sign-in response was incomplete.", 500);
      }
      advanceSessionGeneration();
      clearWorkspaceState();
      setUser(response.user);
      setCsrfToken(response.csrf_token);
      setLoginPassword("");
      setPageState("authenticated");
      setNotice(`Signed in as ${response.user.username}.`);
    } catch (loginError) {
      setError(errorMessage(loginError));
    } finally {
      setBusyAction("");
    }
  }

  async function logout(): Promise<void> {
    if (
      workspaceHasEdits &&
      !window.confirm("Unsaved draft or task edits will be lost. Sign out anyway?")
    ) {
      return;
    }
    setBusyAction("logout");
    setError("");
    setNotice("");
    try {
      await apiRequest<void>("/api/auth/logout", {
        method: "POST",
        csrfToken,
      });
      advanceSessionGeneration();
      clearWorkspaceState();
      setUser(null);
      setCsrfToken("");
      setPageState("anonymous");
      setNotice("You have signed out.");
      clearSensitiveFormValues();
      setDeactivationTarget(null);
      try {
        await refreshCsrf();
      } catch (csrfError) {
        setPageState("unavailable");
        setError(errorMessage(csrfError));
      }
    } catch (logoutError) {
      presentActionError(logoutError);
    } finally {
      setBusyAction("");
    }
  }

  async function createAccount(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusyAction("create-account");
    setError("");
    setNotice("");
    try {
      const created = await apiRequest<User>("/api/admin/users", {
        method: "POST",
        csrfToken,
        body: { username: createUsername, password: createPassword, role: createRole },
      });
      setCreateUsername("");
      setCreatePassword("");
      setCreateRole("user");
      setUserOffset(0);
      setWorkspaceRefreshNumber((number) => number + 1);
      setNotice(`Account ${created.username} was created.`);
    } catch (createError) {
      presentActionError(createError);
    } finally {
      setBusyAction("");
    }
  }

  async function resetAccountPassword(
    account: User,
    password: string,
  ): Promise<ResetPasswordResult> {
    setBusyAction(`reset-${account.id}`);
    setError("");
    setNotice("");
    try {
      await apiRequest<void>(`/api/admin/users/${account.id}/reset-password`, {
        method: "POST",
        csrfToken,
        body: { password },
      });
      return {
        ok: true,
        message: `Temporary password for ${account.username} was changed. Their existing sessions were revoked.`,
      };
    } catch (resetError) {
      presentActionError(resetError);
      return {
        ok: false,
        message: `Password reset for ${account.username} failed: ${errorMessage(resetError)}`,
      };
    } finally {
      setBusyAction("");
    }
  }

  async function deactivateAccount(account: User): Promise<void> {
    setBusyAction(`deactivate-${account.id}`);
    setError("");
    setNotice("");
    try {
      await apiRequest<void>(`/api/admin/users/${account.id}/deactivate`, {
        method: "POST",
        csrfToken,
      });
      setWorkspaceRefreshNumber((number) => number + 1);
      setNotice(`Account ${account.username} was deactivated and its sessions were revoked.`);
      accountsHeadingRef.current?.focus();
    } catch (deactivateError) {
      presentActionError(deactivateError);
    } finally {
      setBusyAction("");
    }
  }

  async function changeOwnPassword(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusyAction("change-password");
    setError("");
    setNotice("");
    try {
      const response = await apiRequest<SessionResponse>("/api/auth/password", {
        method: "POST",
        csrfToken,
        body: { current_password: currentPassword, new_password: newPassword },
      });
      if (!response.csrf_token) {
        throw new ApiError("The password-change response was incomplete.", 500);
      }
      setUser(response.user);
      setCsrfToken(response.csrf_token);
      clearSensitiveFormValues();
      setWorkspaceRefreshNumber((number) => number + 1);
      setNotice("Password updated. Other sessions were signed out.");
    } catch (passwordError) {
      presentActionError(passwordError);
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-canvas text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-48 right-[-12rem] size-[32rem] rounded-full bg-accent/5 blur-3xl"
      />
      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-6 sm:px-8">
        <a
          aria-label="Impostr home"
          className="inline-flex min-h-11 items-center gap-3 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          href="/"
        >
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-xl border border-accent/20 bg-surface-raised text-accent"
          >
            <svg fill="none" height="20" viewBox="0 0 20 20" width="20">
              <path
                d="M4 14.5V5.5h3.25l2.75 4 2.75-4H16v9h-3V9.8l-3 4.1-3-4.1v4.7H4Z"
                fill="currentColor"
              />
            </svg>
          </span>
          <span className="font-semibold tracking-tight text-foreground">Impostr</span>
        </a>
        {user ? (
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-copy-muted sm:inline">
              {user.username} · {user.role === "admin" ? "Administrator" : "Member"}
            </span>
            <button
              className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busyAction === "logout"}
              onClick={() => void logout()}
              type="button"
            >
              {busyAction === "logout" ? "Signing out…" : "Sign out"}
            </button>
          </div>
        ) : null}
      </header>

      <main className="relative z-10 mx-auto w-full max-w-6xl px-5 pb-14 pt-8 sm:px-8 sm:pt-12">
        {pageState === "loading" ? (
          <section
            aria-live="polite"
            className="mx-auto max-w-lg rounded-2xl border border-line bg-surface p-7"
          >
            <h1 className="text-xl font-semibold">Connecting to your workspace</h1>
            <p className="mt-3 text-sm leading-6 text-copy-muted">Checking your secure session…</p>
          </section>
        ) : null}

        {pageState === "unavailable" ? (
          <section
            aria-labelledby="unavailable-title"
            className="mx-auto max-w-lg rounded-2xl border border-line bg-surface p-6 sm:p-8"
          >
            <p className="font-mono text-xs uppercase tracking-[0.16em] text-copy-muted">
              Workspace connection
            </p>
            <h1 className="mt-3 text-2xl font-semibold" id="unavailable-title">
              Sign-in is temporarily unavailable
            </h1>
            <p className="mt-3 leading-6 text-copy-muted">
              Impostr could not check the account service. Try again in a moment.
            </p>
            <p aria-live="polite" className="mt-4 text-sm text-red-300" role="alert">
              {error}
            </p>
            <button
              className="mt-6 min-h-11 rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              onClick={() => setSessionCheckNumber((number) => number + 1)}
              type="button"
            >
              Try again
            </button>
          </section>
        ) : null}

        {pageState === "anonymous" ? (
          <section className="mx-auto grid max-w-5xl items-center gap-10 lg:grid-cols-[1fr_0.8fr] lg:gap-16">
            <div className="max-w-xl">
              <p className="flex items-center gap-3 font-mono text-xs font-medium uppercase tracking-[0.16em] text-accent">
                <span aria-hidden="true" className="h-px w-8 bg-accent/70" />
                Private planning workspace
              </p>
              <h1 className="mt-6 text-balance text-4xl font-semibold leading-tight tracking-[-0.04em] sm:text-5xl">
                Plan clearly.
                <br />
                <span className="text-copy-muted">Build with confidence.</span>
              </h1>
              <p className="mt-5 max-w-lg text-base leading-7 text-copy-muted">
                Sign in to see your private project metadata and planning workspace.
              </p>
              <p className="mt-5 max-w-lg text-sm leading-6 text-copy-muted">
                Access is provided by an administrator. There is no public sign-up.
              </p>
              {notice ? (
                <p aria-live="polite" className="mt-4 text-sm text-accent" role="status">
                  {notice}
                </p>
              ) : null}
            </div>

            <form
              aria-labelledby="sign-in-title"
              className="rounded-2xl border border-line bg-surface/95 p-5 shadow-2xl shadow-black/20 sm:p-7"
              onSubmit={(event) => void submitLogin(event)}
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                Account access
              </p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight" id="sign-in-title">
                Sign in
              </h2>
              <div className="mt-6 grid gap-5">
                <TextField
                  autoComplete="username"
                  id="login-username"
                  label="Username"
                  maxLength={127}
                  onChange={setLoginUsername}
                  value={loginUsername}
                />
                <PasswordField
                  autoComplete="current-password"
                  id="login-password"
                  label="Password"
                  onChange={setLoginPassword}
                  value={loginPassword}
                />
                {error ? (
                  <p aria-live="assertive" className="text-sm leading-5 text-red-300" role="alert">
                    {error}
                  </p>
                ) : null}
                <button
                  className="min-h-11 w-full rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={busyAction === "login" || !csrfToken}
                  type="submit"
                >
                  {busyAction === "login" ? "Signing in…" : "Sign in"}
                </button>
              </div>
              <p className="mt-5 text-xs leading-5 text-copy-muted">
                Password managers and paste are supported. Ask your administrator if you need
                account access.
              </p>
            </form>
          </section>
        ) : null}

        {pageState === "authenticated" && user ? (
          <div className="grid gap-8">
            <section
              aria-labelledby="workspace-title"
              className="flex flex-wrap items-end justify-between gap-5"
            >
              <div>
                <p className="font-mono text-xs uppercase tracking-[0.16em] text-accent">
                  Private workspace
                </p>
                <h1
                  className="mt-3 break-words text-3xl font-semibold tracking-tight sm:text-4xl"
                  id="workspace-title"
                >
                  Welcome, {user.username}
                </h1>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-copy-muted">
                  {user.role === "admin"
                    ? "Administrator view: project metadata from every account is available, and access is recorded."
                    : "You can access project metadata created by your account."}
                </p>
              </div>
              <span className="rounded-full border border-line bg-surface-raised px-3 py-2 font-mono text-xs uppercase tracking-wide text-copy-muted">
                {user.role === "admin" ? "Administrator" : "Member"}
              </span>
            </section>

            {error ? (
              <p
                aria-live="assertive"
                className="rounded-lg border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm text-red-200"
                role="alert"
              >
                {error}
              </p>
            ) : null}
            {notice ? (
              <p
                aria-live="polite"
                className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-foreground"
                role="status"
              >
                {notice}
              </p>
            ) : null}
            {workspaceError ? (
              <div
                aria-live="assertive"
                className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-red-400/40 bg-red-400/10 px-4 py-3 text-sm text-red-200"
                role="alert"
              >
                <p>
                  Workspace data could not be loaded: {workspaceError} Retry before treating this as
                  an empty workspace.
                </p>
                <button
                  className="min-h-11 rounded-lg border border-red-300/50 px-4 py-2 font-medium text-red-100 hover:bg-red-300/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={workspaceLoading}
                  onClick={() => setWorkspaceRefreshNumber((number) => number + 1)}
                  type="button"
                >
                  {workspaceLoading ? "Retrying…" : "Retry workspace load"}
                </button>
              </div>
            ) : null}

            <ProjectWorkspace
              key={sessionGeneration}
              csrfToken={csrfToken}
              loadError={workspaceError}
              loading={workspaceLoading}
              onProjectCreated={addCreatedProject}
              onSessionExpired={handleWorkspaceSessionExpired}
              onPendingChange={reportWorkspacePending}
              onProjectPageChange={setProjectOffset}
              projectOffset={projectOffset}
              projects={projects}
            />

            {user.role === "admin" ? (
              <section
                aria-labelledby="accounts-title"
                className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]"
              >
                <div className="rounded-2xl border border-line bg-surface/95 p-5 sm:p-7">
                  <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                    Operator-managed accounts
                  </p>
                  <h2 className="mt-2 text-xl font-semibold" id="accounts-title">
                    Create an account
                  </h2>
                  <p className="mt-3 text-sm leading-6 text-copy-muted">
                    Set an initial password and share it securely. No self-registration is
                    available.
                  </p>
                  <form className="mt-6 grid gap-5" onSubmit={(event) => void createAccount(event)}>
                    <TextField
                      autoComplete="off"
                      id="new-username"
                      label="Username"
                      maxLength={127}
                      onChange={setCreateUsername}
                      value={createUsername}
                    />
                    <div className="grid gap-2">
                      <label className="text-sm font-medium text-foreground" htmlFor="new-role">
                        Role
                      </label>
                      <select
                        className="min-h-11 rounded-lg border border-input-border bg-canvas px-3 py-2 text-sm text-foreground outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        id="new-role"
                        onChange={(event) => setCreateRole(event.target.value as Role)}
                        value={createRole}
                      >
                        <option value="user">Member</option>
                        <option value="admin">Administrator</option>
                      </select>
                    </div>
                    <PasswordField
                      autoComplete="new-password"
                      id="new-password"
                      label="Initial password"
                      minLength={12}
                      onChange={setCreatePassword}
                      value={createPassword}
                    />
                    <p className="-mt-3 text-xs leading-5 text-copy-muted">
                      Use at least 12 characters. The password is never shown again after creation.
                    </p>
                    <button
                      className="min-h-11 rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={busyAction === "create-account"}
                      type="submit"
                    >
                      {busyAction === "create-account" ? "Creating…" : "Create account"}
                    </button>
                  </form>
                </div>

                <div className="rounded-2xl border border-line bg-surface/95 p-5 sm:p-7">
                  <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line pb-5">
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                        Access controls
                      </p>
                      <h2
                        className="mt-2 text-xl font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        ref={accountsHeadingRef}
                        tabIndex={-1}
                      >
                        Manage accounts
                      </h2>
                    </div>
                    <span className="font-mono text-xs text-copy-muted">
                      {accounts.length ? `${accounts.length} shown` : "No accounts"}
                    </span>
                  </div>
                  {workspaceLoading ? (
                    <p aria-live="polite" className="py-6 text-sm text-copy-muted" role="status">
                      Loading accounts…
                    </p>
                  ) : workspaceError ? (
                    <p className="py-6 text-sm leading-6 text-copy-muted">
                      Account records are unavailable until workspace loading succeeds.
                    </p>
                  ) : accounts.length === 0 ? (
                    <p className="py-6 text-sm text-copy-muted">No accounts are available.</p>
                  ) : (
                    <ul className="grid gap-4 py-5">
                      {accounts.map((account) => (
                        <li
                          className="rounded-xl border border-line bg-canvas p-4"
                          key={account.id}
                        >
                          <article aria-labelledby={`account-${account.id}`}>
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <h3
                                  className="break-words font-medium text-foreground"
                                  id={`account-${account.id}`}
                                >
                                  {account.username}
                                </h3>
                                <p className="mt-1 text-xs text-copy-muted">
                                  {account.role === "admin" ? "Administrator" : "Member"} ·{" "}
                                  {account.is_active ? "Active" : "Deactivated"}
                                </p>
                              </div>
                              {account.is_active ? (
                                <span className="rounded-full border border-accent/35 bg-accent/10 px-3 py-1 font-mono text-[10px] uppercase tracking-wide text-accent">
                                  Active
                                </span>
                              ) : (
                                <span className="rounded-full border border-line bg-surface-raised px-3 py-1 font-mono text-[10px] uppercase tracking-wide text-copy-muted">
                                  Deactivated
                                </span>
                              )}
                            </div>
                            <div className="mt-4 grid gap-3">
                              {account.id !== user.id ? (
                                <ResetPasswordForm
                                  account={account}
                                  busy={busyAction === `reset-${account.id}`}
                                  onReset={resetAccountPassword}
                                />
                              ) : (
                                <p className="text-xs text-copy-muted">
                                  Use Account security below to change your password.
                                </p>
                              )}
                              {account.is_active && account.id !== user.id ? (
                                <button
                                  aria-label={`Deactivate ${account.username}`}
                                  className="min-h-11 w-full rounded-lg border border-red-400/40 bg-red-400/5 px-4 py-2 text-sm font-medium text-red-200 hover:bg-red-400/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 sm:w-fit"
                                  disabled={busyAction === `deactivate-${account.id}`}
                                  onClick={(event) => {
                                    deactivationTriggerRef.current = event.currentTarget;
                                    setDeactivationTarget(account);
                                  }}
                                  type="button"
                                >
                                  {busyAction === `deactivate-${account.id}`
                                    ? "Deactivating…"
                                    : `Deactivate ${account.username}`}
                                </button>
                              ) : null}
                            </div>
                          </article>
                        </li>
                      ))}
                    </ul>
                  )}
                  {accounts.length === 100 || userOffset > 0 ? (
                    <nav
                      aria-label="Account pages"
                      className="flex flex-wrap gap-3 border-t border-line pt-4"
                    >
                      <button
                        className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={userOffset === 0 || workspaceLoading}
                        onClick={() => setUserOffset((offset) => Math.max(0, offset - 100))}
                        type="button"
                      >
                        Previous accounts
                      </button>
                      <button
                        className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={accounts.length < 100 || workspaceLoading}
                        onClick={() => setUserOffset((offset) => offset + 100)}
                        type="button"
                      >
                        Next accounts
                      </button>
                    </nav>
                  ) : null}
                </div>
              </section>
            ) : null}

            <section
              aria-labelledby="security-title"
              className="max-w-2xl rounded-2xl border border-line bg-surface/95 p-5 sm:p-7"
            >
              <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                Account security
              </p>
              <h2 className="mt-2 text-xl font-semibold" id="security-title">
                Change your password
              </h2>
              <p className="mt-3 text-sm leading-6 text-copy-muted">
                Changing your password signs out every other active session.
              </p>
              <form className="mt-6 grid gap-5" onSubmit={(event) => void changeOwnPassword(event)}>
                <PasswordField
                  autoComplete="current-password"
                  id="current-account-password"
                  label="Current password"
                  onChange={setCurrentPassword}
                  value={currentPassword}
                />
                <PasswordField
                  autoComplete="new-password"
                  id="new-account-password"
                  label="New password"
                  minLength={12}
                  onChange={setNewPassword}
                  value={newPassword}
                />
                <button
                  className="min-h-11 rounded-lg border border-line bg-surface-raised px-5 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 sm:w-fit"
                  disabled={busyAction === "change-password"}
                  type="submit"
                >
                  {busyAction === "change-password" ? "Updating…" : "Update password"}
                </button>
              </form>
            </section>
          </div>
        ) : null}
      </main>

      <dialog
        aria-describedby="deactivation-description"
        aria-labelledby="deactivation-title"
        aria-modal="true"
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-line bg-surface p-6 text-foreground shadow-2xl backdrop:bg-black/70"
        onCancel={(event) => {
          event.preventDefault();
          setDeactivationTarget(null);
        }}
        ref={deactivationDialogRef}
        role="alertdialog"
      >
        <h2 className="text-xl font-semibold" id="deactivation-title">
          Deactivate {deactivationTarget?.username ?? "account"}?
        </h2>
        <p className="mt-3 text-sm leading-6 text-copy-muted" id="deactivation-description">
          This blocks future sign-ins and revokes the account&apos;s active sessions. The
          account&apos;s project metadata is not deleted.
        </p>
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button
            className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onClick={() => setDeactivationTarget(null)}
            ref={deactivationCancelRef}
            type="button"
          >
            Cancel
          </button>
          <button
            aria-label={`Confirm deactivation of ${deactivationTarget?.username ?? "account"}`}
            className="min-h-11 rounded-lg border border-red-400/50 bg-red-400/10 px-4 py-2 text-sm font-medium text-red-100 hover:bg-red-400/20 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={deactivationTarget === null}
            onClick={() => {
              if (deactivationTarget === null) return;
              const account = deactivationTarget;
              setDeactivationTarget(null);
              void deactivateAccount(account);
            }}
            type="button"
          >
            Deactivate {deactivationTarget?.username ?? "account"}
          </button>
        </div>
      </dialog>

      <footer className="relative z-10 mx-auto mt-12 flex w-full max-w-6xl flex-col gap-2 border-t border-line px-5 py-5 font-mono text-[10px] uppercase tracking-[0.14em] text-copy-muted sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <span>Private project access</span>
        <span>Cookie session · Operator-provisioned accounts</span>
      </footer>
    </div>
  );
}
