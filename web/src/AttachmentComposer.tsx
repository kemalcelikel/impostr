import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ChatAttachment } from "./chat";
import { Badge, Button, Disclosure, Feedback, Field, IconButton, Input } from "./ui/controls";
import { Icon } from "./ui/Icon";

type AttachmentRecord = {
  id: string;
  filename: string;
  status: string;
  original_size: number | null;
  original_sha256: string | null;
  native_available: boolean;
};
type AttachmentPage = { attachments: AttachmentRecord[]; next_after: string | null };

function formatSize(size: number): string {
  return `${size.toLocaleString()} bytes`;
}

function detail(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) return null;
  const message = (payload as { detail?: unknown }).detail;
  return typeof message === "string" ? message : null;
}

export default function AttachmentComposer({
  projectId,
  conversationId,
  csrfToken,
  selected,
  disabled,
  onSelectionChange,
  onSessionExpired,
}: {
  projectId: string;
  conversationId: string;
  csrfToken: string;
  selected: ChatAttachment[];
  disabled: boolean;
  onSelectionChange: (attachments: ChatAttachment[]) => void;
  onSessionExpired: () => void;
}) {
  const path = `/api/projects/${encodeURIComponent(projectId)}/chat/${encodeURIComponent(
    conversationId,
  )}/attachments`;
  const [attachments, setAttachments] = useState<AttachmentRecord[]>([]);
  const [nextAfter, setNextAfter] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const scope = useRef<AbortController | null>(null);
  const inventoryRevision = useRef(0);

  const loadPage = useCallback(
    async (after: string | null, signal: AbortSignal): Promise<void> => {
      const query = after ? `?after=${encodeURIComponent(after)}` : "";
      const revision = inventoryRevision.current;
      let page: AttachmentPage;
      try {
        page = await apiRequest<AttachmentPage>(`${path}${query}`, { signal });
      } catch (failure) {
        if (signal.aborted || revision !== inventoryRevision.current) return;
        throw failure;
      }
      if (signal.aborted || revision !== inventoryRevision.current) return;
      setAttachments((current) =>
        after
          ? [
              ...current,
              ...page.attachments.filter((item) => !current.some((old) => old.id === item.id)),
            ]
          : page.attachments,
      );
      setNextAfter(page.next_after);
    },
    [path],
  );

  useEffect(() => {
    const controller = new AbortController();
    scope.current = controller;
    void loadPage(null, controller.signal)
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 401) onSessionExpired();
        else setError(failure instanceof Error ? failure.message : "PDF list is unavailable.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      if (scope.current === controller) scope.current = null;
    };
  }, [loadPage, onSessionExpired, path]);

  function replaceSelection(next: ChatAttachment[]): void {
    onSelectionChange(next);
  }

  function toggle(item: AttachmentRecord): void {
    const existing = selected.findIndex((entry) => entry.attachment_id === item.id);
    if (existing >= 0) {
      replaceSelection(selected.filter((entry) => entry.attachment_id !== item.id));
      return;
    }
    if (!item.native_available || !item.original_sha256 || item.original_size === null) return;
    replaceSelection([
      ...selected,
      {
        attachment_id: item.id,
        expected_sha256: item.original_sha256,
        reference_kind: "native-original-v1",
        filename: item.filename,
        original_size: item.original_size,
      },
    ]);
  }

  function removeSelection(attachmentId: string): void {
    replaceSelection(selected.filter((entry) => entry.attachment_id !== attachmentId));
  }

  function move(index: number, delta: number): void {
    const destination = index + delta;
    if (destination < 0 || destination >= selected.length) return;
    const ordered = [...selected];
    [ordered[index], ordered[destination]] = [ordered[destination]!, ordered[index]!];
    replaceSelection(ordered);
  }

  async function upload(file: File | undefined): Promise<void> {
    const controller = scope.current;
    if (!file || !controller || disabled || busy) return;
    setBusy(true);
    setActivity("Uploading PDF… not yet stored or sent.");
    setError("");
    setNotice("");
    try {
      const query = new URLSearchParams({ filename: file.name });
      const response = await fetch(`${path}/upload?${query}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf", "X-CSRF-Token": csrfToken },
        body: file,
        cache: "no-store",
        credentials: "same-origin",
        signal: controller.signal,
      });
      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        payload = undefined;
      }
      if (controller.signal.aborted) return;
      if (!response.ok) {
        if (response.status === 401) {
          onSessionExpired();
          return;
        }
        throw new ApiError(detail(payload) ?? "PDF upload failed.", response.status, payload);
      }
      if (controller.signal.aborted) return;
      const uploaded = payload as AttachmentRecord;
      inventoryRevision.current += 1;
      setAttachments((current) =>
        [...current.filter((item) => item.id !== uploaded.id), uploaded].sort((a, b) =>
          a.id.localeCompare(b.id),
        ),
      );
      setNotice(`${file.name} stored. It has not been sent.`);
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) onSessionExpired();
      else setError(failure instanceof Error ? failure.message : "PDF upload failed.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  async function download(item: AttachmentRecord | ChatAttachment): Promise<void> {
    const controller = scope.current;
    if (!controller) return;
    const attachmentId = "id" in item ? item.id : item.attachment_id;
    setError("");
    try {
      const response = await fetch(`${path}/${encodeURIComponent(attachmentId)}/raw`, {
        headers: { Accept: "application/pdf" },
        cache: "no-store",
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!response.ok) {
        let payload: unknown;
        try {
          payload = await response.json();
        } catch {
          payload = undefined;
        }
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          onSessionExpired();
          return;
        }
        throw new ApiError(detail(payload) ?? "Original PDF is unavailable.", response.status);
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = item.filename;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) onSessionExpired();
      else setError(failure instanceof Error ? failure.message : "Original PDF is unavailable.");
    }
  }

  async function remove(item: AttachmentRecord): Promise<void> {
    const controller = scope.current;
    if (!controller || busy || disabled) return;
    setBusy(true);
    setActivity("Deleting stored PDF…");
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ status?: string }>(
        `${path}/${encodeURIComponent(item.id)}`,
        { method: "DELETE", csrfToken, signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      inventoryRevision.current += 1;
      setAttachments((current) => current.filter((entry) => entry.id !== item.id));
      replaceSelection(selected.filter((entry) => entry.attachment_id !== item.id));
      setNotice(
        result?.status === "cleanup-pending"
          ? `${item.filename} is unavailable for future sends; cleanup is pending. Prior sends cannot be retracted.`
          : `${item.filename} deleted. Prior sends cannot be retracted.`,
      );
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) onSessionExpired();
      else if (failure instanceof ApiError && failure.status === 409)
        setError(`${failure.message} The PDF is still stored; stop the turn before deleting it.`);
      else setError(failure instanceof Error ? failure.message : "PDF deletion failed.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <section aria-labelledby={`pdf-heading-${conversationId}`} className="attachment-composer">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="sr-only" id={`pdf-heading-${conversationId}`}>
          <Icon name="attachment" />
          Original PDF references
        </h3>
        <Badge tone={selected.length ? "info" : "neutral"}>
          {selected.length} selected · not yet sent
        </Badge>
      </div>
      <p className="attachment-consequence" id={`pdf-summary-${conversationId}`}>
        Selected PDFs go to Azure with Send. Uploading alone does not send them; prior sends cannot
        be retracted.
      </p>
      {selected.length ? (
        <div aria-label="Ordered selected PDFs" className="grid min-w-0 gap-2" role="group">
          <p className="sr-only">Selected, in send order</p>
          <ol className="attachment-selection">
            {selected.map((item, index) => {
              const available = attachments.some(
                (record) => record.id === item.attachment_id && record.native_available,
              );
              return (
                <li className="attachment-selected-row" key={item.attachment_id}>
                  <div className="flex min-w-0 items-start gap-2">
                    <span className="min-w-5 text-center text-xs leading-6 text-copy-muted">
                      {index + 1}.
                    </span>
                    <Icon name="document" className="mt-0.5" />
                    <div className="min-w-0 flex-1">
                      <p className="attachment-filename">{item.filename}</p>
                      <Badge className="mt-1" tone={available ? "info" : "warning"}>
                        {formatSize(item.original_size)} · {available ? "Selected" : "Unavailable"}
                      </Badge>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-1">
                    <IconButton
                      label={`Move ${item.filename} earlier`}
                      className="workbench-quiet"
                      icon="chevronLeft"
                      disabled={disabled || busy || index === 0}
                      onClick={() => move(index, -1)}
                      type="button"
                    />
                    <IconButton
                      label={`Move ${item.filename} later`}
                      className="workbench-quiet"
                      icon="chevronRight"
                      disabled={disabled || busy || index === selected.length - 1}
                      onClick={() => move(index, 1)}
                      type="button"
                    />
                    <IconButton
                      label={`Remove ${item.filename} from ordered send selection`}
                      className="workbench-quiet"
                      icon="close"
                      variant="ghost"
                      disabled={disabled || busy}
                      onClick={() => removeSelection(item.attachment_id)}
                      type="button"
                    />
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
      <Disclosure
        className="attachment-disclosure"
        title={`Manage PDFs · ${loading ? "loading" : `${attachments.length} stored${nextAfter ? "+" : ""}`}`}
        icon="attachment"
      >
        <div className="grid min-w-0 gap-3 pt-3">
          <Field
            id={`pdf-upload-${conversationId}`}
            label="Upload a PDF"
            hint="PDF only. Upload first, then select it for a future send."
          >
            <Input
              id={`pdf-upload-${conversationId}`}
              accept="application/pdf,.pdf"
              aria-describedby={`pdf-upload-${conversationId}-hint`}
              className="file:mr-3 file:min-h-8 file:rounded-sm file:border-0 file:bg-surface-raised file:px-3 file:text-sm file:font-medium file:text-foreground"
              disabled={disabled || busy}
              onChange={(event) => {
                const input = event.currentTarget;
                void upload(input.files?.[0]);
                input.value = "";
              }}
              type="file"
            />
          </Field>
          <p className="text-xs font-medium text-copy-muted">
            Stored PDFs · select to include in a message
          </p>
          {attachments.length ? (
            <ul
              aria-label="Stored PDFs"
              className="grid max-h-64 min-w-0 gap-2 overflow-y-auto p-1"
            >
              {attachments.map((item) => {
                const isSelected = selected.some((entry) => entry.attachment_id === item.id);
                const usable = item.status === "stored" && item.native_available;
                return (
                  <li className="attachment-inventory-row" key={item.id}>
                    <div className="flex min-w-0 items-start gap-2">
                      <Icon name="document" className="mt-0.5" />
                      <div className="min-w-0 flex-1">
                        <p className="break-words text-sm font-medium">{item.filename}</p>
                        <Badge
                          className="mt-1"
                          tone={isSelected ? "info" : usable ? "neutral" : "warning"}
                        >
                          {item.original_size === null
                            ? "Original unavailable"
                            : formatSize(item.original_size)}
                          {" · "}
                          {isSelected
                            ? "Selected"
                            : usable
                              ? "Stored"
                              : "Unavailable for new sends"}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      <IconButton
                        label={`Download ${item.filename}`}
                        icon="download"
                        disabled={busy}
                        onClick={() => void download(item)}
                        type="button"
                      />
                      <Button
                        aria-label={`${isSelected ? "Remove" : "Attach"} ${item.filename}${
                          isSelected ? " from selection" : ""
                        }`}
                        icon={isSelected ? "close" : "attachment"}
                        className="workbench-quiet"
                        variant="ghost"
                        aria-pressed={isSelected}
                        disabled={
                          disabled ||
                          busy ||
                          (!usable && !isSelected) ||
                          (!isSelected && selected.length >= 32)
                        }
                        onClick={() => toggle(item)}
                        type="button"
                      >
                        {isSelected ? "Remove selection" : "Attach"}
                      </Button>
                      <IconButton
                        label={`Delete ${item.filename}`}
                        icon="trash"
                        variant="danger"
                        disabled={disabled || busy}
                        onClick={() => void remove(item)}
                        type="button"
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-copy-muted">
              {loading ? "Loading stored PDFs…" : "No stored PDFs in this conversation."}
            </p>
          )}
          {nextAfter ? (
            <Button
              className="justify-self-start"
              disabled={busy}
              onClick={() => {
                const controller = scope.current;
                if (!controller || !nextAfter) return;
                setBusy(true);
                setActivity("Loading stored PDFs…");
                void loadPage(nextAfter, controller.signal)
                  .catch((failure: unknown) => {
                    if (controller.signal.aborted) return;
                    if (failure instanceof ApiError && failure.status === 401) {
                      onSessionExpired();
                    } else {
                      setError(
                        failure instanceof Error ? failure.message : "PDF list is unavailable.",
                      );
                    }
                  })
                  .finally(() => {
                    if (!controller.signal.aborted) setBusy(false);
                  });
              }}
              type="button"
            >
              Load more PDFs
            </Button>
          ) : null}
        </div>
      </Disclosure>
      <Disclosure className="attachment-disclosure" title="PDF limits, cost & privacy" icon="info">
        <div className="grid gap-2 pt-2 text-xs leading-5 text-copy-muted">
          <p>
            Each PDF and the combined original files in a request must be under 50,000,000 bytes,
            including retained earlier-turn references. Page images, transport overhead and model
            context limits still apply; starting a new conversation can reduce retained references.
          </p>
          <p>
            The model may receive extracted text and page images from the original PDFs. Page images
            add context and cost. A sent receipt confirms submission, not provider acceptance,
            parsing or comprehension.
          </p>
          <p>
            Removing a selection only affects a future send. Deleting a stored PDF fences future
            use, but cannot retract prior provider requests, quotations or backups; cleanup may
            remain pending. Stop an active turn before deleting its PDFs.
          </p>
        </div>
      </Disclosure>
      {busy ? (
        <Feedback className="text-xs" role="status">
          {activity}
        </Feedback>
      ) : null}
      {notice ? <Feedback role="status">{notice}</Feedback> : null}
      {error ? (
        <Feedback tone="danger" role="alert">
          {error}
        </Feedback>
      ) : null}
    </section>
  );
}
