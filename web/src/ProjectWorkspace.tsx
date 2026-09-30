import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { ApiError, apiRequest } from "./api";
import BacklogPlanning, { type BacklogTaskDocument } from "./BacklogPlanning";

export type ProjectSummary = {
  id: string;
  name: string;
  owner_user_id: string;
  created_at: string;
};

type DocumentKind = "project" | "agents" | "backlog";
type DocumentOrigin = "template" | "human";

type ProjectDocument = {
  id: string;
  kind: DocumentKind;
  filename: string;
  revision_number: number;
  content: string;
  content_sha256: string;
  origin: DocumentOrigin;
  author_user_id: string | null;
  created_at: string;
  template_source: string | null;
  template_sha256: string | null;
};

type RevisionSummary = {
  revision_number: number;
  content_sha256: string;
  origin: DocumentOrigin;
  author_user_id: string | null;
  created_at: string;
  template_source: string | null;
  template_sha256: string | null;
};

type ConflictProposalSummary = {
  id: string;
  expected_revision_number: number;
  observed_revision_number: number;
  content_sha256: string;
  author_user_id: string;
  created_at: string;
};

type DocumentHistory = {
  kind: DocumentKind;
  current_revision_number: number;
  revisions: RevisionSummary[];
  proposals: ConflictProposalSummary[];
  revision_offset: number;
  proposal_cursor: string | null;
  proposal_next_cursor: string | null;
  revision_has_more: boolean;
  proposal_has_more: boolean;
};

type DocumentRevision = RevisionSummary & { content: string };
type ConflictProposal = ConflictProposalSummary & { content: string };
type CompareContent = { label: string; content: string };
type ProjectDocuments = Record<DocumentKind, ProjectDocument>;
type PairKind = "project" | "agents";
type RevisionReference = { id: string; revision_number: number; content_sha256: string };
type PairApprovalRecord = {
  id: string;
  project_revision_id: string;
  project_revision_number: number;
  agents_revision_id: string;
  agents_revision_number: number;
  actor_user_id: string | null;
  created_at: string;
};
type PairApprovalStatus = {
  current_project_revision: RevisionReference;
  current_agents_revision: RevisionReference;
  approved: boolean;
  latest_approval: PairApprovalRecord | null;
  approvals: PairApprovalRecord[];
  approval_offset: number;
  approval_has_more: boolean;
  approval_next_cursor: string | null;
};
type PairDocuments = { project: ProjectDocument; agents: ProjectDocument };
type PairConflict = { previous: PairDocuments; latest: PairDocuments };
type DiffRowKind = "context" | "added" | "removed" | "note";
type DiffRow = { kind: DiffRowKind; text: string; key: string };
type DiffResult = { rows: DiffRow[]; added: number; removed: number; truncated: boolean };

const MAX_DOCUMENT_BYTES = 128 * 1024;
const documentOptions: { kind: DocumentKind; label: string; filename: string }[] = [
  { kind: "project", label: "Project", filename: "PROJECT.md" },
  { kind: "agents", label: "Agent rules", filename: "AGENTS.md" },
  { kind: "backlog", label: "Backlog", filename: "BACKLOG.md" },
];
const pairDocumentOptions: { kind: PairKind; filename: string }[] = [
  { kind: "project", filename: "PROJECT.md" },
  { kind: "agents", filename: "AGENTS.md" },
];

const MAX_DIFF_MATRIX_CELLS = 1_000_000;
const MAX_DIFF_MATRIX_LINES = 2_000;
const MAX_RENDERED_DIFF_ROWS = 3_000;

function diffLines(content: string): string[] {
  if (content.length === 0) return [];
  const lines = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  return lines;
}

function lineEndingStyle(content: string): string {
  if (content.includes("\r\n")) return "CRLF";
  if (content.includes("\n")) return "LF";
  if (content.includes("\r")) return "CR";
  return "no line breaks";
}

function trimDiffRows(rows: DiffRow[]): { rows: DiffRow[]; truncated: boolean } {
  if (rows.length <= MAX_RENDERED_DIFF_ROWS) return { rows, truncated: false };
  const sideCount = Math.floor((MAX_RENDERED_DIFF_ROWS - 1) / 2);
  const omittedCount = rows.length - sideCount * 2;
  return {
    rows: [
      ...rows.slice(0, sideCount),
      {
        kind: "note",
        text: `… ${omittedCount.toLocaleString()} changed/context lines omitted …`,
        key: "omitted",
      },
      ...rows.slice(-sideCount),
    ],
    truncated: true,
  };
}

function buildDiff(before: string, after: string): DiffResult {
  const oldLines = diffLines(before);
  const newLines = diffLines(after);
  const rawRows: DiffRow[] = [];
  let added = 0;
  let removed = 0;
  const addRow = (kind: DiffRowKind, text: string): void => {
    rawRows.push({ kind, text, key: `${kind}-${rawRows.length}` });
  };

  if (
    oldLines.length * newLines.length <= MAX_DIFF_MATRIX_CELLS &&
    Math.max(oldLines.length, newLines.length) <= MAX_DIFF_MATRIX_LINES
  ) {
    const rows = oldLines.length + 1;
    const columns = newLines.length + 1;
    const lcs = Array.from({ length: rows }, () => new Uint32Array(columns));
    for (let oldIndex = oldLines.length - 1; oldIndex >= 0; oldIndex -= 1) {
      for (let newIndex = newLines.length - 1; newIndex >= 0; newIndex -= 1) {
        const row = lcs[oldIndex];
        const nextRow = lcs[oldIndex + 1];
        if (row && nextRow) {
          row[newIndex] =
            oldLines[oldIndex] === newLines[newIndex]
              ? (nextRow[newIndex + 1] ?? 0) + 1
              : Math.max(nextRow[newIndex] ?? 0, row[newIndex + 1] ?? 0);
        }
      }
    }

    let oldIndex = 0;
    let newIndex = 0;
    while (oldIndex < oldLines.length || newIndex < newLines.length) {
      const oldLine = oldLines[oldIndex];
      const newLine = newLines[newIndex];
      if (oldLine !== undefined && newLine !== undefined && oldLine === newLine) {
        addRow("context", oldLine);
        oldIndex += 1;
        newIndex += 1;
        continue;
      }
      const row = lcs[oldIndex];
      const nextRow = lcs[oldIndex + 1];
      if (
        newLine !== undefined &&
        (oldLine === undefined || (row?.[newIndex + 1] ?? 0) > (nextRow?.[newIndex] ?? 0))
      ) {
        addRow("added", newLine);
        added += 1;
        newIndex += 1;
      } else if (oldLine !== undefined) {
        addRow("removed", oldLine);
        removed += 1;
        oldIndex += 1;
      }
    }
  } else {
    let prefix = 0;
    while (
      prefix < oldLines.length &&
      prefix < newLines.length &&
      oldLines[prefix] === newLines[prefix]
    ) {
      prefix += 1;
    }
    let suffix = 0;
    while (
      suffix < oldLines.length - prefix &&
      suffix < newLines.length - prefix &&
      oldLines[oldLines.length - 1 - suffix] === newLines[newLines.length - 1 - suffix]
    ) {
      suffix += 1;
    }

    const contextLines = 3;
    if (prefix <= contextLines * 2) {
      for (let index = 0; index < prefix; index += 1) {
        addRow("context", oldLines[index] ?? "");
      }
    } else {
      for (let index = 0; index < contextLines; index += 1) {
        addRow("context", oldLines[index] ?? "");
      }
      addRow("note", `… ${prefix - contextLines * 2} unchanged lines omitted …`);
      for (let index = prefix - contextLines; index < prefix; index += 1) {
        addRow("context", oldLines[index] ?? "");
      }
    }

    const oldEnd = oldLines.length - suffix;
    const newEnd = newLines.length - suffix;
    for (let index = prefix; index < oldEnd; index += 1) {
      addRow("removed", oldLines[index] ?? "");
      removed += 1;
    }
    for (let index = prefix; index < newEnd; index += 1) {
      addRow("added", newLines[index] ?? "");
      added += 1;
    }

    if (suffix <= contextLines * 2) {
      for (let index = 0; index < suffix; index += 1) {
        addRow("context", newLines[newEnd + index] ?? "");
      }
    } else {
      for (let index = 0; index < contextLines; index += 1) {
        addRow("context", newLines[newEnd + index] ?? "");
      }
      addRow("note", `… ${suffix - contextLines * 2} unchanged lines omitted …`);
      for (let index = suffix - contextLines; index < suffix; index += 1) {
        addRow("context", newLines[newEnd + index] ?? "");
      }
    }
  }

  const beforeHasFinalNewline = before.endsWith("\n");
  const afterHasFinalNewline = after.endsWith("\n");
  if (beforeHasFinalNewline !== afterHasFinalNewline) {
    addRow("note", `Final newline ${beforeHasFinalNewline ? "removed" : "added"} at end of file.`);
  }
  const beforeLineEnding = lineEndingStyle(before);
  const afterLineEnding = lineEndingStyle(after);
  if (beforeLineEnding !== afterLineEnding) {
    addRow("note", `Line ending style changed from ${beforeLineEnding} to ${afterLineEnding}.`);
  }
  const trimmed = trimDiffRows(rawRows);
  return { rows: trimmed.rows, added, removed, truncated: trimmed.truncated };
}

function DiffViewer({
  beforeLabel,
  before,
  afterLabel,
  after,
}: {
  beforeLabel: string;
  before: string;
  afterLabel: string;
  after: string;
}) {
  const diff = useMemo(() => buildDiff(before, after), [before, after]);
  const sameContent = before === after;
  const diffName = `${beforeLabel} compared with ${afterLabel}`;

  return (
    <div className="grid min-w-0 gap-3">
      <div aria-live="polite" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="text-copy-muted">{diffName}</span>
        {sameContent ? (
          <span className="font-medium text-copy-muted">No saved text differences.</span>
        ) : (
          <span className="font-mono text-xs">
            <span className="text-green-200">+{diff.added} added</span>
            <span aria-hidden="true" className="px-2 text-copy-muted">
              ·
            </span>
            <span className="text-red-200">−{diff.removed} removed</span>
          </span>
        )}
      </div>
      {!sameContent ? (
        <ol
          aria-label={`Line-by-line diff: ${diffName}`}
          className="max-h-[32rem] min-w-0 list-none overflow-auto rounded-lg border border-line bg-canvas p-2 font-mono text-sm leading-6"
        >
          {diff.rows.map((row) => (
            <li
              className={`grid min-w-0 grid-cols-[2rem_minmax(0,1fr)] gap-2 rounded px-2 py-0.5 ${
                row.kind === "added"
                  ? "bg-green-300/10 text-green-100"
                  : row.kind === "removed"
                    ? "bg-red-300/10 text-red-100"
                    : row.kind === "note"
                      ? "text-copy-muted"
                      : "text-foreground"
              }`}
              key={row.key}
            >
              <span aria-hidden="true" className="select-none text-right">
                {row.kind === "added"
                  ? "+"
                  : row.kind === "removed"
                    ? "−"
                    : row.kind === "note"
                      ? "…"
                      : " "}
              </span>
              <span className="min-w-0 break-words whitespace-pre-wrap">
                <span className="sr-only">
                  {row.kind === "added"
                    ? "Added line: "
                    : row.kind === "removed"
                      ? "Removed line: "
                      : row.kind === "note"
                        ? "Diff note: "
                        : "Unchanged line: "}
                </span>
                {row.text || " "}
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      {diff.truncated ? (
        <p className="text-xs leading-5 text-copy-muted">
          The inline diff is capped for readability. The saved revisions remain available in full
          through document history.
        </p>
      ) : null}
    </div>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function pairConflictFrom(error: ApiError): PairDocuments | null {
  if (!isRecord(error.payload) || !isRecord(error.payload.latest)) return null;
  const { project, agents } = error.payload.latest;
  if (
    !isRecord(project) ||
    project.kind !== "project" ||
    typeof project.id !== "string" ||
    typeof project.content !== "string" ||
    typeof project.content_sha256 !== "string" ||
    typeof project.revision_number !== "number" ||
    !Number.isSafeInteger(project.revision_number) ||
    (project.revision_number as number) < 1 ||
    project.filename !== "PROJECT.md" ||
    !isRecord(agents) ||
    agents.kind !== "agents" ||
    typeof agents.id !== "string" ||
    typeof agents.content !== "string" ||
    typeof agents.content_sha256 !== "string" ||
    typeof agents.revision_number !== "number" ||
    !Number.isSafeInteger(agents.revision_number) ||
    (agents.revision_number as number) < 1 ||
    agents.filename !== "AGENTS.md"
  ) {
    return null;
  }
  return { project: project as ProjectDocument, agents: agents as ProjectDocument };
}

function sameSavedPair(a: PairDocuments, b: PairDocuments): boolean {
  return pairDocumentOptions.every(
    ({ kind }) =>
      a[kind].id === b[kind].id &&
      a[kind].revision_number === b[kind].revision_number &&
      a[kind].content_sha256 === b[kind].content_sha256,
  );
}

function sameRevisionReference(a: RevisionReference, b: RevisionReference): boolean {
  return (
    a.id === b.id &&
    a.revision_number === b.revision_number &&
    a.content_sha256 === b.content_sha256
  );
}

function approvalHeadsMatchDocuments(
  status: PairApprovalStatus | null,
  documents: ProjectDocuments | null,
): boolean {
  return Boolean(
    status &&
    documents &&
    status.current_project_revision.revision_number === documents.project.revision_number &&
    status.current_project_revision.content_sha256 === documents.project.content_sha256 &&
    status.current_agents_revision.revision_number === documents.agents.revision_number &&
    status.current_agents_revision.content_sha256 === documents.agents.content_sha256,
  );
}

function reconcileRevisionReference(
  current: RevisionReference,
  incoming: RevisionReference,
): RevisionReference {
  return incoming.revision_number > current.revision_number ? incoming : current;
}

function reconcilePairApprovalStatus(
  current: PairApprovalStatus | null,
  incoming: PairApprovalStatus,
): PairApprovalStatus {
  if (!current) return incoming;
  const currentProject = reconcileRevisionReference(
    current.current_project_revision,
    incoming.current_project_revision,
  );
  const currentAgents = reconcileRevisionReference(
    current.current_agents_revision,
    incoming.current_agents_revision,
  );
  const incomingMatchesCurrentHeads =
    sameRevisionReference(currentProject, incoming.current_project_revision) &&
    sameRevisionReference(currentAgents, incoming.current_agents_revision);
  return {
    ...incoming,
    current_project_revision: currentProject,
    current_agents_revision: currentAgents,
    approved: incomingMatchesCurrentHeads && incoming.approved,
    latest_approval: incomingMatchesCurrentHeads
      ? incoming.latest_approval
      : current.latest_approval,
  };
}

function reconcileDocumentHead(
  current: ProjectDocument,
  incoming: ProjectDocument,
): ProjectDocument {
  if (current.id !== incoming.id || current.kind !== incoming.kind) return current;
  return incoming.revision_number > current.revision_number ? incoming : current;
}

function reconcileDocumentHeads(
  current: ProjectDocuments,
  incoming: ProjectDocuments,
): ProjectDocuments {
  return {
    project: reconcileDocumentHead(current.project, incoming.project),
    agents: reconcileDocumentHead(current.agents, incoming.agents),
    backlog: reconcileDocumentHead(current.backlog, incoming.backlog),
  };
}

function parseApprovalValidationErrors(error: ApiError): Record<string, string[]> | null {
  if (!isRecord(error.payload) || !isRecord(error.payload.detail)) return null;
  const files = error.payload.detail.files;
  if (!isRecord(files)) return null;
  const messages = Object.fromEntries(
    Object.entries(files).flatMap(([filename, value]) => {
      if (!Array.isArray(value)) return [];
      const fileMessages = value.filter(
        (message): message is string => typeof message === "string",
      );
      return fileMessages.length ? [[filename, fileMessages]] : [];
    }),
  );
  return Object.keys(messages).length ? messages : null;
}

function documentPath(projectId: string, kind: DocumentKind): string {
  return `/api/projects/${encodeURIComponent(projectId)}/documents/${kind}`;
}

function pairApprovalPath(projectId: string, cursor: string | null = null): string {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  return `/api/projects/${encodeURIComponent(projectId)}/document-pair-approval?${query.toString()}`;
}

function historyPath(
  projectId: string,
  kind: DocumentKind,
  revisionOffset = 0,
  proposalCursor: string | null = null,
): string {
  const query = new URLSearchParams({ revision_offset: String(revisionOffset) });
  if (proposalCursor !== null) query.set("proposal_cursor", proposalCursor);
  return `${documentPath(projectId, kind)}/history?${query.toString()}`;
}

function isoDate(value: string): string {
  return `${new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  })} UTC`;
}

function contentBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

export default function ProjectWorkspace({
  projects,
  csrfToken,
  loading,
  loadError,
  onProjectCreated,
  onSessionExpired,
  onPendingChange = () => {},
  onProjectPageChange = () => {},
  projectOffset = 0,
}: {
  projects: ProjectSummary[];
  csrfToken: string;
  loading: boolean;
  loadError: string;
  onProjectCreated: (project: ProjectSummary) => void;
  onSessionExpired: () => void;
  onPendingChange?: (pending: boolean) => void;
  onProjectPageChange?: (offset: number) => void;
  projectOffset?: number;
}) {
  const instanceId = `project-workspace-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [newProjectName, setNewProjectName] = useState("");
  const [locallyCreatedProjects, setLocallyCreatedProjects] = useState<ProjectSummary[]>([]);
  const [createError, setCreateError] = useState("");
  const [createNotice, setCreateNotice] = useState("");
  const [createBusy, setCreateBusy] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [selectedProjectSnapshot, setSelectedProjectSnapshot] = useState<ProjectSummary | null>(
    null,
  );
  const [selectedKind, setSelectedKind] = useState<DocumentKind>("project");
  const [backlogPanel, setBacklogPanel] = useState<"tasks" | "detail" | "markdown">("tasks");
  const selectionRef = useRef<{ projectId: string | null; kind: DocumentKind }>({
    projectId: null,
    kind: "project",
  });
  const [documents, setDocumentsState] = useState<ProjectDocuments | null>(null);
  const documentsRef = useRef<ProjectDocuments | null>(null);
  const documentsProjectIdRef = useRef<string | null>(null);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const editorContentRef = useRef(editorContent);
  const editorChangeNumber = useRef(0);
  const [saveBusy, setSaveBusy] = useState(false);
  const [taskEditsPending, setTaskEditsPending] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [conflictNotice, setConflictNotice] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyOpenRef = useRef(false);
  const [history, setHistory] = useState<DocumentHistory | null>(null);
  const historyRevisionRef = useRef<number | null>(null);
  const reloadCurrentHistoryRef = useRef<((knownHead: ProjectDocument) => Promise<void>) | null>(
    null,
  );
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [compareContent, setCompareContent] = useState<CompareContent | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<PairApprovalStatus | null>(null);
  const [approvalStatusLoading, setApprovalStatusLoading] = useState(false);
  const [approvalHistoryLoading, setApprovalHistoryLoading] = useState(false);
  const [pairRefreshBusy, setPairRefreshBusy] = useState(false);
  const [approvalCheckedAt, setApprovalCheckedAt] = useState("");
  const [approvalStatusError, setApprovalStatusError] = useState("");
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [approvalError, setApprovalError] = useState("");
  const [approvalNotice, setApprovalNotice] = useState("");
  const [approvalValidationErrors, setApprovalValidationErrors] = useState<
    Record<string, string[]>
  >({});
  const [pairConflict, setPairConflict] = useState<PairConflict | null>(null);
  const pairConflictRef = useRef<PairConflict | null>(null);
  const [pairConflictKind, setPairConflictKind] = useState<PairKind>("project");
  const [reviewedPairKinds, setReviewedPairKinds] = useState<Set<PairKind>>(() => new Set());
  const reviewedPairKindsRef = useRef<Set<PairKind>>(new Set());
  const [pairReviewConfirmed, setPairReviewConfirmed] = useState(false);
  const pairReviewConfirmedRef = useRef(false);
  const comparisonHeadingRef = useRef<HTMLHeadingElement>(null);
  const comparisonTriggerRef = useRef<HTMLButtonElement | null>(null);
  const historyToggleRef = useRef<HTMLButtonElement>(null);
  const restoreComparisonFocus = useRef(false);
  const documentRequestNumber = useRef(0);
  const documentController = useRef<AbortController | null>(null);
  const [staleEditorRevision, setStaleEditorRevision] = useState<number | null>(null);
  const historyRequestNumber = useRef(0);
  const detailRequestNumber = useRef(0);
  const detailController = useRef<AbortController | null>(null);
  const approvalStatusRef = useRef<PairApprovalStatus | null>(null);
  const approvalStatusRequestNumber = useRef(0);
  const approvalStatusController = useRef<AbortController | null>(null);
  const approvalButtonRef = useRef<HTMLButtonElement>(null);
  const restoreApprovalButtonFocus = useRef(false);
  const createRequestNumber = useRef(0);
  const createController = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  // A list request begun before creation may return without the new project.
  // Keep successful creations discoverable until explicit page navigation.
  const visibleProjects = [
    ...locallyCreatedProjects.filter((item) => !projects.some((project) => project.id === item.id)),
    ...projects,
  ];
  // A background list refresh is not navigation. Keep the open editor even when
  // the refreshed page is empty or no longer contains this project.
  const selectedProject =
    visibleProjects.find((project) => project.id === selectedProjectId) ?? selectedProjectSnapshot;
  const currentDocument = documents?.[selectedKind] ?? null;
  const editorBytes = contentBytes(editorContent);
  const editorIsOversize = editorBytes > MAX_DOCUMENT_BYTES;
  const editorIsDirty = currentDocument !== null && editorContent !== currentDocument.content;
  const pairHeadsMatchVisibleDocuments = approvalHeadsMatchDocuments(approvalStatus, documents);
  const pairReviewMatchesVisibleDocuments = Boolean(
    !pairConflict ||
    (documents &&
      sameSavedPair(pairConflict.latest, { project: documents.project, agents: documents.agents })),
  );
  const pairCanBeApproved = Boolean(
    selectedProject &&
    documents &&
    approvalStatus &&
    pairHeadsMatchVisibleDocuments &&
    pairReviewMatchesVisibleDocuments &&
    !approvalStatus.approved &&
    !approvalStatusLoading &&
    !approvalStatusError &&
    !approvalBusy &&
    !saveBusy &&
    !taskEditsPending &&
    !pairRefreshBusy &&
    !documentsLoading &&
    !editorIsDirty &&
    Boolean(csrfToken) &&
    (pairConflict === null ||
      (reviewedPairKinds.size === pairDocumentOptions.length && pairReviewConfirmed)),
  );
  const currentPairConflictDocument = pairConflict?.latest[pairConflictKind] ?? null;
  const previousPairConflictDocument = pairConflict?.previous[pairConflictKind] ?? null;

  useLayoutEffect(() => {
    if (compareContent) {
      restoreComparisonFocus.current = false;
      const heading = comparisonHeadingRef.current;
      if (!heading) return;
      heading.scrollIntoView({ block: "start" });
      heading.focus({ preventScroll: true });
      return;
    }

    if (restoreComparisonFocus.current) {
      restoreComparisonFocus.current = false;
      const trigger = comparisonTriggerRef.current;
      comparisonTriggerRef.current = null;
      if (trigger?.isConnected && trigger.closest("[hidden]") === null) {
        trigger.focus();
      } else {
        historyToggleRef.current?.focus();
      }
      return;
    }

    comparisonTriggerRef.current = null;
  }, [compareContent]);

  useLayoutEffect(() => {
    if (approvalBusy || !restoreApprovalButtonFocus.current) return;
    restoreApprovalButtonFocus.current = false;
    if (document.activeElement === document.body) {
      approvalButtonRef.current?.focus();
    }
  }, [approvalBusy]);

  useEffect(() => {
    onPendingChange(editorIsDirty || saveBusy || taskEditsPending);
  }, [editorIsDirty, saveBusy, taskEditsPending, onPendingChange]);

  useEffect(() => {
    if (!editorIsDirty && !saveBusy && !approvalBusy && !taskEditsPending) return;
    const warnOnExit = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnOnExit);
    return () => window.removeEventListener("beforeunload", warnOnExit);
  }, [approvalBusy, editorIsDirty, saveBusy, taskEditsPending]);

  function updateEditorContent(content: string): void {
    editorContentRef.current = content;
    editorChangeNumber.current += 1;
    setEditorContent(content);
  }

  function updatePairConflict(next: PairConflict | null): void {
    pairConflictRef.current = next;
    setPairConflict(next);
  }

  function updatePairReviewState(kinds: Set<PairKind>, confirmed: boolean): void {
    const nextKinds = new Set(kinds);
    reviewedPairKindsRef.current = nextKinds;
    pairReviewConfirmedRef.current = confirmed;
    setReviewedPairKinds(nextKinds);
    setPairReviewConfirmed(confirmed);
  }

  function updatePairConflictTarget(latest: PairDocuments): void {
    const existing = pairConflictRef.current;
    if (!existing) return;
    const reconciledLatest = {
      project: reconcileDocumentHead(existing.latest.project, latest.project),
      agents: reconcileDocumentHead(existing.latest.agents, latest.agents),
    };
    if (sameSavedPair(existing.latest, reconciledLatest)) return;
    // `previous` is the immutable pair that was submitted for approval. Only
    // the compare target advances as newer saved heads arrive.
    updatePairConflict({ previous: existing.previous, latest: reconciledLatest });
    updatePairReviewState(new Set(), false);
  }

  function updateDocuments(
    next:
      ProjectDocuments | null | ((previous: ProjectDocuments | null) => ProjectDocuments | null),
  ): ProjectDocuments | null {
    const current = documentsRef.current;
    const candidate = typeof next === "function" ? next(current) : next;
    const updated =
      current !== null && candidate !== null
        ? reconcileDocumentHeads(current, candidate)
        : candidate;
    documentsRef.current = updated;
    setDocumentsState(updated);
    if (updated) {
      updatePairConflictTarget({ project: updated.project, agents: updated.agents });
    }
    return updated;
  }

  function observeBacklogTaskSnapshot(snapshot: BacklogTaskDocument): void {
    if (
      selectionRef.current.projectId !== selectedProjectId ||
      selectionRef.current.kind !== "backlog"
    ) {
      return;
    }
    const currentDocuments = documentsRef.current;
    if (!currentDocuments) return;
    const currentBacklog = currentDocuments.backlog;
    if (snapshot.revision_number <= currentBacklog.revision_number) return;

    const updatedDocuments = updateDocuments((previous) => {
      if (!previous || previous.backlog.revision_number >= snapshot.revision_number)
        return previous;
      return {
        ...previous,
        backlog: {
          ...previous.backlog,
          revision_number: snapshot.revision_number,
          content_sha256: snapshot.content_sha256,
          content: snapshot.content,
          origin: "human",
          template_source: null,
          template_sha256: null,
        },
      };
    });
    const visibleBacklog = updatedDocuments?.backlog;
    if (!visibleBacklog || visibleBacklog.revision_number < snapshot.revision_number) return;

    if (editorContentRef.current === currentBacklog.content) {
      updateEditorContent(visibleBacklog.content);
      setStaleEditorRevision(null);
    } else if (visibleBacklog.revision_number > currentBacklog.revision_number) {
      setStaleEditorRevision((previous) => previous ?? currentBacklog.revision_number);
    }

    invalidateHistory();
    if (historyOpenRef.current) {
      void reloadCurrentHistoryRef.current?.(visibleBacklog);
    }
  }

  async function loadPairApprovalStatus(
    projectId: string,
    cursor: string | null = null,
  ): Promise<void> {
    approvalStatusController.current?.abort();
    const controller = new AbortController();
    approvalStatusController.current = controller;
    const requestNumber = ++approvalStatusRequestNumber.current;
    // A head/status refresh can supersede a pending history page. Its aborted
    // finally block will not run as the current request; clear both locks here.
    setApprovalStatusLoading(false);
    setApprovalHistoryLoading(false);
    if (cursor === null) {
      setApprovalStatusLoading(true);
    } else {
      setApprovalHistoryLoading(true);
    }
    setApprovalStatusError("");
    try {
      const next = await apiRequest<PairApprovalStatus>(pairApprovalPath(projectId, cursor), {
        signal: controller.signal,
      });
      if (
        requestNumber !== approvalStatusRequestNumber.current ||
        selectionRef.current.projectId !== projectId
      ) {
        return;
      }
      const previousStatus = approvalStatusRef.current;
      const reconciled = reconcilePairApprovalStatus(previousStatus, next);
      let result = reconciled;
      if (cursor !== null && previousStatus) {
        const seen = new Set(previousStatus.approvals.map((item) => item.id));
        result = {
          ...reconciled,
          approvals: [
            ...previousStatus.approvals,
            ...next.approvals.filter((item) => !seen.has(item.id)),
          ],
          approval_offset: 0,
        };
      }
      approvalStatusRef.current = result;
      setApprovalStatus(result);
      if (cursor === null) {
        setApprovalCheckedAt(new Date().toLocaleTimeString());
      }
    } catch (approvalLoadFailure) {
      if (
        requestNumber !== approvalStatusRequestNumber.current ||
        controller.signal.aborted ||
        selectionRef.current.projectId !== projectId
      ) {
        return;
      }
      if (approvalLoadFailure instanceof ApiError && approvalLoadFailure.status === 401) {
        onSessionExpired();
      } else {
        setApprovalStatusError(errorMessage(approvalLoadFailure));
      }
    } finally {
      if (requestNumber === approvalStatusRequestNumber.current) {
        if (cursor === null) {
          setApprovalStatusLoading(false);
        } else {
          setApprovalHistoryLoading(false);
        }
        if (approvalStatusController.current === controller)
          approvalStatusController.current = null;
      }
    }
  }

  function invalidateDetailRequest(): void {
    detailRequestNumber.current += 1;
    detailController.current?.abort();
    detailController.current = null;
  }

  function invalidateHistory(): void {
    historyRequestNumber.current += 1;
    historyRevisionRef.current = null;
    setHistory(null);
    setHistoryLoading(false);
    setHistoryError("");
  }

  async function loadProjectDocuments(projectId: string, kind: DocumentKind): Promise<void> {
    invalidateDetailRequest();
    approvalStatusRequestNumber.current += 1;
    approvalStatusController.current?.abort();
    approvalStatusController.current = null;
    setPairRefreshBusy(false);
    const requestNumber = ++documentRequestNumber.current;
    documentController.current?.abort();
    const controller = new AbortController();
    documentController.current = controller;
    const changingProject = documentsProjectIdRef.current !== projectId;
    const headsAtRequest = changingProject ? null : documentsRef.current;
    documentsProjectIdRef.current = projectId;
    if (changingProject) {
      updateDocuments(null);
      setStaleEditorRevision(null);
      updatePairConflict(null);
      approvalStatusRef.current = null;
      updatePairReviewState(new Set(), false);
    }
    setDocumentsError("");
    setDocumentsLoading(true);
    historyRevisionRef.current = null;
    setHistory(null);
    setHistoryOpen(false);
    historyOpenRef.current = false;
    setHistoryLoading(false);
    historyRequestNumber.current += 1;
    setCompareContent(null);
    setApprovalStatus(null);
    setApprovalStatusLoading(false);
    setApprovalHistoryLoading(false);
    setApprovalStatusError("");
    setApprovalError("");
    setApprovalNotice("");
    setApprovalValidationErrors({});
    updatePairReviewState(new Set(), false);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");

    try {
      const response = await apiRequest<ProjectDocument[]>(
        `/api/projects/${encodeURIComponent(projectId)}/documents`,
        { signal: controller.signal },
      );
      if (requestNumber !== documentRequestNumber.current) return;
      const byKind = Object.fromEntries(response.map((item) => [item.kind, item])) as Partial<
        Record<DocumentKind, ProjectDocument>
      >;
      if (!byKind.project || !byKind.agents || !byKind.backlog) {
        throw new Error("This project does not have all three draft documents yet.");
      }
      const complete = byKind as ProjectDocuments;
      const latest = updateDocuments(complete);
      if (latest) {
        const activeKind = selectionRef.current.kind;
        const previousHead = headsAtRequest?.[activeKind] ?? null;
        if (!previousHead || editorContentRef.current === previousHead.content) {
          updateEditorContent(latest[activeKind].content);
          setStaleEditorRevision(null);
        } else if (latest[activeKind].revision_number > previousHead.revision_number) {
          setStaleEditorRevision((previous) => previous ?? previousHead.revision_number);
        }
      } else {
        updateEditorContent(complete[kind].content);
      }
      void loadPairApprovalStatus(projectId);
    } catch (loadFailure) {
      if (controller.signal.aborted || requestNumber !== documentRequestNumber.current) return;
      if (loadFailure instanceof ApiError && loadFailure.status === 401) {
        onSessionExpired();
      } else {
        setDocumentsError(errorMessage(loadFailure));
      }
    } finally {
      if (requestNumber === documentRequestNumber.current) setDocumentsLoading(false);
    }
  }

  async function refreshCurrentDraftPair(): Promise<void> {
    if (
      !selectedProjectId ||
      !documents ||
      saveBusy ||
      taskEditsPending ||
      approvalBusy ||
      pairRefreshBusy
    ) {
      return;
    }
    const projectId = selectedProjectId;
    const kindAtRefreshStart = selectionRef.current.kind;
    const historyRevisionAtRefreshStart = historyRevisionRef.current;
    const documentsAtRefreshStart = documentsRef.current;
    // History may still be resolving against the old head. Stop it *before*
    // the pair request, so it cannot install an old editor base mid-refresh.
    invalidateHistory();
    const historyRequestNumberAtStart = historyRequestNumber.current;
    // A detail response started on the old head cannot reapply after this
    // refresh advances the editor. Requests begun during the fetch are also
    // invalidated when its new heads arrive below.
    invalidateDetailRequest();
    const requestNumber = ++documentRequestNumber.current;
    documentController.current?.abort();
    const controller = new AbortController();
    documentController.current = controller;
    setPairRefreshBusy(true);
    setApprovalStatus(null);
    setApprovalStatusError("");
    setApprovalCheckedAt("");
    approvalStatusRequestNumber.current += 1;
    approvalStatusController.current?.abort();
    approvalStatusController.current = null;
    setApprovalStatusLoading(false);
    setApprovalHistoryLoading(false);
    try {
      const response = await apiRequest<ProjectDocument[]>(
        `/api/projects/${encodeURIComponent(projectId)}/documents`,
        { signal: controller.signal },
      );
      if (
        controller.signal.aborted ||
        requestNumber !== documentRequestNumber.current ||
        selectionRef.current.projectId !== projectId
      )
        return;
      const byKind = Object.fromEntries(response.map((item) => [item.kind, item])) as Partial<
        Record<DocumentKind, ProjectDocument>
      >;
      if (!byKind.project || !byKind.agents || !byKind.backlog) {
        throw new Error("This project does not have all three draft documents yet.");
      }
      const next = byKind as ProjectDocuments;
      const currentDocuments = documentsRef.current;
      if (!currentDocuments) return;
      // The editor may have switched tabs while the pair was loading. Compare
      // its live kind against the latest known head, not the tab or head that
      // happened to be selected when the request began.
      const activeKind = selectionRef.current.kind;
      const previousHead = currentDocuments[activeKind];
      const latest = reconcileDocumentHeads(currentDocuments, next);
      invalidateDetailRequest();
      // Reconcile again at the ref boundary: another source may have advanced a
      // head since the response snapshot was first compared.
      const reconciled = updateDocuments(latest) ?? latest;
      // A refresh must never erase unsaved text, including typing begun while
      // the request was in flight. A clean editor follows the new saved head.
      if (editorContentRef.current === previousHead.content) {
        updateEditorContent(reconciled[activeKind].content);
        setStaleEditorRevision(null);
      } else if (reconciled[activeKind].revision_number !== previousHead.revision_number) {
        setStaleEditorRevision((previous) => previous ?? previousHead.revision_number);
      }
      setApprovalNotice("");
      void loadPairApprovalStatus(projectId);
      const visibleHistoryRevision = historyRevisionRef.current;
      const noHistoryRequestSinceRefreshStarted =
        historyRequestNumber.current === historyRequestNumberAtStart;
      const historyHeadAtRefreshStart =
        activeKind === kindAtRefreshStart && historyRevisionAtRefreshStart !== null
          ? historyRevisionAtRefreshStart
          : (documentsAtRefreshStart?.[activeKind].revision_number ?? previousHead.revision_number);
      const currentHeadRevision = reconciled[activeKind].revision_number;
      const visibleHistoryIsStale =
        visibleHistoryRevision !== null && visibleHistoryRevision !== currentHeadRevision;
      const invalidatedHistoryHeadChanged =
        visibleHistoryRevision === null &&
        noHistoryRequestSinceRefreshStarted &&
        historyHeadAtRefreshStart !== currentHeadRevision;
      if (historyOpenRef.current && (visibleHistoryIsStale || invalidatedHistoryHeadChanged)) {
        if (visibleHistoryRevision !== null) invalidateHistory();
        setHistoryError("Saved drafts changed. Reload history to review the current head.");
      } else if (
        historyOpenRef.current &&
        visibleHistoryRevision === null &&
        noHistoryRequestSinceRefreshStarted
      ) {
        // The pair refresh cleared cached history. If the active saved head did
        // not move, refill the still-open panel instead of claiming it changed.
        void reloadCurrentHistoryRef.current?.(reconciled[activeKind]);
      }
    } catch (failure) {
      if (controller.signal.aborted || requestNumber !== documentRequestNumber.current) return;
      if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpired();
      } else {
        setApprovalStatusError(`Saved drafts could not be refreshed: ${errorMessage(failure)}`);
        if (historyOpenRef.current) {
          setHistoryError(
            "Saved drafts could not be refreshed. Retry history to review this head.",
          );
        }
      }
    } finally {
      if (requestNumber === documentRequestNumber.current) setPairRefreshBusy(false);
    }
  }

  useEffect(() => {
    function refreshOnReturn(): void {
      if (
        document.visibilityState === "visible" &&
        selectedProjectId &&
        documents &&
        !saveBusy &&
        !taskEditsPending &&
        !approvalBusy &&
        !pairRefreshBusy
      ) {
        void refreshCurrentDraftPair();
      }
    }
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => document.removeEventListener("visibilitychange", refreshOnReturn);
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      createRequestNumber.current += 1;
      createController.current?.abort();
      createController.current = null;
      documentRequestNumber.current += 1;
      documentController.current?.abort();
      historyRequestNumber.current += 1;
      detailRequestNumber.current += 1;
      detailController.current?.abort();
      approvalStatusRequestNumber.current += 1;
      approvalStatusController.current?.abort();
    };
  }, []);

  async function createProject(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (saveBusy || taskEditsPending || approvalBusy || editorIsDirty || createBusy) return;
    const selectionAtRequest = selectionRef.current;
    const editorAtRequest = editorChangeNumber.current;
    const requestNumber = ++createRequestNumber.current;
    createController.current?.abort();
    const controller = new AbortController();
    createController.current = controller;
    setCreateBusy(true);
    setCreateError("");
    setCreateNotice("");
    try {
      const created = await apiRequest<ProjectSummary>("/api/projects", {
        method: "POST",
        csrfToken,
        body: { name: newProjectName },
        signal: controller.signal,
      });
      if (
        !mounted.current ||
        requestNumber !== createRequestNumber.current ||
        controller.signal.aborted
      ) {
        return;
      }
      onProjectCreated(created);
      setLocallyCreatedProjects((current) => [
        created,
        ...current.filter((item) => item.id !== created.id),
      ]);
      setNewProjectName("");
      if (
        selectionRef.current !== selectionAtRequest ||
        editorChangeNumber.current !== editorAtRequest ||
        editorContentRef.current !== (documents?.[selectedKind]?.content ?? "") ||
        saveBusy ||
        approvalBusy
      ) {
        setCreateNotice(
          `${created.name} was created. Finish your current draft before opening it.`,
        );
        return;
      }
      setSelectedKind("project");
      setSelectedProjectId(created.id);
      setSelectedProjectSnapshot(created);
      selectionRef.current = { projectId: created.id, kind: "project" };
      setCreateError("");
      void loadProjectDocuments(created.id, "project");
    } catch (createFailure) {
      if (
        !mounted.current ||
        requestNumber !== createRequestNumber.current ||
        controller.signal.aborted
      ) {
        return;
      }
      if (createFailure instanceof ApiError && createFailure.status === 401) {
        onSessionExpired();
      } else {
        setCreateError(errorMessage(createFailure));
      }
    } finally {
      if (mounted.current && requestNumber === createRequestNumber.current) {
        setCreateBusy(false);
      }
      if (createController.current === controller) createController.current = null;
    }
  }

  function projectBaseClass(selected: boolean): string {
    return `flex min-h-12 w-full min-w-0 items-center justify-between gap-3 rounded-lg border px-3 py-3 text-left text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
      selected
        ? "border-accent/60 bg-accent/10 text-foreground"
        : "border-line bg-canvas text-foreground hover:border-accent/40"
    }`;
  }

  function selectProject(project: ProjectSummary): void {
    if (saveBusy || taskEditsPending || approvalBusy || documentsLoading || editorIsDirty) return;
    if (project.id === selectedProjectId && documents) return;
    setSelectedProjectId(project.id);
    setSelectedProjectSnapshot(project);
    setSelectedKind("project");
    selectionRef.current = { projectId: project.id, kind: "project" };
    historyRevisionRef.current = null;
    setHistory(null);
    setHistoryOpen(false);
    historyOpenRef.current = false;
    setHistoryLoading(false);
    historyRequestNumber.current += 1;
    setCompareContent(null);
    void loadProjectDocuments(project.id, "project");
  }

  function changeProjectPage(offset: number): void {
    if (
      saveBusy ||
      taskEditsPending ||
      approvalBusy ||
      createBusy ||
      documentsLoading ||
      editorIsDirty
    ) {
      return;
    }
    // A page change is navigation, not a background refresh. Forget the old selection
    // before the parent swaps lists, so returning to that page cannot resurrect it.
    documentRequestNumber.current += 1;
    documentController.current?.abort();
    invalidateDetailRequest();
    invalidateHistory();
    setSelectedProjectId(null);
    setSelectedProjectSnapshot(null);
    setLocallyCreatedProjects([]);
    selectionRef.current = { projectId: null, kind: "project" };
    setSelectedKind("project");
    updateDocuments(null);
    documentsProjectIdRef.current = null;
    setDocumentsError("");
    setApprovalStatus(null);
    approvalStatusRef.current = null;
    setApprovalStatusError("");
    setApprovalStatusLoading(false);
    setApprovalHistoryLoading(false);
    approvalStatusRequestNumber.current += 1;
    approvalStatusController.current?.abort();
    approvalStatusController.current = null;
    updatePairConflict(null);
    updatePairReviewState(new Set(), false);
    setDocumentsLoading(false);
    updateEditorContent("");
    setHistoryOpen(false);
    historyOpenRef.current = false;
    setCompareContent(null);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
    onProjectPageChange(offset);
  }

  function selectDocument(kind: DocumentKind): void {
    if (saveBusy || taskEditsPending || approvalBusy || editorIsDirty || !documents) return;
    invalidateDetailRequest();
    setSelectedKind(kind);
    if (kind === "backlog") setBacklogPanel("tasks");
    selectionRef.current = { projectId: selectedProjectId, kind };
    setStaleEditorRevision(null);
    updateEditorContent(documents[kind].content);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
    historyRevisionRef.current = null;
    setHistory(null);
    setHistoryOpen(false);
    historyOpenRef.current = false;
    setHistoryLoading(false);
    setHistoryError("");
    setCompareContent(null);
    historyRequestNumber.current += 1;
  }

  function handleDocumentTabKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentKind: DocumentKind,
  ): void {
    const currentIndex = documentOptions.findIndex((option) => option.kind === currentKind);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % documentOptions.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + documentOptions.length) % documentOptions.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = documentOptions.length - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextKind = documentOptions[nextIndex].kind;
    selectDocument(nextKind);
    document.getElementById(`${instanceId}-document-tab-${nextKind}`)?.focus();
  }

  async function fetchHistory(
    projectId: string,
    kind: DocumentKind,
    revisionOffset: number,
    proposalCursor: string | null,
  ): Promise<DocumentHistory> {
    return apiRequest<DocumentHistory>(
      historyPath(projectId, kind, revisionOffset, proposalCursor),
    );
  }

  async function loadHistory(
    append: "none" | "revisions" | "proposals" = "none",
    force = false,
    knownHead: ProjectDocument | null = currentDocument,
  ): Promise<void> {
    if (!selectedProject || (historyLoading && !force)) return;
    const projectId = selectedProject.id;
    const kind = selectedKind;
    const editorAtRequest = editorChangeNumber.current;
    const revisionOffset = append === "revisions" ? (history?.revisions.length ?? 0) : 0;
    const proposalCursor = append === "proposals" ? (history?.proposal_next_cursor ?? null) : null;
    if (append === "proposals" && proposalCursor === null) {
      setHistoryError("Conflict proposal history must be reloaded before it can continue.");
      return;
    }
    const requestNumber = ++historyRequestNumber.current;
    if (force) {
      historyRevisionRef.current = null;
      setHistory(null);
    }
    setHistoryLoading(true);
    setHistoryError("");
    try {
      let next = await fetchHistory(projectId, kind, revisionOffset, proposalCursor);
      if (requestNumber !== historyRequestNumber.current) return;
      if (
        append !== "none" &&
        history &&
        history.current_revision_number !== next.current_revision_number
      ) {
        // Offsets shift when another tab writes. Restart rather than splice incompatible pages.
        next = await fetchHistory(projectId, kind, 0, null);
      }
      if (requestNumber !== historyRequestNumber.current) return;
      const currentSavedHead = documentsRef.current?.[kind] ?? knownHead;
      if (currentSavedHead && next.current_revision_number < currentSavedHead.revision_number) {
        throw new Error("Saved drafts changed. Reload history to review the current head.");
      }
      if (knownHead && next.current_revision_number > knownHead.revision_number) {
        const refreshedHead = await apiRequest<ProjectDocument>(documentPath(projectId, kind));
        if (requestNumber !== historyRequestNumber.current) return;
        if (
          refreshedHead.id !== knownHead.id ||
          refreshedHead.kind !== kind ||
          refreshedHead.revision_number < next.current_revision_number
        ) {
          throw new Error("History moved ahead of the saved draft. Reload history to try again.");
        }
        const latestKnownHead = documentsRef.current?.[kind] ?? knownHead;
        if (latestKnownHead.revision_number > next.current_revision_number) {
          throw new Error("Saved drafts changed. Reload history to review the current head.");
        }
        const latestHead = reconcileDocumentHead(latestKnownHead, refreshedHead);
        invalidateDetailRequest();
        const refreshedDocuments = updateDocuments((previous) =>
          previous ? { ...previous, [kind]: latestHead } : previous,
        );
        const visibleHead = refreshedDocuments?.[kind] ?? latestHead;
        void loadPairApprovalStatus(projectId);
        // A clean editor follows the newly discovered saved head. Text entered
        // while the request was in flight must remain untouched for review.
        if (editorContentRef.current === visibleHead.content) {
          setStaleEditorRevision(null);
        } else if (
          editorAtRequest === editorChangeNumber.current &&
          editorContentRef.current === knownHead.content
        ) {
          updateEditorContent(visibleHead.content);
          setStaleEditorRevision(null);
        } else {
          setStaleEditorRevision((previous) => previous ?? knownHead.revision_number);
        }
        // The history snapshot was r2, but this detail request may already
        // have observed r3. Keep r3 and the editor's original dirty base; never
        // publish the incompatible r2 history beside it.
        if (visibleHead.revision_number !== next.current_revision_number) {
          throw new Error("Saved drafts changed. Reload history to review the current head.");
        }
      }
      if (selectionRef.current.projectId !== projectId || selectionRef.current.kind !== kind)
        return;
      historyRevisionRef.current = next.current_revision_number;
      setHistory((previous) => {
        if (
          append === "revisions" &&
          previous?.current_revision_number === next.current_revision_number
        ) {
          return {
            ...next,
            revisions: [...previous.revisions, ...next.revisions],
            proposals: previous.proposals,
            proposal_cursor: previous.proposal_cursor,
            proposal_next_cursor: previous.proposal_next_cursor,
            proposal_has_more: previous.proposal_has_more,
          };
        }
        if (
          append === "proposals" &&
          previous?.current_revision_number === next.current_revision_number
        ) {
          const previousProposalIds = new Set(previous.proposals.map((proposal) => proposal.id));
          return {
            ...next,
            revisions: previous.revisions,
            proposals: [
              ...previous.proposals,
              ...next.proposals.filter((proposal) => !previousProposalIds.has(proposal.id)),
            ],
            revision_has_more: previous.revision_has_more,
          };
        }
        return next;
      });
    } catch (historyFailure) {
      if (requestNumber !== historyRequestNumber.current) return;
      if (historyFailure instanceof ApiError && historyFailure.status === 401) {
        onSessionExpired();
      } else {
        historyRevisionRef.current = null;
        setHistory(null);
        setCompareContent(null);
        setHistoryError(errorMessage(historyFailure));
      }
    } finally {
      if (requestNumber === historyRequestNumber.current) setHistoryLoading(false);
    }
  }

  useEffect(() => {
    reloadCurrentHistoryRef.current = (knownHead) => loadHistory("none", true, knownHead);
  });

  async function toggleHistory(): Promise<void> {
    if (saveBusy || approvalBusy) return;
    if (historyOpen) {
      setHistoryOpen(false);
      historyOpenRef.current = false;
      return;
    }
    setHistoryOpen(true);
    historyOpenRef.current = true;
    if (!history) await loadHistory();
  }

  async function fetchRevision(
    projectId: string,
    kind: DocumentKind,
    revisionNumber: number,
    signal: AbortSignal,
  ): Promise<DocumentRevision> {
    return apiRequest<DocumentRevision>(
      `${documentPath(projectId, kind)}/revisions/${revisionNumber}`,
      { signal },
    );
  }

  async function fetchProposal(
    projectId: string,
    kind: DocumentKind,
    proposalId: string,
    signal: AbortSignal,
  ): Promise<ConflictProposal> {
    return apiRequest<ConflictProposal>(
      `${documentPath(projectId, kind)}/proposals/${encodeURIComponent(proposalId)}`,
      { signal },
    );
  }

  function beginDetailRequest(): {
    projectId: string;
    kind: DocumentKind;
    requestNumber: number;
    controller: AbortController;
  } | null {
    if (!selectedProject) return null;
    detailController.current?.abort();
    const controller = new AbortController();
    detailController.current = controller;
    return {
      projectId: selectedProject.id,
      kind: selectedKind,
      requestNumber: ++detailRequestNumber.current,
      controller,
    };
  }

  async function compareRevision(
    revision: RevisionSummary,
    trigger: HTMLButtonElement,
  ): Promise<void> {
    const request = beginDetailRequest();
    if (!request) return;
    setHistoryError("");
    try {
      const detail = await fetchRevision(
        request.projectId,
        request.kind,
        revision.revision_number,
        request.controller.signal,
      );
      if (request.requestNumber !== detailRequestNumber.current) return;
      comparisonTriggerRef.current = trigger;
      setCompareContent({
        label: `Revision ${detail.revision_number}`,
        content: detail.content,
      });
    } catch (compareFailure) {
      if (
        request.requestNumber !== detailRequestNumber.current ||
        request.controller.signal.aborted
      ) {
        return;
      }
      if (compareFailure instanceof ApiError && compareFailure.status === 401) {
        onSessionExpired();
      } else {
        setHistoryError(errorMessage(compareFailure));
      }
    } finally {
      if (detailController.current === request.controller) detailController.current = null;
    }
  }

  async function compareProposal(
    proposal: ConflictProposalSummary,
    trigger: HTMLButtonElement,
  ): Promise<void> {
    const request = beginDetailRequest();
    if (!request) return;
    setHistoryError("");
    try {
      const detail = await fetchProposal(
        request.projectId,
        request.kind,
        proposal.id,
        request.controller.signal,
      );
      if (request.requestNumber !== detailRequestNumber.current) return;
      comparisonTriggerRef.current = trigger;
      setCompareContent({ label: "Conflict proposal", content: detail.content });
    } catch (compareFailure) {
      if (
        request.requestNumber !== detailRequestNumber.current ||
        request.controller.signal.aborted
      ) {
        return;
      }
      if (compareFailure instanceof ApiError && compareFailure.status === 401) {
        onSessionExpired();
      } else {
        setHistoryError(errorMessage(compareFailure));
      }
    } finally {
      if (detailController.current === request.controller) detailController.current = null;
    }
  }

  async function reapplyRevision(revision: RevisionSummary): Promise<void> {
    if (
      saveBusy ||
      taskEditsPending ||
      (editorIsDirty && !window.confirm("Replace unsaved editor text with this revision?"))
    )
      return;
    const editorAtRequest = editorChangeNumber.current;
    const request = beginDetailRequest();
    if (!request) return;
    setHistoryError("");
    try {
      const detail = await fetchRevision(
        request.projectId,
        request.kind,
        revision.revision_number,
        request.controller.signal,
      );
      if (request.requestNumber !== detailRequestNumber.current) return;
      if (editorAtRequest !== editorChangeNumber.current) {
        setHistoryError("Editor text changed while loading. Reapply again to replace it.");
        return;
      }
      updateEditorContent(detail.content);
      setStaleEditorRevision(null);
      setConflictNotice("Revision loaded into the editor. Save draft to create a new revision.");
      setSaveNotice("");
      setSaveError("");
    } catch (reapplyFailure) {
      if (
        request.requestNumber !== detailRequestNumber.current ||
        request.controller.signal.aborted
      ) {
        return;
      }
      if (reapplyFailure instanceof ApiError && reapplyFailure.status === 401) {
        onSessionExpired();
      } else {
        setHistoryError(errorMessage(reapplyFailure));
      }
    } finally {
      if (detailController.current === request.controller) detailController.current = null;
    }
  }

  async function reapplyProposal(proposal: ConflictProposalSummary): Promise<void> {
    if (
      saveBusy ||
      taskEditsPending ||
      (editorIsDirty && !window.confirm("Replace unsaved editor text with this conflict proposal?"))
    )
      return;
    const editorAtRequest = editorChangeNumber.current;
    const request = beginDetailRequest();
    if (!request) return;
    setHistoryError("");
    try {
      const detail = await fetchProposal(
        request.projectId,
        request.kind,
        proposal.id,
        request.controller.signal,
      );
      if (request.requestNumber !== detailRequestNumber.current) return;
      if (editorAtRequest !== editorChangeNumber.current) {
        setHistoryError("Editor text changed while loading. Reapply again to replace it.");
        return;
      }
      updateEditorContent(detail.content);
      setStaleEditorRevision(null);
      setConflictNotice(
        "Conflict text loaded into the editor. Save draft to create a new revision; nothing was approved.",
      );
      setSaveNotice("");
      setSaveError("");
    } catch (reapplyFailure) {
      if (
        request.requestNumber !== detailRequestNumber.current ||
        request.controller.signal.aborted
      ) {
        return;
      }
      if (reapplyFailure instanceof ApiError && reapplyFailure.status === 401) {
        onSessionExpired();
      } else {
        setHistoryError(errorMessage(reapplyFailure));
      }
    } finally {
      if (detailController.current === request.controller) detailController.current = null;
    }
  }

  async function saveDraft(): Promise<void> {
    if (
      !selectedProject ||
      !currentDocument ||
      saveBusy ||
      taskEditsPending ||
      approvalBusy ||
      pairRefreshBusy ||
      editorIsOversize
    )
      return;
    const projectId = selectedProject.id;
    const kind = selectedKind;
    const submittedContent = editorContent;
    // A dirty editor may have been based on an older head when a background
    // reload discovered another tab's save. Do not silently promote its write
    // to the new head: the server must record a conflict proposal instead.
    const expectedRevision = staleEditorRevision ?? currentDocument.revision_number;
    invalidateDetailRequest();
    // Any earlier history request may complete after the write. Its result cannot
    // describe the saved head, even when the panel happened to be loading already.
    historyRequestNumber.current += 1;
    setHistoryLoading(false);
    setSaveBusy(true);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
    setApprovalError("");
    setApprovalValidationErrors({});
    try {
      const saved = await apiRequest<ProjectDocument>(documentPath(projectId, kind), {
        method: "PUT",
        csrfToken,
        body: {
          expected_revision: expectedRevision,
          content: submittedContent,
        },
      });
      if (
        !mounted.current ||
        selectionRef.current.projectId !== projectId ||
        selectionRef.current.kind !== kind
      )
        return;
      const savedDocuments = updateDocuments((previous) =>
        previous?.[kind].id === saved.id ? { ...previous, [kind]: saved } : previous,
      );
      const visibleHead = savedDocuments?.[kind] ?? saved;
      if (editorContentRef.current === submittedContent) {
        updateEditorContent(visibleHead.content);
        setStaleEditorRevision(null);
      } else if (visibleHead.revision_number > saved.revision_number) {
        // This save succeeded, but another source already observed a later head.
        // Text entered after submission is based on this save, not that later head.
        setStaleEditorRevision((previous) => previous ?? saved.revision_number);
      } else {
        setStaleEditorRevision(null);
      }
      setSaveNotice(`Saved ${saved.filename} as revision ${saved.revision_number}.`);
      setApprovalNotice("");
      void loadPairApprovalStatus(projectId);
      // A save makes the cached history stale even if its panel is hidden. Drop
      // it now so reopening the panel cannot reuse a snapshot from the old head.
      invalidateHistory();
      if (historyOpen) {
        void loadHistory("none", true, visibleHead);
      }
    } catch (saveFailure) {
      if (!mounted.current) return;
      if (saveFailure instanceof ApiError && saveFailure.status === 401) {
        onSessionExpired();
      } else if (saveFailure instanceof ApiError && saveFailure.status === 409) {
        if (selectionRef.current.projectId !== projectId || selectionRef.current.kind !== kind)
          return;
        setConflictNotice(
          "Another tab saved a newer revision. Your attempted text was preserved as a conflict proposal.",
        );
        try {
          const conflict = saveFailure.payload as { latest?: ProjectDocument } | undefined;
          const knownHead = documentsRef.current?.[kind] ?? currentDocument;
          const latest =
            conflict?.latest?.id === knownHead.id && conflict.latest.kind === kind
              ? conflict.latest
              : await apiRequest<ProjectDocument>(documentPath(projectId, kind));
          if (selectionRef.current.projectId !== projectId || selectionRef.current.kind !== kind)
            return;
          invalidateDetailRequest();
          const latestDocuments = updateDocuments((previous) =>
            previous?.[kind].id === latest.id ? { ...previous, [kind]: latest } : previous,
          );
          const visibleHead = latestDocuments?.[kind] ?? latest;
          // Merely observing the newer head is not a reapply decision. Repeated
          // Save clicks must still use the editor's old base until the human
          // explicitly discards or reapplies the preserved proposal/revision.
          if (editorContentRef.current === visibleHead.content) {
            setStaleEditorRevision(null);
          } else {
            setStaleEditorRevision((previous) => previous ?? expectedRevision);
          }
          setApprovalStatusError("");
          void loadPairApprovalStatus(projectId);
          setHistoryOpen(true);
          historyOpenRef.current = true;
          // History may be slow. Release the save lock once the conflict head is
          // known so the user can discard or continue editing while it loads.
          void loadHistory("none", true, visibleHead);
        } catch {
          // Keep the attempted text in the editor; the saved proposal is available in History.
          setSaveError("The conflict was recorded, but the latest document view could not reload.");
        }
      } else {
        setSaveError(errorMessage(saveFailure));
      }
    } finally {
      if (mounted.current) setSaveBusy(false);
    }
  }

  async function approveSavedPair(): Promise<void> {
    const currentDocuments = documentsRef.current;
    const currentStatus = approvalStatusRef.current;
    const currentConflict = pairConflictRef.current;
    if (
      !pairCanBeApproved ||
      !selectedProject ||
      selectedProject.id !== selectionRef.current.projectId ||
      !currentDocuments ||
      !currentStatus ||
      currentStatus.approved ||
      !approvalHeadsMatchDocuments(currentStatus, currentDocuments) ||
      approvalStatusLoading ||
      Boolean(approvalStatusError) ||
      approvalBusy ||
      saveBusy ||
      taskEditsPending ||
      pairRefreshBusy ||
      documentsLoading ||
      editorContentRef.current !== currentDocuments[selectionRef.current.kind].content ||
      (currentConflict !== null &&
        (!sameSavedPair(currentConflict.latest, {
          project: currentDocuments.project,
          agents: currentDocuments.agents,
        }) ||
          reviewedPairKindsRef.current.size !== pairDocumentOptions.length ||
          !pairReviewConfirmedRef.current))
    ) {
      return;
    }
    const projectId = selectedProject.id;
    const beforeApproval: PairDocuments = {
      project: currentDocuments.project,
      agents: currentDocuments.agents,
    };
    const kindAtRequest = selectionRef.current.kind;
    restoreApprovalButtonFocus.current = document.activeElement === approvalButtonRef.current;
    setApprovalBusy(true);
    setApprovalError("");
    setApprovalNotice("");
    setApprovalValidationErrors({});
    try {
      const approval = await apiRequest<PairApprovalRecord>(
        `/api/projects/${encodeURIComponent(projectId)}/document-pair-approval`,
        {
          method: "POST",
          csrfToken,
          body: {
            expected_project_revision: beforeApproval.project.revision_number,
            expected_agents_revision: beforeApproval.agents.revision_number,
          },
        },
      );
      if (!mounted.current || selectionRef.current.projectId !== projectId) return;
      if (
        approval.project_revision_number !== beforeApproval.project.revision_number ||
        approval.agents_revision_number !== beforeApproval.agents.revision_number
      ) {
        setApprovalError(
          "The server response did not match the submitted saved pair. Refresh the drafts and status before continuing.",
        );
        void loadPairApprovalStatus(projectId);
        return;
      }
      const latestDocuments = documentsRef.current;
      if (!latestDocuments) return;
      const latestPair = { project: latestDocuments.project, agents: latestDocuments.agents };
      if (sameSavedPair(beforeApproval, latestPair)) {
        updatePairConflict(null);
        updatePairReviewState(new Set(), false);
        setApprovalNotice(
          `Approved PROJECT.md revision ${approval.project_revision_number} and AGENTS.md revision ${approval.agents_revision_number} as one saved pair.`,
        );
      } else {
        // The server approved the submitted tuple, but an asynchronous source
        // already found a later current pair. Keep the submitted baseline and
        // require review of that exact new target instead of showing a stale
        // approval as current.
        updatePairConflict({ previous: beforeApproval, latest: latestPair });
        setPairConflictKind(kindAtRequest === "agents" ? "agents" : "project");
        updatePairReviewState(new Set(), false);
        setApprovalNotice(
          `Approved PROJECT.md revision ${approval.project_revision_number} and AGENTS.md revision ${approval.agents_revision_number}; a later saved pair now needs review.`,
        );
        setConflictNotice(
          "Saved heads advanced after the approval request. Review the current pair before approving it.",
        );
      }
      void loadPairApprovalStatus(projectId);
    } catch (approvalFailure) {
      if (!mounted.current) return;
      if (approvalFailure instanceof ApiError && approvalFailure.status === 401) {
        onSessionExpired();
      } else if (approvalFailure instanceof ApiError && approvalFailure.status === 409) {
        if (selectionRef.current.projectId !== projectId) return;
        const latest = pairConflictFrom(approvalFailure);
        if (!latest) {
          setApprovalError(
            "The saved pair changed, but the latest revisions could not be read. Refresh the drafts before approving again.",
          );
          void loadPairApprovalStatus(projectId);
          return;
        }
        const initialConflictKind: PairKind = kindAtRequest === "agents" ? "agents" : "project";
        approvalStatusRequestNumber.current += 1;
        approvalStatusController.current?.abort();
        approvalStatusController.current = null;
        invalidateDetailRequest();
        const documentsAtConflict = documentsRef.current;
        const mergedDocuments = documentsAtConflict
          ? updateDocuments({
              ...documentsAtConflict,
              project: reconcileDocumentHead(documentsAtConflict.project, latest.project),
              agents: reconcileDocumentHead(documentsAtConflict.agents, latest.agents),
            })
          : null;
        // A concurrent history response may already know a head newer than this
        // 409 snapshot. The pair submitted in `beforeApproval` remains the
        // immutable comparison baseline while this target advances.
        const latestPair = mergedDocuments
          ? { project: mergedDocuments.project, agents: mergedDocuments.agents }
          : latest;
        if (
          (kindAtRequest === "project" || kindAtRequest === "agents") &&
          selectionRef.current.kind === kindAtRequest
        ) {
          if (editorContentRef.current === latestPair[kindAtRequest].content) {
            setStaleEditorRevision(null);
          } else if (editorContentRef.current === beforeApproval[kindAtRequest].content) {
            updateEditorContent(latestPair[kindAtRequest].content);
            setStaleEditorRevision(null);
          } else if (
            latestPair[kindAtRequest].revision_number !==
            beforeApproval[kindAtRequest].revision_number
          ) {
            setStaleEditorRevision(
              (previous) => previous ?? beforeApproval[kindAtRequest].revision_number,
            );
          }
        }
        updatePairConflict({ previous: beforeApproval, latest: latestPair });
        setPairConflictKind(initialConflictKind);
        updatePairReviewState(new Set(), false);
        setApprovalNotice("");
        setApprovalStatusError("");
        setConflictNotice(
          "A newer saved revision arrived before approval. Review both latest documents before approving the pair.",
        );
        void loadPairApprovalStatus(projectId);
      } else if (approvalFailure instanceof ApiError && approvalFailure.status === 422) {
        const fileErrors = parseApprovalValidationErrors(approvalFailure);
        if (fileErrors) {
          setApprovalValidationErrors(fileErrors);
          setApprovalError(
            "No approval was recorded. Resolve the document-specific starter issues and save new revisions.",
          );
        } else {
          setApprovalError(errorMessage(approvalFailure));
        }
      } else {
        setApprovalError(errorMessage(approvalFailure));
      }
    } finally {
      if (mounted.current) setApprovalBusy(false);
    }
  }

  function loadOlderApprovals(): void {
    if (!selectedProject || !approvalStatus || approvalHistoryLoading) return;
    if (!approvalStatus.approval_has_more || !approvalStatus.approval_next_cursor) return;
    void loadPairApprovalStatus(selectedProject.id, approvalStatus.approval_next_cursor);
  }

  return (
    <section
      aria-labelledby={`${instanceId}-projects-title`}
      className="grid gap-5 lg:grid-cols-[minmax(15rem,0.7fr)_minmax(0,1.5fr)]"
    >
      <div className="rounded-2xl border border-line bg-surface/95 p-5 sm:p-6">
        <div className="border-b border-line pb-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
            Private project drafts
          </p>
          <h2 className="mt-2 text-xl font-semibold" id={`${instanceId}-projects-title`}>
            Projects
          </h2>
          <p className="mt-2 text-sm leading-6 text-copy-muted">
            Each project begins with three editable drafts. Names are private labels, never
            workspace paths.
          </p>
        </div>

        <form className="mt-5 grid gap-3" onSubmit={(event) => void createProject(event)}>
          <label
            className="text-sm font-medium text-foreground"
            htmlFor={`${instanceId}-new-project-name`}
          >
            Project name
          </label>
          <input
            autoComplete="off"
            className="min-h-11 w-full rounded-lg border border-input-border bg-canvas px-3 py-2 text-sm text-foreground outline-none placeholder:text-copy-muted/70 focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            id={`${instanceId}-new-project-name`}
            maxLength={120}
            name="project-name"
            onChange={(event) => {
              setNewProjectName(event.target.value);
              setCreateError("");
            }}
            placeholder="e.g. Customer research plan"
            required
            value={newProjectName}
          />
          {createError ? (
            <p className="text-sm leading-5 text-red-200" role="alert">
              {createError}
            </p>
          ) : null}
          {createNotice ? (
            <p className="text-sm leading-5 text-accent" role="status">
              {createNotice}
            </p>
          ) : null}
          <button
            className="min-h-11 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={
              createBusy ||
              saveBusy ||
              taskEditsPending ||
              approvalBusy ||
              loading ||
              Boolean(loadError) ||
              !csrfToken ||
              editorIsDirty
            }
            type="submit"
          >
            {createBusy ? "Creating project…" : "Create project"}
          </button>
        </form>

        <div className="mt-6 border-t border-line pt-5">
          <div className="flex items-baseline justify-between gap-3">
            <h3 className="text-sm font-semibold text-foreground">
              {visibleProjects.length ? "Your project list" : "Project list"}
            </h3>
            <span className="font-mono text-[10px] uppercase tracking-wide text-copy-muted">
              {visibleProjects.length} {visibleProjects.length === 1 ? "project" : "projects"}
            </span>
          </div>
          {loading ? (
            <p aria-live="polite" className="py-5 text-sm text-copy-muted" role="status">
              Loading private projects…
            </p>
          ) : loadError ? (
            <p className="py-5 text-sm leading-6 text-copy-muted">
              Project access is unavailable until workspace loading succeeds.
            </p>
          ) : visibleProjects.length === 0 ? (
            <p className="py-5 text-sm leading-6 text-copy-muted">
              No projects yet. Create one to start with the three Markdown drafts.
            </p>
          ) : (
            <ul className="mt-3 grid gap-2">
              {visibleProjects.map((project) => (
                <li key={project.id}>
                  <button
                    aria-label={`Open project ${project.name}`}
                    aria-pressed={selectedProjectId === project.id}
                    className={projectBaseClass(selectedProjectId === project.id)}
                    disabled={
                      saveBusy ||
                      taskEditsPending ||
                      approvalBusy ||
                      documentsLoading ||
                      createBusy ||
                      editorIsDirty
                    }
                    onClick={() => selectProject(project)}
                    type="button"
                  >
                    <span className="min-w-0">
                      <span className="block break-words font-medium">{project.name}</span>
                      <span className="mt-1 block font-mono text-[10px] text-copy-muted">
                        Created {isoDate(project.created_at)}
                      </span>
                    </span>
                    <span aria-hidden="true" className="shrink-0 text-accent">
                      {selectedProjectId === project.id ? "Open" : "View"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {(projects.length === 100 || projectOffset > 0) && !loading && !loadError ? (
            <nav aria-label="Project pages" className="mt-4 flex flex-wrap gap-3">
              <button
                className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                disabled={
                  projectOffset === 0 ||
                  editorIsDirty ||
                  saveBusy ||
                  taskEditsPending ||
                  approvalBusy ||
                  createBusy ||
                  documentsLoading
                }
                onClick={() => changeProjectPage(Math.max(0, projectOffset - 100))}
                type="button"
              >
                Previous projects
              </button>
              <button
                className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                disabled={
                  projects.length < 100 ||
                  editorIsDirty ||
                  saveBusy ||
                  taskEditsPending ||
                  approvalBusy ||
                  createBusy ||
                  documentsLoading ||
                  projectOffset >= 999900
                }
                onClick={() => changeProjectPage(projectOffset + 100)}
                type="button"
              >
                Next projects
              </button>
            </nav>
          ) : null}
        </div>
      </div>

      <div className="min-w-0 rounded-2xl border border-line bg-surface/95 p-5 sm:p-6">
        {selectedProject && !projects.some((item) => item.id === selectedProject.id) ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
            <p className="text-sm text-copy-muted">
              This open project is not on the current list page.
            </p>
            <button
              className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50"
              disabled={
                editorIsDirty || taskEditsPending || saveBusy || approvalBusy || documentsLoading
              }
              onClick={() => {
                setSelectedProjectId(null);
                setSelectedProjectSnapshot(null);
                selectionRef.current = { projectId: null, kind: "project" };
                documentRequestNumber.current += 1;
                documentController.current?.abort();
                invalidateDetailRequest();
                invalidateHistory();
                updateDocuments(null);
                documentsProjectIdRef.current = null;
                setApprovalStatus(null);
                approvalStatusRef.current = null;
                setApprovalStatusError("");
                setApprovalStatusLoading(false);
                setApprovalHistoryLoading(false);
                approvalStatusRequestNumber.current += 1;
                approvalStatusController.current?.abort();
                approvalStatusController.current = null;
                updatePairConflict(null);
                updatePairReviewState(new Set(), false);
              }}
              type="button"
            >
              Close project
            </button>
          </div>
        ) : null}
        {!selectedProject ? (
          <div className="grid min-h-56 content-center justify-items-start">
            <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-accent">
              Draft workspace
            </p>
            <h3 className="mt-3 text-xl font-semibold">Choose a project to review its drafts</h3>
            <p className="mt-2 max-w-xl text-sm leading-6 text-copy-muted">
              Saved revisions and rejected conflict text remain in private project history. No
              approval, chat, export, or runner actions are available here.
            </p>
          </div>
        ) : documentsLoading ? (
          <p aria-live="polite" className="py-12 text-sm text-copy-muted" role="status">
            Loading {selectedProject.name}&apos;s private drafts…
          </p>
        ) : documentsError ? (
          <div className="grid gap-3 py-8" role="alert">
            <h3 className="text-lg font-semibold">Drafts could not be loaded</h3>
            <p className="text-sm leading-6 text-red-200">{documentsError}</p>
            <button
              className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-fit"
              onClick={() => {
                void loadProjectDocuments(selectedProject.id, selectedKind);
              }}
              type="button"
            >
              Retry loading drafts
            </button>
          </div>
        ) : documents && currentDocument ? (
          <div className="min-w-0">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-5">
              <div className="min-w-0">
                <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                  {selectedProject.name}
                </p>
                <h3 className="mt-2 break-words text-xl font-semibold">Planning drafts</h3>
                <p className="mt-2 text-xs leading-5 text-copy-muted">
                  Project created {isoDate(selectedProject.created_at)} · changes create immutable
                  drafts
                </p>
              </div>
              <span className="rounded-full border border-line bg-canvas px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide text-copy-muted">
                Human review · no chat
              </span>
            </div>

            <section
              aria-labelledby={`${instanceId}-pair-approval-title`}
              className="mt-5 grid min-w-0 gap-4 rounded-xl border border-line bg-canvas p-4 sm:p-5"
            >
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-copy-muted">
                    First-stage review
                  </p>
                  <h4
                    className="mt-1 text-lg font-semibold"
                    id={`${instanceId}-pair-approval-title`}
                  >
                    Approve the saved document pair
                  </h4>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-copy-muted">
                    One human action approves exactly the current PROJECT.md and AGENTS.md saved
                    revisions. Any later save needs a new review. This does not approve the backlog
                    or include chat, model proposals, or exports.
                  </p>
                </div>
                <span
                  aria-live="polite"
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
                    approvalStatus?.approved
                      ? "border-accent/35 bg-accent/10 text-accent"
                      : "border-line bg-surface-raised text-copy-muted"
                  }`}
                >
                  {approvalStatusLoading || pairRefreshBusy
                    ? "Refreshing approval status…"
                    : approvalStatusError
                      ? "Approval status unavailable"
                      : approvalStatus?.approved
                        ? "Approved at last check"
                        : approvalStatus?.latest_approval
                          ? "Re-review required"
                          : approvalStatus
                            ? "Not yet approved"
                            : "Approval status unavailable"}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={
                    saveBusy ||
                    taskEditsPending ||
                    approvalBusy ||
                    pairRefreshBusy ||
                    documentsLoading
                  }
                  onClick={() => void refreshCurrentDraftPair()}
                  type="button"
                >
                  {pairRefreshBusy ? "Reloading saved pair…" : "Reload saved pair and status"}
                </button>
                <p className="text-xs leading-5 text-copy-muted">
                  {approvalCheckedAt ? `Last checked ${approvalCheckedAt}. ` : ""}
                  Another tab may have saved since then. Reload checks both heads and approval;
                  unsaved editor text is kept.
                </p>
              </div>

              {approvalStatusLoading && !approvalStatus ? (
                <p aria-live="polite" className="text-sm text-copy-muted" role="status">
                  Loading current pair and approval history…
                </p>
              ) : null}
              {approvalStatusError ? (
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-red-300/30 bg-red-300/5 p-3">
                  <p aria-live="polite" className="min-w-0 text-sm leading-6 text-red-100">
                    Approval status could not be loaded: {approvalStatusError}
                  </p>
                  <button
                    className="min-h-11 rounded-lg border border-line px-3 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={approvalStatusLoading || approvalBusy}
                    onClick={() => void loadPairApprovalStatus(selectedProject.id)}
                    type="button"
                  >
                    {approvalStatusLoading ? "Refreshing…" : "Retry approval status"}
                  </button>
                </div>
              ) : null}

              {approvalStatus ? (
                <>
                  <dl className="grid min-w-0 gap-3 sm:grid-cols-2">
                    {pairDocumentOptions.map((option) => {
                      const revision =
                        option.kind === "project"
                          ? approvalStatus.current_project_revision
                          : approvalStatus.current_agents_revision;
                      return (
                        <div
                          className="min-w-0 rounded-lg border border-line bg-surface-raised p-3"
                          key={option.kind}
                        >
                          <dt className="font-mono text-xs uppercase tracking-wide text-copy-muted">
                            {option.filename}
                          </dt>
                          <dd className="mt-2 font-medium text-foreground">
                            Saved revision {revision.revision_number}
                          </dd>
                          <dd className="mt-1 break-all font-mono text-[11px] leading-5 text-copy-muted">
                            Revision ID {revision.id}
                          </dd>
                        </div>
                      );
                    })}
                  </dl>

                  {approvalStatus.latest_approval ? (
                    <div className="min-w-0 rounded-lg border border-line px-3 py-3">
                      <p className="text-sm font-medium text-foreground">
                        Latest approval · {isoDate(approvalStatus.latest_approval.created_at)}
                      </p>
                      <p className="mt-1 text-sm leading-6 text-copy-muted">
                        PROJECT.md revision {approvalStatus.latest_approval.project_revision_number}
                        {" · "}AGENTS.md revision{" "}
                        {approvalStatus.latest_approval.agents_revision_number}
                        {approvalStatus.approved ? " · current pair" : " · older pair"}
                      </p>
                      <div className="mt-2 grid min-w-0 gap-1 text-xs text-copy-muted sm:grid-cols-2">
                        <code className="min-w-0 break-all">
                          PROJECT.md ID {approvalStatus.latest_approval.project_revision_id}
                        </code>
                        <code className="min-w-0 break-all">
                          AGENTS.md ID {approvalStatus.latest_approval.agents_revision_id}
                        </code>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm leading-6 text-copy-muted">
                      No pair approval is recorded yet. Saving or viewing a draft does not approve
                      it.
                    </p>
                  )}
                </>
              ) : null}

              {approvalStatus && !pairHeadsMatchVisibleDocuments ? (
                <div className="grid min-w-0 gap-3 rounded-lg border border-amber-200/30 bg-amber-100/5 p-3">
                  <p aria-live="polite" className="text-sm leading-6 text-amber-100" role="status">
                    The visible drafts and approval status came from different saved snapshots.
                    Reload both drafts and status before reviewing or approving.
                  </p>
                  <button
                    className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 sm:w-fit"
                    disabled={
                      saveBusy ||
                      taskEditsPending ||
                      approvalBusy ||
                      pairRefreshBusy ||
                      documentsLoading
                    }
                    onClick={() => void refreshCurrentDraftPair()}
                    type="button"
                  >
                    {pairRefreshBusy ? "Reloading drafts…" : "Retry saved pair refresh"}
                  </button>
                </div>
              ) : null}

              {editorIsDirty ? (
                <p className="text-sm leading-6 text-copy-muted" role="status">
                  Unsaved editor text is not part of the displayed approval tuple. Save or discard
                  it before approving the saved pair.
                </p>
              ) : null}

              {approvalError ? (
                <div
                  aria-labelledby={`${instanceId}-approval-error-title`}
                  className="grid min-w-0 gap-2 rounded-lg border border-red-300/35 bg-red-300/5 p-3"
                  role="alert"
                >
                  <h5
                    className="font-medium text-red-100"
                    id={`${instanceId}-approval-error-title`}
                  >
                    Pair approval was not recorded
                  </h5>
                  <p className="text-sm leading-6 text-red-100">{approvalError}</p>
                  {Object.entries(approvalValidationErrors).length ? (
                    <ul className="grid min-w-0 gap-2 text-sm leading-6 text-red-100">
                      {Object.entries(approvalValidationErrors).map(([filename, messages]) => (
                        <li className="min-w-0" key={filename}>
                          <strong className="font-mono">{filename}</strong>
                          <ul className="ml-5 list-disc">
                            {messages.map((message) => (
                              <li className="break-words" key={message}>
                                {message}
                              </li>
                            ))}
                          </ul>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null}

              {approvalNotice ? (
                <p aria-live="polite" className="text-sm leading-6 text-accent" role="status">
                  {approvalNotice}
                </p>
              ) : null}

              {pairConflict && currentPairConflictDocument && previousPairConflictDocument ? (
                <section
                  aria-labelledby={`${instanceId}-approval-conflict-title`}
                  className="grid min-w-0 gap-3 rounded-lg border border-amber-200/35 bg-amber-100/5 p-3 sm:p-4"
                >
                  <div>
                    <h5
                      className="text-base font-semibold text-amber-100"
                      id={`${instanceId}-approval-conflict-title`}
                    >
                      Saved pair changed before approval
                    </h5>
                    <p
                      aria-live="polite"
                      className="mt-1 text-sm leading-6 text-copy-muted"
                      role="status"
                    >
                      {pairReviewMatchesVisibleDocuments
                        ? "Compare both latest documents. Approval stays disabled until you confirm that you reviewed the exact current pair."
                        : "A saved head changed since this comparison. Reload both drafts before reviewing the current pair."}
                    </p>
                  </div>
                  <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                    {pairDocumentOptions.map((option) => (
                      <p className="min-w-0 break-words text-sm leading-6" key={option.kind}>
                        <span className="font-mono text-copy-muted">{option.filename}: </span>
                        revision {pairConflict.previous[option.kind].revision_number}
                        {" → "}
                        revision {pairConflict.latest[option.kind].revision_number}
                      </p>
                    ))}
                  </div>
                  <div className="grid min-w-0 gap-2">
                    <label
                      className="text-sm font-medium text-foreground"
                      htmlFor={`${instanceId}-approval-conflict-document`}
                    >
                      Compare saved document
                    </label>
                    <select
                      className="min-h-11 w-full min-w-0 rounded-lg border border-input-border bg-surface-raised px-3 py-2 text-sm text-foreground outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                      id={`${instanceId}-approval-conflict-document`}
                      onChange={(event) => {
                        const kind = event.target.value as PairKind;
                        setPairConflictKind(kind);
                        const current = documentsRef.current;
                        const conflict = pairConflictRef.current;
                        if (
                          current &&
                          conflict &&
                          sameSavedPair(conflict.latest, {
                            project: current.project,
                            agents: current.agents,
                          })
                        ) {
                          const viewed = new Set(reviewedPairKindsRef.current);
                          viewed.add(kind);
                          updatePairReviewState(viewed, false);
                        } else {
                          updatePairReviewState(new Set(), false);
                        }
                      }}
                      value={pairConflictKind}
                    >
                      <option value="project">PROJECT.md saved-version diff</option>
                      <option value="agents">AGENTS.md saved-version diff</option>
                    </select>
                  </div>
                  <DiffViewer
                    after={currentPairConflictDocument.content}
                    afterLabel={`Latest ${currentPairConflictDocument.filename} revision ${currentPairConflictDocument.revision_number}`}
                    before={previousPairConflictDocument.content}
                    beforeLabel={`Previously reviewed ${previousPairConflictDocument.filename} revision ${previousPairConflictDocument.revision_number}`}
                  />
                  {editorIsDirty ? (
                    <p className="text-sm leading-6 text-copy-muted">
                      Your unsaved editor text is preserved and is not shown in this saved-revision
                      diff.
                    </p>
                  ) : null}
                  <div className="flex min-w-0 flex-wrap items-center gap-3">
                    <button
                      className="min-h-11 rounded-lg border border-amber-100/40 px-4 py-2 text-sm font-medium text-amber-50 hover:bg-amber-100/10 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                      disabled={
                        !pairReviewMatchesVisibleDocuments ||
                        approvalBusy ||
                        reviewedPairKinds.size < pairDocumentOptions.length ||
                        pairReviewConfirmed
                      }
                      onClick={() => {
                        const current = documentsRef.current;
                        const conflict = pairConflictRef.current;
                        if (
                          current &&
                          conflict &&
                          sameSavedPair(conflict.latest, {
                            project: current.project,
                            agents: current.agents,
                          }) &&
                          reviewedPairKindsRef.current.size === pairDocumentOptions.length
                        ) {
                          updatePairReviewState(reviewedPairKindsRef.current, true);
                        }
                      }}
                      type="button"
                    >
                      I reviewed both latest documents
                    </button>
                    {pairReviewConfirmed ? (
                      <span aria-live="polite" className="text-sm text-accent" role="status">
                        Current pair reviewed. Approve only if this exact revision tuple is correct.
                      </span>
                    ) : (
                      <span className="text-sm text-copy-muted">
                        Viewed {reviewedPairKinds.size} of {pairDocumentOptions.length} saved
                        documents.
                      </span>
                    )}
                  </div>
                </section>
              ) : null}

              <div className="grid min-w-0 gap-3 border-t border-line pt-4 lg:flex lg:flex-wrap lg:items-center">
                <button
                  className="min-h-11 w-full min-w-0 whitespace-normal rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 lg:w-auto"
                  disabled={!pairCanBeApproved}
                  onClick={() => void approveSavedPair()}
                  ref={approvalButtonRef}
                  type="button"
                >
                  {approvalBusy
                    ? "Approving saved pair…"
                    : approvalStatus?.approved
                      ? "Approved at last check"
                      : "Approve saved PROJECT.md + AGENTS.md pair"}
                </button>
                {approvalStatus && approvalStatus.approval_has_more ? (
                  <button
                    className="min-h-11 w-full min-w-0 rounded-lg border border-line px-4 py-2 text-sm text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60 lg:w-auto"
                    disabled={approvalHistoryLoading || approvalBusy}
                    onClick={loadOlderApprovals}
                    type="button"
                  >
                    {approvalHistoryLoading ? "Loading history…" : "Load earlier approvals"}
                  </button>
                ) : null}
                {approvalStatus && approvalStatus.approvals.length ? (
                  <details className="w-full min-w-0 rounded-lg border border-line px-3 py-2 lg:min-w-56 lg:flex-1">
                    <summary className="min-h-8 cursor-pointer break-words py-1 text-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
                      Immutable pair approval history ({approvalStatus.approvals.length} shown)
                    </summary>
                    <ol className="mt-3 grid min-w-0 gap-2">
                      {approvalStatus.approvals.map((approval) => (
                        <li className="min-w-0 rounded-md bg-surface-raised p-3" key={approval.id}>
                          <p className="text-sm leading-6 text-foreground">
                            PROJECT.md r{approval.project_revision_number} + AGENTS.md r
                            {approval.agents_revision_number}
                          </p>
                          <p className="mt-1 text-xs text-copy-muted">
                            Approved {isoDate(approval.created_at)}
                          </p>
                          <div className="mt-2 grid min-w-0 gap-1 text-[11px] text-copy-muted sm:grid-cols-2">
                            <code className="min-w-0 break-all">
                              PROJECT.md revision ID {approval.project_revision_id}
                            </code>
                            <code className="min-w-0 break-all">
                              AGENTS.md revision ID {approval.agents_revision_id}
                            </code>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </details>
                ) : null}
              </div>
            </section>

            <div
              aria-label="Draft document switcher"
              className="mt-5 flex flex-wrap gap-2"
              role="tablist"
            >
              {documentOptions.map((option) => (
                <button
                  aria-controls={`${instanceId}-document-panel`}
                  aria-selected={selectedKind === option.kind}
                  className={`min-h-11 rounded-lg border px-4 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                    selectedKind === option.kind
                      ? "border-accent/60 bg-accent/10 text-accent"
                      : "border-line bg-canvas text-copy-muted hover:border-accent/40 hover:text-foreground"
                  } disabled:cursor-not-allowed disabled:opacity-60`}
                  id={`${instanceId}-document-tab-${option.kind}`}
                  key={option.kind}
                  onKeyDown={(event) => handleDocumentTabKeyDown(event, option.kind)}
                  onClick={() => selectDocument(option.kind)}
                  role="tab"
                  tabIndex={selectedKind === option.kind ? 0 : -1}
                  type="button"
                  disabled={
                    saveBusy || taskEditsPending || approvalBusy || editorIsDirty || !documents
                  }
                >
                  {option.label}
                </button>
              ))}
            </div>

            <div
              aria-labelledby={`${instanceId}-document-tab-${selectedKind}`}
              className="mt-4 grid min-w-0 gap-4"
              id={`${instanceId}-document-panel`}
              role="tabpanel"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-mono text-xs text-copy-muted">
                    {currentDocument.filename} · revision {currentDocument.revision_number}
                  </p>
                  <p className="mt-1 text-xs text-copy-muted">
                    {currentDocument.origin === "template"
                      ? `Starter draft from ${currentDocument.template_source ?? "root template"}`
                      : "Saved human draft"}
                  </p>
                </div>
                <span className="font-mono text-[10px] text-copy-muted">
                  {editorBytes.toLocaleString()} / {MAX_DOCUMENT_BYTES.toLocaleString()} bytes
                </span>
              </div>

              {selectedKind === "backlog" && selectedProject ? (
                <BacklogPlanning
                  canEditTasks={Boolean(
                    csrfToken &&
                    !editorIsDirty &&
                    staleEditorRevision === null &&
                    !saveBusy &&
                    !approvalBusy &&
                    !pairRefreshBusy &&
                    !documentsLoading &&
                    !createBusy,
                  )}
                  csrfToken={csrfToken}
                  instanceId={instanceId}
                  markdownPanelId={`${instanceId}-backlog-markdown-panel`}
                  onPanelChange={setBacklogPanel}
                  onPendingChange={setTaskEditsPending}
                  onSessionExpired={onSessionExpired}
                  onSnapshotObserved={observeBacklogTaskSnapshot}
                  panel={backlogPanel}
                  projectId={selectedProject.id}
                  revisionNumber={currentDocument.revision_number}
                  savedContent={currentDocument.content}
                  savedContentSha256={currentDocument.content_sha256}
                />
              ) : null}

              <div
                aria-label={selectedKind === "backlog" ? "Backlog Markdown editor" : undefined}
                className="grid min-w-0 gap-4"
                hidden={selectedKind === "backlog" && backlogPanel !== "markdown"}
                id={selectedKind === "backlog" ? `${instanceId}-backlog-markdown-panel` : undefined}
              >
                {selectedKind === "backlog" && taskEditsPending ? (
                  <p className="text-sm leading-5 text-amber-100" role="status">
                    Task details have unsaved changes. Save or discard them before editing the
                    Markdown draft.
                  </p>
                ) : null}
                <label
                  className="sr-only"
                  htmlFor={`${instanceId}-document-editor-${selectedKind}`}
                >
                  Edit {currentDocument.filename}
                </label>
                <textarea
                  className="min-h-[24rem] w-full min-w-0 resize-y rounded-xl border border-input-border bg-canvas px-4 py-3 font-mono text-xs leading-6 text-foreground outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:min-h-[32rem]"
                  id={`${instanceId}-document-editor-${selectedKind}`}
                  onChange={(event) => {
                    updateEditorContent(event.target.value);
                    setSaveError("");
                    setSaveNotice("");
                    setApprovalError("");
                    setApprovalValidationErrors({});
                  }}
                  readOnly={selectedKind === "backlog" && taskEditsPending}
                  spellCheck={false}
                  value={editorContent}
                />

                {editorIsOversize ? (
                  <p className="text-sm text-red-200" role="alert">
                    This draft exceeds the 128 KiB limit. Shorten it before saving.
                  </p>
                ) : null}
                {staleEditorRevision !== null && editorIsDirty ? (
                  <p className="text-sm leading-5 text-amber-200" role="status">
                    Another tab saved this draft after your editor text was started. Saving now will
                    preserve your text as a conflict proposal, not overwrite the newer revision.
                  </p>
                ) : null}
                {saveError ? (
                  <p className="text-sm leading-5 text-red-200" role="alert">
                    {saveError}
                  </p>
                ) : null}
                {conflictNotice ? (
                  <p aria-live="polite" className="text-sm leading-5 text-amber-200" role="status">
                    {conflictNotice}
                  </p>
                ) : null}
                {saveNotice ? (
                  <p aria-live="polite" className="text-sm leading-5 text-accent" role="status">
                    {saveNotice}
                  </p>
                ) : null}

                <div className="flex flex-wrap items-center gap-3">
                  <button
                    className="min-h-11 rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-canvas hover:bg-accent/90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={
                      !editorIsDirty ||
                      editorIsOversize ||
                      saveBusy ||
                      taskEditsPending ||
                      approvalBusy ||
                      pairRefreshBusy ||
                      !csrfToken
                    }
                    onClick={() => void saveDraft()}
                    type="button"
                  >
                    {saveBusy ? "Saving draft…" : "Save draft"}
                  </button>
                  <button
                    className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={!editorIsDirty || saveBusy || approvalBusy}
                    onClick={() => {
                      if (
                        !currentDocument ||
                        !window.confirm(
                          "Discard unsaved editor text and restore the displayed saved revision?",
                        )
                      )
                        return;
                      invalidateDetailRequest();
                      setStaleEditorRevision(null);
                      updateEditorContent(currentDocument.content);
                      setSaveError("");
                      setSaveNotice("");
                      setConflictNotice("");
                    }}
                    type="button"
                  >
                    Discard editor changes
                  </button>
                  <button
                    aria-controls={`${instanceId}-document-history`}
                    aria-expanded={historyOpen}
                    className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                    disabled={saveBusy || approvalBusy}
                    onClick={() => void toggleHistory()}
                    ref={historyToggleRef}
                    type="button"
                  >
                    {historyOpen ? "Hide history" : "View history"}
                  </button>
                  {editorIsDirty ? (
                    <span className="text-xs text-copy-muted">
                      Unsaved editor text · save before switching drafts
                    </span>
                  ) : null}
                </div>

                {compareContent ? (
                  <section
                    aria-labelledby={`${instanceId}-compare-title`}
                    className="grid gap-3 border-t border-line pt-5"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h4
                        className="scroll-mt-6 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        id={`${instanceId}-compare-title`}
                        ref={comparisonHeadingRef}
                        tabIndex={-1}
                      >
                        Compare {compareContent.label} with saved revision{" "}
                        {currentDocument.revision_number}
                      </h4>
                      <button
                        className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs text-copy-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        onClick={() => {
                          restoreComparisonFocus.current = true;
                          setCompareContent(null);
                        }}
                        type="button"
                      >
                        Close comparison
                      </button>
                    </div>
                    <DiffViewer
                      after={currentDocument.content}
                      afterLabel={`Saved ${currentDocument.filename} revision ${currentDocument.revision_number}`}
                      before={compareContent.content}
                      beforeLabel={compareContent.label}
                    />
                    {editorIsDirty ? (
                      <p className="text-xs text-copy-muted">
                        Unsaved editor text is not shown in this comparison.
                      </p>
                    ) : null}
                  </section>
                ) : null}

                <section
                  aria-labelledby={`${instanceId}-history-title`}
                  className={historyOpen ? "grid min-w-0 gap-5 border-t border-line pt-5" : ""}
                  hidden={!historyOpen}
                  id={`${instanceId}-document-history`}
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <div>
                      <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-copy-muted">
                        Immutable records
                      </p>
                      <h4 className="mt-1 text-lg font-semibold" id={`${instanceId}-history-title`}>
                        {currentDocument.filename} history
                      </h4>
                    </div>
                    {history ? (
                      <span className="font-mono text-xs text-copy-muted">
                        Current revision {history.current_revision_number}
                      </span>
                    ) : null}
                  </div>
                  {historyLoading ? (
                    <p aria-live="polite" className="text-sm text-copy-muted" role="status">
                      Loading revision history…
                    </p>
                  ) : null}
                  {historyError ? (
                    <div className="grid justify-items-start gap-2">
                      <p className="text-sm text-red-200" role="alert">
                        {historyError}
                      </p>
                      <button
                        className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                        disabled={historyLoading}
                        onClick={() => void loadHistory("none", true)}
                        type="button"
                      >
                        Retry history
                      </button>
                    </div>
                  ) : null}
                  {history && !historyLoading ? (
                    <>
                      <div className="grid gap-3">
                        <h5 className="font-mono text-xs uppercase tracking-wide text-copy-muted">
                          Saved revisions
                        </h5>
                        {history.revisions.length === 0 ? (
                          <p className="text-sm text-copy-muted">No saved revisions.</p>
                        ) : (
                          <ol className="grid gap-3">
                            {history.revisions.map((revision) => (
                              <li
                                className="min-w-0 rounded-lg border border-line bg-canvas p-3"
                                key={`revision-${revision.revision_number}`}
                              >
                                <div className="flex flex-wrap items-baseline justify-between gap-2">
                                  <span className="font-medium text-foreground">
                                    Revision {revision.revision_number}
                                    {revision.revision_number === history.current_revision_number
                                      ? " · current"
                                      : ""}
                                  </span>
                                  <span className="text-xs text-copy-muted">
                                    {revision.origin === "template"
                                      ? "Starter template"
                                      : "Human edit"}{" "}
                                    · {isoDate(revision.created_at)}
                                  </span>
                                </div>
                                {revision.template_source ? (
                                  <p className="mt-1 break-words font-mono text-[10px] text-copy-muted">
                                    Source {revision.template_source} · SHA-256{" "}
                                    {revision.template_sha256}
                                  </p>
                                ) : null}
                                <div className="mt-3 flex flex-wrap gap-2">
                                  <button
                                    className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                                    onClick={(event) =>
                                      void compareRevision(revision, event.currentTarget)
                                    }
                                    type="button"
                                  >
                                    Compare revision {revision.revision_number}
                                  </button>
                                  <button
                                    className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                                    onClick={() => void reapplyRevision(revision)}
                                    type="button"
                                  >
                                    Reapply revision {revision.revision_number} in editor
                                  </button>
                                </div>
                              </li>
                            ))}
                          </ol>
                        )}
                        {history.revision_has_more ? (
                          <button
                            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-fit"
                            disabled={historyLoading}
                            onClick={() => void loadHistory("revisions")}
                            type="button"
                          >
                            Load older revisions
                          </button>
                        ) : null}
                      </div>

                      <div className="grid gap-3">
                        <h5 className="font-mono text-xs uppercase tracking-wide text-copy-muted">
                          Conflict proposals
                        </h5>
                        {history.proposals.length === 0 ? (
                          <p className="text-sm text-copy-muted">
                            No rejected edits. If another tab saves first, the attempted text is
                            kept here.
                          </p>
                        ) : (
                          <ol className="grid gap-3">
                            {history.proposals.map((proposal) => (
                              <li
                                className="min-w-0 rounded-lg border border-amber-200/20 bg-amber-100/5 p-3"
                                key={proposal.id}
                              >
                                <p className="font-medium text-foreground">
                                  Conflict proposal · expected revision{" "}
                                  {proposal.expected_revision_number}, newer revision{" "}
                                  {proposal.observed_revision_number}
                                </p>
                                <p className="mt-1 text-xs text-copy-muted">
                                  Saved {isoDate(proposal.created_at)}
                                </p>
                                <div className="mt-3 flex flex-wrap gap-2">
                                  <button
                                    className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                                    onClick={(event) =>
                                      void compareProposal(proposal, event.currentTarget)
                                    }
                                    type="button"
                                  >
                                    Compare conflict proposal
                                  </button>
                                  <button
                                    className="min-h-11 rounded-lg border border-line px-3 py-2 text-xs font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                                    onClick={() => void reapplyProposal(proposal)}
                                    type="button"
                                  >
                                    Reapply conflict proposal in editor
                                  </button>
                                </div>
                              </li>
                            ))}
                          </ol>
                        )}
                        {history.proposal_has_more ? (
                          <button
                            className="min-h-11 rounded-lg border border-line px-4 py-2 text-sm text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:w-fit"
                            disabled={historyLoading}
                            onClick={() => void loadHistory("proposals")}
                            type="button"
                          >
                            Load older conflict proposals
                          </button>
                        ) : null}
                      </div>
                    </>
                  ) : null}
                </section>

                <p className="border-t border-line pt-4 text-xs leading-5 text-copy-muted">
                  Drafts and conflict proposals are saved privately. Workspace files are temporary
                  copies; PostgreSQL is the source of truth. No draft is approved by saving or
                  reapplying it.
                </p>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
