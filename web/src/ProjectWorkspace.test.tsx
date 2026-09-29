import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectWorkspace, { type ProjectSummary } from "./ProjectWorkspace";

const project: ProjectSummary = {
  id: "00000000-0000-4000-8000-000000000020",
  name: "Twin tab plan",
  owner_user_id: "00000000-0000-4000-8000-000000000021",
  created_at: "2026-09-25T10:00:00Z",
};
const secondProject: ProjectSummary = {
  ...project,
  id: "00000000-0000-4000-8000-000000000022",
  name: "Second private plan",
};

type DocumentKind = "project" | "agents" | "backlog";
type TestDocument = {
  id: string;
  kind: DocumentKind;
  filename: string;
  revision_number: number;
  content: string;
  content_sha256: string;
  origin: "template" | "human";
  author_user_id: string | null;
  created_at: string;
  template_source: string | null;
  template_sha256: string | null;
};

const documentIds: Record<DocumentKind, string> = {
  project: "00000000-0000-4000-8000-000000000031",
  agents: "00000000-0000-4000-8000-000000000032",
  backlog: "00000000-0000-4000-8000-000000000033",
};

function makeDocument(kind: DocumentKind, content: string, revision = 1): TestDocument {
  const filename =
    kind === "project" ? "PROJECT.md" : kind === "agents" ? "AGENTS.md" : "BACKLOG.md";
  return {
    id: documentIds[kind],
    kind,
    filename,
    revision_number: revision,
    content,
    content_sha256: `sha256-rev-${revision}`,
    origin: revision === 1 ? "template" : "human",
    author_user_id: revision === 1 ? null : project.owner_user_id,
    created_at: "2026-09-25T10:00:00Z",
    template_source: revision === 1 ? `${filename}.example` : null,
    template_sha256: revision === 1 ? `sha256-template-${kind}` : null,
  };
}

const initialDocuments: Record<DocumentKind, TestDocument> = {
  project: makeDocument("project", "# Starter project\nInitial body.\n"),
  agents: makeDocument("agents", "# Starter agent rules\n"),
  backlog: makeDocument("backlog", "# Starter backlog\n"),
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function renderWorkspace(
  fetchMock: ReturnType<typeof vi.fn>,
  props: {
    projects?: ProjectSummary[];
    onProjectCreated?: (project: ProjectSummary) => void;
    onProjectPageChange?: (offset: number) => void;
    projectOffset?: number;
  } = {},
) {
  vi.stubGlobal("fetch", fetchMock);
  return render(
    <ProjectWorkspace
      csrfToken="csrf-test-token"
      loadError=""
      loading={false}
      onProjectCreated={props.onProjectCreated ?? vi.fn()}
      onSessionExpired={vi.fn()}
      onProjectPageChange={props.onProjectPageChange}
      projectOffset={props.projectOffset}
      projects={props.projects ?? [project]}
    />,
  );
}

let originalScrollIntoViewDescriptor: PropertyDescriptor | undefined;

beforeEach(() => {
  const prototype = HTMLElement.prototype;
  originalScrollIntoViewDescriptor = Object.getOwnPropertyDescriptor(prototype, "scrollIntoView");
  if (typeof prototype.scrollIntoView === "function") return;

  // jsdom omits this browser API; tests that assert scrolling install their own spy.
  Object.defineProperty(prototype, "scrollIntoView", {
    configurable: true,
    value: vi.fn(),
    writable: true,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  const prototype = HTMLElement.prototype;
  if (originalScrollIntoViewDescriptor) {
    Object.defineProperty(prototype, "scrollIntoView", originalScrollIntoViewDescriptor);
  } else {
    Reflect.deleteProperty(prototype, "scrollIntoView");
  }
});

describe("private project drafts", () => {
  it.each(["dirty", "saving"])(
    "keeps the open %s draft when a project create response arrives late",
    async (state) => {
      const creation = deferred<Response>();
      const saving = deferred<Response>();
      const onProjectCreated = vi.fn();
      const created = { ...secondProject, name: "Fresh plan" };
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path.endsWith("/documents"))
          return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
        if (path === "/api/projects" && init?.method === "POST") return creation.promise;
        if (path.endsWith("/documents/project") && init?.method === "PUT") return saving.promise;
        throw new Error(`Unexpected request ${path}`);
      });
      const view = renderWorkspace(fetchMock, { projects: [project], onProjectCreated });
      fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.change(screen.getByRole("textbox", { name: "Project name" }), {
        target: { value: created.name },
      });
      fireEvent.click(screen.getByRole("button", { name: "Create project" }));
      fireEvent.change(editor, { target: { value: "# Edited after create started\n" } });
      if (state === "saving") fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      creation.resolve(jsonResponse(created, 201));
      expect(await screen.findByText(/was created. Finish your current draft/)).toBeInTheDocument();
      expect(onProjectCreated).toHaveBeenCalledWith(created);
      expect(editor).toHaveValue("# Edited after create started\n");
      expect(screen.getByRole("button", { name: "Open project Twin tab plan" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      view.rerender(
        <ProjectWorkspace
          csrfToken="csrf-test-token"
          loadError=""
          loading={false}
          onProjectCreated={onProjectCreated}
          onSessionExpired={vi.fn()}
          projects={[]}
        />,
      );
      expect(screen.getByRole("button", { name: "Open project Fresh plan" })).toBeDisabled();
      expect(editor).toHaveValue("# Edited after create started\n");
      if (state === "saving") {
        saving.resolve(jsonResponse(makeDocument("project", "# Edited after create started\n", 2)));
        expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Open project Fresh plan" })).toBeEnabled();
      }
    },
  );

  it("confirms discard of unsaved/conflicted text before enabling navigation", async () => {
    const newer = makeDocument("project", "# Other tab saved\n", 2);
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && init?.method === "PUT")
        return Promise.resolve(jsonResponse({ detail: "Conflict recorded", latest: newer }, 409));
      if (path.includes("/history?"))
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: 2,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock, { projects: [project, secondProject] });
    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# My unsaved idea\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Discard editor changes" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(editor).toHaveValue("# My unsaved idea\n");
    expect(screen.getByRole("button", { name: "Open project Second private plan" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# My unsaved idea\n");
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard editor changes" }));
    expect(editor).toHaveValue(newer.content);
    expect(screen.getByRole("button", { name: "Open project Second private plan" })).toBeEnabled();
    fireEvent.click(screen.getByRole("tab", { name: "Agent rules" }));
    expect(await screen.findByRole("textbox", { name: "Edit AGENTS.md" })).toBeInTheDocument();
  });

  it("invalidates in-flight history on save and refreshes to the saved head", async () => {
    const oldHistory = deferred<Response>();
    const newHistory = deferred<Response>();
    let historyCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.includes("/history?"))
        return ++historyCalls === 1 ? oldHistory.promise : newHistory.promise;
      if (path.endsWith("/documents/project") && init?.method === "PUT")
        return Promise.resolve(jsonResponse(makeDocument("project", "# Saved\n", 2)));
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    fireEvent.change(editor, { target: { value: "# Saved\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(historyCalls).toBe(2));
    oldHistory.resolve(
      jsonResponse({ kind: "project", current_revision_number: 1, revisions: [], proposals: [] }),
    );
    newHistory.resolve(
      jsonResponse({ kind: "project", current_revision_number: 2, revisions: [], proposals: [] }),
    );
    expect(await screen.findByText("Current revision 2")).toBeInTheDocument();
    expect(screen.queryByText("Current revision 1")).not.toBeInTheDocument();
  });

  it("reloads cached history after saving while the history panel is hidden", async () => {
    let currentDocument = { ...initialDocuments.project };
    let historyRequests = 0;
    const revisionSummary = (revisionNumber: number) => ({
      revision_number: revisionNumber,
      content_sha256: `sha256-rev-${revisionNumber}`,
      origin: revisionNumber === 1 ? "template" : "human",
      author_user_id: revisionNumber === 1 ? null : project.owner_user_id,
      created_at: project.created_at,
      template_source: revisionNumber === 1 ? "PROJECT.md.example" : null,
      template_sha256: revisionNumber === 1 ? "sha256-template-project" : null,
    });
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents")) {
        return Promise.resolve(
          jsonResponse([currentDocument, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.endsWith("/documents/project") && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as { content: string };
        currentDocument = makeDocument("project", payload.content, 2);
        return Promise.resolve(jsonResponse(currentDocument));
      }
      if (path.includes("/documents/project/history?")) {
        historyRequests += 1;
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: currentDocument.revision_number,
            revisions: Array.from({ length: currentDocument.revision_number }, (_, index) =>
              revisionSummary(currentDocument.revision_number - index),
            ),
            proposals: [],
            revision_offset: 0,
            proposal_cursor: null,
            proposal_next_cursor: null,
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByText("Current revision 1")).toBeInTheDocument();
    expect(historyRequests).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Hide history" }));
    fireEvent.change(editor, { target: { value: "# Saved while history was hidden\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved PROJECT.md as revision 2.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View history" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByText("Current revision 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compare revision 2" })).toBeInTheDocument();
    expect(historyRequests).toBeGreaterThan(1);
  });

  it("aligns a clean editor with an externally advanced history head without saving old text", async () => {
    const newest = makeDocument("project", "# Externally saved content\n", 2);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && (init?.method ?? "GET") === "GET")
        return Promise.resolve(jsonResponse(newest));
      if (path.includes("/history?"))
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: 2,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      throw new Error(`Unexpected request ${path} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    expect(editor).toHaveValue(initialDocuments.project.content);
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByText("Current revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue(newest.content);
    expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(0);
  });

  it("keeps typing made during an external-head refresh as unsaved editor text", async () => {
    const pendingHead = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && (init?.method ?? "GET") === "GET")
        return pendingHead.promise;
      if (path.includes("/history?"))
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: 2,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) => pathOf(input).endsWith("/documents/project")),
      ).toBe(true),
    );
    fireEvent.change(editor, { target: { value: "# Keep my new text\n" } });
    pendingHead.resolve(jsonResponse(makeDocument("project", "# Another tab's text\n", 2)));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# Keep my new text\n");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });

  it("does not display conflict history ahead of the shown saved document", async () => {
    const head = deferred<Response>();
    const version2 = makeDocument("project", "# First winner\n", 2);
    const version3 = makeDocument("project", "# Later winner\n", 3);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && init?.method === "PUT")
        return Promise.resolve(
          jsonResponse({ detail: "Conflict recorded", latest: version2 }, 409),
        );
      if (path.endsWith("/documents/project")) return head.promise;
      if (path.includes("/history?"))
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: 3,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# My conflict text\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => pathOf(input).endsWith("/documents/project") && init?.method === "GET",
        ),
      ).toBe(true),
    );
    expect(screen.queryByText("Current revision 3")).not.toBeInTheDocument();
    head.resolve(jsonResponse(version3));
    expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
    expect(await screen.findByText("Current revision 3")).toBeInTheDocument();
    expect(editor).toHaveValue("# My conflict text\n");
  });

  it("keeps conflict text and offers retry when head refresh cannot catch up with history", async () => {
    const version2 = makeDocument("project", "# Other tab\n", 2);
    let headRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && init?.method === "PUT")
        return Promise.resolve(
          jsonResponse({ detail: "Conflict recorded", latest: version2 }, 409),
        );
      if (path.endsWith("/documents/project"))
        return Promise.resolve(
          jsonResponse(
            ++headRequests === 1 ? version2 : makeDocument("project", "# Newest tab\n", 3),
          ),
        );
      if (path.includes("/history?"))
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: 3,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# My rejected text\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "History moved ahead of the saved draft",
    );
    expect(screen.queryByText("Current revision 3")).not.toBeInTheDocument();
    expect(editor).toHaveValue("# My rejected text\n");
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
    expect(await screen.findByText("Current revision 3")).toBeInTheDocument();
    expect(editor).toHaveValue("# My rejected text\n");
    expect(headRequests).toBe(2);
  });

  it("allows confirmed discard and project navigation while conflict history is still loading", async () => {
    const historyResponse = deferred<Response>();
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    const newer = makeDocument("project", "# Saved in another tab\n", 2);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && init?.method === "PUT")
        return Promise.resolve(jsonResponse({ detail: "Conflict recorded", latest: newer }, 409));
      if (path.includes("/history?")) return historyResponse.promise;
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock, { projects: [project, secondProject] });
    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# Attempted text\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Discard editor changes" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Discard editor changes" }));
    expect(editor).toHaveValue(newer.content);
    fireEvent.click(screen.getByRole("button", { name: "Open project Second private plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    historyResponse.resolve(
      jsonResponse({ kind: "project", current_revision_number: 2, revisions: [], proposals: [] }),
    );
    expect(
      screen.getByRole("button", { name: "Open project Second private plan" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Current revision 2")).not.toBeInTheDocument();
  });

  it("clears selected drafts and ignores delayed history when changing project pages", async () => {
    const pendingHistory = deferred<Response>();
    const pageChange = vi.fn();
    const hundred = Array.from({ length: 100 }, (_, index) => ({
      ...project,
      id: `page-one-${index}`,
      name: `Page one ${index}`,
    }));
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.includes("/history?")) return pendingHistory.promise;
      throw new Error(`Unexpected request ${path}`);
    });
    const view = renderWorkspace(fetchMock, { projects: hundred, onProjectPageChange: pageChange });
    fireEvent.click(screen.getByRole("button", { name: "Open project Page one 0" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    fireEvent.click(screen.getByRole("button", { name: "Next projects" }));
    expect(pageChange).toHaveBeenCalledWith(100);
    // Even before the parent supplies the next list, the old selection is gone.
    expect(screen.getByText("Choose a project to review its drafts")).toBeInTheDocument();
    view.rerender(
      <ProjectWorkspace
        csrfToken="csrf-test-token"
        loadError=""
        loading={false}
        onProjectCreated={vi.fn()}
        onSessionExpired={vi.fn()}
        onProjectPageChange={pageChange}
        projectOffset={100}
        projects={[secondProject]}
      />,
    );
    expect(screen.getByText("Choose a project to review its drafts")).toBeInTheDocument();
    view.rerender(
      <ProjectWorkspace
        csrfToken="csrf-test-token"
        loadError=""
        loading={false}
        onProjectCreated={vi.fn()}
        onSessionExpired={vi.fn()}
        onProjectPageChange={pageChange}
        projectOffset={0}
        projects={hundred}
      />,
    );
    expect(screen.getByText("Choose a project to review its drafts")).toBeInTheDocument();
    view.rerender(
      <ProjectWorkspace
        csrfToken="csrf-test-token"
        loadError=""
        loading={false}
        onProjectCreated={vi.fn()}
        onSessionExpired={vi.fn()}
        onProjectPageChange={pageChange}
        projectOffset={100}
        projects={[secondProject]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open project Second private plan" }));
    expect(await screen.findByRole("textbox", { name: "Edit PROJECT.md" })).toHaveValue(
      initialDocuments.project.content,
    );
    pendingHistory.resolve(
      jsonResponse({ kind: "project", current_revision_number: 99, revisions: [], proposals: [] }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Edit PROJECT.md" }), {
      target: { value: "# Unsaved second page\n" },
    });
    expect(screen.getByRole("button", { name: "Previous projects" })).toBeDisabled();
    expect(pageChange).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Edit PROJECT.md" })).toHaveValue(
      "# Unsaved second page\n",
    );
    expect(screen.queryByRole("heading", { name: "PROJECT.md history" })).not.toBeInTheDocument();
  });

  it("uses a stable conflict-proposal cursor when a new proposal arrives between pages", async () => {
    const proposals = Array.from({ length: 4 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index + 51).padStart(12, "0")}`,
      expected_revision_number: index + 1,
      observed_revision_number: index + 2,
      content_sha256: `sha-proposal-${index + 1}`,
      author_user_id: project.owner_user_id,
      created_at: `2026-09-25T12:0${index}:00Z`,
    }));
    const concurrentProposal = {
      id: "00000000-0000-4000-8000-000000000099",
      expected_revision_number: 9,
      observed_revision_number: 10,
      content_sha256: "sha-concurrent-proposal",
      author_user_id: project.owner_user_id,
      created_at: "2026-09-25T12:10:00Z",
    };
    let serverProposals = [...proposals];
    let concurrentInsertApplied = false;
    const currentDocument = makeDocument("project", "# Current revision\n", 2);
    const documents = [currentDocument, initialDocuments.agents, initialDocuments.backlog];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      const url = new URL(path, "http://impostr.test");
      if (url.pathname.endsWith("/documents")) return Promise.resolve(jsonResponse(documents));
      if (url.pathname.endsWith("/history")) {
        const limit = 2;
        const cursor = url.searchParams.get("proposal_cursor");
        const legacyOffset = Number(url.searchParams.get("proposal_offset") ?? 0);
        const start =
          cursor === null
            ? legacyOffset
            : serverProposals.findIndex((proposal) => proposal.id === cursor) + 1;
        const page = serverProposals.slice(start, start + limit);
        const hasMore = start + limit < serverProposals.length;
        const response = {
          kind: "project",
          current_revision_number: 2,
          revisions: [],
          proposals: page,
          revision_offset: 0,
          proposal_cursor: cursor,
          proposal_next_cursor: hasMore ? (page.at(-1)?.id ?? null) : null,
          revision_has_more: false,
          proposal_has_more: hasMore,
        };
        if (cursor === null && !concurrentInsertApplied) {
          serverProposals = [concurrentProposal, ...serverProposals];
          concurrentInsertApplied = true;
        }
        return Promise.resolve(jsonResponse(response));
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(
      await screen.findAllByRole("button", { name: "Compare conflict proposal" }),
    ).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Load older conflict proposals" }));

    expect(
      await screen.findAllByRole("button", { name: "Compare conflict proposal" }),
    ).toHaveLength(4);
    for (let index = 1; index <= proposals.length; index += 1) {
      expect(
        screen.getAllByText(
          new RegExp(`Conflict proposal · expected revision ${index}, newer revision ${index + 1}`),
        ),
      ).toHaveLength(1);
    }
    expect(screen.queryByText(/expected revision 9, newer revision 10/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load older conflict proposals" }),
    ).not.toBeInTheDocument();

    const historyCalls = fetchMock.mock.calls.filter(([input]) =>
      new URL(pathOf(input), "http://impostr.test").pathname.endsWith("/history"),
    );
    expect(historyCalls).toHaveLength(2);
    const nextPageUrl = new URL(pathOf(historyCalls[1]?.[0] ?? ""), "http://impostr.test");
    expect(nextPageUrl.searchParams.get("proposal_cursor")).toBe(proposals[1].id);
    expect(nextPageUrl.searchParams.has("proposal_offset")).toBe(false);
  });

  it("shows server-side duplicate-name errors without losing the entered project name", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (pathOf(input) === "/api/projects" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            { detail: "A project with this name already exists in your workspace." },
            409,
          ),
        );
      }
      throw new Error(`Unexpected request: ${pathOf(input)} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock, { projects: [] });

    const nameField = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(nameField, { target: { value: "Existing project" } });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A project with this name already exists in your workspace.",
    );
    expect(nameField).toHaveValue("Existing project");
    const call = fetchMock.mock.calls[0];
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ name: "Existing project" });
    expect(new Headers(call?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
  });

  it("shows field validation errors returned by the trusted API", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (pathOf(input) === "/api/projects" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              detail: [
                {
                  type: "value_error",
                  loc: ["body", "name"],
                  msg: "Value error, Project names cannot contain path separators.",
                },
              ],
            },
            422,
          ),
        );
      }
      throw new Error(`Unexpected request: ${pathOf(input)} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock, { projects: [] });

    const nameField = screen.getByRole("textbox", { name: "Project name" });
    fireEvent.change(nameField, { target: { value: "../escape" } });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Project names cannot contain path separators.",
    );
    expect(nameField).toHaveValue("../escape");
  });

  it("saves, compares, and explicitly reapplies an immutable revision", async () => {
    let current = { ...initialDocuments.project };
    const history = {
      kind: "project",
      current_revision_number: 2,
      revisions: [
        {
          revision_number: 2,
          content_sha256: "sha256-rev-2",
          origin: "human",
          author_user_id: project.owner_user_id,
          created_at: "2026-09-25T11:00:00Z",
          template_source: null,
          template_sha256: null,
        },
        {
          revision_number: 1,
          content_sha256: "sha256-rev-1",
          origin: "template",
          author_user_id: null,
          created_at: "2026-09-25T10:00:00Z",
          template_source: "PROJECT.md.example",
          template_sha256: "sha256-template-project",
        },
      ],
      proposals: [],
      revision_offset: 0,
      proposal_offset: 0,
      revision_has_more: false,
      proposal_has_more: false,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(
          jsonResponse([current, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.endsWith("/documents/project") && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as {
          expected_revision: number;
          content: string;
        };
        expect(payload.expected_revision).toBe(1);
        current = makeDocument("project", payload.content, 2);
        return Promise.resolve(jsonResponse(current));
      }
      if (path.endsWith("/documents/project/history?revision_offset=0")) {
        return Promise.resolve(jsonResponse(history));
      }
      if (path.endsWith("/documents/project/revisions/1")) {
        return Promise.resolve(
          jsonResponse({ ...history.revisions[1], content: initialDocuments.project.content }),
        );
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const projectTab = await screen.findByRole("tab", { name: "Project" });
    projectTab.focus();
    fireEvent.keyDown(projectTab, { key: "ArrowRight" });
    expect(await screen.findByRole("textbox", { name: "Edit AGENTS.md" })).toBeInTheDocument();
    const agentsTab = screen.getByRole("tab", { name: "Agent rules" });
    expect(agentsTab).toHaveAttribute("aria-selected", "true");
    agentsTab.focus();
    fireEvent.keyDown(agentsTab, { key: "ArrowLeft" });
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# Human edit\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Saved PROJECT.md as revision 2");
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByRole("heading", { name: "PROJECT.md history" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare revision 1" }));
    expect(
      await screen.findByRole("heading", { name: /Compare Revision 1 with saved revision 2/ }),
    ).toBeInTheDocument();
    const comparison = screen.getByRole("heading", {
      name: /Compare Revision 1 with saved revision 2/,
    }).parentElement?.parentElement;
    const comparedText = comparison?.querySelectorAll("pre");
    expect(comparedText).toHaveLength(2);
    expect(comparedText?.[1]).toHaveTextContent("# Starter project Initial body.");

    fireEvent.click(screen.getByRole("button", { name: "Reapply revision 1 in editor" }));
    await waitFor(() => expect(editor).toHaveValue(initialDocuments.project.content));
    expect(screen.getByRole("status")).toHaveTextContent("Save draft to create a new revision");
    expect(
      screen.getByText("Unsaved editor text is not shown in this comparison."),
    ).toBeInTheDocument();
    const writeCall = fetchMock.mock.calls.find(
      ([input, init]) => pathOf(input).endsWith("/documents/project") && init?.method === "PUT",
    );
    expect(new Headers(writeCall?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
  });

  it("keeps a two-tab stale edit in history and offers explicit reapply after reload", async () => {
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    let current = { ...initialDocuments.project };
    const proposals: {
      id: string;
      expected_revision_number: number;
      observed_revision_number: number;
      content_sha256: string;
      author_user_id: string;
      created_at: string;
      content: string;
    }[] = [];
    const savedRevisions: {
      revision_number: number;
      content_sha256: string;
      origin: "template" | "human";
      author_user_id: string | null;
      created_at: string;
      template_source: string | null;
      template_sha256: string | null;
    }[] = [
      {
        revision_number: 1,
        content_sha256: current.content_sha256,
        origin: "template",
        author_user_id: null,
        created_at: current.created_at,
        template_source: "PROJECT.md.example",
        template_sha256: current.template_sha256,
      },
    ];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(
          jsonResponse([current, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.endsWith("/documents/project") && method === "GET") {
        return Promise.resolve(jsonResponse(current));
      }
      if (path.endsWith("/documents/project") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          expected_revision: number;
          content: string;
        };
        if (payload.expected_revision !== current.revision_number) {
          proposals.push({
            id: "00000000-0000-4000-8000-000000000040",
            expected_revision_number: payload.expected_revision,
            observed_revision_number: current.revision_number,
            content_sha256: "sha256-conflict",
            author_user_id: project.owner_user_id,
            created_at: "2026-09-25T12:00:00Z",
            content: payload.content,
          });
          return Promise.resolve(
            jsonResponse(
              {
                detail:
                  "A newer draft already exists. Your attempted text was saved as a conflict proposal.",
                latest: current,
                proposal_id: proposals.at(-1)?.id,
              },
              409,
            ),
          );
        }
        current = makeDocument("project", payload.content, current.revision_number + 1);
        savedRevisions.unshift({
          revision_number: current.revision_number,
          content_sha256: current.content_sha256,
          origin: "human",
          author_user_id: project.owner_user_id,
          created_at: "2026-09-25T11:00:00Z",
          template_source: null,
          template_sha256: null,
        });
        return Promise.resolve(jsonResponse(current));
      }
      if (path.includes("/documents/project/history?")) {
        return Promise.resolve(
          jsonResponse({
            kind: "project",
            current_revision_number: current.revision_number,
            revisions: savedRevisions,
            proposals: proposals.map((proposal) => ({
              id: proposal.id,
              expected_revision_number: proposal.expected_revision_number,
              observed_revision_number: proposal.observed_revision_number,
              content_sha256: proposal.content_sha256,
              author_user_id: proposal.author_user_id,
              created_at: proposal.created_at,
            })),
            revision_offset: 0,
            proposal_offset: 0,
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      }
      if (path.endsWith("/documents/project/proposals/00000000-0000-4000-8000-000000000040")) {
        const proposal = proposals.find((item) => item.id === path.split("/").at(-1));
        return proposal
          ? Promise.resolve(jsonResponse(proposal))
          : Promise.resolve(jsonResponse({ detail: "Conflict proposal not found" }, 404));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const callbacks = { onProjectCreated: vi.fn(), onSessionExpired: vi.fn() };
    const firstTab = render(
      <ProjectWorkspace
        csrfToken="tab-one-csrf"
        loadError=""
        loading={false}
        onProjectCreated={callbacks.onProjectCreated}
        onSessionExpired={callbacks.onSessionExpired}
        projects={[project]}
      />,
    );
    const secondTab = render(
      <ProjectWorkspace
        csrfToken="tab-two-csrf"
        loadError=""
        loading={false}
        onProjectCreated={callbacks.onProjectCreated}
        onSessionExpired={callbacks.onSessionExpired}
        projects={[project]}
      />,
    );

    const first = firstTab.container;
    const second = secondTab.container;
    fireEvent.click(within(first).getByRole("button", { name: /Twin tab plan/ }));
    fireEvent.click(within(second).getByRole("button", { name: /Twin tab plan/ }));
    const firstEditor = await within(first).findByRole("textbox", { name: "Edit PROJECT.md" });
    const secondEditor = await within(second).findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(firstEditor, { target: { value: "# Winning text from tab one\n" } });
    fireEvent.click(within(first).getByRole("button", { name: "Save draft" }));
    await within(first).findByText("Saved PROJECT.md as revision 2.");

    const attemptedText = "# Attempted text from tab two\n";
    fireEvent.change(secondEditor, { target: { value: attemptedText } });
    fireEvent.click(within(second).getByRole("button", { name: "Save draft" }));
    expect(await within(second).findByRole("status")).toHaveTextContent(
      "Your attempted text was preserved as a conflict proposal.",
    );
    expect(
      await within(second).findByText(/Conflict proposal · expected revision 1/),
    ).toBeInTheDocument();
    fireEvent.click(
      within(second).getByRole("button", { name: "Reapply conflict proposal in editor" }),
    );
    await waitFor(() => expect(secondEditor).toHaveValue(attemptedText));

    const reloaded = render(
      <ProjectWorkspace
        csrfToken="tab-reloaded-csrf"
        loadError=""
        loading={false}
        onProjectCreated={callbacks.onProjectCreated}
        onSessionExpired={callbacks.onSessionExpired}
        projects={[project]}
      />,
    );
    fireEvent.click(within(reloaded.container).getByRole("button", { name: /Twin tab plan/ }));
    await within(reloaded.container).findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(within(reloaded.container).getByRole("button", { name: "View history" }));
    fireEvent.click(
      await within(reloaded.container).findByRole("button", {
        name: "Reapply conflict proposal in editor",
      }),
    );
    await waitFor(() =>
      expect(
        within(reloaded.container).getByRole("textbox", { name: "Edit PROJECT.md" }),
      ).toHaveValue(attemptedText),
    );
    expect(current.content).toBe("# Winning text from tab one\n");
    expect(proposals).toHaveLength(1);
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => pathOf(input).endsWith("/documents/project") && init?.method === "GET",
      ),
    ).toHaveLength(0);
  });

  it("keeps newer textarea input when a successful save response arrives late", async () => {
    const pendingSave = deferred<Response>();
    const submittedContent = "# Submitted text\n";
    const typedWhileSaving = "# Newer local text\n";
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(
          jsonResponse([
            initialDocuments.project,
            initialDocuments.agents,
            initialDocuments.backlog,
          ]),
        );
      }
      if (path.endsWith("/documents/project") && init?.method === "PUT") {
        expect(JSON.parse(String(init.body))).toMatchObject({ content: submittedContent });
        return pendingSave.promise;
      }
      throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: submittedContent } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/documents\/project$/),
      expect.objectContaining({ method: "PUT" }),
    );

    fireEvent.change(editor, { target: { value: typedWhileSaving } });
    pendingSave.resolve(jsonResponse(makeDocument("project", submittedContent, 2)));

    expect(await screen.findByText("Saved PROJECT.md as revision 2.")).toBeInTheDocument();
    expect(editor).toHaveValue(typedWhileSaving);
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
    expect(screen.getByText("PROJECT.md · revision 2")).toBeInTheDocument();
  });

  it("scrolls a conflict comparison clear of the viewport edge, then returns focus to its trigger", async () => {
    const prototype = HTMLElement.prototype;
    const scrollDescriptor = Object.getOwnPropertyDescriptor(prototype, "scrollIntoView");
    const scrollIntoView = vi.fn();
    Object.defineProperty(prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
      writable: true,
    });

    try {
      const proposal = {
        id: "00000000-0000-4000-8000-000000000042",
        expected_revision_number: 1,
        observed_revision_number: 2,
        content_sha256: "sha256-conflict-proposal",
        author_user_id: project.owner_user_id,
        created_at: "2026-09-25T12:00:00Z",
      };
      const currentDocument = makeDocument("project", "# Current saved draft\n", 2);
      const proposalContent = "# Rejected draft idea\nKeep this separate for review.\n";
      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const path = pathOf(input);
        if (path.endsWith("/documents")) {
          return Promise.resolve(
            jsonResponse([currentDocument, initialDocuments.agents, initialDocuments.backlog]),
          );
        }
        if (path.includes("/documents/project/history?")) {
          return Promise.resolve(
            jsonResponse({
              kind: "project",
              current_revision_number: 2,
              revisions: [
                {
                  revision_number: 2,
                  content_sha256: currentDocument.content_sha256,
                  origin: currentDocument.origin,
                  author_user_id: currentDocument.author_user_id,
                  created_at: currentDocument.created_at,
                  template_source: null,
                  template_sha256: null,
                },
              ],
              proposals: [proposal],
              revision_offset: 0,
              proposal_cursor: null,
              proposal_next_cursor: null,
              revision_has_more: false,
              proposal_has_more: false,
            }),
          );
        }
        if (path.endsWith(`/proposals/${proposal.id}`)) {
          return Promise.resolve(jsonResponse({ ...proposal, content: proposalContent }));
        }
        throw new Error(`Unexpected request: ${path}`);
      });
      renderWorkspace(fetchMock);

      fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
      await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      const compareButton = await screen.findByRole("button", {
        name: "Compare conflict proposal",
      });
      compareButton.focus();
      fireEvent.click(compareButton);

      const comparisonHeading = await screen.findByRole("heading", {
        name: "Compare Conflict proposal with saved revision 2",
      });
      await waitFor(() => {
        expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
        expect(scrollIntoView.mock.contexts).toContain(comparisonHeading);
        expect(document.activeElement).toBe(comparisonHeading);
      });
      expect(comparisonHeading).toHaveAttribute("tabindex", "-1");
      // scrollIntoView honors scroll-margin on the target in browsers. The heading
      // shares a flex row with a taller close button, so aligning at 0 clips both.
      expect(comparisonHeading).toHaveClass("scroll-mt-6");
      const comparison = screen.getByRole("region", {
        name: "Compare Conflict proposal with saved revision 2",
      });
      const comparisonPanes = comparison.querySelectorAll("pre");
      expect(comparisonPanes).toHaveLength(2);
      expect(comparisonPanes[0]?.textContent).toBe(currentDocument.content);
      expect(comparisonPanes[1]?.textContent).toBe(proposalContent);

      fireEvent.click(within(comparison).getByRole("button", { name: "Close comparison" }));
      expect(
        screen.queryByRole("heading", {
          name: "Compare Conflict proposal with saved revision 2",
        }),
      ).not.toBeInTheDocument();
      expect(document.activeElement).toBe(compareButton);
    } finally {
      if (scrollDescriptor) {
        Object.defineProperty(prototype, "scrollIntoView", scrollDescriptor);
      } else {
        Reflect.deleteProperty(prototype, "scrollIntoView");
      }
    }
  });

  it("keeps newer textarea input when a delayed conflict response and reload finish", async () => {
    const pendingSave = deferred<Response>();
    const submittedContent = "# Submitted stale text\n";
    const typedWhileSaving = "# Newer text to keep\n";
    const current = makeDocument("project", "# Another tab saved this\n", 2);
    const proposal = {
      id: "00000000-0000-4000-8000-000000000040",
      expected_revision_number: 1,
      observed_revision_number: 2,
      content_sha256: "sha256-conflict",
      author_user_id: project.owner_user_id,
      created_at: "2026-09-25T12:00:00Z",
    };
    const history = {
      kind: "project",
      current_revision_number: 2,
      revisions: [],
      proposals: [proposal],
      revision_offset: 0,
      proposal_offset: 0,
      revision_has_more: false,
      proposal_has_more: false,
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(
          jsonResponse([
            initialDocuments.project,
            initialDocuments.agents,
            initialDocuments.backlog,
          ]),
        );
      }
      if (path.endsWith("/documents/project") && method === "PUT") {
        expect(JSON.parse(String(init?.body))).toMatchObject({ content: submittedContent });
        return pendingSave.promise;
      }
      if (path.endsWith("/documents/project") && method === "GET") {
        return Promise.resolve(jsonResponse(current));
      }
      if (path.includes("/documents/project/history?")) {
        return Promise.resolve(jsonResponse(history));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: submittedContent } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.change(editor, { target: { value: typedWhileSaving } });
    pendingSave.resolve(
      jsonResponse(
        {
          detail:
            "A newer draft already exists. Your attempted text was saved as a conflict proposal.",
        },
        409,
      ),
    );

    expect(
      await screen.findByText(/Conflict proposal · expected revision 1, newer revision 2/),
    ).toBeInTheDocument();
    expect(editor).toHaveValue(typedWhileSaving);
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();
  });

  it("keeps save A scoped and locks create while the editor is temporarily clean", async () => {
    const pending = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents") && (init?.method ?? "GET") === "GET")
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.endsWith("/documents/project") && init?.method === "PUT") return pending.promise;
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock, { projects: [project, secondProject] });
    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# Submitted A\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    fireEvent.change(editor, { target: { value: initialDocuments.project.content } });
    expect(screen.getByRole("button", { name: "View history" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard editor changes" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Open project Second private plan" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("button", { name: "Create project" }).closest("form")!);
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
    pending.resolve(jsonResponse(makeDocument("project", "# Submitted A\n", 2)));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue(initialDocuments.project.content);
  });

  it.each(["revision", "proposal"])(
    "does not overwrite newer editor input from a delayed %s reapply",
    async (variant) => {
      const pending = deferred<Response>();
      const proposalId = "00000000-0000-4000-8000-000000000041";
      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const path = pathOf(input);
        if (path.endsWith("/documents"))
          return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
        if (path.includes("/history?"))
          return Promise.resolve(
            jsonResponse({
              kind: "project",
              current_revision_number: 1,
              revisions: [
                { revision_number: 1, origin: "template", created_at: project.created_at },
              ],
              proposals: [
                {
                  id: proposalId,
                  expected_revision_number: 1,
                  observed_revision_number: 1,
                  created_at: project.created_at,
                },
              ],
              revision_has_more: false,
              proposal_has_more: false,
            }),
          );
        if (path.endsWith("/revisions/1") || path.endsWith(`/proposals/${proposalId}`))
          return pending.promise;
        throw new Error(`Unexpected request ${path}`);
      });
      renderWorkspace(fetchMock);
      fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      fireEvent.click(
        await screen.findByRole("button", {
          name:
            variant === "revision"
              ? "Reapply revision 1 in editor"
              : "Reapply conflict proposal in editor",
        }),
      );
      fireEvent.change(editor, { target: { value: "# Typed during request\n" } });
      pending.resolve(jsonResponse({ content: "# Delayed historical text\n" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Editor text changed while loading",
      );
      expect(editor).toHaveValue("# Typed during request\n");
      expect(screen.getByRole("button", { name: "Create project" })).toBeDisabled();
    },
  );

  it.each([
    {
      label: "revision",
      button: "Reapply revision 1 in editor",
      detailsPath: `/api/projects/${project.id}/documents/project/revisions/1`,
    },
    {
      label: "conflict proposal",
      button: "Reapply conflict proposal in editor",
      detailsPath: `/api/projects/${project.id}/documents/project/proposals/00000000-0000-4000-8000-000000000041`,
    },
  ])(
    "ignores a delayed $label from a project after switching workspaces",
    async ({ button, detailsPath }) => {
      const pendingDetail = deferred<Response>();
      const history = {
        kind: "project",
        current_revision_number: 1,
        revisions: [
          {
            revision_number: 1,
            content_sha256: "sha256-rev-1",
            origin: "template",
            author_user_id: null,
            created_at: "2026-09-25T10:00:00Z",
            template_source: "PROJECT.md.example",
            template_sha256: "sha256-template-project",
          },
        ],
        proposals: [
          {
            id: "00000000-0000-4000-8000-000000000041",
            expected_revision_number: 1,
            observed_revision_number: 2,
            content_sha256: "sha256-conflict",
            author_user_id: project.owner_user_id,
            created_at: "2026-09-25T12:00:00Z",
          },
        ],
        revision_offset: 0,
        proposal_offset: 0,
        revision_has_more: false,
        proposal_has_more: false,
      };
      const projectAContent = "# First private project\n";
      const projectBContent = "# Second private project\n";
      const projectADocument = makeDocument("project", projectAContent);
      const projectBDocument = makeDocument("project", projectBContent);
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path.endsWith("/documents") && (init?.method ?? "GET") === "GET") {
          const content = path.includes(project.id) ? projectADocument : projectBDocument;
          return Promise.resolve(
            jsonResponse([content, initialDocuments.agents, initialDocuments.backlog]),
          );
        }
        if (path.includes("/documents/project/history?")) {
          return Promise.resolve(jsonResponse(history));
        }
        if (path === detailsPath) return pendingDetail.promise;
        throw new Error(`Unexpected request: ${path} ${init?.method ?? "GET"}`);
      });
      renderWorkspace(fetchMock, { projects: [project, secondProject] });

      fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      expect(editor).toHaveValue(projectAContent);
      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      fireEvent.click(await screen.findByRole("button", { name: button }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(detailsPath, expect.any(Object)));

      fireEvent.click(screen.getByRole("button", { name: "Open project Second private plan" }));
      const secondEditor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      expect(secondEditor).toHaveValue(projectBContent);
      const detailCall = fetchMock.mock.calls.find(([input]) => pathOf(input) === detailsPath);
      expect(detailCall?.[1]?.signal?.aborted).toBe(true);
      pendingDetail.resolve(
        jsonResponse({
          revision_number: 1,
          id: "00000000-0000-4000-8000-000000000031",
          kind: "project",
          filename: "PROJECT.md",
          content: "# First project's private historical text\n",
          content_sha256: "sha256-old",
          origin: "template",
          author_user_id: null,
          created_at: "2026-09-25T10:00:00Z",
          template_source: "PROJECT.md.example",
          template_sha256: "sha256-template-project",
        }),
      );

      await waitFor(() => expect(secondEditor).toHaveValue(projectBContent));
      expect(
        screen.queryByText("# First project's private historical text"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Open project Second private plan" }),
      ).toHaveAttribute("aria-pressed", "true");
    },
  );
});
