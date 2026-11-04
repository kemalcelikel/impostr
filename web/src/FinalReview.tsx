import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, apiRequest } from "./api";
import type { BacklogTaskDocument } from "./BacklogPlanning";
import { Badge, Button, Disclosure, Feedback, TabButton } from "./ui/controls";

export type ReviewDocumentKind = "project" | "agents" | "backlog";

export type ReviewDocument = {
  id: string;
  kind: ReviewDocumentKind;
  filename: string;
  revision_number: number;
  content: string;
  content_sha256: string;
  origin?: "template" | "human" | "agent";
  author_user_id?: string | null;
  created_at?: string;
  template_source?: string | null;
  template_sha256?: string | null;
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
  pageTitleId?: string;
  onSessionExpired: () => void;
  onReviewDocument: (kind: ReviewDocumentKind) => void;
  onReviewPair: () => void;
  onRefreshDocuments?: () => void;
  refreshNumber?: number;
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
  pageTitleId,
  onSessionExpired,
  onReviewDocument,
  onReviewPair,
  onRefreshDocuments = () => {},
  refreshNumber = 0,
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
    refreshNumber,
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
  const pairState = localChangesPending
    ? "Resolve local changes"
    : documentsLoading || statusBusy
      ? "Checking saved revisions"
      : !status || !headsMatch || statusError
        ? "Unknown"
        : status.pair_approved
          ? "Approved for the displayed PROJECT.md + AGENTS.md pair"
          : "Pair approval needed";
  const finalState = localChangesPending
    ? "Resolve local changes"
    : documentsLoading || statusBusy
      ? "Checking saved revisions"
      : !isStatusCurrent || statusError
        ? "Unknown or stale"
        : currentManifestMatches
          ? "Approved for the displayed three-file tuple"
          : status?.latest_manifest
            ? "Re-review required"
            : "Not yet approved";

  const validationEntries = status ? Object.entries(status.validation_errors) : [];
  const snapshotBlockers = [
    ...(localChangesPending
      ? ["Save or discard local document and task changes before approving or downloading."]
      : []),
    ...(documentsLoading ? ["Wait for the saved documents to finish loading."] : []),
    ...(statusBusy ? ["Checking server approval and saved task readiness…"] : []),
    ...(statusError ? [`Final-review status is unavailable: ${statusError}`] : []),
    ...(snapshotMismatch
      ? [
          "Saved files or task readiness do not match this snapshot. Reload the saved drafts and refresh status.",
        ]
      : []),
    ...(!reviewSnapshotKnown &&
    !statusBusy &&
    !statusError &&
    !snapshotMismatch &&
    !documentsLoading
      ? ["Approval and downloads stay disabled until the server and saved task snapshots match."]
      : []),
  ];
  const approvalBlockers = [
    ...snapshotBlockers,
    ...(reviewSnapshotKnown && (!status?.pair_approved || !status.current_pair_approval_id)
      ? ["Approve the saved PROJECT.md + AGENTS.md pair first."]
      : []),
    ...validationEntries.map(
      ([filename, messages]) =>
        `${filename}: ${messages[0] ?? "Saved file validation needs attention."}`,
    ),
    ...(!csrfToken
      ? ["Your approval session is unavailable. Sign in again before approving."]
      : []),
    ...(actionBusy ? ["Wait for the current approval or download to finish."] : []),
  ];
  const nextAction = snapshotBlockers.length
    ? snapshotBlockers[0]
    : actionBusy
      ? "Wait for the current action to finish."
      : currentManifestMatches
        ? "Download the approved files individually."
        : !status?.pair_approved || !status.current_pair_approval_id
          ? "Review and approve the saved document pair."
          : validationEntries.length
            ? "Resolve saved file validation, then return for final approval."
            : !csrfToken
              ? "Sign in again before approving."
              : "Review all three files, then approve this saved snapshot.";

  const ReviewHeading = pageTitleId ? "h1" : "h2";
  const titleId = pageTitleId ?? `${instanceId}-title`;

  return (
    <section aria-labelledby={titleId} className="final-review-surface" data-testid="final-review">
      <header className="workbench-heading">
        <ReviewHeading className="app-page-title" id={titleId} ref={headingRef} tabIndex={-1}>
          {pageTitleId ? "Review & downloads" : "Review and download approved files"}
        </ReviewHeading>
        <p className="review-next-action" data-testid="review-next-action">
          <strong className="font-medium">Next: </strong>
          {nextAction}
        </p>
      </header>
      <div className="review-grid">
        <section
          className="review-inspection"
          aria-labelledby={`${instanceId}-files-title`}
          data-testid="review-panes"
        >
          <header className="workbench-section-heading">
            <h2 id={`${instanceId}-files-title`}>Saved files</h2>
            <span className="text-xs text-copy-muted">Read-only snapshots</span>
          </header>
          <div className="workbench-panel review-document-panel">
            <div aria-label="Saved file navigation" className="workbench-tab-strip" role="tablist">
              {documentOptions.map((option) => (
                <TabButton
                  aria-controls={`${instanceId}-panel-${option.kind}`}
                  className="workbench-tab"
                  title={option.label}
                  id={`${instanceId}-tab-${option.kind}`}
                  key={option.kind}
                  onClick={() => selectFile(option.kind)}
                  onKeyDown={(event) => handleTabKeyDown(event, option.kind)}
                  selected={selectedKind === option.kind}
                >
                  {option.filename}
                </TabButton>
              ))}
            </div>
            {documentOptions.map((option) => {
              const item = documents[option.kind];
              return (
                <article
                  aria-labelledby={`${instanceId}-tab-${option.kind}`}
                  className="review-file-panel"
                  hidden={selectedKind !== option.kind}
                  id={`${instanceId}-panel-${option.kind}`}
                  key={option.kind}
                  role="tabpanel"
                >
                  <div className="document-toolbar">
                    <div className="document-file-info">
                      <h3 className="document-filename">{option.filename}</h3>
                      <p className="document-file-state">Saved revision {item.revision_number}</p>
                    </div>
                    <Button
                      className="workbench-quiet"
                      variant="ghost"
                      aria-label={`Review ${option.filename}`}
                      icon="document"
                      onClick={() => onReviewDocument(option.kind)}
                    >
                      Open in planning
                    </Button>
                  </div>
                  <pre
                    aria-label={`${option.filename} saved revision ${item.revision_number} content`}
                    className="review-saved-content"
                    role="region"
                    tabIndex={0}
                  >
                    {item.content}
                  </pre>
                </article>
              );
            })}
            <footer className="document-foot">
              Saved snapshot · Unsaved buffers are not shown here
            </footer>
          </div>
        </section>

        <section aria-label="Approval and downloads" className="review-approval">
          <header className="workbench-section-heading">
            <h2>Approval &amp; downloads</h2>
          </header>
          <div className="workbench-panel review-approval-panel">
            <p className="review-summary">
              Final approval freezes all three saved revisions for download; it does not mark tasks
              ready.
            </p>
            {notice ? (
              <p aria-live="polite" className="text-sm text-success" role="status">
                {notice}
              </p>
            ) : null}
            <dl className="review-approval-states">
              <div>
                <dt className="mb-1 font-medium">Document-pair approval</dt>
                <dd>
                  <Badge
                    data-testid="pair-approval-state"
                    tone={
                      status?.pair_approved &&
                      headsMatch &&
                      !localStateBlocked &&
                      !statusBusy &&
                      !statusError
                        ? "success"
                        : "neutral"
                    }
                  >
                    Pair: {pairState}
                  </Badge>
                </dd>
              </div>
              <div>
                <dt className="mb-1 font-medium">Final three-file approval</dt>
                <dd>
                  <Badge
                    aria-live="polite"
                    className="focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    data-testid="final-approval-state"
                    ref={finalApprovalStatusRef}
                    tabIndex={-1}
                    tone={
                      currentManifestMatches && !localStateBlocked && reviewSnapshotKnown
                        ? "success"
                        : "neutral"
                    }
                  >
                    Final: {finalState}
                  </Badge>
                </dd>
              </div>
            </dl>
            <dl className="review-revisions" aria-label="Displayed saved revisions">
              {documentOptions.map((option) => (
                <div key={option.kind}>
                  <dt>{option.filename}</dt>
                  <dd>r{documents[option.kind].revision_number}</dd>
                </div>
              ))}
            </dl>
            {actionError ? (
              <Feedback tone="danger" role="alert">
                <p>{actionError}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    className="workbench-quiet"
                    variant="ghost"
                    onClick={() => void loadStatus()}
                    icon="refresh"
                  >
                    Refresh approval status
                  </Button>
                  <Button className="workbench-quiet" variant="ghost" onClick={onReviewPair}>
                    Review document pair
                  </Button>
                </div>
              </Feedback>
            ) : null}
            <div className="grid gap-2">
              <div
                id={`${instanceId}-approval-reasons`}
                className="review-disabled-reasons"
                aria-live="polite"
              >
                {approvalBlockers.length ? (
                  <ul className="grid gap-1">
                    {approvalBlockers.map((reason) => (
                      <li className="break-words" key={reason}>
                        {reason}
                      </li>
                    ))}
                  </ul>
                ) : currentManifestMatches ? (
                  <p>The displayed saved three-file tuple is already approved.</p>
                ) : (
                  <p>
                    The saved pair is approved; final approval also validates the current backlog.
                  </p>
                )}
              </div>
              {validationEntries.length ? (
                <p className="text-xs leading-5 text-copy-muted">
                  All validation messages are available in Validation and revision details below.
                </p>
              ) : null}
              {reviewSnapshotKnown &&
              (!status?.pair_approved || !status.current_pair_approval_id) ? (
                <Button
                  className="workbench-quiet review-recovery"
                  icon="shield"
                  variant="ghost"
                  onClick={onReviewPair}
                >
                  Review and approve PROJECT.md + AGENTS.md
                </Button>
              ) : null}
              {localChangesPending ? (
                <Button
                  className="workbench-quiet review-recovery"
                  variant="ghost"
                  onClick={() => onReviewDocument("backlog")}
                >
                  Return to planning and resolve local changes
                </Button>
              ) : null}
              <Button
                aria-describedby={`${instanceId}-approval-reasons`}
                className="workbench-save review-approve"
                icon="check"
                variant="primary"
                disabled={!canApprove}
                onClick={() => void approveSnapshot()}
                ref={approvalButtonRef}
              >
                {actionBusy === "approval"
                  ? "Approving displayed revisions…"
                  : currentManifestMatches && !localStateBlocked && reviewSnapshotKnown
                    ? "Approved at last check"
                    : "Approve displayed three-file snapshot"}
              </Button>
            </div>
            <div className="review-downloads">
              <h3 className="text-sm font-semibold">Downloads</h3>
              <p
                id={`${instanceId}-download-reasons`}
                className="text-xs leading-5 text-copy-muted"
              >
                {downloadDisabled
                  ? snapshotBlockers.length
                    ? snapshotBlockers[0]
                    : actionBusy
                      ? "Wait for the current approval or download to finish."
                      : "Downloads require final approval of the displayed saved three-file tuple."
                  : "Individual UTF-8 files from the exact approved revisions. Downloads do not install the toolkit."}
              </p>
              {documentOptions.map((option) => (
                <Button
                  aria-describedby={`${instanceId}-download-reasons`}
                  className="review-download workbench-quiet"
                  variant="ghost"
                  disabled={downloadDisabled}
                  icon="download"
                  key={option.kind}
                  onClick={() => void downloadDocument(option.kind)}
                >
                  {actionBusy === `download-${option.kind}`
                    ? "Preparing download…"
                    : `Download ${option.filename}`}
                </Button>
              ))}
            </div>
            {statusError || snapshotMismatch ? (
              <div className="grid gap-2">
                {statusError ? (
                  <Feedback role="alert" tone="danger">
                    Final-review status is unavailable: {statusError}
                  </Feedback>
                ) : null}
                {snapshotMismatch ? (
                  <Button
                    className="workbench-quiet"
                    variant="ghost"
                    disabled={documentsLoading || statusBusy}
                    onClick={onRefreshDocuments}
                  >
                    Reload current saved drafts
                  </Button>
                ) : null}
                <Button
                  className="workbench-quiet"
                  variant="ghost"
                  disabled={statusBusy}
                  icon="refresh"
                  onClick={() => void loadStatus()}
                >
                  {statusBusy ? "Refreshing…" : "Refresh final-review status"}
                </Button>
              </div>
            ) : null}
            <section className="review-readiness" aria-label="Task readiness">
              <h3 className="text-sm font-semibold">Task readiness</h3>
              <p className="mt-1 text-xs text-copy-muted">
                Saved backlog revision r{documents.backlog.revision_number}
              </p>
              <dl className="review-readiness-counts">
                {(
                  [
                    ["Draft tasks", "draft_count"],
                    ["Owner-ready tasks", "ready_count"],
                    ["Dependency-eligible", "eligible_count"],
                    ["Waiting on dependencies", "waiting_count"],
                  ] as const
                ).map(([label, key]) => (
                  <div key={key}>
                    <dt className="text-xs text-copy-muted">{label}</dt>
                    <dd className="mt-1 font-semibold">
                      {taskSnapshotMatches ? taskDocument?.summary[key] : "Unknown"}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-xs leading-5 text-copy-muted">
                Ready is owner-set; eligible tasks also have completed dependencies. Neither is
                final approval.
              </p>
              <Button
                className="workbench-quiet"
                variant="ghost"
                onClick={() => onReviewDocument("backlog")}
              >
                Review saved backlog
              </Button>
            </section>
            <Disclosure
              className="review-details"
              title="Validation and revision details"
              icon="info"
            >
              <div className="mt-3 grid min-w-0 gap-4">
                <section aria-label="Review validation details">
                  <h3 className="text-sm font-semibold">Review validation details</h3>
                  {validationEntries.length ? (
                    validationEntries.map(([filename, messages]) => (
                      <div className="mt-3 text-sm leading-6" key={filename}>
                        <p className="font-medium">{filename}</p>
                        <ul className="ml-5 list-disc">
                          {messages.map((message) => (
                            <li className="break-words" key={message}>
                              {message}
                            </li>
                          ))}
                        </ul>
                        <Button
                          className="workbench-quiet mt-2"
                          variant="ghost"
                          onClick={() =>
                            onReviewDocument(
                              documentOptions.find((option) => option.filename === filename)
                                ?.kind ?? "backlog",
                            )
                          }
                        >
                          Review {filename}
                        </Button>
                      </div>
                    ))
                  ) : (
                    <p className="mt-2 text-sm text-copy-muted">
                      {reviewSnapshotKnown
                        ? "No saved-file validation blockers at last check."
                        : "Refresh the matching saved snapshot to check validation."}
                    </p>
                  )}
                </section>
                <section
                  aria-label="Saved revision identities and provenance"
                  className="grid min-w-0 gap-3"
                >
                  <h3 className="text-sm font-semibold">
                    Saved revision identities and provenance
                  </h3>
                  <p className="text-xs leading-5 text-copy-muted">
                    Document IDs identify files; revision IDs identify immutable saved versions.
                    They are not interchangeable.
                  </p>
                  {documentOptions.map((option) => {
                    const item = documents[option.kind];
                    const reference = status?.[`current_${option.kind}_revision`];
                    return (
                      <div className="min-w-0 rounded-md border border-line p-3" key={option.kind}>
                        <h4 className="text-sm font-medium">
                          {option.filename} · saved revision {item.revision_number}
                        </h4>
                        <dl className="mt-2 grid min-w-0 gap-2 text-xs leading-5">
                          <div>
                            <dt className="text-copy-muted">Document ID</dt>
                            <dd className="break-all">
                              <code>{item.id}</code>
                            </dd>
                          </div>
                          {headsMatch && reference ? (
                            <div>
                              <dt className="text-copy-muted">Revision ID</dt>
                              <dd className="break-all">
                                <code>{reference.id}</code>
                              </dd>
                            </div>
                          ) : null}
                          <div>
                            <dt className="text-copy-muted">SHA-256</dt>
                            <dd className="break-all">
                              <code>{item.content_sha256}</code>
                            </dd>
                          </div>
                          {item.origin ? (
                            <div>
                              <dt className="text-copy-muted">Saved origin</dt>
                              <dd>{item.origin}</dd>
                            </div>
                          ) : null}
                          {item.created_at ? (
                            <div>
                              <dt className="text-copy-muted">Saved at</dt>
                              <dd>{item.created_at}</dd>
                            </div>
                          ) : null}
                          {item.author_user_id ? (
                            <div>
                              <dt className="text-copy-muted">Author ID</dt>
                              <dd className="break-all">
                                <code>{item.author_user_id}</code>
                              </dd>
                            </div>
                          ) : null}
                          {item.template_source ? (
                            <div>
                              <dt className="text-copy-muted">Template source</dt>
                              <dd className="break-words">{item.template_source}</dd>
                            </div>
                          ) : null}
                          {item.template_sha256 ? (
                            <div>
                              <dt className="text-copy-muted">Template SHA-256</dt>
                              <dd className="break-all">
                                <code>{item.template_sha256}</code>
                              </dd>
                            </div>
                          ) : null}
                        </dl>
                      </div>
                    );
                  })}
                  {status?.current_pair_approval_id ? (
                    <p className="break-all text-xs text-copy-muted">
                      Pair approval ID <code>{status.current_pair_approval_id}</code>
                    </p>
                  ) : null}
                  {status?.latest_manifest ? (
                    <p className="break-all text-xs text-copy-muted">
                      Latest final approval ID <code>{status.latest_manifest.id}</code> · PROJECT.md
                      r{status.latest_manifest.project.revision_number}, AGENTS.md r
                      {status.latest_manifest.agents.revision_number}, BACKLOG.md r
                      {status.latest_manifest.backlog.revision_number}
                    </p>
                  ) : null}
                </section>
              </div>
            </Disclosure>
          </div>
        </section>
      </div>
    </section>
  );
}
