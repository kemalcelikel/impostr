import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";
import ProjectWorkspace, {
  type ProjectSummary,
  type ProjectView,
  type ProjectWorkspaceNavigation,
  type WorkspaceMemory,
} from "./ProjectWorkspace";
import { Badge, Button, Disclosure, Feedback, Field, Input, Select } from "./ui/controls";
import { Icon } from "./ui/Icon";
import { ThemeToggle } from "./ui/ThemeToggle";
import { Brand } from "./ui/Brand";

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
type Destination = "projects" | "workspace" | "accounts" | "security";

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
    <Field id={id} label={label}>
      <Input
        autoComplete={autoComplete}
        id={id}
        maxLength={maxLength}
        name={id}
        onChange={(event) => onChange(event.target.value)}
        required={required}
        value={value}
      />
    </Field>
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
    <Field id={id} label={label}>
      <div className="flex min-w-0 gap-2">
        <Input
          autoComplete={autoComplete}
          className="flex-1"
          id={id}
          maxLength={maxLength}
          minLength={minLength}
          name={id}
          onChange={(event) => onChange(event.target.value)}
          required
          type={visible ? "text" : "password"}
          value={value}
        />
        <Button
          aria-controls={id}
          className="workbench-quiet password-visibility"
          variant="ghost"
          aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          aria-pressed={visible}
          icon={visible ? "eyeOff" : "eye"}
          onClick={() => setVisible((current) => !current)}
          title={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`}
          type="button"
        >
          {visible ? "Hide" : "Show"}
        </Button>
      </div>
    </Field>
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
    <Disclosure
      className="account-reset"
      icon="key"
      title={`Reset password for ${account.username}`}
    >
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
        <Button
          className="workbench-save sm:w-fit"
          variant="primary"
          disabled={busy}
          icon="key"
          type="submit"
        >
          {busy ? "Saving…" : `Set temporary password for ${account.username}`}
        </Button>
        {feedback ? (
          <Feedback
            aria-live={feedback.ok ? "polite" : "assertive"}
            tone={feedback.ok ? "success" : "danger"}
            role={feedback.ok ? "status" : "alert"}
          >
            {feedback.message}
          </Feedback>
        ) : null}
      </form>
    </Disclosure>
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
  const [destination, setDestination] = useState<Destination>("projects");
  // Display-only rail/header label; ProjectWorkspace owns navigation state.
  const [projectView, setProjectView] = useState<ProjectView>("planning");
  const workspaceNavigationRef = useRef<ProjectWorkspaceNavigation>(null);
  const [activeProject, setActiveProject] = useState<ProjectSummary | null>(null);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const navigationToggleRef = useRef<HTMLButtonElement>(null);
  const navigationCloseRef = useRef<HTMLButtonElement>(null);
  const navigationWasOpen = useRef(false);
  const accountsNavigationRef = useRef<HTMLButtonElement>(null);
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
  const retainedWorkspace = useRef<{ userId: string; memory: WorkspaceMemory } | null>(null);
  const [workspaceMemory, setWorkspaceMemory] = useState<WorkspaceMemory>({ chats: {} });

  const memoryForUser = useCallback((userId: string): WorkspaceMemory => {
    const memory =
      retainedWorkspace.current?.userId === userId
        ? retainedWorkspace.current.memory
        : { chats: {} };
    retainedWorkspace.current = { userId, memory };
    setWorkspaceMemory(memory);
    setDestination(memory.projectId ? "workspace" : "projects");
    return memory;
  }, []);
  const reportWorkspaceMemory = useCallback(
    (snapshot: WorkspaceMemory) => {
      const retained = retainedWorkspace.current;
      if (
        retained &&
        retained.userId === user?.id &&
        sessionGenerationRef.current === sessionGeneration
      ) {
        retainedWorkspace.current = { userId: retained.userId, memory: snapshot };
      }
    },
    [user?.id, sessionGeneration],
  );

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
    setDestination("projects");
    setProjectView("planning");
    setActiveProject(null);
    setNavigationOpen(false);
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

  const reportProjectContext = useCallback(
    (project: ProjectSummary | null): void => {
      if (sessionGenerationRef.current !== sessionGeneration) return;
      setActiveProject(project);
    },
    [sessionGeneration],
  );

  const reportProjectView = useCallback(
    (next: ProjectView): void => {
      if (sessionGenerationRef.current === sessionGeneration) setProjectView(next);
    },
    [sessionGeneration],
  );

  function navigate(next: Destination): void {
    setDestination(next);
    setNavigationOpen(false);
  }

  function navigateProject(next: ProjectView): void {
    if (!activeProject || !workspaceNavigationRef.current) return;
    workspaceNavigationRef.current.navigate(next);
    navigate("workspace");
  }

  useEffect(() => {
    if (navigationOpen) {
      navigationWasOpen.current = true;
      navigationCloseRef.current?.focus();
    } else if (navigationWasOpen.current) {
      navigationWasOpen.current = false;
      const mobileBar = navigationToggleRef.current?.closest(".app-mobile-bar");
      if (mobileBar && window.getComputedStyle(mobileBar).display === "none") {
        document.querySelector<HTMLButtonElement>('.app-navigation [aria-current="page"]')?.focus();
      } else {
        navigationToggleRef.current?.focus();
      }
    }
  }, [navigationOpen]);

  useEffect(() => {
    const wideScreen = window.matchMedia?.("(min-width: 701px)");
    if (!wideScreen) return;
    const closeOnWideScreen = () => {
      if (wideScreen.matches) setNavigationOpen(false);
    };
    wideScreen.addEventListener("change", closeOnWideScreen);
    return () => wideScreen.removeEventListener("change", closeOnWideScreen);
  }, []);

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
        memoryForUser(payload.user.id);
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
  }, [
    advanceSessionGeneration,
    clearSensitiveFormValues,
    clearWorkspaceState,
    memoryForUser,
    sessionCheckNumber,
  ]);

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
    if (trigger?.isConnected && trigger.closest("[hidden]") === null) {
      trigger.focus();
    } else {
      const rail = accountsNavigationRef.current?.closest(".app-rail");
      if (rail && window.getComputedStyle(rail).display === "none") {
        navigationToggleRef.current?.focus();
      } else {
        accountsNavigationRef.current?.focus();
      }
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
      memoryForUser(response.user.id);
      setCsrfToken(response.csrf_token);
      setLoginPassword("");
      setPageState("authenticated");
      // Routine identity lives in the rail, not a banner over the working area.
      setNotice("");
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
      retainedWorkspace.current = null;
      setWorkspaceMemory({ chats: {} });
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
      if (accountsHeadingRef.current?.closest("[hidden]") === null) {
        accountsHeadingRef.current.focus();
      }
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

  const currentContext =
    destination === "workspace"
      ? projectView === "review"
        ? "Review & downloads"
        : projectView === "canvas"
          ? "Sample canvas"
          : "Planning"
      : destination === "accounts"
        ? "Accounts"
        : destination === "security"
          ? "Account security"
          : "Projects";

  return (
    <div className={user ? "app-frame" : "public-frame"}>
      {user ? (
        <>
          <a className="app-skip-link" href="#app-page-title">
            Skip to current work
          </a>
          <div className="app-mobile-bar" inert={navigationOpen}>
            <Brand />
            <Button
              aria-controls="app-navigation-rail"
              aria-expanded={navigationOpen}
              className="app-quiet-button"
              icon="chevronDown"
              onClick={() => setNavigationOpen(true)}
              ref={navigationToggleRef}
              variant="ghost"
            >
              Navigation
            </Button>
          </div>
          <button
            aria-label="Close navigation"
            className="app-nav-scrim"
            data-open={navigationOpen}
            onClick={() => setNavigationOpen(false)}
            tabIndex={-1}
            type="button"
          />
          <aside
            aria-label="Application navigation"
            className="app-rail"
            data-open={navigationOpen}
            id="app-navigation-rail"
            onKeyDown={(event) => {
              if (!navigationOpen) return;
              if (event.key === "Escape") {
                event.preventDefault();
                setNavigationOpen(false);
              } else if (event.key === "Tab") {
                const controls = Array.from(
                  event.currentTarget.querySelectorAll<HTMLElement>(
                    "a[href], button:not(:disabled)",
                  ),
                );
                const first = controls[0];
                const last = controls.at(-1);
                if (event.shiftKey && document.activeElement === first) {
                  event.preventDefault();
                  last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <div className="app-brand-row">
              <a
                aria-label="Impostr home"
                className="app-brand-link"
                href="/"
                onClick={(event) => {
                  event.preventDefault();
                  navigate("projects");
                }}
              >
                <Brand />
              </a>
              <Button
                aria-label="Close navigation"
                className="app-nav-close app-quiet-button"
                icon="close"
                onClick={() => setNavigationOpen(false)}
                ref={navigationCloseRef}
                variant="ghost"
              />
            </div>
            <nav aria-label="Application" className="app-navigation">
              <div className="app-rail-scroll">
                <Button
                  aria-controls="app-project-surface"
                  aria-current={destination === "projects" ? "page" : undefined}
                  className="app-nav-row"
                  icon="folder"
                  onClick={() => navigate("projects")}
                  variant="ghost"
                >
                  Projects
                </Button>
                {activeProject ? (
                  <>
                    <p className="app-nav-label">Current project</p>
                    <div className="app-project-name" title={activeProject.name}>
                      <Icon name="document" />
                      <span>{activeProject.name}</span>
                    </div>
                    <div aria-label={activeProject.name} className="app-project-nav" role="group">
                      <Button
                        aria-controls="app-project-surface"
                        aria-current={
                          destination === "workspace" && projectView === "planning"
                            ? "page"
                            : undefined
                        }
                        className="app-nav-row"
                        onClick={() => navigateProject("planning")}
                        variant="ghost"
                      >
                        Planning
                      </Button>
                      <Button
                        aria-controls="app-project-surface"
                        aria-current={
                          destination === "workspace" && projectView === "review"
                            ? "page"
                            : undefined
                        }
                        className="app-nav-row"
                        onClick={() => navigateProject("review")}
                        variant="ghost"
                      >
                        Review &amp; downloads
                      </Button>
                    </div>
                    <p className="app-nav-label">Tools</p>
                    <Button
                      aria-controls="app-project-surface"
                      aria-current={
                        destination === "workspace" && projectView === "canvas" ? "page" : undefined
                      }
                      className="app-nav-row"
                      icon="canvas"
                      onClick={() => navigateProject("canvas")}
                      variant="ghost"
                    >
                      Sample canvas <span className="app-demo-label">Demo</span>
                    </Button>
                  </>
                ) : (
                  <p className="app-project-hint">Open a project to start planning.</p>
                )}
              </div>
              <div className="app-rail-bottom">
                {user.role === "admin" ? (
                  <Button
                    aria-controls="app-accounts"
                    aria-current={destination === "accounts" ? "page" : undefined}
                    className="app-nav-row"
                    icon="user"
                    onClick={() => navigate("accounts")}
                    ref={accountsNavigationRef}
                    variant="ghost"
                  >
                    Accounts
                  </Button>
                ) : null}
                <Button
                  aria-controls="app-security"
                  aria-current={destination === "security" ? "page" : undefined}
                  className="app-nav-row"
                  icon="shield"
                  onClick={() => navigate("security")}
                  variant="ghost"
                >
                  Account security
                </Button>
                <div className="app-identity">
                  <span aria-hidden="true" className="app-avatar">
                    {user.username.slice(0, 2).toUpperCase()}
                  </span>
                  <div>
                    <p className="app-identity-name">{user.username}</p>
                    <p className="app-identity-role">
                      {user.role === "admin" ? "Administrator" : "Member"}
                    </p>
                  </div>
                </div>
                <Button
                  className="app-nav-row app-signout"
                  disabled={busyAction === "logout"}
                  icon="logOut"
                  onClick={() => {
                    setNavigationOpen(false);
                    void logout();
                  }}
                  variant="ghost"
                >
                  {busyAction === "logout" ? "Signing out…" : "Sign out"}
                </Button>
              </div>
            </nav>
          </aside>
        </>
      ) : (
        <header className="login-header">
          <a aria-label="Impostr home" className="app-brand-link" href="/">
            <Brand />
          </a>
          <ThemeToggle />
        </header>
      )}

      <main className={user ? "app-main" : "public-main"}>
        {user ? (
          <header className="app-context-header" inert={navigationOpen}>
            <nav aria-label="Current context" className="app-breadcrumb">
              {destination === "workspace" && activeProject ? (
                <>
                  <button
                    className="app-context-projects"
                    onClick={() => navigate("projects")}
                    type="button"
                  >
                    Projects
                  </button>
                  <span aria-hidden="true">/</span>
                  <span className="app-context-name" title={activeProject.name}>
                    {activeProject.name}
                  </span>
                </>
              ) : (
                <span className="app-context-name">{currentContext}</span>
              )}
            </nav>
            <div className="app-header-tools">
              <ThemeToggle />
            </div>
          </header>
        ) : null}
        {pageState === "loading" ? (
          <section aria-live="polite" className="ui-panel mx-auto max-w-lg p-7">
            <h1 className="text-xl font-semibold">Connecting to your workspace</h1>
            <p className="mt-3 text-sm leading-6 text-copy-muted">Checking your secure session…</p>
          </section>
        ) : null}

        {pageState === "unavailable" ? (
          <section
            aria-labelledby="unavailable-title"
            className="ui-panel mx-auto max-w-lg p-6 sm:p-8"
          >
            <p className="text-sm text-copy-muted">Workspace connection</p>
            <h1 className="mt-3 text-2xl font-semibold" id="unavailable-title">
              Sign-in is temporarily unavailable
            </h1>
            <p className="mt-3 leading-6 text-copy-muted">
              Impostr could not check the account service. Try again in a moment.
            </p>
            <Feedback aria-live="polite" className="mt-4" role="alert" tone="danger">
              {error}
            </Feedback>
            <Button
              className="mt-6"
              icon="refresh"
              onClick={() => setSessionCheckNumber((number) => number + 1)}
              type="button"
              variant="primary"
            >
              Try again
            </Button>
          </section>
        ) : null}

        {pageState === "anonymous" ? (
          <section className="login-surface">
            <form
              aria-labelledby="sign-in-title"
              className="workbench-panel login-form"
              onSubmit={(event) => void submitLogin(event)}
            >
              <header className="login-heading">
                <h1 className="app-page-title" id="sign-in-title">
                  Sign in
                </h1>
                <p className="text-xs text-copy-muted">Private planning workspace</p>
              </header>
              <p className="login-intro">Open your projects and planning documents.</p>
              {notice ? (
                <Feedback aria-live="polite" className="mt-4" role="status" tone="success">
                  {notice}
                </Feedback>
              ) : null}
              <div className="mt-5 grid gap-4">
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
                  <Feedback aria-live="assertive" role="alert" tone="danger">
                    {error}
                  </Feedback>
                ) : null}
                <Button
                  className="workbench-save w-full"
                  disabled={busyAction === "login" || !csrfToken}
                  icon="logIn"
                  type="submit"
                  variant="primary"
                >
                  {busyAction === "login" ? "Signing in…" : "Sign in"}
                </Button>
              </div>
              <p className="login-access-note">
                Access is provided by an administrator. There is no public sign-up.
              </p>
            </form>
          </section>
        ) : null}

        {pageState === "authenticated" && user ? (
          <>
            <div className="app-content" inert={navigationOpen}>
              {destination !== "workspace" || projectView === "canvas" ? (
                <h1 className="app-page-title" id="app-page-title" tabIndex={-1}>
                  {currentContext}
                </h1>
              ) : null}
              {error ? (
                <Feedback aria-live="assertive" role="alert" tone="danger">
                  {error}
                </Feedback>
              ) : null}
              {notice ? (
                <Feedback aria-live="polite" role="status" tone="success">
                  {notice}
                </Feedback>
              ) : null}
              {workspaceError ? (
                <Feedback aria-live="assertive" role="alert" tone="danger">
                  <div className="flex flex-wrap items-center justify-between gap-4">
                    <p>
                      Workspace data could not be loaded: {workspaceError} Retry before treating
                      this as an empty workspace.
                    </p>
                    <Button
                      disabled={workspaceLoading}
                      icon="refresh"
                      onClick={() => setWorkspaceRefreshNumber((number) => number + 1)}
                      type="button"
                    >
                      {workspaceLoading ? "Retrying…" : "Retry workspace load"}
                    </Button>
                  </div>
                </Feedback>
              ) : null}

              {/* One state owner per revalidated session; destination changes only hide surfaces. */}
              <div
                hidden={destination !== "projects" && destination !== "workspace"}
                id="app-project-surface"
              >
                <p className="mb-3 text-sm text-copy-muted" hidden={destination !== "projects"}>
                  {user.role === "admin"
                    ? "Administrator view: project metadata from every account is available, and access is recorded."
                    : "You can access projects created by your account."}
                </p>
                <ProjectWorkspace
                  key={sessionGeneration}
                  memory={workspaceMemory}
                  onMemoryChange={reportWorkspaceMemory}
                  csrfToken={csrfToken}
                  loadError={workspaceError}
                  loading={workspaceLoading}
                  onProjectCreated={addCreatedProject}
                  onSessionExpired={handleWorkspaceSessionExpired}
                  onPendingChange={reportWorkspacePending}
                  onProjectPageChange={setProjectOffset}
                  view={destination === "projects" ? "projects" : "workspace"}
                  onOpenWorkspace={() => setDestination("workspace")}
                  onShowProjects={() => navigate("projects")}
                  onProjectContextChange={reportProjectContext}
                  navigationRef={workspaceNavigationRef}
                  onProjectViewChange={reportProjectView}
                  pageTitleId={
                    destination === "workspace" && projectView !== "canvas"
                      ? "app-page-title"
                      : undefined
                  }
                  projectOffset={projectOffset}
                  projects={projects}
                />
              </div>

              {user.role === "admin" ? (
                <section
                  aria-labelledby="accounts-title"
                  className="account-management"
                  hidden={destination !== "accounts"}
                  id="app-accounts"
                >
                  <div className="account-management-layout">
                    <div className="account-surface">
                      <header className="workbench-section-heading">
                        <h2 id="accounts-title">Create an account</h2>
                        <span className="text-xs text-copy-muted">Administrator access</span>
                      </header>
                      <div className="workbench-panel account-panel">
                        <p className="account-intro">
                          Set an initial password and share it securely. No self-registration is
                          available.
                        </p>
                        <form
                          className="account-form"
                          onSubmit={(event) => void createAccount(event)}
                        >
                          <TextField
                            autoComplete="off"
                            id="new-username"
                            label="Username"
                            maxLength={127}
                            onChange={setCreateUsername}
                            value={createUsername}
                          />
                          <Field id="new-role" label="Role">
                            <Select
                              id="new-role"
                              onChange={(event) => setCreateRole(event.target.value as Role)}
                              value={createRole}
                            >
                              <option value="user">Member</option>
                              <option value="admin">Administrator</option>
                            </Select>
                          </Field>
                          <PasswordField
                            autoComplete="new-password"
                            id="new-password"
                            label="Initial password"
                            minLength={12}
                            onChange={setCreatePassword}
                            value={createPassword}
                          />
                          <p className="text-xs leading-5 text-copy-muted">
                            Use at least 12 characters. The password is never shown again after
                            creation.
                          </p>
                          <Button
                            className="workbench-save"
                            disabled={busyAction === "create-account"}
                            icon="userPlus"
                            type="submit"
                            variant="primary"
                          >
                            {busyAction === "create-account" ? "Creating…" : "Create account"}
                          </Button>
                        </form>
                      </div>
                    </div>

                    <div className="account-surface">
                      <header className="workbench-section-heading">
                        <h2
                          className="focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                          ref={accountsHeadingRef}
                          tabIndex={-1}
                        >
                          Manage accounts
                        </h2>
                        <span className="text-xs text-copy-muted">
                          {accounts.length ? `${accounts.length} shown` : "No accounts"}
                        </span>
                      </header>
                      <div className="workbench-panel account-panel">
                        {workspaceLoading ? (
                          <p
                            aria-live="polite"
                            className="py-6 text-sm text-copy-muted"
                            role="status"
                          >
                            Loading accounts…
                          </p>
                        ) : workspaceError ? (
                          <p className="py-6 text-sm leading-6 text-copy-muted">
                            Account records are unavailable until workspace loading succeeds.
                          </p>
                        ) : accounts.length === 0 ? (
                          <p className="py-6 text-sm text-copy-muted">No accounts are available.</p>
                        ) : (
                          <ul className="account-list">
                            {accounts.map((account) => (
                              <li className="account-row" key={account.id}>
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
                                      <Badge icon="check" tone="success">
                                        Active
                                      </Badge>
                                    ) : (
                                      <Badge icon="lock">Deactivated</Badge>
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
                                        Open Account security to change your password.
                                      </p>
                                    )}
                                    {account.is_active && account.id !== user.id ? (
                                      <Button
                                        aria-label={`Deactivate ${account.username}`}
                                        className="account-danger-tool sm:w-fit"
                                        disabled={busyAction === `deactivate-${account.id}`}
                                        icon="lock"
                                        onClick={(event) => {
                                          deactivationTriggerRef.current = event.currentTarget;
                                          setDeactivationTarget(account);
                                        }}
                                        type="button"
                                        variant="danger"
                                      >
                                        {busyAction === `deactivate-${account.id}`
                                          ? "Deactivating…"
                                          : `Deactivate ${account.username}`}
                                      </Button>
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
                            <Button
                              className="workbench-quiet"
                              variant="ghost"
                              disabled={userOffset === 0 || workspaceLoading}
                              icon="chevronLeft"
                              onClick={() => setUserOffset((offset) => Math.max(0, offset - 100))}
                              type="button"
                            >
                              Previous accounts
                            </Button>
                            <Button
                              className="workbench-quiet"
                              variant="ghost"
                              disabled={accounts.length < 100 || workspaceLoading}
                              icon="chevronRight"
                              onClick={() => setUserOffset((offset) => offset + 100)}
                              type="button"
                            >
                              Next accounts
                            </Button>
                          </nav>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </section>
              ) : null}

              <section
                aria-labelledby="security-title"
                className="account-security"
                hidden={destination !== "security"}
                id="app-security"
              >
                <header className="workbench-section-heading">
                  <h2 id="security-title">Change your password</h2>
                </header>
                <div className="workbench-panel account-panel">
                  <p className="account-intro">
                    Changing your password signs out every other active session.
                  </p>
                  <form
                    className="account-form"
                    onSubmit={(event) => void changeOwnPassword(event)}
                  >
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
                    <Button
                      className="workbench-save sm:w-fit"
                      variant="primary"
                      disabled={busyAction === "change-password"}
                      icon="key"
                      type="submit"
                    >
                      {busyAction === "change-password" ? "Updating…" : "Update password"}
                    </Button>
                  </form>
                </div>
              </section>
            </div>
          </>
        ) : null}
      </main>

      <dialog
        aria-describedby="deactivation-description"
        aria-labelledby="deactivation-title"
        aria-modal="true"
        className="ui-panel m-auto w-[calc(100%-2rem)] max-w-lg p-6 text-foreground backdrop:bg-black/70"
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
          <Button
            onClick={() => setDeactivationTarget(null)}
            ref={deactivationCancelRef}
            type="button"
          >
            Cancel
          </Button>
          <Button
            aria-label={`Confirm deactivation of ${deactivationTarget?.username ?? "account"}`}
            disabled={deactivationTarget === null}
            icon="lock"
            onClick={() => {
              if (deactivationTarget === null) return;
              const account = deactivationTarget;
              setDeactivationTarget(null);
              void deactivateAccount(account);
            }}
            type="button"
            variant="danger"
          >
            Deactivate {deactivationTarget?.username ?? "account"}
          </Button>
        </div>
      </dialog>

      <footer
        hidden={Boolean(user)}
        className="mx-auto mt-8 w-full max-w-6xl px-5 py-5 text-center text-xs text-copy-muted sm:px-8"
      >
        <span>Administrator-managed access</span>
      </footer>
    </div>
  );
}
