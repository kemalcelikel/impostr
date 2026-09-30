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
type TestPairApproval = {
  id: string;
  project_revision_id: string;
  project_revision_number: number;
  agents_revision_id: string;
  agents_revision_number: number;
  actor_user_id: string | null;
  created_at: string;
};
type TestApprovalStatus = {
  current_project_revision: { id: string; revision_number: number; content_sha256: string };
  current_agents_revision: { id: string; revision_number: number; content_sha256: string };
  approved: boolean;
  latest_approval: TestPairApproval | null;
  approvals: TestPairApproval[];
  approval_offset: number;
  approval_has_more: boolean;
  approval_next_cursor: string | null;
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

function makeApprovalStatus(
  projectDocument: TestDocument = initialDocuments.project,
  agentsDocument: TestDocument = initialDocuments.agents,
  approved = false,
): TestApprovalStatus {
  return {
    current_project_revision: {
      id: `revision-project-${projectDocument.revision_number}`,
      revision_number: projectDocument.revision_number,
      content_sha256: projectDocument.content_sha256,
    },
    current_agents_revision: {
      id: `revision-agents-${agentsDocument.revision_number}`,
      revision_number: agentsDocument.revision_number,
      content_sha256: agentsDocument.content_sha256,
    },
    approved,
    latest_approval: null,
    approvals: [],
    approval_offset: 0,
    approval_has_more: false,
    approval_next_cursor: null,
  };
}

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
  const originalImplementation = fetchMock.getMockImplementation() as
    ((input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) | undefined;
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(input);
    const isApprovalStatusRequest =
      path.includes("/document-pair-approval") && (init?.method ?? "GET") === "GET";
    if (originalImplementation) {
      try {
        const response = originalImplementation(input, init);
        if (isApprovalStatusRequest && response === undefined) {
          return Promise.resolve(jsonResponse(makeApprovalStatus()));
        }
        return response;
      } catch (error) {
        if (isApprovalStatusRequest) {
          return Promise.resolve(jsonResponse(makeApprovalStatus()));
        }
        throw error;
      }
    }
    if (isApprovalStatusRequest) {
      return Promise.resolve(jsonResponse(makeApprovalStatus()));
    }
    return Promise.reject(new Error(`Unexpected request ${path}`));
  });
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
  it.each([
    { draftCount: 1, message: "1 draft task is not ready." },
    { draftCount: 2, message: "2 draft tasks are not ready." },
  ])(
    "explains owner task readiness and backlog approval (draft count: $draftCount)",
    async ({ draftCount, message }) => {
      const taskDescriptions = [
        { id: "TASK-001", status: "x", title: "Complete", dependencies: [], body: "Completed." },
        {
          id: "TASK-002",
          status: " ",
          title: "Ready and eligible",
          dependencies: [],
          body: "Independent work.",
        },
        {
          id: "TASK-003",
          status: " ",
          title: "Ready and waiting",
          dependencies: ["TASK-004"],
          body: "Wait for the prerequisite.",
        },
        {
          id: "TASK-004",
          status: "-",
          title: "Draft prerequisite",
          dependencies: [],
          body: "Draft.",
        },
        ...(draftCount === 2
          ? [
              {
                id: "TASK-005",
                status: "-",
                title: "Second draft",
                dependencies: [],
                body: "Draft two.",
              },
            ]
          : []),
      ];
      const statusById = new Map(taskDescriptions.map((task) => [task.id, task.status]));
      const tasks = taskDescriptions.map((task, index) => {
        const ready = task.status === " ";
        const waiting_on = ready
          ? task.dependencies.filter((dependency) => statusById.get(dependency) !== "x")
          : [];
        const dependencyLine = task.dependencies.length ? task.dependencies.join(", ") : "None";
        return {
          id: task.id,
          status: task.status,
          title: task.title,
          dependencies: task.dependencies,
          body: `\n**Depends on:** ${dependencyLine}\n\n${task.body}\n${
            index < taskDescriptions.length - 1 ? "\n" : ""
          }`,
          acceptance: null,
          verification: null,
          ready,
          eligible: ready && waiting_on.length === 0,
          waiting_on,
        };
      });
      const backlogContent = `# Saved plan\n\n${tasks
        .map((task) => `## [${task.status}] ${task.id} — ${task.title}${task.body}`)
        .join("")}`;
      const backlog = makeDocument("backlog", backlogContent, 3);
      const taskSnapshot = {
        revision_number: 3,
        content: backlog.content,
        content_sha256: backlog.content_sha256,
        tasks,
        summary: {
          draft_count: tasks.filter((task) => task.status === "-").length,
          ready_count: tasks.filter((task) => task.status === " ").length,
          eligible_count: tasks.filter((task) => task.eligible).length,
          waiting_count: tasks.filter((task) => task.status === " " && !task.eligible).length,
        },
      };
      const fetchMock = vi.fn((input: RequestInfo | URL) => {
        const path = pathOf(input);
        if (path.endsWith("/documents"))
          return Promise.resolve(
            jsonResponse([initialDocuments.project, initialDocuments.agents, backlog]),
          );
        if (path.endsWith("/backlog/tasks")) return Promise.resolve(jsonResponse(taskSnapshot));
        if (path.includes("/document-pair-approval"))
          return Promise.resolve(jsonResponse(makeApprovalStatus()));
        return Promise.reject(new Error(`Unexpected request ${path}`));
      });
      renderWorkspace(fetchMock);

      fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
      await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.click(screen.getByRole("tab", { name: "Backlog" }));

      const summary = await screen.findByRole("region", { name: "Saved task status" });
      expect(summary).toHaveTextContent("BACKLOG.md revision 3");
      expect(
        within(summary).getByText(
          "Read-only summary for BACKLOG.md revision 3. Ready means the owner marked a task as ready; it does not mean this backlog revision is approved. Dependency-eligible means every prerequisite is complete.",
        ),
      ).toBeInTheDocument();
      expect(summary).toHaveTextContent(message);
      expect(summary).toHaveTextContent("Ready2");
      expect(summary).toHaveTextContent("Dependency-eligible1");
      expect(summary).toHaveTextContent("Waiting on prerequisites1");
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/projects/${project.id}/backlog/tasks`,
        expect.objectContaining({ method: "GET" }),
      );
    },
  );

  it("keeps task edits pending until saved and mirrors the returned backlog revision into Markdown", async () => {
    const backlogContent =
      "# Planning draft\n\n## [-] TASK-101 — Existing task\n\n**Depends on:** None\n\nInitial task body.\n";
    const updatedContent =
      "# Planning draft\n\n## [-] TASK-101 — Updated task\n\n**Depends on:** None\n\nInitial task body.\n";
    let backlog = makeDocument("backlog", backlogContent, 3);
    let taskSnapshot = {
      revision_number: 3,
      content_sha256: "sha256-rev-3",
      content: backlogContent,
      tasks: [
        {
          id: "TASK-101",
          status: "-",
          title: "Existing task",
          dependencies: [],
          body: "\n**Depends on:** None\n\nInitial task body.\n",
          acceptance: null,
          verification: null,
          ready: false,
          eligible: false,
          waiting_on: [],
        },
      ],
      summary: { draft_count: 1, ready_count: 0, eligible_count: 0, waiting_count: 0 },
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents")) {
        return Promise.resolve(
          jsonResponse([initialDocuments.project, initialDocuments.agents, backlog]),
        );
      }
      if (path.endsWith("/documents/backlog") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as { content: string };
        const content = payload.content;
        backlog = makeDocument("backlog", content, 5);
        taskSnapshot = {
          revision_number: 5,
          content_sha256: backlog.content_sha256,
          content,
          tasks: [
            {
              ...taskSnapshot.tasks[0],
              title: "Markdown title",
            },
          ],
          summary: taskSnapshot.summary,
        };
        return Promise.resolve(jsonResponse(backlog));
      }
      if (path.endsWith("/backlog/tasks") && method === "GET") {
        return Promise.resolve(jsonResponse(taskSnapshot));
      }
      if (path.endsWith("/backlog/tasks/TASK-101") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          expected_revision: number;
          title: string;
          status: "-" | " ";
        };
        expect(payload).toMatchObject({
          expected_revision: 3,
          title: "Updated task",
          status: "-",
        });
        backlog = makeDocument("backlog", updatedContent, 4);
        taskSnapshot = {
          revision_number: 4,
          content_sha256: backlog.content_sha256,
          content: updatedContent,
          tasks: [
            {
              ...taskSnapshot.tasks[0],
              title: "Updated task",
            },
          ],
          summary: taskSnapshot.summary,
        };
        return Promise.resolve(jsonResponse(taskSnapshot));
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("tab", { name: "Backlog" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Select task TASK-101: Existing task" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task title" }), {
      target: { value: "Updated task" },
    });

    expect(screen.getByRole("tab", { name: "Project" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));
    expect(await screen.findByText("Saved TASK-101 to BACKLOG.md revision 4.")).toBeInTheDocument();
    expect(screen.getByText("BACKLOG.md · revision 4")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByRole("textbox", { name: "Edit BACKLOG.md" })).toHaveValue(updatedContent);

    const markdownUpdate = updatedContent.replace("Updated task", "Markdown title");
    fireEvent.change(screen.getByRole("textbox", { name: "Edit BACKLOG.md" }), {
      target: { value: markdownUpdate },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved BACKLOG.md as revision 5.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Tasks" }));
    expect(
      await screen.findByRole("button", { name: "Select task TASK-101: Markdown title" }),
    ).toBeInTheDocument();
    const taskWrite = fetchMock.mock.calls.find(
      ([input, init]) =>
        pathOf(input).endsWith("/backlog/tasks/TASK-101") && init?.method === "PUT",
    );
    expect(new Headers(taskWrite?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
  });

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

  it.each(["detail-first", "pair-first"] as const)(
    "does not show history r2 beside a detail/pair head r3 when %s resolves first",
    async (responseOrder) => {
      const delayedDetail = deferred<Response>();
      const newer = makeDocument("project", "# Third saved head\n", 3);
      const unsavedText = "# My unsaved revision-one edit\n";
      let pairHead = initialDocuments.project;
      let historyRequests = 0;
      const expectedRevisions: number[] = [];
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        const method = init?.method ?? "GET";
        if (path.endsWith("/documents") && method === "GET") {
          return Promise.resolve(
            jsonResponse([pairHead, initialDocuments.agents, initialDocuments.backlog]),
          );
        }
        if (path.includes("/document-pair-approval") && method === "GET") {
          return Promise.resolve(jsonResponse(makeApprovalStatus(pairHead)));
        }
        if (path.includes("/documents/project/history?")) {
          historyRequests += 1;
          return Promise.resolve(
            jsonResponse({
              kind: "project",
              current_revision_number: historyRequests === 1 ? 2 : 3,
              revisions: [],
              proposals: [],
              revision_has_more: false,
              proposal_has_more: false,
            }),
          );
        }
        if (path.endsWith("/documents/project") && method === "GET") {
          return delayedDetail.promise;
        }
        if (path.endsWith("/documents/project") && method === "PUT") {
          const payload = JSON.parse(String(init?.body)) as { expected_revision: number };
          expectedRevisions.push(payload.expected_revision);
          return Promise.resolve(jsonResponse({ detail: "Conflict recorded", latest: newer }, 409));
        }
        throw new Error(`Unexpected request ${path} ${method}`);
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
      fireEvent.change(editor, { target: { value: unsavedText } });
      if (responseOrder === "pair-first") {
        pairHead = newer;
        fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
        expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
      }
      delayedDetail.resolve(jsonResponse(newer));
      expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
      expect(editor).toHaveValue(unsavedText);
      expect(screen.queryByText("Current revision 2")).not.toBeInTheDocument();
      expect(await screen.findByRole("alert")).toHaveTextContent("Reload history");
      fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
      expect(await screen.findByText("Current revision 3")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      expect(
        await screen.findByText(/attempted text was preserved as a conflict proposal/),
      ).toBeInTheDocument();
      expect(expectedRevisions).toEqual([1]);
      expect(editor).toHaveValue(unsavedText);
    },
  );

  it("does not let an older in-flight history request stale a clean editor after pair refresh", async () => {
    const pendingHistory = deferred<Response>();
    const newer = makeDocument("project", "# Pair refresh head\n", 2);
    let projectHead = initialDocuments.project;
    let historyCalls = 0;
    const expectedRevisions: number[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET")
        return Promise.resolve(
          jsonResponse([projectHead, initialDocuments.agents, initialDocuments.backlog]),
        );
      if (path.includes("/document-pair-approval") && method === "GET")
        return Promise.resolve(jsonResponse(makeApprovalStatus(projectHead)));
      if (path.includes("/documents/project/history?")) {
        historyCalls += 1;
        return historyCalls === 1
          ? pendingHistory.promise
          : Promise.resolve(
              jsonResponse({
                kind: "project",
                current_revision_number: 2,
                revisions: [],
                proposals: [],
                revision_has_more: false,
                proposal_has_more: false,
              }),
            );
      }
      if (path.endsWith("/documents/project") && method === "GET")
        return Promise.resolve(jsonResponse(newer));
      if (path.endsWith("/documents/project") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          expected_revision: number;
          content: string;
        };
        expectedRevisions.push(payload.expected_revision);
        return Promise.resolve(
          payload.expected_revision === 2
            ? jsonResponse(makeDocument("project", payload.content, 3))
            : jsonResponse({ detail: "Conflict recorded", latest: newer }, 409),
        );
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    await waitFor(() => expect(historyCalls).toBe(1));

    projectHead = newer;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue(newer.content);
    pendingHistory.resolve(
      jsonResponse({
        kind: "project",
        current_revision_number: 2,
        revisions: [],
        proposals: [],
        revision_has_more: false,
        proposal_has_more: false,
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Reload history");
    fireEvent.click(screen.getByRole("button", { name: "Retry history" }));
    await waitFor(() => expect(screen.getByText("Current revision 2")).toBeInTheDocument());
    fireEvent.change(editor, { target: { value: "# My next change\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved PROJECT.md as revision 3.")).toBeInTheDocument();
    expect(expectedRevisions).toEqual([2]);
  });

  it.each(["history-first", "pair-first"] as const)(
    "keeps a history-discovered saved head when the older pair response resolves %s",
    async (responseOrder) => {
      const pendingPair = deferred<Response>();
      const pendingHistory = deferred<Response>();
      const newer = makeDocument("project", "# History-discovered saved head\n", 2);
      const historyPayload = {
        kind: "project",
        current_revision_number: 2,
        revisions: [],
        proposals: [],
        revision_has_more: false,
        proposal_has_more: false,
      };
      let documentRequests = 0;
      let historyRequests = 0;
      let savedProject = initialDocuments.project;
      const expectedRevisions: number[] = [];
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        const method = init?.method ?? "GET";
        if (path.endsWith("/documents") && method === "GET") {
          documentRequests += 1;
          return documentRequests === 1
            ? Promise.resolve(jsonResponse(Object.values(initialDocuments)))
            : pendingPair.promise;
        }
        if (path.includes("/document-pair-approval") && method === "GET") {
          return Promise.resolve(
            jsonResponse(makeApprovalStatus(savedProject, initialDocuments.agents)),
          );
        }
        if (path.includes("/documents/project/history?")) {
          historyRequests += 1;
          return historyRequests === 1
            ? pendingHistory.promise
            : Promise.resolve(jsonResponse(historyPayload));
        }
        if (path.endsWith("/documents/project") && method === "GET")
          return Promise.resolve(jsonResponse(newer));
        if (path.endsWith("/documents/project") && method === "PUT") {
          const payload = JSON.parse(String(init?.body)) as { expected_revision: number };
          expectedRevisions.push(payload.expected_revision);
          return Promise.resolve(jsonResponse({ detail: "Conflict recorded", latest: newer }, 409));
        }
        throw new Error(`Unexpected request ${path} ${method}`);
      });
      renderWorkspace(fetchMock);
      fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
      await waitFor(() => expect(documentRequests).toBe(2));
      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      await waitFor(() => expect(historyRequests).toBe(1));
      fireEvent.change(editor, { target: { value: "# My unsaved decision\n" } });
      savedProject = newer;

      if (responseOrder === "history-first") {
        pendingHistory.resolve(jsonResponse(historyPayload));
        expect(await screen.findByText("Current revision 2")).toBeInTheDocument();
        expect(editor).toHaveValue("# My unsaved decision\n");
        pendingPair.resolve(jsonResponse(Object.values(initialDocuments)));
      } else {
        pendingPair.resolve(jsonResponse(Object.values(initialDocuments)));
        expect(
          await screen.findByRole("button", { name: "Reload saved pair and status" }),
        ).toBeEnabled();
        pendingHistory.resolve(jsonResponse(historyPayload));
        expect(await screen.findByText("Current revision 2")).toBeInTheDocument();
      }

      expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
      expect(editor).toHaveValue("# My unsaved decision\n");
      expect(
        screen.getByText(/Saving now will preserve your text as a conflict proposal/),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      expect(
        await screen.findByText(/attempted text was preserved as a conflict proposal/),
      ).toBeInTheDocument();
      expect(expectedRevisions).toEqual([1]);
      expect(editor).toHaveValue("# My unsaved decision\n");
      expect(screen.getByText("PROJECT.md · revision 2")).toBeInTheDocument();
    },
  );

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
    expect(await screen.findByText(/History moved ahead of the saved draft/)).toBeInTheDocument();
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

    expect(await screen.findByText("Saved PROJECT.md as revision 2.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByRole("heading", { name: "PROJECT.md history" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare revision 1" }));
    expect(
      await screen.findByRole("heading", { name: /Compare Revision 1 with saved revision 2/ }),
    ).toBeInTheDocument();
    const comparison = screen.getByRole("heading", {
      name: /Compare Revision 1 with saved revision 2/,
    }).parentElement?.parentElement;
    const savedDiff = within(comparison as HTMLElement).getByRole("list", {
      name: /Line-by-line diff: Revision 1 compared with Saved PROJECT.md revision 2/,
    });
    expect(savedDiff).toHaveTextContent("Removed line: # Starter project");
    expect(savedDiff).toHaveTextContent("Added line: # Human edit");

    fireEvent.click(screen.getByRole("button", { name: "Reapply revision 1 in editor" }));
    await waitFor(() => expect(editor).toHaveValue(initialDocuments.project.content));
    expect(
      screen.getByText("Revision loaded into the editor. Save draft to create a new revision."),
    ).toBeInTheDocument();
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
    expect(
      await within(second).findByText(/attempted text was preserved as a conflict proposal/),
    ).toBeInTheDocument();
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
      const comparisonDiff = within(comparison).getByRole("list", {
        name: /Line-by-line diff: Conflict proposal compared with Saved PROJECT.md revision 2/,
      });
      expect(comparisonDiff).toHaveTextContent("Removed line: # Rejected draft idea");
      expect(comparisonDiff).toHaveTextContent("Added line: # Current saved draft");

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

  it.each(["revision", "proposal"])(
    "keeps a delayed %s reapply bound to the old head when pair reload advances it",
    async (variant) => {
      const pendingDetail = deferred<Response>();
      const newer = makeDocument("project", "# Externally saved head\n", 2);
      const proposalId = "00000000-0000-4000-8000-000000000041";
      let currentHead = initialDocuments.project;
      const expectedRevisions: number[] = [];
      vi.stubGlobal(
        "confirm",
        vi.fn(() => true),
      );
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        if (path.endsWith("/documents"))
          return Promise.resolve(
            jsonResponse([currentHead, initialDocuments.agents, initialDocuments.backlog]),
          );
        if (path.includes("/document-pair-approval"))
          return Promise.resolve(jsonResponse(makeApprovalStatus(currentHead)));
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
          return pendingDetail.promise;
        if (path.endsWith("/documents/project") && init?.method === "PUT") {
          const payload = JSON.parse(String(init.body)) as {
            expected_revision: number;
            content: string;
          };
          expectedRevisions.push(payload.expected_revision);
          if (payload.expected_revision === 1)
            return Promise.resolve(
              jsonResponse({ detail: "Conflict recorded", latest: newer }, 409),
            );
          currentHead = makeDocument("project", payload.content, 3);
          return Promise.resolve(jsonResponse(currentHead));
        }
        throw new Error(`Unexpected request ${path}`);
      });
      renderWorkspace(fetchMock);
      fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      fireEvent.change(editor, { target: { value: "# My original unsaved draft\n" } });
      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      fireEvent.click(
        await screen.findByRole("button", {
          name:
            variant === "revision"
              ? "Reapply revision 1 in editor"
              : "Reapply conflict proposal in editor",
        }),
      );
      currentHead = newer;
      fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
      expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
      pendingDetail.resolve(
        jsonResponse({ content: "# Old historical text\n", revision_number: 1 }),
      );
      expect(editor).toHaveValue("# My original unsaved draft\n");
      expect(screen.queryByText(/loaded into the editor/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
      expect(
        await screen.findByText(/attempted text was preserved as a conflict proposal/),
      ).toBeInTheDocument();
      expect(expectedRevisions).toEqual([1]);
      expect(currentHead).toEqual(newer);
      expect(editor).toHaveValue("# My original unsaved draft\n");
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

  it("approves the exact current saved pair once and disables repeated/dirty approval", async () => {
    const pendingApproval = deferred<Response>();
    const currentDocuments: Record<DocumentKind, TestDocument> = { ...initialDocuments };
    let status = makeApprovalStatus(currentDocuments.project, currentDocuments.agents);
    const approval = {
      id: "approval-1",
      project_revision_id: "project-revision-2",
      project_revision_number: 2,
      agents_revision_id: "agents-revision-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: "2026-09-25T12:00:00Z",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(jsonResponse(Object.values(currentDocuments)));
      }
      if (path.endsWith("/documents/project") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as { content: string };
        currentDocuments.project = makeDocument("project", payload.content, 2);
        status = makeApprovalStatus(currentDocuments.project, currentDocuments.agents);
        return Promise.resolve(jsonResponse(currentDocuments.project));
      }
      if (path.includes("/document-pair-approval")) {
        if (method === "POST") return pendingApproval.promise;
        return Promise.resolve(jsonResponse(status));
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approveButton = await screen.findByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    expect(approveButton).toBeEnabled();
    fireEvent.change(editor, { target: { value: "# Saved project revision\n" } });
    expect(approveButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved PROJECT.md as revision 2.")).toBeInTheDocument();
    await waitFor(() => expect(approveButton).toBeEnabled());

    const approveRequestButton = screen.getByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    approveRequestButton.focus();
    fireEvent.click(approveRequestButton);
    await waitFor(() => expect(approveRequestButton).toBeDisabled());
    fireEvent.click(approveRequestButton);
    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) =>
        pathOf(input).includes("/document-pair-approval") && init?.method === "POST",
    );
    expect(postCalls).toHaveLength(1);
    expect(JSON.parse(String(postCalls[0]?.[1]?.body))).toEqual({
      expected_project_revision: 2,
      expected_agents_revision: 1,
    });
    expect(new Headers(postCalls[0]?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");

    status = {
      ...makeApprovalStatus(currentDocuments.project, currentDocuments.agents, true),
      latest_approval: approval,
      approvals: [approval],
    };
    pendingApproval.resolve(jsonResponse(approval));
    expect(
      await screen.findByText(
        "Approved PROJECT.md revision 2 and AGENTS.md revision 1 as one saved pair.",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Approved at last check" })).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approved at last check" })).toBeDisabled(),
    );
  });

  it("stacks approved-pair actions on narrow screens and restores the desktop row", async () => {
    const approval: TestPairApproval = {
      id: "approved-pair",
      project_revision_id: "revision-project-1",
      project_revision_number: 1,
      agents_revision_id: "revision-agents-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: project.created_at,
    };
    const approvedStatus: TestApprovalStatus = {
      ...makeApprovalStatus(initialDocuments.project, initialDocuments.agents, true),
      latest_approval: approval,
      approvals: [approval],
      approval_has_more: true,
      approval_next_cursor: "older-approvals",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.includes("/document-pair-approval"))
        return Promise.resolve(jsonResponse(approvedStatus));
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const approvalSection = await screen.findByRole("region", {
      name: "Approve the saved document pair",
    });
    const approvedButton = within(approvalSection).getByRole("button", {
      name: "Approved at last check",
    });
    const olderApprovalsButton = within(approvalSection).getByRole("button", {
      name: "Load earlier approvals",
    });
    const historySummary = within(approvalSection).getByText(
      "Immutable pair approval history (1 shown)",
    );
    const historyControl = historySummary.closest("details");
    const actions = approvedButton.parentElement;

    expect(approvedButton).toBeDisabled();
    expect(actions).toHaveClass("grid", "min-w-0", "gap-3", "lg:flex", "lg:flex-wrap");
    expect(approvedButton).toHaveClass(
      "w-full",
      "lg:w-auto",
      "whitespace-normal",
      "focus-visible:outline-2",
    );
    expect(olderApprovalsButton).toHaveClass("w-full", "lg:w-auto");
    expect(historyControl).not.toBeNull();
    expect(historyControl).toHaveClass("w-full", "min-w-0", "lg:flex-1", "lg:min-w-56");
    expect(historyControl).toContainElement(historySummary);
    expect(historySummary.tagName).toBe("SUMMARY");
    expect(historySummary).toHaveClass("break-words", "focus-visible:outline-2");
  });

  it("refreshes both saved heads and approval on tab return without erasing dirty typing", async () => {
    const nextDocuments = {
      ...initialDocuments,
      agents: makeDocument("agents", "# Saved in another tab\n", 2),
    };
    let savedDocuments: Record<DocumentKind, TestDocument> = { ...initialDocuments };
    const originalApproval: TestPairApproval = {
      id: "approved-original-pair",
      project_revision_id: "revision-project-1",
      project_revision_number: 1,
      agents_revision_id: "revision-agents-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: project.created_at,
    };
    const headRefresh = deferred<Response>();
    let documentCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents")) {
        documentCalls += 1;
        return documentCalls === 1
          ? Promise.resolve(jsonResponse(Object.values(initialDocuments)))
          : documentCalls === 2
            ? headRefresh.promise
            : Promise.resolve(jsonResponse(Object.values(savedDocuments)));
      }
      if (path.includes("/document-pair-approval")) {
        return Promise.resolve(
          jsonResponse({
            ...makeApprovalStatus(
              savedDocuments.project,
              savedDocuments.agents,
              documentCalls === 1,
            ),
            latest_approval: originalApproval,
            approvals: [originalApproval],
          }),
        );
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    expect(await screen.findByRole("button", { name: "Approved at last check" })).toBeDisabled();
    expect(screen.getByText(/Another tab may have saved since then/)).toBeInTheDocument();

    savedDocuments = nextDocuments;
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(documentCalls).toBe(2));
    expect(screen.queryByText("Approved at last check")).not.toBeInTheDocument();
    fireEvent.change(editor, { target: { value: "# My unsaved idea\n" } });
    headRefresh.resolve(jsonResponse(Object.values(savedDocuments)));
    expect(await screen.findByText("Re-review required")).toBeInTheDocument();
    expect(screen.getByText("Saved revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# My unsaved idea\n");
    expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() => expect(documentCalls).toBe(3));
    expect(editor).toHaveValue("# My unsaved idea\n");
    expect(screen.getByText("Re-review required")).toBeInTheDocument();
  });

  it("reloads unchanged open AGENTS history without a saved-head warning", async () => {
    const historyPayload = {
      kind: "agents",
      current_revision_number: 1,
      revisions: [
        {
          revision_number: 1,
          content_sha256: initialDocuments.agents.content_sha256,
          origin: "template",
          author_user_id: null,
          created_at: initialDocuments.agents.created_at,
          template_source: "AGENTS.md.example",
          template_sha256: initialDocuments.agents.template_sha256,
        },
      ],
      proposals: [],
      revision_offset: 0,
      proposal_cursor: null,
      proposal_next_cursor: null,
      revision_has_more: false,
      proposal_has_more: false,
    };
    const refreshedHistory = deferred<Response>();
    let historyRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.includes("/document-pair-approval"))
        return Promise.resolve(
          jsonResponse(makeApprovalStatus(initialDocuments.project, initialDocuments.agents)),
        );
      if (path.includes("/documents/agents/history?")) {
        historyRequests += 1;
        return historyRequests === 1
          ? Promise.resolve(jsonResponse(historyPayload))
          : refreshedHistory.promise;
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("tab", { name: "Agent rules" }));
    await screen.findByRole("textbox", { name: "Edit AGENTS.md" });
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    expect(await screen.findByText("Current revision 1")).toBeInTheDocument();
    expect(historyRequests).toBe(1);

    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() => expect(historyRequests).toBe(2));
    expect(screen.getByRole("heading", { name: "AGENTS.md history" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide history" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Loading revision history…")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    refreshedHistory.resolve(jsonResponse(historyPayload));
    expect(await screen.findByText("Current revision 1")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("submits a dirty editor's original base revision after a new saved head is discovered", async () => {
    const newer = makeDocument("project", "# Other tab saved\n", 2);
    let savedProject = initialDocuments.project;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents") && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(
          jsonResponse([savedProject, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.includes("/document-pair-approval")) {
        return Promise.resolve(jsonResponse(makeApprovalStatus(savedProject)));
      }
      if (path.endsWith("/documents/project") && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as { expected_revision: number };
        expect(payload.expected_revision).toBe(1);
        return Promise.resolve(jsonResponse({ detail: "Conflict recorded", latest: newer }, 409));
      }
      if (path.includes("/history?")) {
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
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.change(editor, { target: { value: "# My unsaved specification\n" } });
    savedProject = newer;
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# My unsaved specification\n");
    expect(
      screen.getByText(/Saving now will preserve your text as a conflict proposal/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(/attempted text was preserved as a conflict proposal/),
    ).toBeInTheDocument();
    expect(editor).toHaveValue("# My unsaved specification\n");
  });

  it("does not promote typing during a stale pair approval to the newer saved revision", async () => {
    const pendingApproval = deferred<Response>();
    const newer = makeDocument("project", "# Different tab's saved project\n", 2);
    let projectHead = initialDocuments.project;
    const writes: number[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(
          jsonResponse([projectHead, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.includes("/document-pair-approval")) {
        return method === "POST"
          ? pendingApproval.promise
          : Promise.resolve(jsonResponse(makeApprovalStatus(projectHead)));
      }
      if (path.endsWith("/documents/project") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          expected_revision: number;
          content: string;
        };
        writes.push(payload.expected_revision);
        return Promise.resolve(
          payload.expected_revision === 1
            ? jsonResponse({ detail: "Conflict recorded", latest: newer }, 409)
            : jsonResponse(makeDocument("project", payload.content, 3)),
        );
      }
      if (path.includes("/history?")) {
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
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approvalButton = await screen.findByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    fireEvent.click(approvalButton);
    fireEvent.change(editor, { target: { value: "# My text while approving\n" } });
    projectHead = newer;
    pendingApproval.resolve(
      jsonResponse(
        {
          detail: "The saved pair changed",
          latest: { project: newer, agents: initialDocuments.agents },
        },
        409,
      ),
    );
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# My text while approving\n");
    expect(
      screen.getByText(/Saving now will preserve your text as a conflict proposal/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(/attempted text was preserved as a conflict proposal/),
    ).toBeInTheDocument();
    expect(editor).toHaveValue("# My text while approving\n");
    expect(writes).toEqual([1]);
    // A second click without an explicit reapply must not overwrite the head either.
    await waitFor(() => expect(screen.getByRole("button", { name: "Save draft" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes).toEqual([1, 1]);
  });

  it.each(["clean", "dirty"] as const)(
    "keeps the history-discovered head when a stale approval response arrives last with a %s editor",
    async (editorPath) => {
      const pendingHistory = deferred<Response>();
      const pendingApproval = deferred<Response>();
      const historyHead = makeDocument(
        "project",
        "# History-discovered saved head\nNewest saved specification.\n",
        3,
      );
      const approvalSnapshotProject = makeDocument(
        "project",
        "# Approval conflict snapshot\nAn older saved specification.\n",
        2,
      );
      const latestAgents = makeDocument(
        "agents",
        "# Concurrently saved agent rules\nCurrent agent boundary.\n",
        2,
      );
      let latestProject = initialDocuments.project;
      let approvalStatus = makeApprovalStatus(initialDocuments.project, initialDocuments.agents);
      let historyRequests = 0;
      const writes: { expected_revision: number; content: string }[] = [];
      const unsavedText = "# Keep this unsaved text\nDo not replace it with a saved head.\n";
      const postApprovalEdit = "# Deliberate edit after reviewing the latest head\n";
      const historyResponse = () => ({
        kind: "project",
        current_revision_number: latestProject.revision_number,
        revisions: [],
        proposals: [],
        revision_offset: 0,
        proposal_cursor: null,
        proposal_next_cursor: null,
        revision_has_more: false,
        proposal_has_more: false,
      });
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        const method = init?.method ?? "GET";
        if (path.endsWith("/documents") && method === "GET") {
          return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
        }
        if (path.includes("/document-pair-approval")) {
          return method === "POST"
            ? pendingApproval.promise
            : Promise.resolve(jsonResponse(approvalStatus));
        }
        if (path.includes("/documents/project/history?")) {
          historyRequests += 1;
          return historyRequests === 1
            ? pendingHistory.promise
            : Promise.resolve(jsonResponse(historyResponse()));
        }
        if (path.endsWith("/documents/project") && method === "GET") {
          return Promise.resolve(jsonResponse(latestProject));
        }
        if (path.endsWith("/documents/project") && method === "PUT") {
          const payload = JSON.parse(String(init?.body)) as {
            expected_revision: number;
            content: string;
          };
          writes.push(payload);
          if (editorPath === "dirty") {
            return Promise.resolve(
              jsonResponse(
                {
                  detail: "Conflict recorded",
                  latest: latestProject,
                  proposal_id: "saved-as-proposal",
                },
                409,
              ),
            );
          }
          latestProject = makeDocument(
            "project",
            payload.content,
            latestProject.revision_number + 1,
          );
          approvalStatus = makeApprovalStatus(latestProject, latestAgents);
          return Promise.resolve(jsonResponse(latestProject));
        }
        throw new Error(`Unexpected request: ${path} ${method}`);
      });
      renderWorkspace(fetchMock);

      fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
      const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      const approveButton = await screen.findByRole("button", {
        name: "Approve saved PROJECT.md + AGENTS.md pair",
      });
      await waitFor(() => expect(approveButton).toBeEnabled());

      fireEvent.click(screen.getByRole("button", { name: "View history" }));
      await waitFor(() => expect(historyRequests).toBe(1));
      fireEvent.click(approveButton);
      await waitFor(() => {
        expect(
          fetchMock.mock.calls.filter(
            ([input, request]) =>
              pathOf(input).includes("/document-pair-approval") && request?.method === "POST",
          ),
        ).toHaveLength(1);
      });
      if (editorPath === "dirty") {
        fireEvent.change(editor, { target: { value: unsavedText } });
      }

      latestProject = historyHead;
      approvalStatus = makeApprovalStatus(historyHead, latestAgents);
      pendingHistory.resolve(
        jsonResponse({
          kind: "project",
          current_revision_number: historyHead.revision_number,
          revisions: [],
          proposals: [],
          revision_offset: 0,
          proposal_cursor: null,
          proposal_next_cursor: null,
          revision_has_more: false,
          proposal_has_more: false,
        }),
      );
      expect(await screen.findByText("Current revision 3")).toBeInTheDocument();
      expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
      expect(editor).toHaveValue(editorPath === "clean" ? historyHead.content : unsavedText);

      pendingApproval.resolve(
        jsonResponse(
          {
            detail: "A saved document changed before approval.",
            latest: { project: approvalSnapshotProject, agents: latestAgents },
          },
          409,
        ),
      );

      expect(
        await screen.findByRole("heading", { name: "Saved pair changed before approval" }),
      ).toBeInTheDocument();
      expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
      const pairConflict = screen.getByRole("region", {
        name: "Saved pair changed before approval",
      });
      expect(pairConflict).toHaveTextContent("PROJECT.md: revision 1 → revision 3");
      expect(pairConflict).toHaveTextContent("AGENTS.md: revision 1 → revision 2");
      const savedPairDiff = within(pairConflict).getByRole("list", {
        name: /Previously reviewed PROJECT\.md revision 1 compared with Latest PROJECT\.md revision 3/,
      });
      expect(savedPairDiff).toHaveTextContent("Removed line: # Starter project");
      expect(savedPairDiff).toHaveTextContent("Added line: # History-discovered saved head");

      if (editorPath === "dirty") {
        expect(editor).toHaveValue(unsavedText);
        expect(
          screen.getByText(/Saving now will preserve your text as a conflict proposal/),
        ).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
        expect(
          await screen.findByText(/attempted text was preserved as a conflict proposal/),
        ).toBeInTheDocument();
        expect(writes).toEqual([{ expected_revision: 1, content: unsavedText }]);
        expect(editor).toHaveValue(unsavedText);
        expect(screen.getByText("PROJECT.md · revision 3")).toBeInTheDocument();
      } else {
        expect(editor).toHaveValue(historyHead.content);
        expect(screen.getByRole("button", { name: "Save draft" })).toBeDisabled();
        fireEvent.change(editor, { target: { value: postApprovalEdit } });
        fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
        expect(await screen.findByText("Saved PROJECT.md as revision 4.")).toBeInTheDocument();
        expect(writes).toEqual([{ expected_revision: 3, content: postApprovalEdit }]);
      }
    },
  );

  it("keeps the switched editor's original base when pair refresh completes mid-edit", async () => {
    const pendingPair = deferred<Response>();
    const newerAgents = makeDocument("agents", "# Another tab's agent rules\n", 2);
    let documentCalls = 0;
    const writes: number[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        documentCalls += 1;
        return documentCalls === 1
          ? Promise.resolve(jsonResponse(Object.values(initialDocuments)))
          : pendingPair.promise;
      }
      if (path.includes("/document-pair-approval")) {
        return Promise.resolve(
          jsonResponse(makeApprovalStatus(initialDocuments.project, newerAgents)),
        );
      }
      if (path.endsWith("/documents/agents") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          expected_revision: number;
          content: string;
        };
        writes.push(payload.expected_revision);
        return Promise.resolve(
          payload.expected_revision === 1
            ? jsonResponse({ detail: "Conflict recorded", latest: newerAgents }, 409)
            : jsonResponse(makeDocument("agents", payload.content, 3)),
        );
      }
      if (path.includes("/history?")) {
        return Promise.resolve(
          jsonResponse({
            kind: "agents",
            current_revision_number: 2,
            revisions: [],
            proposals: [],
            revision_has_more: false,
            proposal_has_more: false,
          }),
        );
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() => expect(documentCalls).toBe(2));
    fireEvent.click(screen.getByRole("tab", { name: "Agent rules" }));
    const editor = screen.getByRole("textbox", { name: "Edit AGENTS.md" });
    fireEvent.change(editor, { target: { value: "# My agent policy\n" } });
    pendingPair.resolve(
      jsonResponse([initialDocuments.project, newerAgents, initialDocuments.backlog]),
    );
    expect(await screen.findByText("AGENTS.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue("# My agent policy\n");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(
      await screen.findByText(/attempted text was preserved as a conflict proposal/),
    ).toBeInTheDocument();
    expect(writes).toEqual([1]);
    expect(editor).toHaveValue("# My agent policy\n");
  });

  it("unlocks cursor pagination when a newer head/status reload aborts the older page", async () => {
    const firstPage = Array.from({ length: 20 }, (_, index): TestPairApproval => ({
      id: `approval-${index}`,
      project_revision_id: "revision-project-1",
      project_revision_number: 1,
      agents_revision_id: "revision-agents-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: project.created_at,
    }));
    const older = deferred<Response>();
    const retried = deferred<Response>();
    let olderRequests = 0;
    const status = {
      ...makeApprovalStatus(),
      latest_approval: firstPage[0],
      approvals: firstPage,
      approval_has_more: true,
      approval_next_cursor: "after-first-page",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(initialDocuments)));
      if (path.includes("/document-pair-approval")) {
        if (path.includes("cursor=after-first-page"))
          return ++olderRequests === 1 ? older.promise : retried.promise;
        return Promise.resolve(jsonResponse(status));
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    const olderButton = await screen.findByRole("button", { name: "Load earlier approvals" });
    fireEvent.click(olderButton);
    expect(olderRequests).toBe(1);
    expect(olderButton).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Load earlier approvals" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Load earlier approvals" }));
    expect(olderRequests).toBe(2);
    older.resolve(jsonResponse({ ...status, approvals: [{ ...firstPage[0], id: "stale" }] }));
    retried.resolve(
      jsonResponse({
        ...status,
        approvals: [firstPage[19], { ...firstPage[0], id: "older" }],
        approval_has_more: false,
        approval_next_cursor: null,
      }),
    );
    expect(
      await screen.findByText("Immutable pair approval history (21 shown)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("stale")).not.toBeInTheDocument();
  });

  it("does not let an older approval-history snapshot regress either current head", async () => {
    const projectHead = makeDocument("project", "# Current project head\n", 2);
    const firstPage = Array.from({ length: 20 }, (_, index): TestPairApproval => ({
      id: `current-approval-${index}`,
      project_revision_id: "project-revision-2",
      project_revision_number: 2,
      agents_revision_id: "agents-revision-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: project.created_at,
    }));
    const stalePage = deferred<Response>();
    const currentStatus = {
      ...makeApprovalStatus(projectHead, initialDocuments.agents),
      latest_approval: firstPage[0],
      approvals: firstPage,
      approval_has_more: true,
      approval_next_cursor: "older-than-current-head",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents")) {
        return Promise.resolve(
          jsonResponse([projectHead, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.includes("/document-pair-approval")) {
        return path.includes("cursor=older-than-current-head")
          ? stalePage.promise
          : Promise.resolve(jsonResponse(currentStatus));
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approvalSection = screen.getByRole("region", { name: "Approve the saved document pair" });
    const olderButton = await within(approvalSection).findByRole("button", {
      name: "Load earlier approvals",
    });
    fireEvent.click(olderButton);
    stalePage.resolve(
      jsonResponse({
        ...makeApprovalStatus(initialDocuments.project, initialDocuments.agents),
        latest_approval: firstPage[0],
        approvals: [{ ...firstPage[0], id: "older-page-row" }],
        approval_has_more: false,
        approval_next_cursor: null,
      }),
    );

    expect(
      await within(approvalSection).findByText("Immutable pair approval history (21 shown)"),
    ).toBeInTheDocument();
    expect(within(approvalSection).getByText("Saved revision 2")).toBeInTheDocument();
    expect(within(approvalSection).getByText("Saved revision 1")).toBeInTheDocument();
  });

  it.each(["refresh", "history"] as const)(
    "keeps the submitted approval baseline immutable when a later %s advances the compare target",
    async (advanceSource) => {
      const projectTwo = makeDocument("project", "# First newer project head\n", 2);
      const projectThree = makeDocument("project", "# Later project head\n", 3);
      const agentsTwo = makeDocument("agents", "# First newer agent head\n", 2);
      let latestPair = { project: initialDocuments.project, agents: initialDocuments.agents };
      let approvalPosts = 0;
      let approved = false;
      const approval = {
        id: "approved-after-re-review",
        project_revision_id: "project-revision-3",
        project_revision_number: 3,
        agents_revision_id: "agents-revision-2",
        agents_revision_number: 2,
        actor_user_id: project.owner_user_id,
        created_at: "2026-09-25T12:00:00Z",
      };
      const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const path = pathOf(input);
        const method = init?.method ?? "GET";
        if (path.endsWith("/documents") && method === "GET") {
          return Promise.resolve(
            jsonResponse([latestPair.project, latestPair.agents, initialDocuments.backlog]),
          );
        }
        if (path.endsWith("/documents/project") && method === "GET") {
          return Promise.resolve(jsonResponse(latestPair.project));
        }
        if (path.includes("/history?") && method === "GET") {
          return Promise.resolve(
            jsonResponse({
              kind: "project",
              current_revision_number: latestPair.project.revision_number,
              revisions: [],
              proposals: [],
              revision_offset: 0,
              proposal_cursor: null,
              proposal_next_cursor: null,
              revision_has_more: false,
              proposal_has_more: false,
            }),
          );
        }
        if (path.includes("/document-pair-approval")) {
          if (method === "POST") {
            approvalPosts += 1;
            if (approvalPosts === 1) {
              latestPair = { project: projectTwo, agents: agentsTwo };
              return Promise.resolve(
                jsonResponse(
                  {
                    detail: "A saved document changed.",
                    latest: latestPair,
                    approval_status: makeApprovalStatus(projectTwo, agentsTwo),
                  },
                  409,
                ),
              );
            }
            approved = true;
            return Promise.resolve(jsonResponse(approval));
          }
          return Promise.resolve(
            jsonResponse({
              ...makeApprovalStatus(latestPair.project, latestPair.agents, approved),
              latest_approval: approved ? approval : null,
              approvals: approved ? [approval] : [],
            }),
          );
        }
        throw new Error(`Unexpected request: ${path} ${method}`);
      });
      renderWorkspace(fetchMock);

      fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
      await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
      const approveButton = await screen.findByRole("button", {
        name: "Approve saved PROJECT.md + AGENTS.md pair",
      });
      await waitFor(() => expect(approveButton).toBeEnabled());

      latestPair = { project: projectTwo, agents: agentsTwo };
      fireEvent.click(approveButton);
      const conflict = await screen.findByRole("region", {
        name: "Saved pair changed before approval",
      });
      expect(conflict).toHaveTextContent("PROJECT.md: revision 1 → revision 2");
      expect(
        within(conflict).getByRole("list", {
          name: /Previously reviewed PROJECT\.md revision 1 compared with Latest PROJECT\.md revision 2/,
        }),
      ).toBeInTheDocument();
      expect(approveButton).toBeDisabled();

      const switcher = screen.getByRole("combobox", { name: "Compare saved document" });
      fireEvent.change(switcher, { target: { value: "agents" } });
      fireEvent.change(switcher, { target: { value: "project" } });
      const reviewButton = screen.getByRole("button", {
        name: "I reviewed both latest documents",
      });
      await waitFor(() => expect(reviewButton).toBeEnabled());
      fireEvent.click(reviewButton);
      await waitFor(() => expect(approveButton).toBeEnabled());

      latestPair = { project: projectThree, agents: agentsTwo };
      if (advanceSource === "refresh") {
        fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
      } else {
        fireEvent.click(screen.getByRole("button", { name: "View history" }));
      }
      expect(await screen.findByText("PROJECT.md · revision 3")).toBeInTheDocument();
      expect(conflict).toHaveTextContent("PROJECT.md: revision 1 → revision 3");
      expect(
        within(conflict).getByRole("list", {
          name: /Previously reviewed PROJECT\.md revision 1 compared with Latest PROJECT\.md revision 3/,
        }),
      ).toBeInTheDocument();
      expect(reviewButton).toBeDisabled();
      expect(approveButton).toBeDisabled();

      fireEvent.change(switcher, { target: { value: "agents" } });
      fireEvent.change(switcher, { target: { value: "project" } });
      await waitFor(() => expect(reviewButton).toBeEnabled());
      fireEvent.click(reviewButton);
      await waitFor(() => expect(approveButton).toBeEnabled());
      fireEvent.click(approveButton);
      await waitFor(() => expect(approveButton).toBeDisabled());

      const posts = fetchMock.mock.calls.filter(
        ([request, options]) =>
          pathOf(request).includes("/document-pair-approval") && options?.method === "POST",
      );
      expect(posts).toHaveLength(2);
      expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual({
        expected_project_revision: 1,
        expected_agents_revision: 1,
      });
      expect(JSON.parse(String(posts[1]?.[1]?.body))).toEqual({
        expected_project_revision: 3,
        expected_agents_revision: 2,
      });
      expect(await screen.findByText(/Approved PROJECT\.md revision 3/)).toBeInTheDocument();
    },
  );

  it("ignores a delayed pair refresh from the previous project after switching workspaces", async () => {
    const pendingProjectARefresh = deferred<Response>();
    const projectAHead = makeDocument("project", "# First private project sentinel\n", 2);
    const projectBDocument = {
      ...makeDocument("project", "# Second private project only\n", 1),
      id: "00000000-0000-4000-8000-000000000099",
    };
    let projectADocumentRequests = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = pathOf(input);
      if (path.endsWith("/documents")) {
        if (path.includes(project.id)) {
          projectADocumentRequests += 1;
          return projectADocumentRequests === 1
            ? Promise.resolve(jsonResponse(Object.values(initialDocuments)))
            : pendingProjectARefresh.promise;
        }
        return Promise.resolve(
          jsonResponse([projectBDocument, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.includes("/document-pair-approval")) {
        const isProjectA = path.includes(project.id);
        return Promise.resolve(
          jsonResponse(
            makeApprovalStatus(
              isProjectA ? initialDocuments.project : projectBDocument,
              initialDocuments.agents,
            ),
          ),
        );
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock, { projects: [project, secondProject] });

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() => expect(projectADocumentRequests).toBe(2));

    fireEvent.click(screen.getByRole("button", { name: "Open project Second private plan" }));
    const secondEditor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    expect(secondEditor).toHaveValue(projectBDocument.content);
    pendingProjectARefresh.resolve(
      jsonResponse([projectAHead, initialDocuments.agents, initialDocuments.backlog]),
    );

    await waitFor(() => expect(secondEditor).toHaveValue(projectBDocument.content));
    expect(screen.getByText("PROJECT.md · revision 1")).toBeInTheDocument();
    expect(screen.queryByText("# First private project sentinel")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open project Second private plan" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("does not present a delayed successful approval as current after history advances a head", async () => {
    const pendingApproval = deferred<Response>();
    const pendingHistory = deferred<Response>();
    const newerProject = makeDocument("project", "# Saved while approval was in flight\n", 2);
    let currentProject = initialDocuments.project;
    let approvalRecorded = false;
    const savedApproval = {
      id: "approved-original-tuple",
      project_revision_id: "project-revision-1",
      project_revision_number: 1,
      agents_revision_id: "agents-revision-1",
      agents_revision_number: 1,
      actor_user_id: project.owner_user_id,
      created_at: "2026-09-25T12:00:00Z",
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(
          jsonResponse([currentProject, initialDocuments.agents, initialDocuments.backlog]),
        );
      }
      if (path.endsWith("/documents/project") && method === "GET") {
        return Promise.resolve(jsonResponse(newerProject));
      }
      if (path.includes("/documents/project/history?") && method === "GET") {
        return pendingHistory.promise;
      }
      if (path.includes("/document-pair-approval")) {
        if (method === "POST") return pendingApproval.promise;
        return Promise.resolve(
          jsonResponse({
            ...makeApprovalStatus(currentProject, initialDocuments.agents, false),
            latest_approval: approvalRecorded ? savedApproval : null,
            approvals: approvalRecorded ? [savedApproval] : [],
          }),
        );
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approveButton = await screen.findByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    await waitFor(() => expect(approveButton).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "View history" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([input]) =>
          pathOf(input).includes("/documents/project/history?"),
        ),
      ).toBe(true),
    );
    fireEvent.click(approveButton);

    currentProject = newerProject;
    pendingHistory.resolve(
      jsonResponse({
        kind: "project",
        current_revision_number: 2,
        revisions: [],
        proposals: [],
        revision_offset: 0,
        proposal_cursor: null,
        proposal_next_cursor: null,
        revision_has_more: false,
        proposal_has_more: false,
      }),
    );
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    expect(editor).toHaveValue(newerProject.content);

    approvalRecorded = true;
    pendingApproval.resolve(jsonResponse(savedApproval));
    const conflict = await screen.findByRole("region", {
      name: "Saved pair changed before approval",
    });
    expect(conflict).toHaveTextContent("PROJECT.md: revision 1 → revision 2");
    expect(
      within(conflict).getByRole("list", {
        name: /Previously reviewed PROJECT\.md revision 1 compared with Latest PROJECT\.md revision 2/,
      }),
    ).toBeInTheDocument();
    await waitFor(() => expect(approveButton).toBeDisabled());
    expect(await screen.findByText("Re-review required")).toBeInTheDocument();
    expect(editor).toHaveValue(newerProject.content);
  });

  it("preserves typing and focus on a stale approval and requires review of both latest files", async () => {
    const pendingApproval = deferred<Response>();
    let currentDocuments: Record<DocumentKind, TestDocument> = { ...initialDocuments };
    let status = makeApprovalStatus(currentDocuments.project, currentDocuments.agents);
    const latestPair = {
      project: makeDocument("project", "# Latest saved specification\nNew project boundary.\n", 2),
      agents: makeDocument("agents", "# Latest saved agent rules\nNew execution limits.\n", 2),
    };
    const stalePayload = {
      detail: "A saved document changed. Review the latest pair.",
      latest: latestPair,
      approval_status: makeApprovalStatus(latestPair.project, latestPair.agents),
    };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(jsonResponse(Object.values(currentDocuments)));
      }
      if (path.includes("/document-pair-approval")) {
        if (method === "POST") return pendingApproval.promise;
        return Promise.resolve(jsonResponse(status));
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approveButton = await screen.findByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    editor.focus();
    fireEvent.click(approveButton);
    await waitFor(() => expect(approveButton).toBeDisabled());
    fireEvent.change(editor, { target: { value: "# My unsaved edit remains here\n" } });
    expect(document.activeElement).toBe(editor);

    currentDocuments = {
      ...currentDocuments,
      project: latestPair.project,
      agents: latestPair.agents,
    };
    status = makeApprovalStatus(latestPair.project, latestPair.agents);
    pendingApproval.resolve(jsonResponse(stalePayload, 409));

    expect(
      await screen.findByRole("heading", { name: "Saved pair changed before approval" }),
    ).toBeInTheDocument();
    expect(editor).toHaveValue("# My unsaved edit remains here\n");
    expect(document.activeElement).toBe(editor);
    expect(await screen.findByText("PROJECT.md · revision 2")).toBeInTheDocument();
    const reviewButton = screen.getByRole("button", {
      name: "I reviewed both latest documents",
    });
    expect(reviewButton).toBeDisabled();

    const switcher = screen.getByRole("combobox", { name: "Compare saved document" });
    fireEvent.change(switcher, { target: { value: "agents" } });
    expect(reviewButton).toBeDisabled();
    expect(
      screen.getByRole("list", {
        name: /Latest AGENTS.md revision 2/,
      }),
    ).toHaveTextContent("Added line: # Latest saved agent rules");
    expect(reviewButton).toBeDisabled();
    fireEvent.change(switcher, { target: { value: "project" } });
    await waitFor(() => expect(reviewButton).toBeEnabled());
    fireEvent.click(reviewButton);
    expect(screen.getByText(/Current pair reviewed/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve saved PROJECT.md + AGENTS.md pair" }),
    ).toBeDisabled();
    expect(editor).toHaveValue("# My unsaved edit remains here\n");
  });

  it("requires reviewing both current heads after saving PROJECT following a stale AGENTS change", async () => {
    const projectHead = makeDocument("project", "# Current project\n", 2);
    const agentsHead = makeDocument("agents", "# Current agent rules\n", 2);
    const staleAgents = makeDocument("agents", "# New agent rules from another tab\n", 3);
    let currentDocuments: Record<DocumentKind, TestDocument> = {
      ...initialDocuments,
      project: projectHead,
      agents: agentsHead,
    };
    let latestPair = { project: projectHead, agents: agentsHead };
    let status = makeApprovalStatus(projectHead, agentsHead);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/documents") && method === "GET") {
        return Promise.resolve(jsonResponse(Object.values(currentDocuments)));
      }
      if (path.endsWith("/documents/project") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as { content: string };
        const saved = makeDocument(
          "project",
          payload.content,
          currentDocuments.project.revision_number + 1,
        );
        currentDocuments = { ...currentDocuments, project: saved };
        latestPair = { project: saved, agents: currentDocuments.agents };
        status = makeApprovalStatus(saved, currentDocuments.agents);
        return Promise.resolve(jsonResponse(saved));
      }
      if (path.includes("/document-pair-approval")) {
        if (method === "POST") {
          currentDocuments = { ...currentDocuments, agents: staleAgents };
          latestPair = { project: currentDocuments.project, agents: staleAgents };
          status = makeApprovalStatus(latestPair.project, latestPair.agents);
          return Promise.resolve(
            jsonResponse({ detail: "A saved document changed.", latest: latestPair }, 409),
          );
        }
        return Promise.resolve(jsonResponse(status));
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    renderWorkspace(fetchMock);

    fireEvent.click(screen.getByRole("button", { name: "Open project Twin tab plan" }));
    const editor = await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    const approveButton = await screen.findByRole("button", {
      name: "Approve saved PROJECT.md + AGENTS.md pair",
    });
    fireEvent.click(approveButton);
    expect(
      await screen.findByRole("heading", { name: "Saved pair changed before approval" }),
    ).toBeInTheDocument();

    fireEvent.change(editor, { target: { value: "# Project saved after agent change\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved PROJECT.md as revision 3.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("PROJECT.md · revision 3")).toBeInTheDocument());
    expect(approveButton).toBeDisabled();
    expect(screen.getByText(/Compare both latest documents/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "I reviewed both latest documents" })).toBeDisabled();

    const reloadButton = screen.getByRole("button", { name: "Reload saved pair and status" });
    await waitFor(() => expect(reloadButton).toBeEnabled());
    fireEvent.click(reloadButton);
    expect(
      await screen.findByRole("list", { name: /Latest PROJECT\.md revision 3/ }),
    ).toBeInTheDocument();
    const reviewButton = screen.getByRole("button", {
      name: "I reviewed both latest documents",
    });
    expect(reviewButton).toBeDisabled();

    const switcher = screen.getByRole("combobox", { name: "Compare saved document" });
    fireEvent.change(switcher, { target: { value: "agents" } });
    fireEvent.change(switcher, { target: { value: "project" } });
    await waitFor(() => expect(reviewButton).toBeEnabled());
    fireEvent.click(reviewButton);
    expect(screen.getByText(/Current pair reviewed/)).toBeInTheDocument();
    await waitFor(() => expect(approveButton).toBeEnabled());
  });

  it("keeps pair-conflict review after BACKLOG save/reload and resets if the tuple moves", async () => {
    const latestProject = makeDocument("project", "# Latest project\n", 2);
    const latestAgents = makeDocument("agents", "# Latest rules\n", 2);
    const newerAgents = makeDocument("agents", "# Newer rules\n", 3);
    let currentPair = { project: latestProject, agents: latestAgents };
    let documents = { ...initialDocuments };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.endsWith("/documents"))
        return Promise.resolve(jsonResponse(Object.values(documents)));
      if (path.endsWith("/documents/backlog") && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body)) as { content: string };
        documents = { ...documents, backlog: makeDocument("backlog", payload.content, 2) };
        return Promise.resolve(jsonResponse(documents.backlog));
      }
      if (path.endsWith("/backlog/tasks"))
        return Promise.resolve(
          jsonResponse({ detail: "The test backlog is intentionally invalid." }, 422),
        );
      if (path.includes("/document-pair-approval")) {
        if (init?.method === "POST")
          return Promise.resolve(jsonResponse({ detail: "Newer pair", latest: currentPair }, 409));
        return Promise.resolve(
          jsonResponse(makeApprovalStatus(documents.project, documents.agents)),
        );
      }
      throw new Error(`Unexpected request ${path}`);
    });
    renderWorkspace(fetchMock);
    fireEvent.click(screen.getByRole("button", { name: /Twin tab plan/ }));
    await screen.findByRole("textbox", { name: "Edit PROJECT.md" });
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve saved PROJECT.md + AGENTS.md pair" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Saved pair changed before approval" }),
    ).toBeInTheDocument();
    documents = { ...documents, ...currentPair };
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Approve saved PROJECT.md + AGENTS.md pair" }),
      ).toBeDisabled(),
    );
    expect(
      screen.getByRole("heading", { name: "Saved pair changed before approval" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Backlog" }));
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Edit BACKLOG.md" }), {
      target: { value: "# Separate backlog update\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Saved BACKLOG.md as revision 2.")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Saved pair changed before approval" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "I reviewed both latest documents" })).toBeDisabled();
    let reviewButton = screen.getByRole("button", { name: "I reviewed both latest documents" });
    expect(reviewButton).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Compare saved document" }), {
      target: { value: "agents" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: "Compare saved document" }), {
      target: { value: "project" },
    });
    fireEvent.click(reviewButton);
    expect(
      screen.getByRole("button", { name: "Approve saved PROJECT.md + AGENTS.md pair" }),
    ).toBeEnabled();

    currentPair = { project: latestProject, agents: newerAgents };
    documents = { ...documents, ...currentPair };
    fireEvent.click(screen.getByRole("button", { name: "Reload saved pair and status" }));
    await waitFor(() => expect(screen.getByText("Saved revision 3")).toBeInTheDocument());
    expect(
      screen.getByRole("button", { name: "Approve saved PROJECT.md + AGENTS.md pair" }),
    ).toBeDisabled();
    reviewButton = screen.getByRole("button", { name: "I reviewed both latest documents" });
    expect(reviewButton).toBeDisabled();
    expect(
      screen.getByRole("region", { name: "Saved pair changed before approval" }),
    ).toHaveTextContent("AGENTS.md: revision 1 → revision 3");
  });
});
