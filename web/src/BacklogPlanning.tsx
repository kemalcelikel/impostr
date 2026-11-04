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
import { Badge, Button, Disclosure, Input } from "./ui/controls";

type BacklogTaskStatus = "-" | " " | "~" | "x" | "!";
type EditableTaskStatus = "-" | " ";
type BacklogPanel = "tasks" | "detail" | "markdown";

export type BacklogTask = {
  id: string;
  status: BacklogTaskStatus;
  title: string;
  dependencies: string[];
  body: string;
  acceptance: string | null;
  verification: string | null;
  ready: boolean;
  eligible: boolean;
  waiting_on: string[];
};

export type BacklogTaskDocument = {
  revision_number: number;
  content_sha256: string;
  content: string;
  tasks: BacklogTask[];
  summary: {
    draft_count: number;
    ready_count: number;
    eligible_count: number;
    waiting_count: number;
  };
};

type TaskDraft = {
  taskId: string;
  title: string;
  body: string;
  dependencies: string;
  status: EditableTaskStatus;
};

export type TaskMemory = {
  projectId?: string;
  draft?: TaskDraft;
  baseTask?: BacklogTask;
  revision?: number;
  conflict?: TaskConflict;
};

type TaskConflict = {
  state: "loading" | "ready" | "error";
  expectedRevision: number;
  latestRevision: number | null;
  latestTask: BacklogTask | null;
  attempted: TaskDraft;
  reapplyRevision: number | null;
  message: string;
  savedBeforeNewerRevision: boolean;
};

type BacklogPlanningProps = {
  instanceId: string;
  projectId: string;
  csrfToken: string;
  panel: BacklogPanel;
  onPanelChange: (panel: BacklogPanel) => void;
  markdownPanelId: string;
  revisionNumber: number;
  savedContent: string;
  savedContentSha256: string;
  canEditTasks: boolean;
  onPendingChange: (pending: boolean) => void;
  onSnapshotObserved: (snapshot: BacklogTaskDocument) => void;
  onSessionExpired: () => void;
  memory?: TaskMemory;
  onMemoryChange?: (snapshot: TaskMemory) => void;
};
const ignoreTaskMemory: (snapshot: TaskMemory) => void = () => {};

const MAX_DOCUMENT_BYTES = 128 * 1024;
const taskStatuses: readonly BacklogTaskStatus[] = ["-", " ", "~", "x", "!"];
const taskPanels: readonly BacklogPanel[] = ["tasks", "detail", "markdown"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isEditableStatus(status: BacklogTaskStatus): status is EditableTaskStatus {
  return status === "-" || status === " ";
}

function parseBacklogTaskDocument(value: unknown): BacklogTaskDocument {
  if (
    !isRecord(value) ||
    typeof value.revision_number !== "number" ||
    !Number.isSafeInteger(value.revision_number) ||
    value.revision_number < 1 ||
    typeof value.content_sha256 !== "string" ||
    typeof value.content !== "string" ||
    !Array.isArray(value.tasks) ||
    !isRecord(value.summary)
  ) {
    throw new Error("The saved task response was incomplete. Reload the backlog to try again.");
  }

  const tasks = value.tasks.map((candidate): BacklogTask => {
    if (
      !isRecord(candidate) ||
      typeof candidate.id !== "string" ||
      typeof candidate.status !== "string" ||
      !taskStatuses.includes(candidate.status as BacklogTaskStatus) ||
      typeof candidate.title !== "string" ||
      !Array.isArray(candidate.dependencies) ||
      !candidate.dependencies.every((item) => typeof item === "string") ||
      typeof candidate.body !== "string" ||
      (candidate.acceptance !== null && typeof candidate.acceptance !== "string") ||
      (candidate.verification !== null && typeof candidate.verification !== "string") ||
      typeof candidate.ready !== "boolean" ||
      typeof candidate.eligible !== "boolean" ||
      !Array.isArray(candidate.waiting_on) ||
      !candidate.waiting_on.every((item) => typeof item === "string")
    ) {
      throw new Error("The saved task response was incomplete. Reload the backlog to try again.");
    }
    return candidate as BacklogTask;
  });

  const summary = value.summary;
  const summaryKeys = ["draft_count", "ready_count", "eligible_count", "waiting_count"] as const;
  if (
    !summaryKeys.every(
      (key) =>
        typeof summary[key] === "number" &&
        Number.isSafeInteger(summary[key]) &&
        (summary[key] as number) >= 0,
    )
  ) {
    throw new Error("The saved task summary was incomplete. Reload the backlog to try again.");
  }

  return {
    revision_number: value.revision_number,
    content_sha256: value.content_sha256,
    content: value.content,
    tasks,
    summary: {
      draft_count: summary.draft_count as number,
      ready_count: summary.ready_count as number,
      eligible_count: summary.eligible_count as number,
      waiting_count: summary.waiting_count as number,
    },
  };
}

function taskPath(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/backlog/tasks`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function isDocumentConflict(error: ApiError): boolean {
  if (!isRecord(error.payload) || !isRecord(error.payload.latest)) return false;
  const latest = error.payload.latest;
  return (
    latest.kind === "backlog" &&
    typeof latest.id === "string" &&
    typeof latest.revision_number === "number" &&
    typeof latest.content === "string" &&
    typeof latest.content_sha256 === "string"
  );
}

function taskStatusLabel(status: BacklogTaskStatus): string {
  switch (status) {
    case "-":
      return "Draft";
    case " ":
      return "Ready";
    case "~":
      return "In progress · runner-managed";
    case "x":
      return "Complete · runner-managed";
    case "!":
      return "Blocked · runner-managed";
  }
}

function dependenciesFromText(value: string): string[] {
  return value
    .split(",")
    .map((dependency) => dependency.trim())
    .filter(Boolean);
}

function draftFromTask(task: BacklogTask): TaskDraft | null {
  if (!isEditableStatus(task.status)) return null;
  return {
    taskId: task.id,
    title: task.title,
    body: task.body,
    dependencies: task.dependencies.join(", "),
    status: task.status,
  };
}

function draftMatchesTask(draft: TaskDraft | null, task: BacklogTask | null): boolean {
  if (!draft || !task || !isEditableStatus(task.status)) return false;
  const dependencies = dependenciesFromText(draft.dependencies);
  return (
    draft.taskId === task.id &&
    draft.title.trim() === task.title &&
    draft.body === task.body &&
    draft.status === task.status &&
    dependencies.length === task.dependencies.length &&
    dependencies.every((dependency, index) => dependency === task.dependencies[index])
  );
}

function hasDependencyLine(body: string): boolean {
  return body
    .split(/\r\n|\r|\n/)
    .some((line) => /^[ \t]*(?:\*\*)?Depends on:(?:\*\*)?[ \t]*/.test(line));
}

function bodyForTaskUpdate(body: string, originalBody: string, dependencies: string[]): string {
  const lineEnding = originalBody.match(/\r\n|\r|\n/)?.[0] ?? "\n";
  if (!hasDependencyLine(originalBody) || hasDependencyLine(body)) {
    return body.endsWith("\n") || body.endsWith("\r") ? body : `${body}${lineEnding}`;
  }
  const separator =
    body.length === 0 || body.endsWith("\n") || body.endsWith("\r")
      ? lineEnding
      : `${lineEnding}${lineEnding}`;
  const dependencyValue = dependencies.length ? dependencies.join(", ") : "None";
  return `${body}${separator}**Depends on:** ${dependencyValue}${lineEnding}`;
}

function textBytes(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

export default function BacklogPlanning({
  instanceId,
  projectId,
  csrfToken,
  panel,
  onPanelChange,
  markdownPanelId,
  revisionNumber,
  savedContent,
  savedContentSha256,
  canEditTasks,
  onPendingChange,
  onSnapshotObserved,
  onSessionExpired,
  memory,
  onMemoryChange = ignoreTaskMemory,
}: BacklogPlanningProps) {
  const generatedId = `${instanceId}-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const taskListId = `${generatedId}-task-list`;
  const taskDetailId = `${generatedId}-task-detail`;
  const markdownId = markdownPanelId;
  const [railOpen, setRailOpen] = useState(true);
  const [taskDocument, setTaskDocumentState] = useState<BacklogTaskDocument | null>(null);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState("");
  const [retryNumber, setRetryNumber] = useState(0);
  const retained = memory?.projectId === projectId ? memory : undefined;
  const [selectedTaskId, setSelectedTaskIdState] = useState<string | null>(
    retained?.draft?.taskId ?? null,
  );
  const [baseTask, setBaseTaskState] = useState<BacklogTask | null>(retained?.baseTask ?? null);
  const [draft, setDraftState] = useState<TaskDraft | null>(retained?.draft ?? null);
  const [conflict, setConflictState] = useState<TaskConflict | null>(retained?.conflict ?? null);
  const [taskBusy, setTaskBusy] = useState(false);
  const [taskError, setTaskError] = useState("");
  const [taskNotice, setTaskNotice] = useState("");
  const snapshotRef = useRef<BacklogTaskDocument | null>(null);
  const selectedTaskIdRef = useRef<string | null>(retained?.draft?.taskId ?? null);
  const baseTaskRef = useRef<BacklogTask | null>(retained?.baseTask ?? null);
  const baseRevisionRef = useRef<number | null>(retained?.revision ?? null);
  const draftRef = useRef<TaskDraft | null>(retained?.draft ?? null);
  const conflictRef = useRef<TaskConflict | null>(retained?.conflict ?? null);
  const taskBusyRef = useRef(false);
  const mountedRef = useRef(false);
  const loadRequestNumberRef = useRef(0);
  const writeRequestNumberRef = useRef(0);
  const lastLoadedRetryNumberRef = useRef(-1);
  const loadControllerRef = useRef<AbortController | null>(null);
  const conflictControllerRef = useRef<AbortController | null>(null);
  const onSnapshotObservedRef = useRef(onSnapshotObserved);
  const onSessionExpiredRef = useRef(onSessionExpired);
  const installSnapshotRef = useRef(installSnapshot);
  const focusRailAfterOpenRef = useRef(false);
  const focusDetailAfterSelectionRef = useRef(false);
  const selectedTaskButtonRef = useRef<HTMLButtonElement>(null);
  const taskListHeadingRef = useRef<HTMLHeadingElement>(null);
  const taskDetailHeadingRef = useRef<HTMLHeadingElement>(null);

  const formIsDirty = Boolean(draft && !draftMatchesTask(draft, baseTask));
  useEffect(() => {
    onMemoryChange({
      projectId,
      ...(conflict ? { conflict } : {}),
      ...(draft && (formIsDirty || conflict)
        ? {
            draft,
            baseTask: baseTask ?? undefined,
            revision: baseRevisionRef.current ?? revisionNumber,
          }
        : {}),
    });
  }, [onMemoryChange, projectId, draft, baseTask, formIsDirty, revisionNumber, conflict]);
  const taskPending = formIsDirty || conflict !== null || taskBusy;
  const snapshotMatchesMarkdown = Boolean(
    taskDocument &&
    taskDocument.revision_number === revisionNumber &&
    taskDocument.content_sha256 === savedContentSha256 &&
    taskDocument.content === savedContent,
  );
  const selectedTask = taskDocument?.tasks.find((task) => task.id === selectedTaskId) ?? null;
  const detailTask = baseTask ?? selectedTask;
  const displayedDraft = draft ?? conflict?.attempted ?? null;
  const bodySize = displayedDraft ? textBytes(displayedDraft.body) : 0;
  const titleError = displayedDraft
    ? !displayedDraft.title.trim()
      ? "A task title is required."
      : /[\r\n]/.test(displayedDraft.title)
        ? "Task titles must use one line."
        : ""
    : "";
  const bodyTooLarge = bodySize > MAX_DOCUMENT_BYTES;
  const taskActionsAllowed = Boolean(
    canEditTasks &&
    csrfToken &&
    taskDocument &&
    snapshotMatchesMarkdown &&
    loadState === "ready" &&
    !taskBusy,
  );
  const canSaveDraft = Boolean(
    taskActionsAllowed &&
    draft &&
    formIsDirty &&
    !titleError &&
    !bodyTooLarge &&
    (conflict === null ||
      (conflict.state === "ready" &&
        conflict.latestTask !== null &&
        isEditableStatus(conflict.latestTask.status) &&
        conflict.reapplyRevision === taskDocument?.revision_number)),
  );

  function updateTaskDocument(next: BacklogTaskDocument): void {
    snapshotRef.current = next;
    setTaskDocumentState(next);
  }

  function updateSelectedTaskId(next: string | null): void {
    selectedTaskIdRef.current = next;
    setSelectedTaskIdState(next);
  }

  function updateBaseTask(next: BacklogTask | null, revision: number | null): void {
    baseTaskRef.current = next;
    baseRevisionRef.current = revision;
    setBaseTaskState(next);
  }

  function updateDraft(next: TaskDraft | null): void {
    draftRef.current = next;
    setDraftState(next);
  }

  function updateConflict(next: TaskConflict | null): void {
    conflictRef.current = next;
    setConflictState(next);
  }

  function installSnapshot(
    incoming: BacklogTaskDocument,
    mode: "refresh" | "save" | "conflict",
    options: {
      taskId?: string;
      attempted?: TaskDraft;
      expectedRevision?: number;
      savedBeforeNewerRevision?: boolean;
    } = {},
  ): void {
    const previousDocument = snapshotRef.current;
    const previousBase = baseTaskRef.current;
    const previousDraft = draftRef.current;
    const previousConflict = conflictRef.current;
    const previousBaseRevision = baseRevisionRef.current;
    const localChanges =
      previousConflict !== null ||
      (previousDraft !== null && !draftMatchesTask(previousDraft, previousBase));
    const taskId =
      options.taskId ??
      selectedTaskIdRef.current ??
      previousDraft?.taskId ??
      previousConflict?.attempted.taskId ??
      previousBase?.id ??
      incoming.tasks[0]?.id ??
      null;
    let latestTask = taskId ? (incoming.tasks.find((task) => task.id === taskId) ?? null) : null;
    let nextTaskId = taskId;

    if (mode === "refresh" && !localChanges && latestTask === null) {
      nextTaskId = incoming.tasks[0]?.id ?? null;
      latestTask = nextTaskId
        ? (incoming.tasks.find((task) => task.id === nextTaskId) ?? null)
        : null;
    }

    updateTaskDocument(incoming);
    updateSelectedTaskId(nextTaskId);

    if (mode === "save") {
      updateBaseTask(latestTask, incoming.revision_number);
      updateDraft(latestTask ? draftFromTask(latestTask) : null);
      updateConflict(null);
      return;
    }

    if (mode === "conflict") {
      const attempted = options.attempted ?? previousDraft ?? previousConflict?.attempted;
      if (attempted) {
        updateBaseTask(latestTask, incoming.revision_number);
        updateDraft(attempted);
        updateConflict({
          state: "ready",
          expectedRevision:
            options.expectedRevision ??
            previousBaseRevision ??
            previousDocument?.revision_number ??
            1,
          latestRevision: incoming.revision_number,
          latestTask,
          attempted,
          reapplyRevision: null,
          message: options.savedBeforeNewerRevision
            ? "Your edit was saved, but a later backlog revision is now current. Review the latest task before reapplying."
            : "Another tab saved a newer backlog revision. Your attempted task text remains in the form and has not overwritten that revision.",
          savedBeforeNewerRevision: options.savedBeforeNewerRevision ?? false,
        });
      }
      return;
    }

    if (previousConflict) {
      const attempted = previousDraft ?? previousConflict.attempted;
      updateBaseTask(latestTask, incoming.revision_number);
      updateDraft(attempted);
      updateConflict({
        ...previousConflict,
        state: "ready",
        latestRevision: incoming.revision_number,
        latestTask,
        attempted,
        reapplyRevision: null,
        message:
          incoming.revision_number > (previousConflict.latestRevision ?? 0)
            ? "The backlog advanced again. Review the new latest task before reapplying."
            : previousConflict.message,
      });
      return;
    }

    if (localChanges) {
      const originalRevision = previousBaseRevision ?? previousDocument?.revision_number ?? null;
      if (
        originalRevision !== null &&
        incoming.revision_number > originalRevision &&
        previousDraft
      ) {
        updateBaseTask(latestTask, incoming.revision_number);
        updateDraft(previousDraft);
        updateConflict({
          state: "ready",
          expectedRevision: originalRevision,
          latestRevision: incoming.revision_number,
          latestTask,
          attempted: previousDraft,
          reapplyRevision: null,
          message:
            "Another tab saved a newer backlog revision. Your attempted task text remains in the form and has not overwritten that revision.",
          savedBeforeNewerRevision: false,
        });
      }
      return;
    }

    updateBaseTask(latestTask, incoming.revision_number);
    updateDraft(latestTask ? draftFromTask(latestTask) : null);
    updateConflict(null);
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loadRequestNumberRef.current += 1;
      writeRequestNumberRef.current += 1;
      loadControllerRef.current?.abort();
      conflictControllerRef.current?.abort();
      onPendingChange(false);
    };
  }, [onPendingChange]);

  useEffect(() => {
    onSnapshotObservedRef.current = onSnapshotObserved;
    onSessionExpiredRef.current = onSessionExpired;
    installSnapshotRef.current = installSnapshot;
  });

  useEffect(() => {
    if (
      snapshotRef.current?.revision_number === revisionNumber &&
      lastLoadedRetryNumberRef.current === retryNumber
    ) {
      return;
    }

    const requestNumber = ++loadRequestNumberRef.current;
    loadControllerRef.current?.abort();
    const controller = new AbortController();
    loadControllerRef.current = controller;
    setLoadState("loading");
    setLoadError("");

    void apiRequest<unknown>(taskPath(projectId), { signal: controller.signal })
      .then((payload) => {
        if (
          !mountedRef.current ||
          controller.signal.aborted ||
          requestNumber !== loadRequestNumberRef.current
        ) {
          return;
        }
        const latest = parseBacklogTaskDocument(payload);
        if (latest.revision_number < revisionNumber) {
          throw new Error(
            `The task list is at revision ${latest.revision_number}, older than BACKLOG.md revision ${revisionNumber}. Reload the saved drafts to try again.`,
          );
        }
        if (
          latest.revision_number === revisionNumber &&
          (latest.content !== savedContent || latest.content_sha256 !== savedContentSha256)
        ) {
          throw new Error(
            "The task list and Markdown response did not match the same saved revision. Reload the backlog to try again.",
          );
        }
        installSnapshotRef.current(latest, "refresh");
        lastLoadedRetryNumberRef.current = retryNumber;
        onSnapshotObservedRef.current(latest);
        setLoadState("ready");
      })
      .catch((failure: unknown) => {
        if (
          !mountedRef.current ||
          controller.signal.aborted ||
          requestNumber !== loadRequestNumberRef.current
        ) {
          return;
        }
        if (failure instanceof ApiError && failure.status === 401) {
          onSessionExpiredRef.current();
        }
        setLoadState("error");
        setLoadError(errorMessage(failure));
      })
      .finally(() => {
        if (loadControllerRef.current === controller) loadControllerRef.current = null;
      });

    return () => {
      controller.abort();
      if (loadControllerRef.current === controller) loadControllerRef.current = null;
    };
  }, [projectId, revisionNumber, retryNumber, savedContent, savedContentSha256]);

  useEffect(() => {
    onPendingChange(taskPending);
  }, [onPendingChange, taskPending]);

  useLayoutEffect(() => {
    if (focusRailAfterOpenRef.current && railOpen) {
      focusRailAfterOpenRef.current = false;
      if (selectedTaskButtonRef.current?.isConnected) {
        selectedTaskButtonRef.current.focus();
      } else {
        taskListHeadingRef.current?.focus();
      }
    }
    if (focusDetailAfterSelectionRef.current && panel === "detail") {
      focusDetailAfterSelectionRef.current = false;
      taskDetailHeadingRef.current?.focus();
    }
  }, [panel, railOpen, selectedTaskId, taskDocument]);

  function selectTask(task: BacklogTask): void {
    if (taskBusyRef.current || formIsDirty || conflictRef.current !== null) return;
    updateSelectedTaskId(task.id);
    updateBaseTask(task, snapshotRef.current?.revision_number ?? revisionNumber);
    updateDraft(draftFromTask(task));
    updateConflict(null);
    setTaskError("");
    setTaskNotice("");
    focusDetailAfterSelectionRef.current = true;
    onPanelChange("detail");
  }

  async function reloadConflictLatest(
    requestNumber: number,
    taskId: string,
    expectedRevision: number,
    attempted: TaskDraft,
    savedBeforeNewerRevision = false,
  ): Promise<void> {
    conflictControllerRef.current?.abort();
    const controller = new AbortController();
    conflictControllerRef.current = controller;
    updateConflict({
      state: "loading",
      expectedRevision,
      latestRevision: null,
      latestTask: null,
      attempted,
      reapplyRevision: null,
      message: "Loading the latest saved task before reapply.",
      savedBeforeNewerRevision,
    });
    try {
      const payload = await apiRequest<unknown>(taskPath(projectId), { signal: controller.signal });
      if (
        !mountedRef.current ||
        controller.signal.aborted ||
        requestNumber !== writeRequestNumberRef.current
      ) {
        return;
      }
      const latest = parseBacklogTaskDocument(payload);
      installSnapshot(latest, "conflict", {
        taskId,
        attempted,
        expectedRevision,
        savedBeforeNewerRevision,
      });
      lastLoadedRetryNumberRef.current = retryNumber;
      onSnapshotObservedRef.current(latest);
      setTaskError("");
      setTaskNotice(
        savedBeforeNewerRevision
          ? `Your task edit saved, but a later revision ${latest.revision_number} is current. Review the latest task before reapplying.`
          : `The backlog changed during the save. Your attempted task text is preserved; review revision ${latest.revision_number} before reapplying.`,
      );
    } catch (failure) {
      if (
        !mountedRef.current ||
        controller.signal.aborted ||
        requestNumber !== writeRequestNumberRef.current
      ) {
        return;
      }
      if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpiredRef.current();
      }
      const previous = conflictRef.current;
      if (previous) {
        const message = `The latest task could not be loaded. Your attempted text is still here. ${errorMessage(failure)}`;
        updateConflict({
          ...previous,
          state: "error",
          message,
        });
        setTaskError(message);
      }
    } finally {
      if (conflictControllerRef.current === controller) conflictControllerRef.current = null;
    }
  }

  async function saveTaskDraft(attempted: TaskDraft, taskAtSubmit: BacklogTask): Promise<void> {
    const currentSnapshot = snapshotRef.current;
    if (
      !currentSnapshot ||
      !taskActionsAllowed ||
      taskBusyRef.current ||
      !isEditableStatus(taskAtSubmit.status)
    ) {
      return;
    }
    const activeConflict = conflictRef.current;
    if (
      activeConflict !== null &&
      (activeConflict.state !== "ready" ||
        activeConflict.reapplyRevision !== currentSnapshot.revision_number)
    ) {
      return;
    }
    const expectedRevision = activeConflict?.reapplyRevision ?? currentSnapshot.revision_number;
    const dependencies = dependenciesFromText(attempted.dependencies);
    const body = bodyForTaskUpdate(attempted.body, taskAtSubmit.body, dependencies);
    const requestNumber = ++writeRequestNumberRef.current;
    taskBusyRef.current = true;
    setTaskBusy(true);
    setTaskError("");
    setTaskNotice("");
    try {
      const payload = await apiRequest<unknown>(
        `${taskPath(projectId)}/${encodeURIComponent(attempted.taskId)}`,
        {
          method: "PUT",
          csrfToken,
          body: {
            expected_revision: expectedRevision,
            title: attempted.title,
            body,
            dependencies,
            status: attempted.status,
          },
        },
      );
      if (!mountedRef.current || requestNumber !== writeRequestNumberRef.current) return;
      const saved = parseBacklogTaskDocument(payload);
      const savedTask = saved.tasks.find((task) => task.id === attempted.taskId);
      if (!savedTask) {
        throw new Error("The saved task was not returned. Reload the backlog before continuing.");
      }
      const latestKnown = snapshotRef.current;
      if (latestKnown && latestKnown.revision_number > saved.revision_number) {
        const latestTask = latestKnown.tasks.find((task) => task.id === attempted.taskId) ?? null;
        installSnapshot(latestKnown, "conflict", {
          taskId: attempted.taskId,
          attempted,
          expectedRevision: saved.revision_number,
          savedBeforeNewerRevision: true,
        });
        setTaskNotice(
          `Saved revision ${saved.revision_number}; a newer revision is already current.`,
        );
        setTaskError("");
        if (!latestTask) {
          updateConflict({
            state: "ready",
            expectedRevision: saved.revision_number,
            latestRevision: latestKnown.revision_number,
            latestTask: null,
            attempted,
            reapplyRevision: null,
            message:
              "Your edit was saved, but a later backlog revision is now current. This task is not present in the latest task list, so it cannot be reapplied here.",
            savedBeforeNewerRevision: true,
          });
        }
        return;
      }
      installSnapshot(saved, "save", { taskId: attempted.taskId });
      lastLoadedRetryNumberRef.current = retryNumber;
      onSnapshotObservedRef.current(saved);
      setTaskNotice(`Saved ${attempted.taskId} to BACKLOG.md revision ${saved.revision_number}.`);
      setTaskError("");
    } catch (failure) {
      if (!mountedRef.current || requestNumber !== writeRequestNumberRef.current) return;
      if (failure instanceof ApiError && failure.status === 401) {
        onSessionExpiredRef.current();
      } else if (
        failure instanceof ApiError &&
        failure.status === 409 &&
        isDocumentConflict(failure)
      ) {
        setTaskError("");
        await reloadConflictLatest(requestNumber, attempted.taskId, expectedRevision, attempted);
      } else {
        if (failure instanceof ApiError && failure.status === 409) {
          setRetryNumber((number) => number + 1);
        }
        setTaskError(errorMessage(failure));
      }
    } finally {
      if (mountedRef.current && requestNumber === writeRequestNumberRef.current) {
        taskBusyRef.current = false;
        setTaskBusy(false);
      }
    }
  }

  function toggleTaskStatus(task: BacklogTask): void {
    if (!taskActionsAllowed || taskPending || !isEditableStatus(task.status)) return;
    const nextStatus: EditableTaskStatus = task.status === "-" ? " " : "-";
    const attempted = draftFromTask(task);
    if (!attempted) return;
    attempted.status = nextStatus;
    updateSelectedTaskId(task.id);
    updateBaseTask(task, snapshotRef.current?.revision_number ?? revisionNumber);
    updateDraft(attempted);
    updateConflict(null);
    setTaskError("");
    setTaskNotice("");
    void saveTaskDraft(attempted, task);
  }

  function submitTaskForm(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!draft || !baseTask || !canSaveDraft) return;
    void saveTaskDraft(draft, baseTask);
  }

  function updateDraftField<K extends keyof TaskDraft>(key: K, value: TaskDraft[K]): void {
    const current = draftRef.current;
    if (!current || taskBusyRef.current) return;
    updateDraft({ ...current, [key]: value });
    setTaskError("");
    setTaskNotice("");
    const currentConflict = conflictRef.current;
    if (currentConflict && currentConflict.reapplyRevision !== null) {
      updateConflict({ ...currentConflict, reapplyRevision: null });
    }
  }

  function discardTaskChanges(): void {
    if (taskBusyRef.current) return;
    const savedTask = snapshotRef.current?.tasks.find(
      (task) => task.id === selectedTaskIdRef.current,
    );
    updateBaseTask(savedTask ?? null, snapshotRef.current?.revision_number ?? null);
    updateDraft(savedTask ? draftFromTask(savedTask) : null);
    updateConflict(null);
    setTaskError("");
    setTaskNotice("");
  }

  function retryConflict(): void {
    const currentConflict = conflictRef.current;
    if (!currentConflict || taskBusyRef.current) return;
    const requestNumber = ++writeRequestNumberRef.current;
    taskBusyRef.current = true;
    setTaskBusy(true);
    void reloadConflictLatest(
      requestNumber,
      currentConflict.attempted.taskId,
      currentConflict.expectedRevision,
      draftRef.current ?? currentConflict.attempted,
      currentConflict.savedBeforeNewerRevision,
    ).finally(() => {
      if (mountedRef.current && requestNumber === writeRequestNumberRef.current) {
        taskBusyRef.current = false;
        setTaskBusy(false);
      }
    });
  }

  function armReapply(): void {
    const currentConflict = conflictRef.current;
    const currentSnapshot = snapshotRef.current;
    if (
      !currentConflict ||
      currentConflict.state !== "ready" ||
      !currentConflict.latestTask ||
      !isEditableStatus(currentConflict.latestTask.status) ||
      !currentSnapshot ||
      currentSnapshot.revision_number !== revisionNumber ||
      !canEditTasks
    ) {
      return;
    }
    updateConflict({
      ...currentConflict,
      reapplyRevision: currentSnapshot.revision_number,
    });
    setTaskNotice(
      `Your attempted text is still in the form. Saving now will apply it to revision ${currentSnapshot.revision_number}.`,
    );
  }

  function changePanel(next: BacklogPanel): void {
    onPanelChange(next);
  }

  function handlePanelKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentPanel: BacklogPanel,
  ): void {
    const currentIndex = taskPanels.indexOf(currentPanel);
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % taskPanels.length;
    else if (event.key === "ArrowLeft")
      nextIndex = (currentIndex - 1 + taskPanels.length) % taskPanels.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = taskPanels.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextPanel = taskPanels[nextIndex];
    onPanelChange(nextPanel);
    document.getElementById(`${generatedId}-view-${nextPanel}`)?.focus();
  }

  function retryTasks(): void {
    setLoadError("");
    setLoadState("loading");
    setRetryNumber((number) => number + 1);
  }

  const summary = taskDocument?.summary;
  const statusSummary = taskDocument ? (
    <section
      aria-labelledby={`${generatedId}-status-title`}
      className="backlog-status"
      role="region"
    >
      <div>
        <h5 className="text-sm font-semibold text-foreground" id={`${generatedId}-status-title`}>
          Saved task status
        </h5>
        <Disclosure className="backlog-rules" title="Readiness & runner rules">
          <p className="text-xs leading-5 text-copy-muted">
            Read-only summary for BACKLOG.md revision {taskDocument.revision_number}. Ready means
            the owner marked a task as ready; it does not mean this backlog revision is approved.
            Dependency-eligible means every prerequisite is complete.
          </p>
        </Disclosure>
      </div>
      {summary ? (
        <div aria-live="polite" className="grid min-w-0 gap-2">
          <dl className="flex min-w-0 flex-wrap gap-x-5 gap-y-2">
            <div className="min-w-0">
              <dt className="text-xs text-copy-muted">Ready</dt>
              <dd className="font-medium text-foreground">{summary.ready_count}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-copy-muted">Dependency-eligible</dt>
              <dd className="font-medium text-accent">{summary.eligible_count}</dd>
            </div>
            <div className="min-w-0">
              <dt className="text-xs text-copy-muted">Waiting on prerequisites</dt>
              <dd className="font-medium text-foreground">{summary.waiting_count}</dd>
            </div>
          </dl>
          <p className="text-xs text-copy-muted">
            {summary.draft_count === 0
              ? "No draft tasks in this saved backlog."
              : summary.draft_count === 1
                ? "1 draft task is not ready."
                : `${summary.draft_count} draft tasks are not ready.`}
          </p>
        </div>
      ) : null}
    </section>
  ) : null;

  return (
    <section aria-labelledby={`${generatedId}-heading`} className="backlog-planning">
      <header className="backlog-heading">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold" id={`${generatedId}-heading`}>
            Task list and details
          </h4>
          <Disclosure className="backlog-rules" title="Task edit rules">
            <p className="text-xs leading-5 text-copy-muted">
              Task edits save a new BACKLOG.md revision and refresh this list and Markdown together.
              Runner-owned outcomes remain read-only.
            </p>
          </Disclosure>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            aria-controls={taskListId}
            aria-expanded={railOpen}
            className="backlog-wide-control workbench-quiet"
            variant="ghost"
            hidden={panel === "markdown"}
            icon="folder"
            onClick={() => {
              if (!railOpen) focusRailAfterOpenRef.current = true;
              setRailOpen((open) => !open);
            }}
            type="button"
          >
            {railOpen ? "Hide task list" : "Show task list"}
          </Button>
          <Button
            className="workbench-quiet"
            variant="ghost"
            icon="refresh"
            disabled={loadState === "loading" || taskBusy}
            onClick={retryTasks}
            type="button"
          >
            {loadState === "loading" ? "Loading tasks…" : "Reload task list"}
          </Button>
        </div>
      </header>

      <div aria-label="Backlog view" className="backlog-view-choice" role="group">
        {taskPanels.map((item) => (
          <Button
            aria-controls={
              item === "tasks" ? taskListId : item === "detail" ? taskDetailId : markdownId
            }
            aria-pressed={panel === item}
            className="workbench-surface-choice"
            variant="ghost"
            id={`${generatedId}-view-${item}`}
            key={item}
            onClick={() => changePanel(item)}
            onKeyDown={(event) => handlePanelKeyDown(event, item)}
            type="button"
          >
            {item === "tasks" ? "Tasks" : item === "detail" ? "Detail" : "Markdown"}
          </Button>
        ))}
      </div>

      {statusSummary}

      {!canEditTasks ? (
        <p
          className="rounded-lg border border-amber-200/30 bg-amber-100/5 px-3 py-2 text-sm leading-5 text-amber-100"
          role="status"
        >
          Save or discard pending Markdown edits and refresh the saved backlog before editing task
          details.
        </p>
      ) : null}
      {loadState === "error" ? (
        <div
          className="grid gap-2 rounded-lg border border-red-300/35 bg-red-300/5 p-3"
          role="alert"
        >
          <p className="text-sm leading-6 text-red-100">
            Saved task details are unavailable: {loadError}
          </p>
          <Button className="justify-self-start" icon="refresh" onClick={retryTasks} type="button">
            Retry loading tasks
          </Button>
        </div>
      ) : loadState === "loading" ? (
        <p aria-live="polite" className="text-sm text-copy-muted" role="status">
          Loading saved task list and details…
        </p>
      ) : null}
      {taskBusy ? (
        <p aria-live="polite" className="text-sm text-copy-muted" role="status">
          Saving task details to BACKLOG.md revision{" "}
          {taskDocument?.revision_number ?? revisionNumber}…
        </p>
      ) : null}
      {taskError && !(conflict?.state === "error" && panel === "detail") ? (
        <p aria-live="assertive" className="text-sm leading-5 text-red-200" role="alert">
          Task update could not be saved: {taskError}
        </p>
      ) : null}
      {taskNotice ? (
        <p aria-live="polite" className="text-sm leading-5 text-accent" role="status">
          {taskNotice}
        </p>
      ) : null}
      {conflict && panel !== "detail" ? (
        <Button
          aria-controls={taskDetailId}
          className="justify-self-start"
          icon="alert"
          onClick={() => {
            focusDetailAfterSelectionRef.current = true;
            onPanelChange("detail");
          }}
          type="button"
        >
          Review task conflict details
        </Button>
      ) : null}
      {taskDocument && !snapshotMatchesMarkdown ? (
        <p
          aria-live="polite"
          className="rounded-lg border border-amber-200/30 bg-amber-100/5 px-3 py-2 text-sm leading-5 text-amber-100"
          role="status"
        >
          {taskDocument.revision_number > revisionNumber
            ? `Task details are at revision ${taskDocument.revision_number}; synchronizing BACKLOG.md revision ${revisionNumber}.`
            : `Task details do not match BACKLOG.md revision ${revisionNumber}. Reload the saved backlog before editing.`}
        </p>
      ) : null}

      <div
        className="backlog-layout"
        data-panel={panel}
        data-rail={railOpen ? "open" : "closed"}
        hidden={panel === "markdown"}
      >
        <aside
          aria-labelledby={`${generatedId}-task-list-title`}
          className="backlog-rail min-w-0"
          id={taskListId}
        >
          <div className="flex min-w-0 items-baseline justify-between gap-2 border-b border-line pb-3">
            <h5
              className="min-w-0 break-words text-sm font-semibold text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              id={`${generatedId}-task-list-title`}
              ref={taskListHeadingRef}
              tabIndex={-1}
            >
              Saved tasks
            </h5>
            <span className="shrink-0 text-xs text-copy-muted">
              {taskDocument?.tasks.length ?? 0}
            </span>
          </div>
          <p className="py-3 text-xs leading-5 text-copy-muted">
            Select a task to edit its title, body, and dependencies. Only draft and ready are
            human-settable.
          </p>
          {taskDocument && taskDocument.tasks.length === 0 && snapshotMatchesMarkdown ? (
            <p className="rounded-lg border border-line bg-surface-raised p-3 text-sm leading-5 text-copy-muted">
              No tasks in this saved backlog. Open Markdown to review or edit its contents.
            </p>
          ) : null}
          {taskDocument && taskDocument.tasks.length > 0 ? (
            <ul className="grid max-h-[55vh] min-w-0 gap-2 overflow-y-auto pr-1">
              {taskDocument.tasks.map((task) => {
                const isSelected = selectedTaskId === task.id;
                const nextStatus: EditableTaskStatus | null =
                  task.status === "-" ? " " : task.status === " " ? "-" : null;
                const taskIsEditable = nextStatus !== null;
                return (
                  <li className="grid min-w-0 gap-2 border-b border-line py-2" key={task.id}>
                    <Button
                      aria-label={`Select task ${task.id}: ${task.title}`}
                      aria-pressed={isSelected}
                      className="backlog-task-row"
                      variant="ghost"
                      disabled={
                        !snapshotMatchesMarkdown || formIsDirty || conflict !== null || taskBusy
                      }
                      onClick={() => selectTask(task)}
                      ref={isSelected ? selectedTaskButtonRef : undefined}
                      type="button"
                    >
                      <span className="block break-all font-mono text-xs text-copy-muted">
                        {task.id}
                      </span>
                      <span className="mt-1 block break-words text-sm font-medium">
                        {task.title}
                      </span>
                      <Badge className="mt-2" tone={taskIsEditable ? "info" : "neutral"}>
                        <span aria-hidden="true">[{task.status}]</span>
                        {taskStatusLabel(task.status)}
                      </Badge>
                      {task.status === " " && !task.eligible ? (
                        <span className="mt-2 block break-words text-xs leading-5 text-amber-100">
                          Waiting on {task.waiting_on.join(", ") || "prerequisites"}
                        </span>
                      ) : task.eligible ? (
                        <span className="mt-2 block text-xs text-copy-muted">
                          Dependency-eligible
                        </span>
                      ) : null}
                    </Button>
                    {taskIsEditable ? (
                      <Button
                        aria-controls={taskDetailId}
                        aria-label={`Mark ${task.id} ${nextStatus === " " ? "ready" : "draft"}`}
                        className="workbench-quiet"
                        variant="ghost"
                        icon={nextStatus === " " ? "check" : "document"}
                        disabled={!taskActionsAllowed || taskPending}
                        onClick={() => toggleTaskStatus(task)}
                        type="button"
                      >
                        Mark {nextStatus === " " ? "ready" : "draft"}
                      </Button>
                    ) : (
                      <p className="px-2 pb-1 text-xs leading-5 text-copy-muted">
                        Runner-managed status · read-only
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </aside>

        <section
          aria-labelledby={`${generatedId}-task-detail-title`}
          className="backlog-detail min-w-0"
          id={taskDetailId}
        >
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
            <div className="min-w-0">
              <p className="text-sm text-copy-muted">Task details</p>
              <h5
                className="mt-1 break-words text-base font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                id={`${generatedId}-task-detail-title`}
                ref={taskDetailHeadingRef}
                tabIndex={-1}
              >
                {detailTask ? `${detailTask.id} · ${detailTask.title}` : "Choose a task"}
              </h5>
            </div>
            {detailTask ? (
              <Badge>
                [{detailTask.status}] {taskStatusLabel(detailTask.status)}
              </Badge>
            ) : null}
          </div>

          {!taskDocument && loadState === "loading" ? (
            <p aria-live="polite" className="py-6 text-sm text-copy-muted" role="status">
              Task details are loading…
            </p>
          ) : null}
          {taskDocument && taskDocument.tasks.length === 0 && snapshotMatchesMarkdown ? (
            <p className="py-6 text-sm leading-6 text-copy-muted">
              This backlog has no saved tasks yet. The Markdown editor remains available for direct
              review and editing.
            </p>
          ) : null}
          {detailTask && !draft && conflict === null ? (
            <div className="grid min-w-0 gap-4 py-4">
              <p className="text-sm leading-6 text-copy-muted">
                This task has a runner-owned status and cannot be changed in the planning UI. Its
                title, body, dependencies, and marker are read-only here.
              </p>
              <dl className="grid min-w-0 gap-3">
                <div>
                  <dt className="text-xs font-medium text-copy-muted">Dependencies</dt>
                  <dd className="mt-1 break-words text-sm text-foreground">
                    {detailTask.dependencies.length ? detailTask.dependencies.join(", ") : "None"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium text-copy-muted">Task body · Markdown</dt>
                  <dd className="mt-1 min-w-0 overflow-x-auto rounded-lg border border-line bg-canvas p-3 font-mono text-xs leading-5 text-foreground">
                    <pre className="whitespace-pre-wrap break-words">
                      {detailTask.body || "(empty)"}
                    </pre>
                  </dd>
                </div>
              </dl>
            </div>
          ) : null}
          {!detailTask && taskDocument?.tasks.length ? (
            <p className="py-6 text-sm leading-6 text-copy-muted">
              Select a task from the list to see its editable details.
            </p>
          ) : null}

          {displayedDraft && (draft !== null || conflict !== null) ? (
            <div className="grid min-w-0 gap-4 py-4">
              {conflict ? (
                <section
                  aria-labelledby={`${generatedId}-task-conflict-title`}
                  className="grid min-w-0 gap-3 rounded-lg border border-amber-200/35 bg-amber-100/5 p-3"
                  role="alert"
                >
                  <div>
                    <h6
                      className="font-semibold text-amber-100"
                      id={`${generatedId}-task-conflict-title`}
                    >
                      Backlog changed during this task edit
                    </h6>
                    <p className="mt-1 break-words text-sm leading-6 text-copy-muted">
                      {conflict.message}
                    </p>
                    <p className="mt-1 text-xs text-copy-muted">
                      Attempted revision {conflict.expectedRevision}
                      {conflict.latestRevision !== null
                        ? ` · latest saved revision ${conflict.latestRevision}`
                        : " · latest revision not loaded"}
                    </p>
                  </div>
                  {conflict.state === "loading" ? (
                    <p aria-live="polite" className="text-sm text-copy-muted" role="status">
                      Loading the latest saved task…
                    </p>
                  ) : null}
                  {conflict.state === "error" ? (
                    <>
                      <p className="text-sm leading-6 text-red-100">{conflict.message}</p>
                      <Button
                        className="justify-self-start"
                        icon="refresh"
                        disabled={taskBusy}
                        onClick={retryConflict}
                        type="button"
                      >
                        {taskBusy ? "Reloading latest task…" : "Retry latest task"}
                      </Button>
                    </>
                  ) : null}
                  {conflict.latestTask ? (
                    <details className="min-w-0 rounded-lg border border-line bg-canvas px-3 py-2">
                      <summary className="min-h-11 cursor-pointer py-2 text-sm font-medium text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
                        Review latest saved {conflict.latestTask.id} before reapplying
                      </summary>
                      <dl className="mt-2 grid min-w-0 gap-3 pb-2 text-sm">
                        <div>
                          <dt className="text-xs font-medium text-copy-muted">
                            Latest saved title
                          </dt>
                          <dd className="mt-1 break-words text-foreground">
                            {conflict.latestTask.title}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs font-medium text-copy-muted">
                            Latest saved readiness and dependencies
                          </dt>
                          <dd className="mt-1 break-words text-foreground">
                            {taskStatusLabel(conflict.latestTask.status)} ·{" "}
                            {conflict.latestTask.dependencies.length
                              ? conflict.latestTask.dependencies.join(", ")
                              : "no dependencies"}
                          </dd>
                        </div>
                        <div>
                          <dt className="text-xs font-medium text-copy-muted">Latest saved body</dt>
                          <dd className="mt-1 min-w-0 overflow-x-auto rounded-md border border-line p-2 font-mono text-xs leading-5 text-foreground">
                            <pre className="whitespace-pre-wrap break-words">
                              {conflict.latestTask.body || "(empty)"}
                            </pre>
                          </dd>
                        </div>
                      </dl>
                    </details>
                  ) : null}
                  {conflict.state === "ready" ? (
                    <div className="flex min-w-0 flex-wrap items-center gap-3">
                      <Button
                        icon="history"
                        disabled={
                          !conflict.latestTask ||
                          !isEditableStatus(conflict.latestTask.status) ||
                          !snapshotMatchesMarkdown ||
                          taskBusy ||
                          !canEditTasks
                        }
                        onClick={armReapply}
                        type="button"
                      >
                        Reapply attempted task edits to revision {taskDocument?.revision_number}
                      </Button>
                      {conflict.reapplyRevision === taskDocument?.revision_number ? (
                        <span aria-live="polite" className="text-sm text-accent" role="status">
                          Reapply confirmed for revision {conflict.reapplyRevision}. Save to create
                          a new revision.
                        </span>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {draft !== null || (conflict !== null && conflict.latestTask === null) ? (
                <form className="grid min-w-0 gap-4" onSubmit={submitTaskForm}>
                  <div className="grid min-w-0 gap-2">
                    <label
                      className="text-sm font-medium text-foreground"
                      htmlFor={`${generatedId}-task-title`}
                    >
                      Task title
                    </label>
                    <Input
                      aria-invalid={Boolean(titleError)}
                      aria-describedby={titleError ? `${generatedId}-task-title-error` : undefined}
                      disabled={!taskActionsAllowed || !snapshotMatchesMarkdown}
                      id={`${generatedId}-task-title`}
                      maxLength={256}
                      onChange={(event) => updateDraftField("title", event.target.value)}
                      required
                      value={displayedDraft.title}
                    />
                    {titleError ? (
                      <p
                        className="text-sm text-danger"
                        id={`${generatedId}-task-title-error`}
                        role="alert"
                      >
                        {titleError}
                      </p>
                    ) : null}
                  </div>

                  <div className="grid min-w-0 gap-2">
                    <label
                      className="text-sm font-medium text-foreground"
                      htmlFor={`${generatedId}-task-dependencies`}
                    >
                      Dependencies · task IDs, comma-separated
                    </label>
                    <Input
                      aria-describedby={`${generatedId}-task-dependencies-hint`}
                      disabled={!taskActionsAllowed || !snapshotMatchesMarkdown}
                      id={`${generatedId}-task-dependencies`}
                      onChange={(event) => updateDraftField("dependencies", event.target.value)}
                      value={displayedDraft.dependencies}
                    />
                    <p
                      className="text-xs leading-5 text-copy-muted"
                      id={`${generatedId}-task-dependencies-hint`}
                    >
                      Leave blank for no dependencies. IDs must already exist; the saved backlog
                      validator rejects unknown tasks and dependency cycles.
                    </p>
                  </div>

                  <div className="grid min-w-0 gap-2">
                    <label
                      className="text-sm font-medium text-foreground"
                      htmlFor={`${generatedId}-task-body`}
                    >
                      Task body · Markdown
                    </label>
                    <textarea
                      className="ui-input min-h-56 resize-y py-3 font-mono text-sm leading-6"
                      disabled={!taskActionsAllowed || !snapshotMatchesMarkdown}
                      id={`${generatedId}-task-body`}
                      onChange={(event) => updateDraftField("body", event.target.value)}
                      spellCheck={false}
                      value={displayedDraft.body}
                    />
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-copy-muted">
                      <span>
                        Dependencies are edited above; an inline Depends on line stays in sync when
                        saved.
                      </span>
                      <span>{bodySize.toLocaleString()} / 131,072 bytes</span>
                    </div>
                    {bodyTooLarge ? (
                      <p className="text-sm text-red-200" role="alert">
                        This task body exceeds the 128 KiB limit. Shorten it before saving.
                      </p>
                    ) : null}
                  </div>

                  {baseTask && isEditableStatus(baseTask.status) ? (
                    <p className="text-sm leading-5 text-copy-muted" role="status">
                      Readiness is changed with the task-row draft/ready control. Current state:{" "}
                      {taskStatusLabel(displayedDraft.status)}.
                    </p>
                  ) : null}
                  <div className="flex min-w-0 flex-wrap items-center gap-3 border-t border-line pt-4">
                    <Button icon="save" variant="primary" disabled={!canSaveDraft} type="submit">
                      {taskBusy
                        ? "Saving task…"
                        : conflict?.reapplyRevision === taskDocument?.revision_number
                          ? "Save re-applied task edits"
                          : "Save task changes"}
                    </Button>
                    <Button
                      disabled={!taskPending || taskBusy}
                      onClick={discardTaskChanges}
                      type="button"
                    >
                      Discard task edits
                    </Button>
                    {taskPending ? (
                      <span className="text-xs text-copy-muted">
                        Unsaved task text · save or discard before switching projects or drafts
                      </span>
                    ) : null}
                  </div>
                </form>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>
    </section>
  );
}
