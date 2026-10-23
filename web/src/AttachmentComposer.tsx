import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiRequest } from "./api";
import type { ChatAttachment } from "./chat";

type AttachmentRecord = {
  id: string;
  filename: string;
  status: string;
  original_size: number | null;
  original_sha256: string | null;
  native_available: boolean;
};
type AttachmentPage = { attachments: AttachmentRecord[]; next_after: string | null };

const button =
  "min-h-11 rounded-lg border border-line bg-canvas px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50";
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
    <section aria-labelledby={`pdf-heading-${conversationId}`} className="grid min-w-0 gap-3">
      <h3 className="font-medium" id={`pdf-heading-${conversationId}`}>
        Original PDF references
      </h3>
      <p className="text-xs leading-5 text-copy-muted">
        Selected original PDFs are sent to Azure with the request. The model may receive extracted
        text and page images; page images add context and cost. Removing a selection only affects a
        future send. Deleting a stored PDF cannot retract an earlier send. Each PDF and the combined
        original files included in a request, including retained earlier-turn references, must be
        under 50,000,000 bytes; page images and model context limits still apply.
      </p>
      <label className="grid gap-2 text-sm">
        Upload a PDF
        <input
          accept="application/pdf,.pdf"
          aria-label="Upload a PDF"
          className="min-h-11 min-w-0 rounded-lg border border-line bg-canvas px-3 py-2 text-sm file:mr-3 file:min-h-8 file:rounded-md file:border-0 file:bg-surface-raised file:px-3 file:text-sm"
          disabled={disabled || busy}
          onChange={(event) => {
            const input = event.currentTarget;
            void upload(input.files?.[0]);
            input.value = "";
          }}
          type="file"
        />
      </label>
      {selected.length ? (
        <div aria-label="Ordered selected PDFs" className="grid min-w-0 gap-2" role="group">
          <p className="text-sm font-medium">Selected, in send order</p>
          <ol className="grid min-w-0 gap-2">
            {selected.map((item, index) => {
              const available = attachments.some(
                (record) => record.id === item.attachment_id && record.native_available,
              );
              return (
                <li
                  className="grid min-w-0 gap-2 rounded-lg border border-accent/30 bg-accent/5 p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                  key={item.attachment_id}
                >
                  <div className="min-w-0">
                    <p className="break-all text-sm font-medium">{item.filename}</p>
                    <p className="text-xs text-copy-muted">
                      {formatSize(item.original_size)} · {available ? "Selected" : "Unavailable"}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      aria-label={`Move ${item.filename} earlier`}
                      className={button}
                      disabled={disabled || busy || index === 0}
                      onClick={() => move(index, -1)}
                      type="button"
                    >
                      Earlier
                    </button>
                    <button
                      aria-label={`Move ${item.filename} later`}
                      className={button}
                      disabled={disabled || busy || index === selected.length - 1}
                      onClick={() => move(index, 1)}
                      type="button"
                    >
                      Later
                    </button>
                    <button
                      aria-label={`Remove ${item.filename} from ordered send selection`}
                      className={button}
                      disabled={disabled || busy}
                      onClick={() => removeSelection(item.attachment_id)}
                      type="button"
                    >
                      Remove selection
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
      <div className="grid min-w-0 gap-2">
        <p className="text-sm font-medium">Stored PDFs</p>
        {attachments.length ? (
          <ul className="grid min-w-0 gap-2">
            {attachments.map((item) => {
              const isSelected = selected.some((entry) => entry.attachment_id === item.id);
              const usable = item.status === "stored" && item.native_available;
              return (
                <li
                  className="grid min-w-0 gap-2 rounded-lg border border-line bg-canvas p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                  key={item.id}
                >
                  <div className="min-w-0">
                    <p className="break-all text-sm font-medium">{item.filename}</p>
                    <p className="text-xs text-copy-muted">
                      {item.original_size === null
                        ? "Original unavailable"
                        : formatSize(item.original_size)}
                      {" · "}
                      {isSelected ? "Selected" : usable ? "Stored" : "Unavailable for new sends"}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      aria-label={`Download ${item.filename}`}
                      className={button}
                      disabled={busy}
                      onClick={() => void download(item)}
                      type="button"
                    >
                      Download
                    </button>
                    <button
                      aria-label={`${isSelected ? "Remove" : "Attach"} ${item.filename}${
                        isSelected ? " from selection" : ""
                      }`}
                      className={button}
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
                    </button>
                    <button
                      aria-label={`Delete ${item.filename}`}
                      className={button}
                      disabled={disabled || busy}
                      onClick={() => void remove(item)}
                      type="button"
                    >
                      Delete stored PDF
                    </button>
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
          <button
            className={`${button} justify-self-start`}
            disabled={busy}
            onClick={() => {
              const controller = scope.current;
              if (!controller || !nextAfter) return;
              setBusy(true);
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
          </button>
        ) : null}
      </div>
      {busy ? (
        <p className="text-xs text-copy-muted" role="status">
          Updating PDFs…
        </p>
      ) : null}
      {notice ? (
        <p className="text-sm text-accent" role="status">
          {notice}
        </p>
      ) : null}
      {error ? (
        <p className="text-sm text-red-200" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
