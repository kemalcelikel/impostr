import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import {
  changeCanvasViewport,
  updateCanvasBoard,
  type CanvasState,
  type CanvasUpdate,
} from "./canvasState";

const canvasFixture = vi.hoisted(() => ({
  state: null as CanvasState | null,
  onChange: null as ((update: CanvasUpdate) => void) | null,
}));

// Canvas interaction itself is covered by CardCanvas tests. Here only its mounted
// view and project-memory callback boundary matter; no pointer/SVG renderer needed.
vi.mock("./CardCanvas", () => ({
  default: ({
    state,
    onChange,
  }: {
    state: CanvasState;
    onChange: (update: CanvasUpdate) => void;
  }) => {
    canvasFixture.state = state;
    canvasFixture.onChange = onChange;
    return <section aria-label="Sample canvas fixture" />;
  },
}));

vi.mock("./chat", async (original) => ({
  ...(await original<typeof import("./chat")>()),
  streamChat: vi.fn(async (_path: string, signal: AbortSignal) => {
    await new Promise<void>((resolve) =>
      signal.addEventListener("abort", () => resolve(), { once: true }),
    );
  }),
}));

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

function navigateTo(
  name:
    | "Projects"
    | "Planning"
    | "Review & downloads"
    | "Sample canvas Demo"
    | "Accounts"
    | "Account security",
) {
  fireEvent.click(
    within(screen.getByRole("navigation", { name: "Application" })).getByRole("button", { name }),
  );
}

function stubAppFetch(fetchMock: ReturnType<typeof vi.fn>): void {
  const original = fetchMock.getMockImplementation() as (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => Promise<Response>;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (/^\/api\/projects\/[^/]+\/chat$/.test(pathOf(input)) && (init?.method ?? "GET") === "GET") {
      return Promise.resolve(jsonResponse({ conversations: [], last_conversation_id: null }));
    }
    return original(input, init);
  });
  vi.stubGlobal("fetch", fetchMock);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  canvasFixture.state = null;
  canvasFixture.onChange = null;
});

describe("account access", () => {
  it("uses a labelled navigation disclosure with Escape, bounded focus and focus return", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
      if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
      if (path === "/api/projects" || path.startsWith("/api/admin/users"))
        return Promise.resolve(jsonResponse([]));
      throw new Error(`Unexpected request ${path}`);
    });
    stubAppFetch(fetchMock);
    render(<App />);
    const navigation = await screen.findByRole("button", { name: "Navigation" });
    const rail = screen.getByRole("complementary", { name: "Application navigation" });
    const close = within(rail).getByRole("button", { name: "Close navigation" });
    expect(navigation).toHaveAttribute("aria-controls", rail.id);
    expect(navigation).toHaveAttribute("aria-expanded", "false");
    const requests = fetchMock.mock.calls.length;
    fireEvent.click(navigation);
    expect(navigation).toHaveAttribute("aria-expanded", "true");
    expect(close).toHaveFocus();
    expect(
      screen.getByRole("heading", { name: "Projects", level: 1 }).closest("[inert]"),
    ).not.toBeNull();
    const home = within(rail).getByRole("link", { name: "Impostr home" });
    const signout = within(rail).getByRole("button", { name: "Sign out" });
    home.focus();
    fireEvent.keyDown(home, { key: "Tab", shiftKey: true });
    expect(signout).toHaveFocus();
    fireEvent.keyDown(signout, { key: "Tab" });
    expect(home).toHaveFocus();
    fireEvent.keyDown(home, { key: "Escape" });
    expect(navigation).toHaveAttribute("aria-expanded", "false");
    expect(navigation).toHaveFocus();
    fireEvent.click(navigation);
    navigateTo("Account security");
    expect(navigation).toHaveFocus();
    expect(navigation).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("heading", { name: "Account security", level: 1 }).closest("[inert]"),
    ).toBeNull();
    expect(screen.getByRole("navigation", { name: "Current context" })).toHaveTextContent(
      "Account security",
    );
    expect(fetchMock.mock.calls).toHaveLength(requests);
  });

  it("opens the explicitly created project in Planning without another selection", async () => {
    const project = {
      id: "new-plan",
      name: "New plan",
      owner_user_id: admin.id,
      created_at: admin.created_at,
    };
    const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
      id: kind,
      kind,
      filename: `${kind.toUpperCase()}.md`,
      content: `# Saved ${kind}\n`,
      revision_number: 1,
    }));
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
      if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
      if (path === "/api/projects")
        return Promise.resolve(
          jsonResponse(init?.method === "POST" ? project : [], init?.method === "POST" ? 201 : 200),
        );
      if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
      if (path.endsWith("/documents")) return Promise.resolve(jsonResponse(drafts));
      if (path.includes("/document-pair-approval"))
        return Promise.resolve(jsonResponse({ detail: "No fixture approval" }, 503));
      throw new Error(`Unexpected request ${path}`);
    });
    stubAppFetch(fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "New project" }));
    expect(screen.queryByRole("button", { name: "Planning" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input).endsWith("/documents"))).toBe(
      false,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
      target: { value: project.name },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));
    expect(await screen.findByRole("textbox", { name: "Edit PROJECT.md" })).toHaveValue(
      "# Saved project\n",
    );
    expect(screen.getByRole("heading", { name: "Planning", level: 1 })).toBeInTheDocument();
    // Document rendering can precede the workspace's context effect and App's
    // subsequent rail render. Await that distinct observable settlement too.
    const projectGroup = await within(
      screen.getByRole("navigation", { name: "Application" }),
    ).findByRole("group", { name: "New plan" });
    expect(within(projectGroup).getByRole("button", { name: "Planning" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByText("Open a project to start planning.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sample canvas Demo" })).toBeInTheDocument();
    navigateTo("Projects");
    expect(screen.getByRole("button", { name: "Open project New plan" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      fetchMock.mock.calls.filter(([input]) => pathOf(input).endsWith("/documents")),
    ).toHaveLength(1);
  });

  it.each(["admin", "user"] as const)(
    "keeps the %s user's editor, composer and pending turn across shell destinations",
    async (role) => {
      const user = { ...admin, role };
      const project = {
        id: "shell-project",
        name: "Working plan",
        owner_user_id: user.id,
        created_at: admin.created_at,
      };
      const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
        id: kind,
        kind,
        filename: `${kind.toUpperCase()}.md`,
        content: `# Saved ${kind}\n`,
        revision_number: 1,
      }));
      let finishSend!: (response: Response) => void;
      const sending = new Promise<Response>((resolve) => {
        finishSend = resolve;
      });
      let sendSignal: AbortSignal | null | undefined;
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
        if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user }));
        if (path === "/api/projects") return Promise.resolve(jsonResponse([project]));
        if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
        if (path.endsWith("/documents")) return Promise.resolve(jsonResponse(drafts));
        if (path.includes("/document-pair-approval"))
          return Promise.resolve(jsonResponse({ detail: "No fixture approval" }, 503));
        if (path.endsWith("/final-approval") || path.endsWith("/backlog/tasks"))
          return Promise.resolve(jsonResponse({ detail: "Review service unavailable" }, 503));
        if (path.endsWith("/chat") && init?.method === "POST")
          return Promise.resolve(
            jsonResponse({ id: "shell-chat", title: "Working conversation" }, 201),
          );
        if (path.endsWith("/turns") && init?.method === "POST") {
          sendSignal = init.signal;
          return sending;
        }
        if (path.includes("/attachments"))
          return Promise.resolve(jsonResponse({ attachments: [], next_after: null }));
        if (path.includes("/events?"))
          return Promise.resolve(jsonResponse({ events: [], after: 0 }));
        if (path.endsWith("/chat/shell-chat"))
          return Promise.resolve(jsonResponse({ turns: [], interactions: [] }));
        throw new Error(`Unexpected request ${path}`);
      });
      stubAppFetch(fetchMock);
      render(<App />);
      const openProject = await screen.findByRole("button", { name: "Open project Working plan" });
      expect(screen.queryByRole("button", { name: "Workspace" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Planning" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Sample canvas/ })).not.toBeInTheDocument();
      expect(screen.getByText("Open a project to start planning.")).toBeInTheDocument();
      fireEvent.click(openProject);
      expect(
        within(screen.getByRole("group", { name: "Working plan" })).getByRole("button", {
          name: "Planning",
        }),
      ).toHaveAttribute("aria-current", "page");
      expect(screen.queryByRole("navigation", { name: "Project stages" })).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Planning", level: 1 })).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Create an account" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Accounts" }) !== null).toBe(role === "admin");
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      const planningHeading = screen.getByRole("heading", { name: "Planning", level: 1 });
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(planningHeading).toHaveAttribute("id", "app-page-title");
      expect(planningHeading.closest(".workbench-heading")).toHaveTextContent(
        "Project + agent rules",
      );
      expect(screen.getByRole("link", { name: "Skip to current work" })).toHaveAttribute(
        "href",
        "#app-page-title",
      );
      const projectTab = screen.getByRole("tab", { name: "Project" });
      const layout = editor.closest(".workspace-layout")!;
      expect(layout).toHaveClass("workspace-layout--planning");
      fireEvent.change(editor, { target: { value: "# Unsent project decisions\n" } });
      fireEvent.click(screen.getByRole("button", { name: "Conversation" }));
      expect(layout).toHaveAttribute("data-region", "conversation");
      fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
      const composer = screen.getByRole("textbox", { name: "Message tech-lead" });
      await waitFor(() => expect(composer).toBeEnabled());
      fireEvent.change(composer, { target: { value: "Keep this pending planning message" } });
      fireEvent.click(screen.getByRole("button", { name: "Send" }));
      await waitFor(() => expect(sendSignal).toBeDefined());
      const requestCount = fetchMock.mock.calls.length;
      navigateTo("Sample canvas Demo");
      expect(screen.getByRole("heading", { name: "Sample canvas", level: 1 })).toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Sample canvas fixture" })).toBeInTheDocument();
      expect(layout).toHaveAttribute("hidden");
      expect(layout).toHaveClass("workspace-layout--planning");
      expect(screen.queryByTestId("final-review")).not.toBeInTheDocument();
      expect(editor).toBeInTheDocument();
      expect(composer).toBeInTheDocument();
      expect(editor).toHaveValue("# Unsent project decisions\n");
      expect(composer).toHaveValue("Keep this pending planning message");
      expect(sendSignal?.aborted).toBe(false);
      const boardId = canvasFixture.state!.activeBoardId;
      act(() =>
        canvasFixture.onChange!((current) =>
          updateCanvasBoard(current, boardId, (board) =>
            changeCanvasViewport(board, { x: 42, y: -30, zoom: 0.8 }),
          ),
        ),
      );
      const retainedCanvas = canvasFixture.state;
      const destinations =
        role === "admin"
          ? (["Accounts", "Account security", "Projects"] as const)
          : (["Account security", "Projects"] as const);
      for (const destination of destinations) {
        navigateTo(destination);
        expect(editor).toBeInTheDocument();
        expect(editor.closest("[hidden]")).not.toBeNull();
        expect(composer).toHaveValue("Keep this pending planning message");
        expect(sendSignal?.aborted).toBe(false);
        const context = screen.getByRole("navigation", { name: "Current context" });
        expect(context).toHaveTextContent(destination);
        expect(context).not.toHaveTextContent("Working plan");
        expect(screen.getByRole("heading", { name: destination, level: 1 })).toBeInTheDocument();
      }
      expect(screen.getByRole("button", { name: "Open project Working plan" })).toBeDisabled();
      navigateTo("Planning");
      expect(layout).not.toHaveAttribute("hidden");
      expect(layout).toHaveAttribute("data-region", "work");
      expect(layout).toHaveClass("workspace-layout--planning");
      expect(screen.getByRole("button", { name: "Documents" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByRole("textbox", { name: "Edit PROJECT.md" })).toBe(editor);
      expect(editor).toHaveValue("# Unsent project decisions\n");
      fireEvent.click(screen.getByRole("button", { name: "Conversation" }));
      expect(screen.getByRole("textbox", { name: "Message tech-lead" })).toBe(composer);
      expect(fetchMock.mock.calls).toHaveLength(requestCount);
      navigateTo("Sample canvas Demo");
      expect(canvasFixture.state).toBe(retainedCanvas);
      expect(canvasFixture.state!.boards[boardId].viewport).toEqual({ x: 42, y: -30, zoom: 0.8 });
      expect(sendSignal?.aborted).toBe(false);
      navigateTo("Planning");
      fireEvent.click(screen.getByRole("button", { name: "Conversation" }));
      navigateTo("Review & downloads");
      const finalReview = screen.getByTestId("final-review");
      expect(finalReview.closest(".workspace-layout")).toBe(layout);
      expect(layout).not.toHaveClass("workspace-layout--planning");
      expect(layout).not.toHaveAttribute("hidden");
      expect(layout).toHaveAttribute("data-region", "work");
      expect(layout).toHaveAttribute("data-review-mode", "inspection");
      expect(
        screen.queryByRole("navigation", { name: "Workspace regions" }),
      ).not.toBeInTheDocument();
      const reviewHeading = screen.getByRole("heading", { name: "Review & downloads", level: 1 });
      expect(reviewHeading).toHaveAttribute("id", "app-page-title");
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(document.querySelectorAll("#app-page-title")).toHaveLength(1);
      expect(composer).toBeInTheDocument();
      expect(composer.closest(".workspace-conversation")).toHaveAttribute("hidden");
      expect(screen.queryByRole("textbox", { name: "Message tech-lead" })).not.toBeInTheDocument();
      expect(sendSignal?.aborted).toBe(false);
      finishSend(jsonResponse({ detail: "Another project turn is active" }, 409));
      expect(await screen.findByText("Another project turn is active")).toBeInTheDocument();
      expect(editor.closest('[role="tabpanel"]')).toHaveAttribute("hidden");
      expect(
        await within(screen.getByTestId("final-review")).findByRole("alert"),
      ).toHaveTextContent("Review service unavailable");
      expect(screen.getByRole("button", { name: "Review & downloads" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(editor).toHaveValue("# Unsent project decisions\n");
      expect(composer).toHaveValue("Keep this pending planning message");
      // Re-entering the inspection view must not mount a second workspace or
      // reset its saved-file selection. Chat stays mounted but hidden in Review.
      navigateTo("Review & downloads");
      expect(layout).toHaveAttribute("data-region", "work");
      const agentsTab = within(finalReview).getByRole("tab", { name: "AGENTS.md" });
      fireEvent.click(agentsTab);
      navigateTo("Sample canvas Demo");
      expect(screen.getByRole("heading", { name: "Sample canvas", level: 1 })).toHaveAttribute(
        "id",
        "app-page-title",
      );
      expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
      expect(document.querySelectorAll("#app-page-title")).toHaveLength(1);
      expect(screen.getByTestId("final-review")).toBe(finalReview);
      expect(layout).toHaveAttribute("hidden");
      expect(layout).not.toHaveClass("workspace-layout--planning");
      expect(canvasFixture.state).toBe(retainedCanvas);
      navigateTo("Review & downloads");
      expect(screen.getByTestId("final-review")).toBe(finalReview);
      expect(layout).not.toHaveAttribute("hidden");
      expect(layout).toHaveAttribute("data-region", "work");
      expect(agentsTab).toHaveAttribute("aria-selected", "true");
      fireEvent.click(within(finalReview).getByRole("tab", { name: "PROJECT.md" }));
      // Internal review recovery must update the shell too, without changing the
      // unsaved file. jsdom does not implement the element's scrolling operation.
      projectTab.scrollIntoView = vi.fn();
      fireEvent.click(
        within(screen.getByTestId("final-review")).getByRole("button", {
          name: "Review PROJECT.md",
        }),
      );
      expect(screen.getByRole("button", { name: "Planning" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      expect(screen.getByRole("heading", { name: "Planning", level: 1 })).toBeInTheDocument();
      expect(
        screen.getByText(
          "Resolve the current local edit before switching files. Your unsaved work has been kept.",
        ),
      ).toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: "Edit PROJECT.md" })).toBe(editor);
      expect(layout).toHaveClass("workspace-layout--planning");
      expect(layout).toHaveAttribute("data-region", "work");
      expect(screen.queryByTestId("final-review")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Conversation" }));
      expect(screen.getByRole("textbox", { name: "Message tech-lead" })).toBe(composer);
    },
  );
  it.each(["same", "different"])(
    "restores retained editor text only for the %s revalidated account",
    async (account) => {
      const other = { ...admin, id: "other-user", username: "other", role: "user" as const };
      let activeUser = admin;
      let revoked = false;
      const projectFor = (owner: TestUser) => ({
        id: owner.id === admin.id ? "retained-project" : "other-project",
        name: owner.id === admin.id ? "Retained plan" : "Other plan",
        owner_user_id: owner.id,
        created_at: admin.created_at,
      });
      const drafts = (owner: TestUser) =>
        (["project", "agents", "backlog"] as const).map((kind) => ({
          id: `${owner.id}-${kind}`,
          kind,
          filename: `${kind.toUpperCase()}.md`,
          content: `# Saved ${owner.username} ${kind}\n`,
          revision_number: 1,
        }));
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
        if (path === "/api/auth/session") return Promise.resolve(jsonResponse({ user: admin }));
        if (path === "/api/auth/login") {
          activeUser = account === "same" ? admin : other;
          revoked = false;
          return Promise.resolve(jsonResponse({ user: activeUser, csrf_token: "session-csrf" }));
        }
        if (path === "/api/projects")
          return Promise.resolve(jsonResponse([projectFor(activeUser)]));
        if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
        if (path.endsWith("/documents"))
          return Promise.resolve(
            revoked
              ? jsonResponse({ detail: "Authentication required" }, 401)
              : jsonResponse(drafts(activeUser)),
          );
        if (path.includes("/document-pair-approval"))
          return Promise.resolve(jsonResponse({ detail: "No fixture approval" }, 503));
        throw new Error(`Unexpected request ${path} ${init?.method ?? "GET"}`);
      });
      stubAppFetch(fetchMock);
      render(<App />);
      fireEvent.click(await screen.findByRole("button", { name: "Open project Retained plan" }));
      fireEvent.change(await screen.findByRole("textbox", { name: "Edit PROJECT.md" }), {
        target: { value: "# Private unsent editor\n" },
      });
      revoked = true;
      fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
      expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Edit PROJECT.md" })).not.toBeInTheDocument();
      expect(screen.queryByText(/Private unsent editor/)).not.toBeInTheDocument();
      fireEvent.change(screen.getByLabelText("Username"), {
        target: { value: account === "same" ? admin.username : other.username },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "synthetic passphrase" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      if (account === "different")
        fireEvent.click(await screen.findByRole("button", { name: "Open project Other plan" }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      await waitFor(() =>
        expect(editor).toHaveValue(
          account === "same" ? "# Private unsent editor\n" : "# Saved other project\n",
        ),
      );
      if (account === "different")
        expect(screen.queryByText(/Private unsent editor/)).not.toBeInTheDocument();
    },
  );

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
      stubAppFetch(fetchMock);
      render(<App />);
      fireEvent.click(await screen.findByRole("button", { name: "Open project Open plan" }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.change(editor, { target: { value: "# Keep this edit\n" } });
      if (state === "saving") fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      const requestsBeforeThemeChange = fetchMock.mock.calls.length;
      fireEvent.click(screen.getByRole("button", { name: /Switch to (light|dark) mode/ }));
      expect(screen.getByRole("textbox", { name: "Edit PROJECT.md" })).toBe(editor);
      expect(editor).toHaveValue("# Keep this edit\n");
      expect(fetchMock.mock.calls).toHaveLength(requestsBeforeThemeChange);
      navigateTo("Accounts");
      expect(screen.queryByRole("textbox", { name: "Edit PROJECT.md" })).not.toBeInTheDocument();
      expect(editor).toBeInTheDocument();
      fireEvent.change(screen.getByRole("textbox", { name: "Username" }), {
        target: { value: "new-member" },
      });
      fireEvent.change(screen.getByLabelText("Initial password"), {
        target: { value: "a strong passphrase" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Create account" }));
      await waitFor(() => expect(projectLists).toBe(2));
      expect(editor).toHaveValue("# Keep this edit\n");
      navigateTo("Planning");
      expect(screen.getByRole("textbox", { name: "Edit PROJECT.md" })).toBe(editor);
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
    stubAppFetch(fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project Plan 0" }));
    expect(await screen.findByRole("textbox", { name: "Edit project.md" })).toHaveValue(
      "# project page one\n",
    );
    navigateTo("Projects");
    fireEvent.click(await screen.findByRole("button", { name: "Next projects" }));
    expect(
      await screen.findByRole("button", { name: "Open project Plan 101" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next projects" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous projects" }));
    expect(await screen.findByRole("button", { name: "Open project Plan 99" })).toBeInTheDocument();
    // Explicit project pagination still clears selection; the shell no longer
    // offers a dead-end workspace destination that could resurrect it.
    expect(screen.queryByRole("button", { name: "Planning" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByText("Open a project to start planning.")).toBeInTheDocument();
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
    stubAppFetch(fetchMock);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open project Pending plan" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Edit project.md" }), {
      target: { value: "# New text\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(confirm).toHaveBeenCalledWith(
      "Unsaved draft or task edits will be lost. Sign out anyway?",
    );
    expect(fetchMock.mock.calls.some(([path]) => pathOf(path) === "/api/auth/logout")).toBe(false);
    expect(screen.getByRole("textbox", { name: "Edit project.md" })).toHaveValue("# New text\n");
  });

  it("warns before signing out with unsaved task details", async () => {
    const project = {
      id: "00000000-0000-4000-8000-000000000061",
      name: "Task edit plan",
      owner_user_id: admin.id,
      created_at: admin.created_at,
    };
    const backlogContent =
      "# Task plan\n\n## [-] TASK-201 — Draft task\n\n**Depends on:** None\n\nTask body.\n";
    const drafts = (["project", "agents", "backlog"] as const).map((kind) => ({
      id: kind,
      kind,
      filename: kind === "project" ? "PROJECT.md" : kind === "agents" ? "AGENTS.md" : "BACKLOG.md",
      content:
        kind === "backlog"
          ? backlogContent
          : kind === "project"
            ? "# Project draft\n"
            : "# Agent rules draft\n",
      revision_number: 1,
      content_sha256: "sha256-rev-1",
      origin: "template",
      author_user_id: null,
      created_at: admin.created_at,
      template_source: `${kind}.example`,
      template_sha256: `template-${kind}`,
    }));
    const taskSnapshot = {
      revision_number: 1,
      content_sha256: "sha256-rev-1",
      content: backlogContent,
      tasks: [
        {
          id: "TASK-201",
          status: "-",
          title: "Draft task",
          dependencies: [],
          body: "\n**Depends on:** None\n\nTask body.\n",
          acceptance: null,
          verification: null,
          ready: false,
          eligible: false,
          waiting_on: [],
        },
      ],
      summary: { draft_count: 1, ready_count: 0, eligible_count: 0, waiting_count: 0 },
    };
    const approvalStatus = {
      current_project_revision: {
        id: "project-revision-1",
        revision_number: 1,
        content_sha256: "sha256-rev-1",
      },
      current_agents_revision: {
        id: "agents-revision-1",
        revision_number: 1,
        content_sha256: "sha256-rev-1",
      },
      approved: false,
      latest_approval: null,
      approvals: [],
      approval_offset: 0,
      approval_has_more: false,
      approval_next_cursor: null,
    };
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path === "/api/auth/csrf") return Promise.resolve(jsonResponse({ csrf_token: "csrf" }));
      if (path === "/api/auth/session")
        return Promise.resolve(jsonResponse({ detail: "Authentication required" }, 401));
      if (path === "/api/auth/login")
        return Promise.resolve(jsonResponse({ user: admin, csrf_token: "session-csrf" }));
      if (path === "/api/projects") return Promise.resolve(jsonResponse([project]));
      if (path.startsWith("/api/admin/users")) return Promise.resolve(jsonResponse([]));
      if (path.endsWith("/documents")) return Promise.resolve(jsonResponse(drafts));
      if (path.endsWith("/backlog/tasks")) return Promise.resolve(jsonResponse(taskSnapshot));
      if (path.includes("/document-pair-approval") && method === "GET")
        return Promise.resolve(jsonResponse(approvalStatus));
      if (path === "/api/auth/logout") return Promise.resolve(jsonResponse(undefined, 204));
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    stubAppFetch(fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: admin.username },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open project Task edit plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("tab", { name: "Backlog" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Select task TASK-201: Draft task" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task title" }), {
      target: { value: "Unsent task idea" },
    });
    const taskTitle = screen.getByRole("textbox", { name: "Task title" });
    navigateTo("Accounts");
    navigateTo("Account security");
    navigateTo("Planning");
    expect(screen.getByRole("textbox", { name: "Task title" })).toBe(taskTitle);
    expect(taskTitle).toHaveValue("Unsent task idea");
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(confirm).toHaveBeenCalledWith(
      "Unsaved draft or task edits will be lost. Sign out anyway?",
    );
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === "/api/auth/logout")).toBe(
      false,
    );
    expect(screen.getByRole("textbox", { name: "Task title" })).toHaveValue("Unsent task idea");
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
    stubAppFetch(fetchMock);
    render(<App />);

    async function signIn(username: string): Promise<void> {
      fireEvent.change(await screen.findByLabelText("Username"), {
        target: { value: username },
      });
      fireEvent.change(screen.getByLabelText("Password"), {
        target: { value: "correct passphrase" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
      expect(await screen.findByRole("navigation", { name: "Application" })).toBeInTheDocument();
      expect(
        within(screen.getByRole("navigation", { name: "Application" })).getByText(username),
      ).toBeInTheDocument();
      expect(screen.queryByText(`Signed in as ${username}.`)).not.toBeInTheDocument();
    }

    await signIn(memberA.username);
    expect(await screen.findByText(/No projects yet\. Create one/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "New project" }));
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
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
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
    navigateTo("Projects");
    expect(screen.getByRole("button", { name: "Open project Bob private plan" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.queryByRole("button", { name: "Open project Alice confidential plan" }),
    ).not.toBeInTheDocument();
    expect(bEditor).toHaveValue("# Bob's in-progress edit\n");
    expect(
      within(screen.getByRole("navigation", { name: "Application" })).getByText("bob"),
    ).toBeInTheDocument();
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
    stubAppFetch(fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Welcome back", level: 1 })).toHaveAttribute(
      "id",
      "sign-in-title",
    );
    const signInForm = screen.getByRole("form", { name: "Welcome back" });
    expect(signInForm).toHaveClass("login-form");
    expect(
      screen.getByRole("link", { name: "Impostr home" }).closest(".login-header"),
    ).not.toBeNull();
    expect(signInForm.tagName).toBe("FORM");
    expect(signInForm.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(
      within(signInForm).getByText("Open your projects and planning documents."),
    ).toBeVisible();
    expect(screen.getByRole("contentinfo")).toHaveTextContent("Private planning workspace");
    expect(within(signInForm).queryByText("Private planning workspace")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveAttribute("autocomplete", "current-password");
    expect(screen.queryByRole("link", { name: /sign up/i })).not.toBeInTheDocument();
    expect(screen.getByText(/There is no public sign-up\./)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "operator" } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    const password = screen.getByLabelText("Password");
    const previousTheme = document.documentElement.dataset.theme;
    fireEvent.click(screen.getByRole("button", { name: /Switch to (light|dark) mode/ }));
    expect(document.documentElement.dataset.theme).not.toBe(previousTheme);
    expect(screen.getByLabelText("Password")).toBe(password);
    expect(password).toHaveValue("correct passphrase");
    const visibilityToggle = screen.getByRole("button", { name: "Show password" });
    expect(visibilityToggle.tagName).toBe("BUTTON");
    expect(visibilityToggle).toHaveAttribute("type", "button");
    expect(visibilityToggle).toHaveAttribute("aria-controls", "login-password");
    expect(visibilityToggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(visibilityToggle);
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("correct passphrase");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveValue("correct passphrase");
    expect(visibilityToggle).toHaveAttribute("aria-pressed", "false");
    expect(fetchMock.mock.calls.some(([input]) => pathOf(input) === "/api/auth/login")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("navigation", { name: "Application" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("navigation", { name: "Application" })).getByRole("button", {
        name: "Projects",
      }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /Switch to (light|dark) mode/ })).toBeInTheDocument();
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
    stubAppFetch(fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "unknown-user" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "incorrect password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid username or password");
    const signInForm = screen.getByRole("form", { name: "Welcome back" });
    expect(within(signInForm).getByRole("textbox", { name: "Username" })).toHaveValue(
      "unknown-user",
    );
    expect(within(signInForm).getByLabelText("Password")).toHaveValue("incorrect password");
    expect(within(signInForm).getByRole("alert")).toHaveAttribute("aria-live", "assertive");
    expect(within(signInForm).getByRole("button", { name: "Sign in" })).toBeEnabled();
    expect(screen.queryByRole("navigation", { name: "Application" })).not.toBeInTheDocument();
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
    stubAppFetch(fetchMock);

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign-in is temporarily unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Service temporarily unavailable");

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
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
    stubAppFetch(fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("navigation", { name: "Application" });
    expect(
      screen.getByText(/project metadata from every account is available/i),
    ).toBeInTheDocument();
    navigateTo("Accounts");
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();

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
    stubAppFetch(fetchMock);

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
    navigateTo("Accounts");
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
    stubAppFetch(fetchMock);

    render(<App />);
    fireEvent.change(await screen.findByLabelText("Username"), {
      target: { value: "operator" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("navigation", { name: "Application" });
    navigateTo("Accounts");
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Initial password"), {
      target: { value: "unsaved initial password" },
    });
    navigateTo("Account security");
    fireEvent.change(screen.getByLabelText("Current password"), {
      target: { value: "unsaved current password" },
    });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "unsaved new password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
    await waitFor(() => expect(finishCsrfRefresh).toBeDefined());
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    expect(screen.getByLabelText("Password")).toHaveValue("");

    finishCsrfRefresh?.(jsonResponse({ csrf_token: "refreshed-pre-auth-token" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "correct passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("navigation", { name: "Application" });
    navigateTo("Accounts");
    expect(screen.getByRole("heading", { name: "Create an account" })).toBeInTheDocument();
    expect(screen.getByLabelText("Initial password")).toHaveValue("");
    navigateTo("Account security");
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
