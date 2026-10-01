import { ApiError } from "./api";

export type ChatEvent = {
  id: number;
  turn_id: string;
  sequence: number;
  type: string;
  data: Record<string, unknown>;
};
export type ChatTurn = { id: string; prompt: string; state: string };
export type Question = {
  header: string;
  question: string;
  options: { label: string; description: string }[];
  multiple?: boolean;
  custom?: boolean;
};
export type Interaction = {
  id: string;
  turn_id: string;
  kind: "question" | "permission";
  state: string;
  data: { questions?: Question[]; permission?: string; once_allowed?: boolean };
};
export type ChatHistory = { turns: ChatTurn[]; interactions: Interaction[] };
export type ChatDraft = { text: string; requestId: string };
export type ChatMemory = {
  drafts: Record<string, ChatDraft>;
  answers: Record<string, string[][]>;
  replies?: Record<string, { requestId: string; answer: unknown }>;
};
export const terminalStates = new Set(["completed", "failed", "cancelled", "interrupted"]);

export function mergeEvents(current: ChatEvent[], incoming: ChatEvent[]): ChatEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) {
    if (!Number.isSafeInteger(event.id) || event.id < 1 || typeof event.turn_id !== "string") {
      throw new Error("Invalid chat replay. Reconnect to reload history.");
    }
    byId.set(event.id, event);
  }
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

// Fetch rather than EventSource lets HTTP 401 be distinguished from an outage,
// and aborts both the request and the reader on navigation/auth-generation change.
export async function streamChat(
  path: string,
  signal: AbortSignal,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch(path, {
    headers: { Accept: "text/event-stream" },
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) throw new ApiError("Chat stream unavailable.", response.status);
  if (!response.body || !response.headers.get("Content-Type")?.startsWith("text/event-stream")) {
    throw new Error("Chat streaming is unavailable.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      pending = (pending + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
      if (pending.length > 1024 * 1024)
        throw new Error("Chat stream frame exceeds supported bounds.");
      let end: number;
      while ((end = pending.indexOf("\n\n")) !== -1) {
        const frame = pending.slice(0, end);
        pending = pending.slice(end + 2);
        const lines = frame.split("\n");
        const kind = lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        if (kind === "unavailable") throw new ApiError("Chat authorization or service changed.", 0);
        if (kind !== "chat") continue;
        const data = lines
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        onEvent(JSON.parse(data) as ChatEvent);
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
