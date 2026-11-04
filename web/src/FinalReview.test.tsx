import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import FinalReview, { type ReviewDocument, type ReviewDocumentKind } from "./FinalReview";

const projectId = "00000000-0000-4000-8000-000000000020";

function documentSet(backlogRevision = 1): Record<ReviewDocumentKind, ReviewDocument> {
  return {
    project: {
      id: "00000000-0000-4000-8000-000000000031",
      kind: "project",
      filename: "PROJECT.md",
      revision_number: 2,
      content: "# Project\nA long line that stays readable when wrapped.",
      content_sha256: "project-hash",
    },
    agents: {
      id: "00000000-0000-4000-8000-000000000032",
      kind: "agents",
      filename: "AGENTS.md",
      revision_number: 3,
      content: "# Agent rules\nKeep the project isolated.",
      content_sha256: "agents-hash",
    },
    backlog: {
      id: "00000000-0000-4000-8000-000000000033",
      kind: "backlog",
      filename: "BACKLOG.md",
      revision_number: backlogRevision,
      content: `## [ ] TEST-001 — ${"A".repeat(130)}\n**Depends on:** None\n`,
      content_sha256: `backlog-hash-${backlogRevision}`,
    },
  };
}

function manifest(documents: Record<ReviewDocumentKind, ReviewDocument>, id = "manifest-1") {
  return {
    id,
    pair_approval_id: "pair-approval-1",
    project: {
      id: `project-revision-${documents.project.revision_number}`,
      revision_number: documents.project.revision_number,
      content_sha256: documents.project.content_sha256,
    },
    agents: {
      id: `agents-revision-${documents.agents.revision_number}`,
      revision_number: documents.agents.revision_number,
      content_sha256: documents.agents.content_sha256,
    },
    backlog: {
      id: `backlog-revision-${documents.backlog.revision_number}`,
      revision_number: documents.backlog.revision_number,
      content_sha256: documents.backlog.content_sha256,
    },
  };
}

function approvalStatus(
  documents: Record<ReviewDocumentKind, ReviewDocument>,
  approved: boolean,
  latestManifest: ReturnType<typeof manifest> | null = null,
) {
  const currentManifest = approved
    ? manifest(documents, `manifest-${documents.backlog.revision_number}`)
    : null;
  return {
    current_project_revision: {
      id: `project-revision-${documents.project.revision_number}`,
      revision_number: documents.project.revision_number,
      content_sha256: documents.project.content_sha256,
    },
    current_agents_revision: {
      id: `agents-revision-${documents.agents.revision_number}`,
      revision_number: documents.agents.revision_number,
      content_sha256: documents.agents.content_sha256,
    },
    current_backlog_revision: {
      id: `backlog-revision-${documents.backlog.revision_number}`,
      revision_number: documents.backlog.revision_number,
      content_sha256: documents.backlog.content_sha256,
    },
    current_pair_approval_id: "pair-approval-1",
    pair_approved: true,
    approved,
    current_manifest: currentManifest,
    latest_manifest: currentManifest ?? latestManifest,
    validation_errors: {},
  };
}

function tasks(documents: Record<ReviewDocumentKind, ReviewDocument>) {
  return {
    revision_number: documents.backlog.revision_number,
    content_sha256: documents.backlog.content_sha256,
    summary: { draft_count: 1, ready_count: 2, eligible_count: 1, waiting_count: 1 },
  };
}

function jsonResponse(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function renderReview(
  fetchMock: ReturnType<typeof vi.fn>,
  documents: Record<ReviewDocumentKind, ReviewDocument>,
  onReviewDocument = vi.fn(),
) {
  vi.stubGlobal("fetch", fetchMock);
  return render(
    <FinalReview
      csrfToken={["csrf", "test-token"].join("-")}
      documents={documents}
      documentsLoading={false}
      localChangesPending={false}
      onReviewDocument={onReviewDocument}
      onReviewPair={vi.fn()}
      onSessionExpired={vi.fn()}
      projectId={projectId}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("three-file final review", () => {
  it("owns the shared page heading and focus target when integrated into the shell", async () => {
    const saved = documentSet();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/final-approval"))
        return jsonResponse(approvalStatus(saved, false));
      if (String(input).endsWith("/backlog/tasks")) return jsonResponse(tasks(saved));
      throw new Error(`Unexpected request ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <FinalReview
        projectId={projectId}
        documents={saved}
        csrfToken="csrf-test-token"
        localChangesPending={false}
        documentsLoading={false}
        pageTitleId="app-page-title"
        focusHeadingOnMount
        onSessionExpired={vi.fn()}
        onReviewDocument={vi.fn()}
        onReviewPair={vi.fn()}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Review & downloads", level: 1 });
    expect(heading).toHaveAttribute("id", "app-page-title");
    expect(heading).toHaveFocus();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(document.querySelectorAll("#app-page-title")).toHaveLength(1);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Approve displayed three-file snapshot" }),
      ).toBeEnabled(),
    );
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toBeDisabled();
  });

  it("approves the displayed tuple, invalidates it after a saved edit, and downloads the current file", async () => {
    let saved = documentSet();
    let currentStatus = approvalStatus(saved, false);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      if (path === `/api/projects/${projectId}/final-approval` && method === "GET") {
        return jsonResponse(currentStatus);
      }
      if (path === `/api/projects/${projectId}/backlog/tasks` && method === "GET") {
        return jsonResponse(tasks(saved));
      }
      if (path === `/api/projects/${projectId}/final-approval` && method === "POST") {
        expect(new Headers(init?.headers).get("X-CSRF-Token")).toBe("csrf-test-token");
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        expect(body).toEqual({
          expected_pair_approval_id: "pair-approval-1",
          expected_backlog_revision: saved.backlog.revision_number,
        });
        const result = manifest(saved, `manifest-${saved.backlog.revision_number}`);
        currentStatus = approvalStatus(saved, true);
        return jsonResponse(result);
      }
      if (path === `/api/projects/${projectId}/final-approval/files/backlog`) {
        return {
          ok: true,
          status: 200,
          blob: async () => new Blob([saved.backlog.content], { type: "text/markdown" }),
        } as Response;
      }
      throw new Error(`Unexpected request ${path} ${method}`);
    });
    const createObjectUrl = vi.fn(() => "blob:review-download");
    const originalCreateObjectUrl = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const originalRevokeObjectUrl = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrl });
    const downloads: { href: string; filename: string }[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push({ href: this.href, filename: this.download });
    });
    const onReviewDocument = vi.fn();

    const view = renderReview(fetchMock, saved, onReviewDocument);
    const approve = await screen.findByRole("button", {
      name: "Approve displayed three-file snapshot",
    });
    await waitFor(() => expect(approve).toBeEnabled());
    const inspection = screen.getByRole("region", { name: "Saved files" });
    const approval = screen.getByRole("region", { name: "Approval and downloads" });
    const content = within(inspection).getByRole("region", {
      name: "PROJECT.md saved revision 2 content",
    });
    const tabs = within(inspection).getByRole("tablist", { name: "Saved file navigation" });
    const filePanel = content.closest(".review-document-panel");
    expect(filePanel).toContainElement(tabs);
    expect(tabs).toHaveClass("workbench-tab-strip");
    expect(within(tabs).getByRole("tab", { name: "PROJECT.md" })).toHaveTextContent("PROJECT.md");
    expect(content).toHaveClass("review-saved-content");
    expect(inspection.closest(".review-grid")).toBe(approval.closest(".review-grid"));
    expect(
      within(approval).getByRole("heading", { name: "Approval & downloads" }),
    ).toBeInTheDocument();
    expect(approval).toContainElement(approve);
    expect(approve).toHaveAccessibleDescription(/saved pair is approved/);
    const details = screen.getByText("Validation and revision details").closest("details")!;
    expect(approval).toContainElement(details);
    expect(details).not.toHaveAttribute("open");
    expect(within(approval).getByRole("region", { name: "Task readiness" })).toBeInTheDocument();
    expect(screen.getByTestId("review-next-action")).toHaveTextContent(
      "Review all three files, then approve this saved snapshot",
    );
    expect(screen.getByText("Owner-ready tasks")).toBeInTheDocument();
    expect(screen.getByText("Dependency-eligible")).toBeInTheDocument();
    expect(screen.getByTestId("pair-approval-state")).toHaveTextContent(
      "Approved for the displayed",
    );

    const projectTab = screen.getByRole("tab", { name: "PROJECT.md" });
    projectTab.focus();
    fireEvent.keyDown(projectTab, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "AGENTS.md" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("tab", { name: "AGENTS.md" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "BACKLOG.md" })).toHaveFocus();
    expect(
      screen.getByRole("region", { name: "BACKLOG.md saved revision 1 content" }).textContent,
    ).toBe(saved.backlog.content);

    approve.focus();
    fireEvent.click(approve);
    await waitFor(() =>
      expect(screen.getByTestId("final-approval-state")).toHaveTextContent(
        "Approved for the displayed three-file tuple",
      ),
    );
    expect(screen.getByTestId("final-approval-state")).toHaveFocus();
    expect(screen.getByRole("button", { name: "Download BACKLOG.md" })).toBeEnabled();

    const oldManifest = manifest(saved);
    saved = documentSet(2);
    currentStatus = approvalStatus(saved, false, oldManifest);
    view.rerender(
      <FinalReview
        csrfToken={["csrf", "test-token"].join("-")}
        documents={saved}
        documentsLoading={false}
        localChangesPending={false}
        onReviewDocument={onReviewDocument}
        onReviewPair={vi.fn()}
        onSessionExpired={vi.fn()}
        projectId={projectId}
      />,
    );
    await waitFor(() =>
      expect(screen.getByTestId("final-approval-state")).toHaveTextContent("Re-review required"),
    );
    expect(screen.getByRole("button", { name: "Download BACKLOG.md" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Review BACKLOG.md" }));
    expect(onReviewDocument).toHaveBeenCalledWith("backlog");

    fireEvent.click(
      await screen.findByRole("button", { name: "Approve displayed three-file snapshot" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("final-approval-state")).toHaveTextContent(
        "Approved for the displayed three-file tuple",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Download BACKLOG.md" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/projects/${projectId}/final-approval/files/backlog`,
        { cache: "no-store", credentials: "same-origin" },
      );
      expect(createObjectUrl).toHaveBeenCalledOnce();
      expect(click).toHaveBeenCalledOnce();
    });

    expect(downloads).toEqual([{ href: "blob:review-download", filename: "BACKLOG.md" }]);
    await waitFor(() => expect(revokeObjectUrl).toHaveBeenCalledWith("blob:review-download"));
    click.mockRestore();
    if (originalCreateObjectUrl) {
      Object.defineProperty(URL, "createObjectURL", originalCreateObjectUrl);
    } else {
      Reflect.deleteProperty(URL, "createObjectURL");
    }
    if (originalRevokeObjectUrl) {
      Object.defineProperty(URL, "revokeObjectURL", originalRevokeObjectUrl);
    } else {
      Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });

  it("keeps approval and downloads disabled for unknown, stale, or locally dirty state", async () => {
    const saved = documentSet();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/final-approval")) {
        return jsonResponse(approvalStatus(saved, true));
      }
      if (String(input).endsWith("/backlog/tasks")) {
        return jsonResponse({ ...tasks(saved), revision_number: 99 });
      }
      throw new Error(`Unexpected request ${String(input)}`);
    });
    const view = renderReview(fetchMock, saved);
    await screen.findByText(
      "Backlog readiness belongs to another saved revision. Refresh before continuing.",
    );
    expect(
      screen.getByRole("button", { name: "Approve displayed three-file snapshot" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toBeDisabled();
    expect(screen.getByTestId("final-approval-state")).toHaveTextContent("Unknown or stale");
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toHaveAccessibleDescription(
      /do not match this snapshot/,
    );

    view.rerender(
      <FinalReview
        csrfToken={["csrf", "test-token"].join("-")}
        documents={saved}
        documentsLoading={false}
        localChangesPending
        onReviewDocument={vi.fn()}
        onReviewPair={vi.fn()}
        onSessionExpired={vi.fn()}
        projectId={projectId}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Approve displayed three-file snapshot" }),
    ).toHaveAccessibleDescription(/Save or discard local document and task changes/);
    expect(screen.getByTestId("final-approval-state")).toHaveTextContent("Resolve local changes");
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toBeDisabled();
  });

  it("keeps every file reachable by roving tabs and preserves the mounted active file on resize", async () => {
    const saved = documentSet();
    vi.stubGlobal("innerWidth", 1440);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/final-approval")) {
        return jsonResponse(approvalStatus(saved, false));
      }
      if (String(input).endsWith("/backlog/tasks")) return jsonResponse(tasks(saved));
      throw new Error(`Unexpected request ${String(input)}`);
    });
    renderReview(fetchMock, saved);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Approve displayed three-file snapshot" }),
      ).toBeEnabled(),
    );
    const projectTab = screen.getByRole("tab", { name: "PROJECT.md" });
    const agentsTab = screen.getByRole("tab", { name: "AGENTS.md" });
    const backlogTab = screen.getByRole("tab", { name: "BACKLOG.md" });
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(
      screen.getByRole("region", { name: "PROJECT.md saved revision 2 content" }).textContent,
    ).toBe(saved.project.content);
    projectTab.focus();
    fireEvent.keyDown(projectTab, { key: "ArrowRight" });
    expect(agentsTab).toHaveFocus();
    expect(agentsTab).toHaveAttribute("tabindex", "0");
    expect(projectTab).toHaveAttribute("tabindex", "-1");
    expect(
      screen.getByRole("region", { name: "AGENTS.md saved revision 3 content" }).textContent,
    ).toBe(saved.agents.content);
    fireEvent.keyDown(agentsTab, { key: "End" });
    expect(backlogTab).toHaveFocus();
    const backlogContent = await screen.findByRole("region", {
      name: "BACKLOG.md saved revision 1 content",
    });
    expect(backlogContent.textContent).toBe(saved.backlog.content);
    expect(screen.getByRole("tabpanel", { name: "BACKLOG.md" })).toHaveAttribute(
      "id",
      backlogTab.getAttribute("aria-controls"),
    );
    backlogContent.scrollTop = 42;
    backlogContent.focus();
    expect(backlogContent).toHaveFocus();

    vi.stubGlobal("innerWidth", 390);
    fireEvent(window, new Event("resize"));

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "BACKLOG.md" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(backlogContent).toHaveFocus();
    });
    expect(backlogContent.scrollTop).toBe(42);
    expect(backlogContent.closest('[role="tabpanel"]')).not.toHaveAttribute("hidden");
    backlogTab.focus();
    fireEvent.keyDown(backlogTab, { key: "ArrowRight" });
    expect(projectTab).toHaveFocus();
    expect(backlogContent.closest('[role="tabpanel"]')).toHaveAttribute("hidden");
    fireEvent.keyDown(projectTab, { key: "ArrowLeft" });
    expect(backlogTab).toHaveFocus();
    expect(screen.getByRole("region", { name: "BACKLOG.md saved revision 1 content" })).toBe(
      backlogContent,
    );
    expect(backlogContent.scrollTop).toBe(42);
    fireEvent.keyDown(backlogTab, { key: "Home" });
    expect(projectTab).toHaveFocus();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
  });

  it("explains missing pair approval without treating owner-ready tasks as approval", async () => {
    const saved = documentSet();
    const onReviewPair = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/backlog/tasks")
        ? jsonResponse(tasks(saved))
        : jsonResponse({
            ...approvalStatus(saved, false),
            pair_approved: false,
            current_pair_approval_id: null,
          }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <FinalReview
        csrfToken="csrf-test-token"
        documents={saved}
        documentsLoading={false}
        localChangesPending={false}
        onReviewDocument={vi.fn()}
        onReviewPair={onReviewPair}
        onSessionExpired={vi.fn()}
        projectId={projectId}
      />,
    );
    const approve = screen.getByRole("button", { name: "Approve displayed three-file snapshot" });
    await waitFor(() =>
      expect(approve).toHaveAccessibleDescription(
        /Approve the saved PROJECT.md \+ AGENTS.md pair first/,
      ),
    );
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("pair-approval-state")).toHaveTextContent("Pair approval needed");
    expect(screen.getByTestId("final-approval-state")).toHaveTextContent("Not yet approved");
    const readyLabel = screen.getByText("Owner-ready tasks");
    expect(readyLabel.parentElement).toHaveTextContent("2");
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toHaveAccessibleDescription(
      /require final approval/,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Review and approve PROJECT.md + AGENTS.md" }),
    );
    expect(onReviewPair).toHaveBeenCalledOnce();
    fireEvent.click(approve);
    fireEvent.click(screen.getByRole("button", { name: "Download PROJECT.md" }));
    expect(fetchMock.mock.calls.every((call) => !String(call[0]).includes("/files/"))).toBe(true);
  });

  it("shows file-specific validation reasons near approval and keeps full details and distinct IDs expandable", async () => {
    const saved = documentSet();
    saved.project = {
      ...saved.project,
      origin: "template",
      template_source: "PROJECT.md.example",
      template_sha256: "starter-project-hash",
    };
    const messages = [
      "Decide the required project boundary.",
      "Replace unresolved starter decisions.",
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/backlog/tasks")
        ? jsonResponse(tasks(saved))
        : jsonResponse({
            ...approvalStatus(saved, false),
            validation_errors: { "PROJECT.md": messages },
          }),
    );
    const onReviewDocument = vi.fn();
    renderReview(fetchMock, saved, onReviewDocument);
    const approve = screen.getByRole("button", { name: "Approve displayed three-file snapshot" });
    await waitFor(() =>
      expect(approve).toHaveAccessibleDescription(
        /PROJECT.md: Decide the required project boundary/,
      ),
    );
    expect(approve).toBeDisabled();
    expect(screen.getByTestId("review-next-action")).toHaveTextContent(
      "Resolve saved file validation",
    );
    const summary = screen.getByText("Validation and revision details");
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(summary.closest("summary")!);
    // Make the native disclosure state explicit in this jsdom fixture.
    details.open = true;
    const validation = screen.getByRole("region", { name: "Review validation details" });
    for (const message of messages)
      expect(within(validation).getByText(message)).toBeInTheDocument();
    fireEvent.click(within(validation).getByRole("button", { name: "Review PROJECT.md" }));
    expect(onReviewDocument).toHaveBeenCalledWith("project");
    const identities = screen.getByRole("region", {
      name: "Saved revision identities and provenance",
    });
    const documentId = within(identities).getByText(saved.project.id);
    expect(documentId.closest("div")).toHaveTextContent("Document ID");
    expect(within(identities).getByText("project-revision-2").closest("div")).toHaveTextContent(
      "Revision ID",
    );
    expect(within(identities).getByText("PROJECT.md.example")).toBeInTheDocument();
    expect(within(identities).getByText("starter-project-hash")).toBeInTheDocument();
  });

  it.each([401, 409])(
    "handles a %s approval failure without exporting or losing review navigation",
    async (failureStatus) => {
      const saved = documentSet();
      const onSessionExpired = vi.fn();
      const onRefreshDocuments = vi.fn();
      let status = approvalStatus(saved, false);
      const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === "POST") {
          status = {
            ...status,
            current_backlog_revision: { ...status.current_backlog_revision, revision_number: 99 },
          };
          return jsonResponse(
            { detail: "Saved revisions changed or access expired." },
            failureStatus,
          );
        }
        return String(input).endsWith("/backlog/tasks")
          ? jsonResponse(tasks(saved))
          : jsonResponse(status);
      });
      vi.stubGlobal("fetch", fetchMock);
      render(
        <FinalReview
          csrfToken="csrf-test-token"
          documents={saved}
          documentsLoading={false}
          localChangesPending={false}
          onReviewDocument={vi.fn()}
          onReviewPair={vi.fn()}
          onSessionExpired={onSessionExpired}
          onRefreshDocuments={onRefreshDocuments}
          projectId={projectId}
        />,
      );
      const approve = screen.getByRole("button", { name: "Approve displayed three-file snapshot" });
      await waitFor(() => expect(approve).toBeEnabled());
      fireEvent.click(approve);
      if (failureStatus === 401) {
        await waitFor(() => expect(onSessionExpired).toHaveBeenCalledOnce());
      } else {
        expect(await screen.findByRole("alert")).toHaveTextContent(
          "Saved revisions changed before approval",
        );
        await waitFor(() => expect(onRefreshDocuments).toHaveBeenCalledOnce());
        expect(approve).toBeDisabled();
      }
      for (const filename of ["PROJECT.md", "AGENTS.md", "BACKLOG.md"]) {
        expect(screen.getByRole("button", { name: `Download ${filename}` })).toBeDisabled();
      }
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/files/"))).toBe(false);
    },
  );

  it.each([401, 409])(
    "does not create a file from a %s download response",
    async (failureStatus) => {
      const saved = documentSet();
      const onSessionExpired = vi.fn();
      const onRefreshDocuments = vi.fn();
      const deniedBlob = vi.fn();
      let status = approvalStatus(saved, true);
      const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes("/files/")) {
          status = approvalStatus(saved, false, manifest(saved));
          return { ok: false, status: failureStatus, blob: deniedBlob } as unknown as Response;
        }
        return path.endsWith("/backlog/tasks") ? jsonResponse(tasks(saved)) : jsonResponse(status);
      });
      vi.stubGlobal("fetch", fetchMock);
      render(
        <FinalReview
          csrfToken="csrf-test-token"
          documents={saved}
          documentsLoading={false}
          localChangesPending={false}
          onReviewDocument={vi.fn()}
          onReviewPair={vi.fn()}
          onSessionExpired={onSessionExpired}
          onRefreshDocuments={onRefreshDocuments}
          projectId={projectId}
        />,
      );
      const download = screen.getByRole("button", { name: "Download AGENTS.md" });
      await waitFor(() => expect(download).toBeEnabled());
      fireEvent.click(download);
      if (failureStatus === 401) {
        await waitFor(() => expect(onSessionExpired).toHaveBeenCalledOnce());
      } else {
        expect(await screen.findByRole("alert")).toHaveTextContent(
          "approved saved revisions are no longer current",
        );
        await waitFor(() => expect(onRefreshDocuments).toHaveBeenCalledOnce());
        expect(download).toBeDisabled();
        expect(screen.getByTestId("final-approval-state")).toHaveTextContent("Re-review required");
      }
      expect(deniedBlob).not.toHaveBeenCalled();
    },
  );

  it("downloads all three exact UTF-8 responses independently, regardless of the active tab", async () => {
    const saved = documentSet();
    saved.project.content = "# Project\r\nRésumé — preserve bytes.\r\n";
    saved.agents.content = "# Rules\n安全\n";
    const blobs: Blob[] = [];
    const createObjectUrl = vi.fn((blob: Blob) => {
      blobs.push(blob);
      return "blob:approved-file";
    });
    const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    const revokeObjectUrl = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrl });
    const downloads: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloads.push(this.download);
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/backlog/tasks")) return jsonResponse(tasks(saved));
      const kind = path.split("/files/")[1] as ReviewDocumentKind | undefined;
      if (kind)
        return {
          ok: true,
          status: 200,
          blob: async () =>
            new Blob([saved[kind].content], { type: "text/markdown;charset=utf-8" }),
        } as Response;
      return jsonResponse(approvalStatus(saved, true));
    });
    try {
      renderReview(fetchMock, saved);
      for (const kind of ["project", "agents", "backlog"] as const) {
        const download = screen.getByRole("button", { name: `Download ${saved[kind].filename}` });
        await waitFor(() => expect(download).toBeEnabled());
        fireEvent.click(download);
        await waitFor(() => expect(download).toBeEnabled());
        const blob = blobs.at(-1)!;
        const bytes = await new Promise<ArrayBuffer>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result as ArrayBuffer);
          reader.onerror = () => reject(reader.error);
          reader.readAsArrayBuffer(blob);
        });
        expect(Array.from(new Uint8Array(bytes))).toEqual(
          Array.from(new TextEncoder().encode(saved[kind].content)),
        );
        expect(fetchMock).toHaveBeenCalledWith(
          `/api/projects/${projectId}/final-approval/files/${kind}`,
          { cache: "no-store", credentials: "same-origin" },
        );
      }
      expect(downloads).toEqual(["PROJECT.md", "AGENTS.md", "BACKLOG.md"]);
      await waitFor(() => expect(revokeObjectUrl).toHaveBeenCalledTimes(3));
      expect(screen.getByRole("tab", { name: "PROJECT.md" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    } finally {
      click.mockRestore();
      if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });
});
