import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, apiRequest } from "./api";
import type { BacklogTaskDocument } from "./BacklogPlanning";

export type ReviewDocumentKind = "project" | "agents" | "backlog";

export type ReviewDocument = {
  id: string;
  kind: ReviewDocumentKind;
  filename: string;
  revision_number: number;
  content: string;
  content_sha256: string;
};

type RevisionReference = {
  id: string;
  revision_number: number;
  content_sha256: string;
};

type ManifestReference = {
  id: string;
  pair_approval_id: string;
  project: RevisionReference;
  agents: RevisionReference;
  backlog: RevisionReference;
};

type FinalApprovalStatus = {
  current_project_revision: RevisionReference;
  current_agents_revision: RevisionReference;
  current_backlog_revision: RevisionReference;
  current_pair_approval_id: string | null;
  pair_approved: boolean;
  approved: boolean;
  current_manifest: ManifestReference | null;
  latest_manifest: ManifestReference | null;
  validation_errors: Record<string, string[]>;
};

type ReviewProps = {
  projectId: string;
  documents: Record<ReviewDocumentKind, ReviewDocument>;
  csrfToken: string;
  localChangesPending: boolean;
  documentsLoading: boolean;
  focusHeadingOnMount?: boolean;
  onSessionExpired: () => void;
  onReviewDocument: (kind: ReviewDocumentKind) => void;
  onReviewPair: () => void;
  onRefreshDocuments?: () => void;
};

const documentOptions: { kind: ReviewDocumentKind; filename: string; label: string }[] = [
  { kind: "project", filename: "PROJECT.md", label: "Project" },
  { kind: "agents", filename: "AGENTS.md", label: "Agent rules" },
  { kind: "backlog", filename: "BACKLOG.md", label: "Backlog" },
];

function finalApprovalPath(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/final-approval`;
}

function sameRevision(reference: RevisionReference | null | undefined, document: ReviewDocument) {
  return Boolean(
    reference &&
    reference.revision_number === document.revision_number &&
    reference.content_sha256 === document.content_sha256,
  );
}

function statusMatchesDocuments(
  status: FinalApprovalStatus,
  documents: Record<ReviewDocumentKind, ReviewDocument>,
): boolean {
  return (
    sameRevision(status.current_project_revision, documents.project) &&
    sameRevision(status.current_agents_revision, documents.agents) &&
    sameRevision(status.current_backlog_revision, documents.backlog)
  );
}

function manifestMatchesDocuments(
  manifest: ManifestReference | null,
  documents: Record<ReviewDocumentKind, ReviewDocument>,
  pairApprovalId: string | null,
): boolean {
  return Boolean(
    manifest &&
    manifest.pair_approval_id === pairApprovalId &&
    sameRevision(manifest.project, documents.project) &&
    sameRevision(manifest.agents, documents.agents) &&
    sameRevision(manifest.backlog, documents.backlog),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isRevisionReference(value: unknown): value is RevisionReference {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.revision_number === "number" &&
    Number.isSafeInteger(value.revision_number) &&
    value.revision_number > 0 &&
    typeof value.content_sha256 === "string"
  );
}

function isManifestReference(value: unknown): value is ManifestReference | null {
  if (value === null) return true;
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.pair_approval_id === "string" &&
    isRevisionReference(value.project) &&
    isRevisionReference(value.agents) &&
    isRevisionReference(value.backlog)
  );
}

function parseFinalApprovalStatus(value: unknown): FinalApprovalStatus {
  if (
    !isRecord(value) ||
    !isRevisionReference(value.current_project_revision) ||
    !isRevisionReference(value.current_agents_revision) ||
    !isRevisionReference(value.current_backlog_revision) ||
    (value.current_pair_approval_id !== null &&
      typeof value.current_pair_approval_id !== "string") ||
    typeof value.pair_approved !== "boolean" ||
    typeof value.approved !== "boolean" ||
    !isManifestReference(value.current_manifest) ||
    !isManifestReference(value.latest_manifest) ||
    !isRecord(value.validation_errors) ||
    !Object.values(value.validation_errors).every(
      (messages) =>
        Array.isArray(messages) && messages.every((message) => typeof message === "string"),
    )
  ) {
    throw new Error("The final approval status is incomplete. Refresh it before continuing.");
  }
  return value as unknown as FinalApprovalStatus;
}

function isTaskDocument(value: unknown): value is BacklogTaskDocument {
  if (
    !isRecord(value) ||
    typeof value.revision_number !== "number" ||
    !Number.isSafeInteger(value.revision_number) ||
    typeof value.content_sha256 !== "string"
  ) {
    return false;
  }
  const summary = value.summary;
  if (!isRecord(summary)) return false;
  return ["draft_count", "ready_count", "eligible_count", "waiting_count"].every(
    (key) =>
      typeof summary[key] === "number" &&
      Number.isSafeInteger(summary[key]) &&
      (summary[key] as number) >= 0,
  );
}

function errorDetail(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  return fallback;
}

async function responseFailureMessage(response: Response): Promise<string> {
  try {
    return errorDetail(await response.json(), "The approved file could not be downloaded.");
  } catch {
    return "The approved file could not be downloaded.";
  }
}

function friendlyError(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

export default function FinalReview({
  projectId,
  documents,
  csrfToken,
  localChangesPending,
  documentsLoading,
  focusHeadingOnMount = false,
  onSessionExpired,
  onReviewDocument,
  onReviewPair,
  onRefreshDocuments = () => {},
}: ReviewProps) {
  const instanceId = `final-review-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [selectedKind, setSelectedKind] = useState<ReviewDocumentKind>("project");
  const [status, setStatus] = useState<FinalApprovalStatus | null>(null);
  const [taskDocument, setTaskDocument] = useState<BacklogTaskDocument | null>(null);
  const [statusBusy, setStatusBusy] = useState(false);
  const [statusError, setStatusError] = useState("");
  const [actionBusy, setActionBusy] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const restoreApprovalFocus = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const approvalButtonRef = useRef<HTMLButtonElement>(null);
  const finalApprovalStatusRef = useRef<HTMLSpanElement>(null);
  const requestNumber = useRef(0);
  const selectedKindRef = useRef<ReviewDocumentKind>("project");
  const focusedPaneKind = useRef<ReviewDocumentKind | null>(null);
  const focusedPaneElement = useRef<HTMLElement | null>(null);
  const focusedTabElement = useRef<HTMLElement | null>(null);
  const tabNavigationHasFocus = useRef(false);
  const viewportIsWide = useRef(
    typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(min-width: 1280px)").matches,
  );
  const responsiveFocus = useRef<{
    kind: ReviewDocumentKind;
    target: "last-focused" | "content";
  } | null>(null);
  const contentRegionRefs = useRef<Record<ReviewDocumentKind, HTMLPreElement | null>>({
    project: null,
    agents: null,
    backlog: null,
  });

  const headsMatch = status ? statusMatchesDocuments(status, documents) : false;
  const taskSnapshotMatches = Boolean(
    taskDocument &&
    taskDocument.revision_number === documents.backlog.revision_number &&
    taskDocument.content_sha256 === documents.backlog.content_sha256,
  );
  const currentManifestMatches = Boolean(
    status &&
    headsMatch &&
    status.approved &&
    manifestMatchesDocuments(status.current_manifest, documents, status.current_pair_approval_id),
  );
  const reviewSnapshotKnown = Boolean(
    status && headsMatch && taskSnapshotMatches && !statusBusy && !statusError && !documentsLoading,
  );
  const localStateBlocked = localChangesPending || documentsLoading;
  const downloadDisabled =
    !reviewSnapshotKnown || !currentManifestMatches || localStateBlocked || Boolean(actionBusy);
  const canApprove = Boolean(
    reviewSnapshotKnown &&
    status?.pair_approved &&
    status.current_pair_approval_id &&
    !status.approved &&
    Object.keys(status.validation_errors).length === 0 &&
    !localStateBlocked &&
    !actionBusy &&
    csrfToken,
  );

  function selectFile(kind: ReviewDocumentKind): void {
    selectedKindRef.current = kind;
    setSelectedKind(kind);
  }

  async function loadStatus(): Promise<void> {
    const currentRequest = ++requestNumber.current;
    setStatusBusy(true);
    setStatusError("");
    try {
      const [statusValue, tasksValue] = await Promise.all([
        apiRequest<unknown>(finalApprovalPath(projectId)),
        apiRequest<unknown>(`/api/projects/${encodeURIComponent(projectId)}/backlog/tasks`),
      ]);
      if (currentRequest !== requestNumber.current) return;
      const nextStatus = parseFinalApprovalStatus(statusValue);
      if (!isTaskDocument(tasksValue)) {
        throw new Error("Saved task readiness is unavailable. Refresh it before continuing.");
      }
      setStatus(nextStatus);
      setTaskDocument(tasksValue);
      if (!statusMatchesDocuments(nextStatus, documents)) {
        setNotice(
          "Saved document heads changed. Reload the drafts before final approval or download.",
        );
      } else if (
        tasksValue.revision_number !== documents.backlog.revision_number ||
        tasksValue.content_sha256 !== documents.backlog.content_sha256
      ) {
        setNotice(
          "Backlog readiness belongs to another saved revision. Refresh before continuing.",
        );
      } else {
        setNotice("");
      }
    } catch (failure) {
      if (currentRequest !== requestNumber.current) return;
      if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpired();
      } else {
        setStatus(null);
        setTaskDocument(null);
        setStatusError(friendlyError(failure));
      }
    } finally {
      if (currentRequest === requestNumber.current) setStatusBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void loadStatus();
    });
    return () => {
      active = false;
      requestNumber.current += 1;
    };
    // The server snapshot is refreshed whenever a saved document head changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    projectId,
    documents.project.id,
    documents.project.revision_number,
    documents.project.content_sha256,
    documents.agents.revision_number,
    documents.agents.content_sha256,
    documents.backlog.revision_number,
    documents.backlog.content_sha256,
  ]);

  useLayoutEffect(() => {
    if (focusHeadingOnMount) headingRef.current?.focus();
  }, [focusHeadingOnMount]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(min-width: 1280px)");
    viewportIsWide.current = query.matches;
    const handleViewportChange = (event: MediaQueryListEvent): void => {
      const wasWide = viewportIsWide.current;
      viewportIsWide.current = event.matches;
      if (
        wasWide &&
        !event.matches &&
        focusedPaneKind.current &&
        focusedPaneElement.current === document.activeElement
      ) {
        const kind = focusedPaneKind.current;
        selectFile(kind);
        responsiveFocus.current = { kind, target: "last-focused" };
      } else if (
        !wasWide &&
        event.matches &&
        tabNavigationHasFocus.current &&
        focusedTabElement.current === document.activeElement
      ) {
        responsiveFocus.current = {
          kind: selectedKindRef.current,
          target: "content",
        };
      }
    };
    query.addEventListener("change", handleViewportChange);
    return () => query.removeEventListener("change", handleViewportChange);
  }, []);

  useLayoutEffect(() => {
    const intent = responsiveFocus.current;
    if (!intent) return;
    responsiveFocus.current = null;
    const target =
      intent.target === "content"
        ? contentRegionRefs.current[intent.kind]
        : focusedPaneElement.current;
    if (target?.isConnected) target.focus({ preventScroll: true });
  }, [selectedKind]);

  useLayoutEffect(() => {
    if (!actionBusy && restoreApprovalFocus.current) {
      restoreApprovalFocus.current = false;
      if (currentManifestMatches) finalApprovalStatusRef.current?.focus();
      else if (canApprove) approvalButtonRef.current?.focus();
      else headingRef.current?.focus();
    }
  }, [actionBusy, canApprove, currentManifestMatches]);

  async function approveSnapshot(): Promise<void> {
    if (!canApprove || !status?.current_pair_approval_id || !taskDocument) return;
    const expected = {
      pairApprovalId: status.current_pair_approval_id,
      backlogRevision: documents.backlog.revision_number,
    };
    restoreApprovalFocus.current = document.activeElement === approvalButtonRef.current;
    setActionBusy("approval");
    setActionError("");
    setNotice("");
    try {
      const response = await apiRequest<ManifestReference>(finalApprovalPath(projectId), {
        method: "POST",
        csrfToken,
        body: {
          expected_pair_approval_id: expected.pairApprovalId,
          expected_backlog_revision: expected.backlogRevision,
        },
      });
      if (
        response.pair_approval_id !== expected.pairApprovalId ||
        !sameRevision(response.project, documents.project) ||
        !sameRevision(response.agents, documents.agents) ||
        !sameRevision(response.backlog, documents.backlog)
      ) {
        setActionError(
          "The server approval did not match the displayed saved revisions. Refresh before continuing.",
        );
      } else {
        setNotice(
          "The displayed PROJECT.md, AGENTS.md and BACKLOG.md revisions were approved together.",
        );
      }
      await loadStatus();
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpired();
      } else if (failure instanceof ApiError && failure.status === 409) {
        setActionError(
          "Saved revisions changed before approval. Review the current files and approve again.",
        );
        await loadStatus();
        onRefreshDocuments();
      } else if (failure instanceof ApiError && failure.status === 422) {
        setActionError(
          "The saved files need attention before final approval. Review the validation details below.",
        );
        await loadStatus();
      } else {
        setActionError(friendlyError(failure));
      }
    } finally {
      setActionBusy("");
    }
  }

  async function downloadDocument(kind: ReviewDocumentKind): Promise<void> {
    if (downloadDisabled) return;
    setActionBusy(`download-${kind}`);
    setActionError("");
    try {
      const response = await fetch(`${finalApprovalPath(projectId)}/files/${kind}`, {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (response.status === 401) {
        onSessionExpired();
        return;
      }
      if (response.status === 409) {
        setActionError(
          "The approved saved revisions are no longer current. Review the files and approve the new tuple.",
        );
        await loadStatus();
        onRefreshDocuments();
        return;
      }
      if (!response.ok) {
        setActionError(await responseFailureMessage(response));
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = documentOptions.find((item) => item.kind === kind)?.filename ?? "";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (failure) {
      setActionError(friendlyError(failure));
    } finally {
      setActionBusy("");
    }
  }

  function handleTabKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    currentKind: ReviewDocumentKind,
  ) {
    const index = documentOptions.findIndex((option) => option.kind === currentKind);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % documentOptions.length;
    else if (event.key === "ArrowLeft")
      nextIndex = (index - 1 + documentOptions.length) % documentOptions.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = documentOptions.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const next = documentOptions[nextIndex];
    selectFile(next.kind);
    document.getElementById(`${instanceId}-tab-${next.kind}`)?.focus();
  }

  const isStatusCurrent = Boolean(status && headsMatch && taskSnapshotMatches);
  const snapshotMismatch = Boolean(
    status && (!headsMatch || (taskDocument !== null && !taskSnapshotMatches)),
  );
  const pairState =
    !status || !headsMatch
      ? "Unknown"
      : status.pair_approved
        ? "Approved for the displayed PROJECT.md + AGENTS.md pair"
        : "Pair approval needed";
  const finalState = !isStatusCurrent
    ? "Unknown or stale"
    : currentManifestMatches
      ? "Approved for the displayed three-file tuple"
      : status?.latest_manifest
        ? "Re-review required"
        : "Not yet approved";

  return (
    <section
      aria-labelledby={`${instanceId}-title`}
      className="grid min-w-0 gap-5"
      data-testid="final-review"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-5">
        <div className="min-w-0">
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-accent">
            Stage 3 · Final review
          </p>
          <h2
            className="mt-2 text-2xl font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            id={`${instanceId}-title`}
            ref={headingRef}
            tabIndex={-1}
          >
            Review and download approved files
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-copy-muted">
            Final approval records the exact saved PROJECT.md, AGENTS.md and BACKLOG.md revisions
            shown here. Task readiness, pair approval and final approval are separate states.
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap gap-2">
          <span
            className="rounded-full border border-line bg-canvas px-3 py-2 text-xs text-copy-muted"
            data-testid="pair-approval-state"
          >
            Pair: {pairState}
          </span>
          <span
            aria-live="polite"
            className={`rounded-full border px-3 py-2 text-xs ${currentManifestMatches ? "border-accent/40 bg-accent/10 text-accent" : "border-line bg-canvas text-copy-muted"}`}
            data-testid="final-approval-state"
            ref={finalApprovalStatusRef}
            tabIndex={-1}
          >
            Final: {finalState}
          </span>
        </div>
      </div>

      {localChangesPending ? (
        <div className="grid gap-2 rounded-lg border border-amber-200/35 bg-amber-100/5 p-4">
          <p className="text-sm leading-6 text-amber-100" role="status">
            Local document or task changes are not part of this saved revision tuple. Save or
            discard them, then refresh final-review status before approving or downloading.
          </p>
          <button
            className="min-h-11 justify-self-start rounded-lg border border-line px-4 py-2 text-sm text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onClick={() => onReviewDocument("backlog")}
            type="button"
          >
            Return to planning and resolve local changes
          </button>
        </div>
      ) : null}

      {notice ? (
        <p aria-live="polite" className="text-sm leading-6 text-copy-muted" role="status">
          {notice}
        </p>
      ) : null}
      {statusError ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-300/35 bg-red-300/5 p-4">
          <p className="text-sm leading-6 text-red-100" role="alert">
            Final-review status is unavailable: {statusError}
          </p>
          <button
            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            disabled={statusBusy}
            onClick={() => void loadStatus()}
            type="button"
          >
            {statusBusy ? "Refreshing…" : "Refresh final-review status"}
          </button>
        </div>
      ) : null}
      {snapshotMismatch ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200/35 bg-amber-100/5 p-4">
          <p className="text-sm leading-6 text-amber-100" role="status">
            Saved document heads or task readiness do not match the server snapshot. Reload the
            drafts before reviewing or approving this tuple.
          </p>
          <button
            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            disabled={documentsLoading || statusBusy}
            onClick={onRefreshDocuments}
            type="button"
          >
            Reload current saved drafts
          </button>
          <button
            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            disabled={statusBusy}
            onClick={() => void loadStatus()}
            type="button"
          >
            Refresh approval status
          </button>
        </div>
      ) : null}

      <dl className="grid min-w-0 gap-3 rounded-xl border border-line bg-canvas p-4 sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <dt className="text-xs uppercase tracking-wide text-copy-muted">
            Saved backlog revision
          </dt>
          <dd className="mt-1 font-mono text-sm text-foreground">
            r{documents.backlog.revision_number}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-copy-muted">Draft tasks</dt>
          <dd className="mt-1 font-mono text-sm text-foreground">
            {taskSnapshotMatches ? taskDocument?.summary.draft_count : "Unknown"}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-copy-muted">Owner-ready tasks</dt>
          <dd className="mt-1 font-mono text-sm text-foreground">
            {taskSnapshotMatches ? taskDocument?.summary.ready_count : "Unknown"}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-copy-muted">Dependency-eligible</dt>
          <dd className="mt-1 font-mono text-sm text-foreground">
            {taskSnapshotMatches ? taskDocument?.summary.eligible_count : "Unknown"}
          </dd>
        </div>
        <p className="text-xs leading-5 text-copy-muted sm:col-span-2 xl:col-span-4">
          Ready is owner-set backlog metadata; dependency eligibility is a separate task summary.
          Neither means the three-file snapshot has final approval.
        </p>
      </dl>

      <div
        aria-label="Approved file navigation"
        className="flex flex-wrap gap-2 min-[1280px]:hidden focus-within:flex"
        onFocusCapture={(event) => {
          tabNavigationHasFocus.current = true;
          focusedTabElement.current = event.target as HTMLElement;
        }}
        role="tablist"
      >
        {documentOptions.map((option) => (
          <button
            aria-controls={`${instanceId}-panel-${option.kind}`}
            aria-selected={selectedKind === option.kind}
            className={`min-h-11 rounded-lg border px-4 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${selectedKind === option.kind ? "border-accent/60 bg-accent/10 text-accent" : "border-line bg-canvas text-copy-muted hover:border-accent/40"}`}
            id={`${instanceId}-tab-${option.kind}`}
            key={option.kind}
            onClick={() => selectFile(option.kind)}
            onKeyDown={(event) => handleTabKeyDown(event, option.kind)}
            role="tab"
            tabIndex={selectedKind === option.kind ? 0 : -1}
            type="button"
          >
            {option.filename}
          </button>
        ))}
      </div>

      <div className="grid min-w-0 gap-4 min-[1280px]:grid-cols-3" data-testid="review-panes">
        {documentOptions.map((option) => {
          const item = documents[option.kind];
          const paneSelected = selectedKind === option.kind;
          const paneClasses = paneSelected
            ? "grid min-w-0 content-start gap-3"
            : "hidden min-w-0 content-start gap-3 min-[1280px]:grid focus-within:grid";
          return (
            <article
              aria-labelledby={`${instanceId}-pane-title-${option.kind}`}
              className={`${paneClasses} rounded-xl border border-line bg-surface/95 p-4 sm:p-5`}
              id={`${instanceId}-panel-${option.kind}`}
              key={option.kind}
              onFocusCapture={(event) => {
                tabNavigationHasFocus.current = false;
                focusedPaneKind.current = option.kind;
                focusedPaneElement.current = event.target as HTMLElement;
              }}
              role="tabpanel"
              tabIndex={-1}
            >
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3
                    className="font-mono text-sm font-semibold text-foreground"
                    id={`${instanceId}-pane-title-${option.kind}`}
                  >
                    {option.filename}
                  </h3>
                  <p className="mt-1 text-xs text-copy-muted">
                    Saved revision {item.revision_number}
                  </p>
                </div>
                <button
                  className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  onClick={() => onReviewDocument(option.kind)}
                  type="button"
                >
                  Review {option.filename}
                </button>
              </div>
              <p className="break-all font-mono text-[11px] leading-5 text-copy-muted">
                Revision ID <code>{item.id}</code>
              </p>
              <p className="break-all font-mono text-[11px] leading-5 text-copy-muted">
                SHA-256 <code>{item.content_sha256}</code>
              </p>
              <pre
                aria-label={`${option.filename} saved revision ${item.revision_number} content`}
                className="max-h-[58vh] min-h-48 min-w-0 overflow-auto rounded-lg border border-line bg-canvas p-3 font-mono text-xs leading-6 text-foreground whitespace-pre-wrap break-words focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                role="region"
                ref={(element) => {
                  contentRegionRefs.current[option.kind] = element;
                }}
                tabIndex={0}
              >
                {item.content}
              </pre>
              <button
                className="min-h-11 w-full rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={downloadDisabled}
                onClick={() => void downloadDocument(option.kind)}
                type="button"
              >
                {actionBusy === `download-${option.kind}`
                  ? "Preparing download…"
                  : `Download ${option.filename}`}
              </button>
            </article>
          );
        })}
      </div>

      {status && Object.keys(status.validation_errors).length ? (
        <div className="grid gap-2 rounded-lg border border-amber-200/35 bg-amber-100/5 p-4">
          <h3 className="font-medium text-amber-100">Review validation details</h3>
          {Object.entries(status.validation_errors).map(([filename, messages]) => (
            <div className="text-sm leading-6 text-amber-50" key={filename}>
              <p className="font-mono">{filename}</p>
              <ul className="ml-5 list-disc">
                {messages.map((message) => (
                  <li className="break-words" key={message}>
                    {message}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <button
            className="min-h-11 justify-self-start rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onClick={() => onReviewDocument("backlog")}
            type="button"
          >
            Review saved backlog
          </button>
        </div>
      ) : null}

      {actionError ? (
        <div
          className="grid gap-3 rounded-lg border border-red-300/35 bg-red-300/5 p-4"
          role="alert"
        >
          <p className="text-sm leading-6 text-red-100">{actionError}</p>
          <div className="flex flex-wrap gap-2">
            <button
              className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              onClick={() => void loadStatus()}
              type="button"
            >
              Refresh approval status
            </button>
            <button
              className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              onClick={onReviewPair}
              type="button"
            >
              Review document pair
            </button>
            <button
              className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              onClick={() => onReviewDocument("backlog")}
              type="button"
            >
              Review saved backlog
            </button>
          </div>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <button
          className="min-h-11 rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={!canApprove}
          onClick={() => void approveSnapshot()}
          ref={approvalButtonRef}
          type="button"
        >
          {actionBusy === "approval"
            ? "Approving displayed revisions…"
            : currentManifestMatches
              ? "Approved at last check"
              : "Approve displayed three-file snapshot"}
        </button>
        {status?.pair_approved ? (
          <span className="text-sm text-copy-muted">
            The saved pair is approved; final approval also validates the current backlog.
          </span>
        ) : (
          <button
            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onClick={onReviewPair}
            type="button"
          >
            Review and approve PROJECT.md + AGENTS.md
          </button>
        )}
        {statusBusy ? (
          <span aria-live="polite" className="text-xs text-copy-muted" role="status">
            Refreshing server approval and readiness…
          </span>
        ) : null}
        {!reviewSnapshotKnown && !statusBusy && !statusError ? (
          <span className="text-xs text-copy-muted">
            Approval and downloads stay disabled until the server and saved task snapshots match.
          </span>
        ) : null}
      </div>
    </section>
  );
}
