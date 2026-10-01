import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BacklogPlanning, { type BacklogTask, type BacklogTaskDocument } from "./BacklogPlanning";

const projectId = "00000000-0000-4000-8000-000000000114";
const markdown = [
  "# Project plan",
  "",
  "## [-] IMP-101 — Draft discovery",
  "",
  "**Depends on:** None",
  "",
  "Initial body.",
  "",
  "## [ ] IMP-102 — Ready prerequisite",
  "",
  "**Depends on:** IMP-101",
  "",
  "Prerequisite body.",
  "",
  "## [x] IMP-103 — Runner completed",
  "",
  "**Depends on:** None",
  "",
  "Runner-owned body.",
  "",
].join("\n");

function makeTask(
  id: string,
  status: BacklogTask["status"],
  title: string,
  dependencies: string[] = [],
  body = `\n**Depends on:** ${dependencies.length ? dependencies.join(", ") : "None"}\n\nTask scope.\n`,
): BacklogTask {
  const ready = status === " ";
  return {
    id,
    status,
    title,
    dependencies,
    body,
    acceptance: null,
    verification: null,
    ready,
    eligible: ready && dependencies.length === 0,
    waiting_on: ready && dependencies.length ? dependencies : [],
  };
}

const initialTasks = [
  makeTask("IMP-101", "-", "Draft discovery", [], "\n**Depends on:** None\n\nInitial body.\n\n"),
  makeTask(
    "IMP-102",
    " ",
    "Ready prerequisite",
    ["IMP-101"],
    "\n**Depends on:** IMP-101\n\nPrerequisite body.\n\n",
  ),
  makeTask(
    "IMP-103",
    "x",
    "Runner completed",
    [],
    "\n**Depends on:** None\n\nRunner-owned body.\n",
  ),
];

function makeSnapshot(
  revision: number,
  tasks: BacklogTask[] = initialTasks,
  content = markdown,
): BacklogTaskDocument {
  return {
    revision_number: revision,
    content_sha256: `sha256-rev-${revision}`,
    content,
    tasks,
    summary: {
      draft_count: tasks.filter((task) => task.status === "-").length,
      ready_count: tasks.filter((task) => task.status === " ").length,
      eligible_count: tasks.filter((task) => task.eligible).length,
      waiting_count: tasks.filter((task) => task.status === " " && !task.eligible).length,
    },
  };
}

const initialSnapshot = makeSnapshot(1);

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

function renderPlanner(
  fetchMock: ReturnType<typeof vi.fn>,
  options: {
    initial?: BacklogTaskDocument;
    onPendingChange?: (pending: boolean) => void;
    onSnapshotObserved?: (snapshot: BacklogTaskDocument) => void;
    onSessionExpired?: () => void;
  } = {},
) {
  const onPendingChange = options.onPendingChange ?? vi.fn();
  const onSnapshotObserved = options.onSnapshotObserved ?? vi.fn();
  const onSessionExpired = options.onSessionExpired ?? vi.fn();

  function Harness() {
    const [saved, setSaved] = useState(options.initial ?? initialSnapshot);
    const [panel, setPanel] = useState<"tasks" | "detail" | "markdown">("tasks");
    return (
      <>
        <BacklogPlanning
          canEditTasks
          csrfToken="csrf-backlog-test"
          instanceId="planner-test"
          markdownPanelId="backlog-markdown-panel"
          onPanelChange={setPanel}
          onPendingChange={onPendingChange}
          onSessionExpired={onSessionExpired}
          onSnapshotObserved={(snapshot) => {
            setSaved(snapshot);
            onSnapshotObserved(snapshot);
          }}
          panel={panel}
          projectId={projectId}
          revisionNumber={saved.revision_number}
          savedContent={saved.content}
          savedContentSha256={saved.content_sha256}
        />
        <div
          aria-label="Backlog Markdown editor"
          hidden={panel !== "markdown"}
          id="backlog-markdown-panel"
        >
          <label htmlFor="test-markdown">Markdown source</label>
          <textarea id="test-markdown" readOnly value={saved.content} />
        </div>
      </>
    );
  }

  vi.stubGlobal("fetch", fetchMock);
  const view = render(<Harness />);
  return { ...view, onPendingChange, onSnapshotObserved, onSessionExpired };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("human backlog planning", () => {
  it("loads a saved revision, changes only draft/ready on-row, and leaves runner outcomes read-only", async () => {
    let current = initialSnapshot;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET") {
        return Promise.resolve(jsonResponse(current));
      }
      if (path.endsWith("/backlog/tasks/IMP-101") && method === "PUT") {
        current = makeSnapshot(
          2,
          [
            makeTask("IMP-101", " ", "Draft discovery", [], initialTasks[0].body),
            ...initialTasks.slice(1),
          ],
          markdown.replace("## [-] IMP-101", "## [ ] IMP-101"),
        );
        return Promise.resolve(jsonResponse(current));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    const { onSnapshotObserved } = renderPlanner(fetchMock);

    const statusSummary = await screen.findByRole("region", { name: "Saved task status" });
    expect(statusSummary).toHaveTextContent("BACKLOG.md revision 1");
    expect(statusSummary).toHaveTextContent("Ready1");
    expect(
      await screen.findByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Runner-managed status · read-only")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Select task IMP-103: Runner completed" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("button", { name: "Mark IMP-103 draft" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mark IMP-101 ready" }));

    await waitFor(() => expect(current.revision_number).toBe(2));
    expect(onSnapshotObserved).toHaveBeenCalledWith(current);
    const call = fetchMock.mock.calls.find(
      ([input, init]) => pathOf(input).endsWith("/backlog/tasks/IMP-101") && init?.method === "PUT",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      expected_revision: 1,
      title: "Draft discovery",
      body: initialTasks[0].body,
      dependencies: [],
      status: " ",
    });
    expect(new Headers(call?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-backlog-test");
    expect(await screen.findByText("Saved IMP-101 to BACKLOG.md revision 2.")).toBeInTheDocument();
  });

  it("saves title, body, and dependencies with the expected revision and synchronizes Markdown and list", async () => {
    const nextContent = markdown
      .replace("Draft discovery", "Updated discovery")
      .replace("Initial body.", "Updated scope.")
      .replace("**Depends on:** None", "**Depends on:** IMP-103");
    const updatedTask = makeTask(
      "IMP-101",
      "-",
      "Updated discovery",
      ["IMP-103"],
      "\n**Depends on:** IMP-103\n\nUpdated scope.\n\n",
    );
    const updated = makeSnapshot(2, [updatedTask, ...initialTasks.slice(1)], nextContent);
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET")
        return Promise.resolve(jsonResponse(initialSnapshot));
      if (path.endsWith("/backlog/tasks/IMP-101") && method === "PUT")
        return Promise.resolve(jsonResponse(updated));
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    renderPlanner(fetchMock);

    fireEvent.click(
      await screen.findByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    );
    const title = screen.getByRole("textbox", { name: "Task title" });
    const dependencies = screen.getByRole("textbox", {
      name: "Dependencies · task IDs, comma-separated",
    });
    const body = screen.getByRole("textbox", { name: "Task body · Markdown" });
    fireEvent.change(title, { target: { value: "Updated discovery" } });
    fireEvent.change(dependencies, { target: { value: "IMP-103" } });
    fireEvent.change(body, { target: { value: "\n**Depends on:** None\n\nUpdated scope.\n\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));

    expect(await screen.findByText("Saved IMP-101 to BACKLOG.md revision 2.")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(
      ([input, init]) => pathOf(input).endsWith("/backlog/tasks/IMP-101") && init?.method === "PUT",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      expected_revision: 1,
      title: "Updated discovery",
      body: "\n**Depends on:** None\n\nUpdated scope.\n\n",
      dependencies: ["IMP-103"],
      status: "-",
    });
    expect(
      screen.getByRole("button", { name: "Select task IMP-101: Updated discovery" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByRole("textbox", { name: "Markdown source" })).toHaveValue(nextContent);
  });

  it.each([
    ["ordinary body replacement", "Replacement scope."],
    ["removing only the terminal newline", "Original scope."],
  ])("preserves a task boundary when saving after %s", async (_caseName, attemptedBody) => {
    const originalBody = "Original scope.\n";
    const attempted = attemptedBody;
    const expectedBody = `${attempted}\n`;
    const originalContent =
      "# Task plan\n\n" +
      "## [-] TASK-001 — Note-boundary task\n" +
      `${originalBody}## Reference notes\n` +
      "**Depends on:** None\n\n";
    const initial = makeSnapshot(
      1,
      [makeTask("TASK-001", "-", "Note-boundary task", [], originalBody)],
      originalContent,
    );
    const savedContent = originalContent.replace(originalBody, expectedBody);
    const saved = makeSnapshot(
      attemptedBody === "Original scope." ? 1 : 2,
      [makeTask("TASK-001", "-", "Note-boundary task", [], expectedBody)],
      savedContent,
    );
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET")
        return Promise.resolve(jsonResponse(initial));
      if (path.endsWith("/backlog/tasks/TASK-001") && method === "PUT") {
        const payload = JSON.parse(String(init?.body)) as {
          body: string;
          dependencies: string[];
        };
        const dependencyLines = payload.body.match(/^\s*(?:\*\*)?Depends on:/gm) ?? [];
        if (!payload.body.endsWith("\n") || dependencyLines.length !== 0) {
          return Promise.resolve(
            jsonResponse(
              { detail: "Task TASK-001 edit would merge a preserved level-two section." },
              422,
            ),
          );
        }
        return Promise.resolve(jsonResponse(saved));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    renderPlanner(fetchMock, { initial });

    fireEvent.click(
      await screen.findByRole("button", { name: "Select task TASK-001: Note-boundary task" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task body · Markdown" }), {
      target: { value: attempted },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));

    expect(
      await screen.findByText(`Saved TASK-001 to BACKLOG.md revision ${saved.revision_number}.`),
    ).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(
      ([input, init]) =>
        pathOf(input).endsWith("/backlog/tasks/TASK-001") && init?.method === "PUT",
    );
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      body: expectedBody,
      dependencies: [],
    });
    expect(saved.content.match(/^\*\*Depends on:/gm)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByRole("textbox", { name: "Markdown source" })).toHaveValue(savedContent);
  });

  it("rejects a cyclic dependency edit and leaves both the saved list and Markdown unchanged", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET")
        return Promise.resolve(jsonResponse(initialSnapshot));
      if (path.endsWith("/backlog/tasks/IMP-101") && method === "PUT")
        return Promise.resolve(
          jsonResponse({ detail: "Dependency cycle includes task IMP-101." }, 422),
        );
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    renderPlanner(fetchMock);

    fireEvent.click(
      await screen.findByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    );
    fireEvent.change(
      screen.getByRole("textbox", { name: "Dependencies · task IDs, comma-separated" }),
      { target: { value: "IMP-102" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Dependency cycle includes task IMP-101.",
    );
    expect(
      screen.getByRole("textbox", { name: "Dependencies · task IDs, comma-separated" }),
    ).toHaveValue("IMP-102");
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByRole("textbox", { name: "Markdown source" })).toHaveValue(markdown);
    const call = fetchMock.mock.calls.find(
      ([input, init]) => pathOf(input).endsWith("/backlog/tasks/IMP-101") && init?.method === "PUT",
    );
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      expected_revision: 1,
      dependencies: ["IMP-102"],
    });
  });

  it("preserves attempted task text on a stale revision and requires an explicit reviewed reapply", async () => {
    const latestTask = makeTask(
      "IMP-101",
      "-",
      "Saved in another tab",
      [],
      "\n**Depends on:** None\n\nOther tab scope.\n\n",
    );
    const latestContent = markdown
      .replace("Draft discovery", "Saved in another tab")
      .replace("Initial body.", "Other tab scope.");
    const latest = makeSnapshot(2, [latestTask, ...initialTasks.slice(1)], latestContent);
    const attemptedTitle = "My attempted title";
    const attemptedBody = "\n**Depends on:** None\n\nMy attempted body.\n\n";
    const savedContent = markdown
      .replace("Draft discovery", attemptedTitle)
      .replace("Initial body.", "My attempted body.");
    const saved = makeSnapshot(
      3,
      [makeTask("IMP-101", "-", attemptedTitle, [], attemptedBody), ...initialTasks.slice(1)],
      savedContent,
    );
    let putCount = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET")
        return Promise.resolve(jsonResponse(putCount === 0 ? initialSnapshot : latest));
      if (path.endsWith("/backlog/tasks/IMP-101") && method === "PUT") {
        putCount += 1;
        if (putCount === 1) {
          return Promise.resolve(
            jsonResponse(
              {
                detail: "Conflict recorded",
                latest: {
                  id: "backlog-document-id",
                  kind: "backlog",
                  revision_number: 2,
                  content: latest.content,
                  content_sha256: latest.content_sha256,
                },
              },
              409,
            ),
          );
        }
        return Promise.resolve(jsonResponse(saved));
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    renderPlanner(fetchMock);

    fireEvent.click(
      await screen.findByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task title" }), {
      target: { value: attemptedTitle },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Task body · Markdown" }), {
      target: { value: attemptedBody },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));

    expect(
      await screen.findByRole("heading", { name: "Backlog changed during this task edit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Task title" })).toHaveValue(attemptedTitle);
    expect(screen.getByRole("textbox", { name: "Task body · Markdown" })).toHaveValue(
      attemptedBody,
    );
    fireEvent.click(screen.getByText("Review latest saved IMP-101 before reapplying"));
    expect(screen.getAllByText("Saved in another tab").length).toBeGreaterThan(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Reapply attempted task edits to revision 2" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save re-applied task edits" }));

    expect(await screen.findByText("Saved IMP-101 to BACKLOG.md revision 3.")).toBeInTheDocument();
    const writes = fetchMock.mock.calls.filter(
      ([input, init]) => pathOf(input).endsWith("/backlog/tasks/IMP-101") && init?.method === "PUT",
    );
    expect(writes).toHaveLength(2);
    expect(JSON.parse(String(writes[0]?.[1]?.body))).toMatchObject({ expected_revision: 1 });
    expect(JSON.parse(String(writes[1]?.[1]?.body))).toMatchObject({
      expected_revision: 2,
      title: attemptedTitle,
      body: attemptedBody,
    });
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByRole("textbox", { name: "Markdown source" })).toHaveValue(savedContent);
  });

  it("keeps attempted text after server validation and requests session recovery on 401", async () => {
    let returnUnauthorized = false;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(input);
      const method = init?.method ?? "GET";
      if (path.endsWith("/backlog/tasks") && method === "GET")
        return Promise.resolve(jsonResponse(initialSnapshot));
      if (path.endsWith("/backlog/tasks/IMP-101") && method === "PUT") {
        return Promise.resolve(
          returnUnauthorized
            ? jsonResponse({ detail: "Authentication required" }, 401)
            : jsonResponse({ detail: "Task IDs cannot be repeated in the title." }, 422),
        );
      }
      throw new Error(`Unexpected request: ${path} ${method}`);
    });
    const { onSessionExpired } = renderPlanner(fetchMock);

    fireEvent.click(
      await screen.findByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Task title" }), {
      target: { value: "Invalid but preserved" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Task IDs cannot be repeated in the title.",
    );
    expect(screen.getByRole("textbox", { name: "Task title" })).toHaveValue(
      "Invalid but preserved",
    );

    returnUnauthorized = true;
    fireEvent.click(screen.getByRole("button", { name: "Save task changes" }));
    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("textbox", { name: "Task title" })).toHaveValue(
      "Invalid but preserved",
    );
    const writes = fetchMock.mock.calls.filter(
      ([input, init]) => pathOf(input).endsWith("/backlog/tasks/IMP-101") && init?.method === "PUT",
    );
    expect(writes).toHaveLength(2);
    expect(
      writes.every(([, init]) => Boolean(new Headers(init?.headers).get("X-CSRF-Token"))),
    ).toBe(true);
  });

  it("distinguishes task-load failure from an empty backlog and retries", async () => {
    let failFirstRead = true;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (pathOf(input).endsWith("/backlog/tasks") && (init?.method ?? "GET") === "GET") {
        if (failFirstRead) {
          failFirstRead = false;
          return Promise.resolve(
            jsonResponse({ detail: "Backlog parser rejected this draft." }, 422),
          );
        }
        return Promise.resolve(jsonResponse(makeSnapshot(2, [], "# Empty saved backlog\n")));
      }
      throw new Error(`Unexpected request: ${pathOf(input)}`);
    });
    renderPlanner(fetchMock);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Backlog parser rejected this draft.",
    );
    expect(screen.queryByText(/No tasks in this saved backlog/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading tasks" }));
    expect(await screen.findByText(/No tasks in this saved backlog/)).toBeInTheDocument();
  });

  it("supports keyboard view switching and labelled rail show/hide with focus restoration", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (pathOf(input).endsWith("/backlog/tasks"))
        return Promise.resolve(jsonResponse(initialSnapshot));
      throw new Error(`Unexpected request: ${pathOf(input)}`);
    });
    renderPlanner(fetchMock);

    const tasksView = await screen.findByRole("button", { name: "Tasks" });
    const detailView = screen.getByRole("button", { name: "Detail" });
    const markdownView = screen.getByRole("button", { name: "Markdown" });
    fireEvent.keyDown(tasksView, { key: "ArrowRight" });
    expect(detailView).toHaveAttribute("aria-pressed", "true");
    expect(document.activeElement).toBe(detailView);
    fireEvent.keyDown(detailView, { key: "ArrowRight" });
    expect(markdownView).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("textbox", { name: "Markdown source" })).toBeInTheDocument();

    fireEvent.click(tasksView);
    const hideButton = screen.getByRole("button", { name: "Hide task list" });
    fireEvent.click(hideButton);
    expect(hideButton).toHaveAttribute("aria-expanded", "false");
    const showButton = screen.getByRole("button", { name: "Show task list" });
    fireEvent.click(showButton);
    expect(showButton).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Select task IMP-101: Draft discovery" }),
    );
  });
});
