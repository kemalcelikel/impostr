import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      id: documents.project.id,
      revision_number: documents.project.revision_number,
      content_sha256: documents.project.content_sha256,
    },
    agents: {
      id: documents.agents.id,
      revision_number: documents.agents.revision_number,
      content_sha256: documents.agents.content_sha256,
    },
    backlog: {
      id: documents.backlog.id,
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
      id: documents.project.id,
      revision_number: documents.project.revision_number,
      content_sha256: documents.project.content_sha256,
    },
    current_agents_revision: {
      id: documents.agents.id,
      revision_number: documents.agents.revision_number,
      content_sha256: documents.agents.content_sha256,
    },
    current_backlog_revision: {
      id: documents.backlog.id,
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
    expect(approve).toBeEnabled();
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
    expect(screen.getByRole("button", { name: "Approved at last check" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toBeDisabled();

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
    expect(screen.getByText(/Local document or task changes are not part/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download PROJECT.md" })).toBeDisabled();
  });

  it("activates the pane that owns focus before a desktop-to-narrow resize hides other files", async () => {
    const saved = documentSet();
    const changeListener: { current: ((event: MediaQueryListEvent) => void) | null } = {
      current: null,
    };
    const mediaState = { matches: true };
    const media = {
      get matches() {
        return mediaState.matches;
      },
      addEventListener: vi.fn((_event: string, listener: EventListener) => {
        changeListener.current = listener as (event: MediaQueryListEvent) => void;
      }),
      removeEventListener: vi.fn(),
    } as unknown as MediaQueryList;
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => media),
    );
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/final-approval")) {
        return jsonResponse(approvalStatus(saved, false));
      }
      if (String(input).endsWith("/backlog/tasks")) return jsonResponse(tasks(saved));
      throw new Error(`Unexpected request ${String(input)}`);
    });
    renderReview(fetchMock, saved);

    const backlogContent = await screen.findByRole("region", {
      name: "BACKLOG.md saved revision 1 content",
    });
    backlogContent.scrollTop = 42;
    backlogContent.focus();
    expect(backlogContent).toHaveFocus();

    mediaState.matches = false;
    changeListener.current?.({ matches: false } as MediaQueryListEvent);

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "BACKLOG.md" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(backlogContent).toHaveFocus();
    });
    expect(backlogContent.scrollTop).toBe(42);
    expect(backlogContent.closest('[role="tabpanel"]')).not.toHaveClass("hidden");
  });
});
