import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { ApiError, apiRequest } from "./api";

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

const MAX_DOCUMENT_BYTES = 128 * 1024;
const documentOptions: { kind: DocumentKind; label: string; filename: string }[] = [
  { kind: "project", label: "Project", filename: "PROJECT.md" },
  { kind: "agents", label: "Agent rules", filename: "AGENTS.md" },
  { kind: "backlog", label: "Backlog", filename: "BACKLOG.md" },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function documentPath(projectId: string, kind: DocumentKind): string {
  return `/api/projects/${encodeURIComponent(projectId)}/documents/${kind}`;
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
  const selectionRef = useRef<{ projectId: string | null; kind: DocumentKind }>({
    projectId: null,
    kind: "project",
  });
  const [documents, setDocuments] = useState<Record<DocumentKind, ProjectDocument> | null>(null);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [editorContent, setEditorContent] = useState("");
  const editorContentRef = useRef(editorContent);
  const editorChangeNumber = useRef(0);
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [conflictNotice, setConflictNotice] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<DocumentHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [compareContent, setCompareContent] = useState<CompareContent | null>(null);
  const comparisonHeadingRef = useRef<HTMLHeadingElement>(null);
  const comparisonTriggerRef = useRef<HTMLButtonElement | null>(null);
  const historyToggleRef = useRef<HTMLButtonElement>(null);
  const restoreComparisonFocus = useRef(false);
  const documentRequestNumber = useRef(0);
  const documentController = useRef<AbortController | null>(null);
  const historyRequestNumber = useRef(0);
  const detailRequestNumber = useRef(0);
  const detailController = useRef<AbortController | null>(null);
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

  useEffect(() => {
    onPendingChange(editorIsDirty || saveBusy);
  }, [editorIsDirty, saveBusy, onPendingChange]);

  useEffect(() => {
    if (!editorIsDirty && !saveBusy) return;
    const warnOnExit = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warnOnExit);
    return () => window.removeEventListener("beforeunload", warnOnExit);
  }, [editorIsDirty, saveBusy]);

  function updateEditorContent(content: string): void {
    editorContentRef.current = content;
    editorChangeNumber.current += 1;
    setEditorContent(content);
  }

  function invalidateDetailRequest(): void {
    detailRequestNumber.current += 1;
    detailController.current?.abort();
    detailController.current = null;
  }

  function invalidateHistory(): void {
    historyRequestNumber.current += 1;
    setHistory(null);
    setHistoryLoading(false);
    setHistoryError("");
  }

  async function loadProjectDocuments(projectId: string, kind: DocumentKind): Promise<void> {
    invalidateDetailRequest();
    const requestNumber = ++documentRequestNumber.current;
    documentController.current?.abort();
    const controller = new AbortController();
    documentController.current = controller;
    setDocuments(null);
    setDocumentsError("");
    setDocumentsLoading(true);
    setHistory(null);
    setHistoryOpen(false);
    setHistoryLoading(false);
    historyRequestNumber.current += 1;
    setCompareContent(null);
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
      const complete = byKind as Record<DocumentKind, ProjectDocument>;
      setDocuments(complete);
      updateEditorContent(complete[kind].content);
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
    };
  }, []);

  async function createProject(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (saveBusy || editorIsDirty || createBusy) return;
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
        saveBusy
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
    if (saveBusy || documentsLoading || editorIsDirty) return;
    if (project.id === selectedProjectId && documents) return;
    setSelectedProjectId(project.id);
    setSelectedProjectSnapshot(project);
    setSelectedKind("project");
    selectionRef.current = { projectId: project.id, kind: "project" };
    setHistory(null);
    setHistoryOpen(false);
    setHistoryLoading(false);
    historyRequestNumber.current += 1;
    setCompareContent(null);
    void loadProjectDocuments(project.id, "project");
  }

  function changeProjectPage(offset: number): void {
    if (saveBusy || createBusy || documentsLoading || editorIsDirty) return;
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
    setDocuments(null);
    setDocumentsError("");
    setDocumentsLoading(false);
    updateEditorContent("");
    setHistoryOpen(false);
    setCompareContent(null);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
    onProjectPageChange(offset);
  }

  function selectDocument(kind: DocumentKind): void {
    if (saveBusy || editorIsDirty || !documents) return;
    invalidateDetailRequest();
    setSelectedKind(kind);
    selectionRef.current = { projectId: selectedProjectId, kind };
    updateEditorContent(documents[kind].content);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
    setHistory(null);
    setHistoryOpen(false);
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
    if (force) setHistory(null);
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
        setDocuments((previous) =>
          previous?.[kind].id === refreshedHead.id &&
          previous[kind].revision_number < refreshedHead.revision_number
            ? { ...previous, [kind]: refreshedHead }
            : previous,
        );
        // A clean editor follows the newly discovered saved head. Text entered
        // while the request was in flight must remain untouched for review.
        if (
          editorAtRequest === editorChangeNumber.current &&
          editorContentRef.current === knownHead.content
        ) {
          updateEditorContent(refreshedHead.content);
        }
      }
      if (selectionRef.current.projectId !== projectId || selectionRef.current.kind !== kind)
        return;
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
        setHistoryError(errorMessage(historyFailure));
      }
    } finally {
      if (requestNumber === historyRequestNumber.current) setHistoryLoading(false);
    }
  }

  async function toggleHistory(): Promise<void> {
    if (saveBusy) return;
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setHistoryOpen(true);
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
    if (!selectedProject || !currentDocument || saveBusy || editorIsOversize) return;
    const projectId = selectedProject.id;
    const kind = selectedKind;
    const submittedContent = editorContent;
    const expectedRevision = currentDocument.revision_number;
    // Any earlier history request may complete after the write. Its result cannot
    // describe the saved head, even when the panel happened to be loading already.
    historyRequestNumber.current += 1;
    setHistoryLoading(false);
    setSaveBusy(true);
    setSaveError("");
    setSaveNotice("");
    setConflictNotice("");
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
      setDocuments((previous) =>
        previous?.[kind].id === saved.id ? { ...previous, [kind]: saved } : previous,
      );
      if (editorContentRef.current === submittedContent) updateEditorContent(saved.content);
      setSaveNotice(`Saved ${saved.filename} as revision ${saved.revision_number}.`);
      // A save makes the cached history stale even if its panel is hidden. Drop
      // it now so reopening the panel cannot reuse a snapshot from the old head.
      invalidateHistory();
      if (historyOpen) {
        void loadHistory("none", true, saved);
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
          const latest =
            conflict?.latest?.id === currentDocument.id && conflict.latest.kind === kind
              ? conflict.latest
              : await apiRequest<ProjectDocument>(documentPath(projectId, kind));
          if (selectionRef.current.projectId !== projectId || selectionRef.current.kind !== kind)
            return;
          setDocuments((previous) =>
            previous?.[kind].id === latest.id ? { ...previous, [kind]: latest } : previous,
          );
          setHistoryOpen(true);
          // History may be slow. Release the save lock once the conflict head is
          // known so the user can discard or continue editing while it loads.
          void loadHistory("none", true, latest);
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
              createBusy || saveBusy || loading || Boolean(loadError) || !csrfToken || editorIsDirty
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
                    disabled={saveBusy || documentsLoading || createBusy || editorIsDirty}
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
                  projectOffset === 0 || editorIsDirty || saveBusy || createBusy || documentsLoading
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
              disabled={editorIsDirty || saveBusy || documentsLoading}
              onClick={() => {
                setSelectedProjectId(null);
                setSelectedProjectSnapshot(null);
                selectionRef.current = { projectId: null, kind: "project" };
                documentRequestNumber.current += 1;
                documentController.current?.abort();
                invalidateDetailRequest();
                invalidateHistory();
                setDocuments(null);
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
              <span className="rounded-full border border-accent/35 bg-accent/10 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide text-accent">
                Draft only
              </span>
            </div>

            <div aria-label="Draft documents" className="mt-5 flex flex-wrap gap-2" role="tablist">
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
                  disabled={saveBusy || editorIsDirty || !documents}
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

              <label className="sr-only" htmlFor={`${instanceId}-document-editor-${selectedKind}`}>
                Edit {currentDocument.filename}
              </label>
              <textarea
                className="min-h-[24rem] w-full min-w-0 resize-y rounded-xl border border-input-border bg-canvas px-4 py-3 font-mono text-xs leading-6 text-foreground outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:min-h-[32rem]"
                id={`${instanceId}-document-editor-${selectedKind}`}
                onChange={(event) => {
                  updateEditorContent(event.target.value);
                  setSaveError("");
                  setSaveNotice("");
                }}
                spellCheck={false}
                value={editorContent}
              />

              {editorIsOversize ? (
                <p className="text-sm text-red-200" role="alert">
                  This draft exceeds the 128 KiB limit. Shorten it before saving.
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
                  disabled={!editorIsDirty || editorIsOversize || saveBusy || !csrfToken}
                  onClick={() => void saveDraft()}
                  type="button"
                >
                  {saveBusy ? "Saving draft…" : "Save draft"}
                </button>
                <button
                  className="min-h-11 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!editorIsDirty || saveBusy}
                  onClick={() => {
                    if (
                      !currentDocument ||
                      !window.confirm(
                        "Discard unsaved editor text and restore the displayed saved revision?",
                      )
                    )
                      return;
                    invalidateDetailRequest();
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
                  disabled={saveBusy}
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
                  <div className="grid min-w-0 gap-3 md:grid-cols-2">
                    <article className="min-w-0 rounded-lg border border-line bg-canvas p-3">
                      <h5 className="font-mono text-xs text-copy-muted">
                        Saved revision {currentDocument.revision_number}
                      </h5>
                      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-foreground">
                        {currentDocument.content}
                      </pre>
                    </article>
                    <article className="min-w-0 rounded-lg border border-line bg-canvas p-3">
                      <h5 className="font-mono text-xs text-copy-muted">{compareContent.label}</h5>
                      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-foreground">
                        {compareContent.content}
                      </pre>
                    </article>
                  </div>
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
                          No rejected edits. If another tab saves first, the attempted text is kept
                          here.
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
        ) : null}
      </div>
    </section>
  );
}
