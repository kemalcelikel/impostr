import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

type TestUser = {
  id: string;
  username: string;
  role: "admin" | "user";
  is_active: boolean;
  created_at: string;
};

const admin: TestUser = {
  id: "00000000-0000-4000-8000-000000000001",
  username: "operator",
  role: "admin",
  is_active: true,
  created_at: "2026-09-25T10:00:00Z",
};

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function pathOf(input: RequestInfo | URL): string {
  return String(input);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("account access", () => {
  it.each(["dirty", "saving"])(
    "keeps the %s editor through project-list refresh even when the new page omits it",
    async (state) => {
      const project = {
        id: "00000000-0000-4000-8000-000000000020",
        name: "Open plan",
        owner_user_id: admin.id,
        created_at: admin.created_at,
      };
      const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
        id: kind,
        kind,
        filename: `${kind.toUpperCase()}.md`,
        content: `# Original ${kind}\n`,
        revision_number: 1,
      }));
      let projectLists = 0;
      let finishRefresh!: (response: Response) => void;
      const refreshed = new Promise<Response>((resolve) => {
        finishRefresh = resolve;
      });
      let finishSave!: (response: Response) => void;
      const saved = new Promise<Response>((resolve) => {
        finishSave = resolve;
      });
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
        if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
        if (path === "/api/projects")
          return ++projectLists === 1 ? Promise.resolve(jsonResponse([project])) : refreshed;
        if (path.startsWith("/api/admin/users") && init?.method === "POST")
          return Promise.resolve(jsonResponse({ ...admin, username: "new-member" }, 201));
        if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
        if (path.endsWith("/documents")) return Promise.resolve(jsonResponse(drafts));
        if (path.endsWith("/documents/project") && init?.method === "PUT") return saved;
        throw new Error(`Unexpected request ${path}`);
      });
      vi.stubGlobal("fetch", fetchMock);
      render(<App />);
      fireEvent.click(await screen.findByRole("button", { name: "Open project Open plan" }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.change(editor, { target: { value: "# Keep this edit\n" } });
      if (state === "saving") fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      fireEvent.change(screen.getByRole("textbox", { name: "Username" }), {
        target: { value: "new-member" },
      });
      fireEvent.change(screen.getByLabelText("Initial password"), {
        target: { value: "a strong passphrase" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Create account" }));
      await waitFor(() => expect(projectLists).toBe(2));
      expect(editor).toHaveValue("# Keep this edit\n");
      finishRefresh(jsonResponse([]));
      expect(
        await screen.findByText("This open project is not on the current list page."),
      ).toBeInTheDocument();
      expect(editor).toHaveValue("# Keep this edit\n");
      expect(screen.getByRole("button", { name: "Close project" })).toBeDisabled();
      if (state === "saving") {
        finishSave(
          jsonResponse({ ...drafts[0], revision_number: 2, content: "# Keep this edit\n" }),
        );
        expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Close project" })).toBeEnabled();
      }
    },
  );

  it("pages through private projects beyond the first hundred", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      name: `Plan ${index}`,
      owner_user_id: admin.id,
      created_at: admin.created_at,
    }));
    const last = { ...firstPage[0], id: "00000000-0000-4000-8000-999999999999", name: "Plan 101" };
    const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
      id: kind,
      kind,
      filename: `${kind}.md`,
      content: `# ${kind} page one\n`,
      revision_number: 1,
    }));
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
      if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
      if (path === "/api/projects") return Promise.resolve(jsonResponse(firstPage));
      if (path === "/api/projects?limit=100&offset=100")
        return Promise.resolve(jsonResponse([last]));
      if (path === `/api/projects/${firstPage[0].id}/documents`)
        return Promise.resolve(jsonResponse(drafts));
      if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected request ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project Plan 0" }));
    expect(await screen.findByRole("textbox", { name: "Edit project.md" })).toHaveValue(
      "# project page one\n",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Next projects" }));
    expect(
      await screen.findByRole("button", { name: "Open project Plan 101" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next projects" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous projects" }));
    expect(await screen.findByRole("button", { name: "Open project Plan 99" })).toBeInTheDocument();
    expect(screen.getByText("Choose a project to review its drafts")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Edit project.md" })).not.toBeInTheDocument();
  });

  it("warns before signing out with unsaved project text", async () => {
    const project = {
      id: "00000000-0000-4000-8000-000000000020",
      name: "Pending plan",
      owner_user_id: admin.id,
      created_at: admin.created_at,
    };
    const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
      id: kind,
      kind,
      filename: `${kind}.md`,
      content: `# Original ${kind}\n`,
      revision_number: 1,
    }));
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
      if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
      if (path === "/api/projects") return Promise.resolve(jsonResponse([project]));
      if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
      if (path.endsWith("/documents")) return Promise.resolve(jsonResponse(drafts));
      if (path === "/api/auth/logout") return Promise.resolve(jsonResponse(undefined, 204));
      throw new Error(`Unexpected request ${path} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project Pending plan" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Edit project.md" }), {
      target: { value: "# New text\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(confirm).toHaveBeenCalledWith("Unsaved draft text will be lost. Sign out anyway?");
    expect(fetchMock.mock.calls.some(([path]) => pathOf(path) === "/api/auth/logout")).toBe(false);
    expect(screen.getByRole("textbox", { name: "Edit project.md" })).toHaveValue("# New text\n");
  });

  it("ignores a late project create from account A after account B signs in", async () => {
    const memberA: TestUser = {
      ...admin,
      id: "00000000-0000-4000-8000-000000000041",
      username: "alice",
      role: "user",
    };
    const memberB: TestUser = {
      ...admin,
      id: "00000000-0000-4000-8000-000000000042",
      username: "bob",
      role: "user",
    };
    const projectA = {
      id: "00000000-0000-4000-8000-000000000043",
      name: "Alice confidential plan",
      owner_user_id: memberA.id,
      created_at: admin.created_at,
    };
    const projectB = {
      id: "00000000-0000-4000-8000-000000000044",
      name: "Bob private plan",
      owner_user_id: memberB.id,
      created_at: admin.created_at,
    };
    const bDrafts = (["project", "agents", "backlog"] as const).map((kind) => ({
      id: kind,
      kind,
      filename: kind === "project" ? "PROJECT.md" : `${kind.toUpperCase()}.md`,
      content: kind === "project" ? "# Bob's private draft\n" : `# ${kind}\n`,
      revision_number: 1,
      content_sha256: `sha-${kind}`,
      origin: "template",
      author_user_id: null,
      created_at: admin.created_at,
      template_source: `${kind}.example`,
      template_sha256: `template-${kind}`,
    }));
    let activeUser: TestUser | null = null;
    let csrfRequests = 0;
    let finishCreate!: (response: Response) => void;
    const pendingCreate = new Promise<Response>((resolve) => {
      finishCreate = resolve;
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path === "/api/auth/csrf") {
        csrfRequests += 1;
        return Promise.resolve(jsonResponse({ csrf_token: `csrf-${csrfRequests}` }));
      }
      if (path === "/api/auth/session")
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      if (path === "/api/auth/login" && method === "POST") {
        const payload = JSON.parse(String(init?.body)) as { username: string };
        activeUser = payload.username === memberA.username ? memberA : memberB;
        return Promise.resolve(
          jsonResponse({
            user: activeUser,
            csrf_token: `session-${activeUser.username}`,
          }),
        );
      }
      if (path === "/api/auth/logout" && method === "POST") {
        activeUser = null;
        return Promise.resolve(jsonResponse(undefined, 204));
      }
      if (path === "/api/projects" && method === "POST") return pendingCreate;
      if (path === "/api/projects") {
        return Promise.resolve(jsonResponse(activeUser?.id === memberB.id ? [projectB] : []));
      }
      if (path === `/api/projects/${projectB.id}/documents`)
        return Promise.resolve(jsonResponse(bDrafts));
      if (path === `/api/projects/${projectA.id}/documents`)
        return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    async function signIn(username: string): Promise<void> {
      fireEvent.change(await screen.findByLabelText("Username"), {
        target: { value: username },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "correct passphrase" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(
        await screen.findByRole("heading", { name: `Welcome, ${username}` }),
      ).toBeInTheDocument();
    }

    await signIn(memberA.username);
    expect(await screen.findByText(/No projects yet\. Create one/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
      target: { value: projectA.name },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([path, options]) => pathOf(path) === "/api/projects" && options?.method === "POST",
        ),
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await signIn(memberB.username);
    fireEvent.click(await screen.findByRole("button", { name: "Open project Bob private plan" }));
    const bEditor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(bEditor, { target: { value: "# Bob's in-progress edit\n" } });

    await act(async () => {
      // Deliberately resolve even though the browser request was aborted: a
      // response already in transit must not cross the account boundary.
      finishCreate(jsonResponse(projectA, 201));
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    const createCall = fetchMock.mock.calls.find(
      ([path, options]) => pathOf(path) === "/api/projects" && options?.method === "POST",
    );
    expect(createCall?.[1]?.signal?.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Open project Bob private plan" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.queryByRole("button", { name: "Open project Alice confidential plan" }),
    ).not.toBeInTheDocument();
    expect(bEditor).toHaveValue("# Bob's in-progress edit\n");
    expect(screen.getByText("Signed in as bob.")).toBeInTheDocument();
    expect(screen.queryByText(/Alice confidential plan/)).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([path]) => pathOf(path) === `/api/projects/${projectA.id}/documents`,
      ),
    ).toBe(false);
  });

  it("loads a pre-login CSRF token and submits a same-origin login without signup", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") {
        return Promise.resolve(jsonResponse({ csrf_token: "pre-auth-token" }));
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      if (path === "/api/auth/login") {
        return Promise.resolve(jsonResponse({ user: admin, csrf_token: "session-token" }));
      }
      if (path === "/api/projects") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path.startsWith("/api/admin/users")) {
        return Promise.resolve(jsonResponse([]));
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.queryByRole("link", { name: /sign up/i })).not.toBeInTheDocument();
    expect(screen.getByText(/There is no public sign-up\./)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Welcome, operator" })).toBeInTheDocument();
    const loginCall = fetchMock.mock.calls.find(([input]) => pathOf(input) === "/api/auth/login");
    expect(loginCall).toBeDefined();
    const [, loginOptions] = loginCall ?? [];
    expect(new Headers(loginOptions?.headers).get("X-CSRF-Token")).toBe("pre-auth-token");
    expect(JSON.parse(String(loginOptions?.body))).toEqual({
      username: "operator",
      password: "correct passphrase",
    });
    expect(loginOptions?.credentials).toBe("same-origin");
    expect(await screen.findByText(/No projects yet\. Create one/)).toBeInTheDocument();
  });

  it("shows an accessible generic sign-in error without losing the form", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") {
        return Promise.resolve(jsonResponse({ csrf_token: "pre-auth-token" }));
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      if (path === "/api/auth/login") {
        return Promise.resolve(jsonResponse({ detail: "Invalid username or password" }, 401));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "unknown-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "incorrect password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
    expect(screen.getByRole("textbox", { name: "Username" })).toBeInTheDocument();
  });

  it("clears a CSRF service error when retry restores anonymous sign-in", async () => {
    let csrfRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") {
        csrfRequests += 1;
        return Promise.resolve(
          csrfRequests === 1
            ? jsonResponse({ detail: "Service temporarily unavailable" }, 503)
            : jsonResponse({ csrf_token: "pre-auth-token" }),
        );
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign-in is temporarily unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Service temporarily unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
    expect(csrfRequests).toBe(2);
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === "/api/auth/session")).toBe(
      true,
    );
  });

  it("supports administrator account creation, reset, and deactivation controls", async () => {
    const accounts: TestUser[] = [admin];
    let failFirstReset = true;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path === "/api/auth/csrf") {
        return Promise.resolve(jsonResponse({ csrf_token: "pre-auth-token" }));
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      if (path === "/api/auth/login" && method === "POST") {
        return Promise.resolve(jsonResponse({ user: admin, csrf_token: "session-token" }));
      }
      if (path === "/api/projects") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/admin/users?limit=100&offset=0" && method === "GET") {
        return Promise.resolve(jsonResponse(accounts));
      }
      if (path === "/api/admin/users" && method === "POST") {
        const body = JSON.parse(String(init?.body)) as {
          username: string;
          role: "admin" | "user";
        };
        const created: TestUser = {
          id: "00000000-0000-4000-8000-000000000002",
          username: body.username,
          role: body.role,
          is_active: true,
          created_at: "2026-09-25T10:00:00Z",
        };
        accounts.push(created);
        return Promise.resolve(jsonResponse(created, 201));
      }
      if (path.endsWith("/reset-password") && method === "POST") {
        if (failFirstReset) {
          failFirstReset = false;
          return Promise.resolve(jsonResponse({ detail: "Password service is busy" }, 503));
        }
        return Promise.resolve(jsonResponse(undefined, 204));
      }
      if (path.endsWith("/deactivate") && method === "POST") {
        const target = accounts.find((account) => path.includes(account.id));
        if (target) target.is_active = false;
        return Promise.resolve(jsonResponse(undefined, 204));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    expect(
      screen.getByText(/project metadata from every account is available/i),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Username", { selector: "input#new-username" }), {
      target: { value: "teammate" },
    });
    fireEvent.change(screen.getByLabelText("Initial password"), {
      target: { value: "temporary passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "teammate" })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Account teammate was created");
    });

    fireEvent.click(await screen.findByText("Reset password for teammate"));
    fireEvent.change(screen.getByLabelText("Temporary password for teammate"), {
      target: { value: "replacement passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Set temporary password for teammate" }));
    expect(
      await screen.findByText("Password reset for teammate failed: Password service is busy"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Temporary password for teammate")).toHaveValue(
      "replacement passphrase",
    );
    fireEvent.click(screen.getByRole("button", { name: "Set temporary password for teammate" }));
    expect(
      await screen.findByText(
        "Temporary password for teammate was changed. Their existing sessions were revoked.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Temporary password for teammate")).toHaveValue("");

    const deactivateButton = await screen.findByRole("button", { name: "Deactivate teammate" });
    fireEvent.click(deactivateButton);
    const deactivationDialog = await screen.findByRole("alertdialog");
    expect(deactivationDialog).toHaveTextContent("Deactivate teammate?");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
    expect(
      fetchMock.mock.calls.filter(([input]) => pathOf(input).endsWith("/deactivate")),
    ).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(deactivationDialog).not.toHaveAttribute("open"));
    expect(document.activeElement).toBe(deactivateButton);

    fireEvent.click(deactivateButton);
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirm deactivation of teammate" }),
    );
    await waitFor(() => expect(accounts[1].is_active).toBe(false));
    expect(await screen.findByText(/Account teammate was deactivated/)).toBeInTheDocument();

    const mutations = fetchMock.mock.calls.filter(([, options]) => options?.method === "POST");
    expect(mutations.length).toBe(5);
    expect(
      mutations.every((call) => Boolean(new Headers(call[1]?.headers).get("X-CSRF-Token"))),
    ).toBe(true);
  });

  it("distinguishes a failed workspace load from an empty list and retries the load", async () => {
    let projectRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") {
        return Promise.resolve(jsonResponse({ csrf_token: "pre-auth-token" }));
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      if (path === "/api/auth/login") {
        return Promise.resolve(jsonResponse({ user: admin, csrf_token: "session-token" }));
      }
      if (path === "/api/projects") {
        projectRequests += 1;
        return projectRequests === 1
          ? Promise.resolve(jsonResponse({ detail: "Project service is unavailable" }, 503))
          : Promise.resolve(jsonResponse([]));
      }
      if (path.startsWith("/api/admin/users")) {
        return Promise.resolve(jsonResponse([]));
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Workspace data could not be loaded: Project service is unavailable",
    );
    expect(screen.queryByText(/No projects yet\. Create one/)).not.toBeInTheDocument();
    expect(screen.queryByText("No accounts are available.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry workspace load" }));
    expect(await screen.findByText(/No projects yet\. Create one/)).toBeInTheDocument();
    expect(screen.getByText("No accounts are available.")).toBeInTheDocument();
    expect(projectRequests).toBe(2);
  });

  it("clears sensitive forms on logout and waits for pre-login CSRF refresh", async () => {
    let csrfRequests = 0;
    let finishCsrfRefresh: ((response: Response) => void) | undefined;
    let loginRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path === "/api/auth/csrf") {
        csrfRequests += 1;
        if (csrfRequests === 1) {
          return Promise.resolve(jsonResponse({ csrf_token: "pre-auth-token" }));
        }
        return new Promise<Response>((resolve) => {
          finishCsrfRefresh = resolve;
        });
      }
      if (path === "/api/auth/session") {
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      }
      if (path === "/api/auth/login" && method === "POST") {
        loginRequests += 1;
        return Promise.resolve(
          jsonResponse({ user: admin, csrf_token: `session-token-${loginRequests}` }),
        );
      }
      if (path === "/api/auth/logout" && method === "POST") {
        return Promise.resolve(jsonResponse(undefined, 204));
      }
      if (path === "/api/projects") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path.startsWith("/api/admin/users")) {
        return Promise.resolve(jsonResponse([]));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Create an account" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Initial password"), {
      target: { value: "unsaved initial password" },
    });
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "unsaved current password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "unsaved new password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await waitFor(() => expect(finishCsrfRefresh).toBeDefined());
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(screen.getByLabelText("Password")).toHaveValue("");

    finishCsrfRefresh?.(jsonResponse({ csrf_token: "refreshed-pre-auth-token" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    expect(screen.getByLabelText("Initial password")).toHaveValue("");
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");

    const loginCalls = fetchMock.mock.calls.filter(
      ([input]) => pathOf(input) === "/api/auth/login",
    );
    expect(new Headers(loginCalls[1]?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "refreshed-pre-auth-token",
    );
  });
});
