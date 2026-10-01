import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";
import {
  mergeEvents,
  streamChat,
  terminalStates,
  type ChatEvent,
  type ChatHistory,
  type ChatMemory,
  type ChatTurn,
  type Interaction,
} from "./chat";

const control =
  "min-h-11 rounded-lg border border-line bg-canvas px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50";
type Conversation = { id: string; title: string };
const ignoreMemory: (snapshot: ChatMemory) => void = () => {};

function InteractionCard({
  interaction,
  initialAnswers,
  busy,
  onReply,
  onDraft,
}: {
  interaction: Interaction;
  initialAnswers?: string[][];
  busy: boolean;
  onReply: (answer: unknown) => void;
  onDraft: (answers: string[][]) => void;
}) {
  const [answers, setAnswers] = useState<string[][]>(
    () => initialAnswers ?? interaction.data.questions?.map(() => []) ?? [],
  );
  const [custom, setCustom] = useState<Record<number, string>>({});
  function update(index: number, values: string[]) {
    const next = answers.map((value, i) => (i === index ? values : value));
    setAnswers(next);
    onDraft(next);
  }
  return (
    <div className="grid gap-3 rounded-lg border border-amber-200/30 bg-amber-100/5 p-3">
      <p className="text-sm font-semibold">
        {interaction.kind === "permission" ? "Permission required" : "Answer required"}
      </p>
      {interaction.kind === "permission" ? (
        <>
          <p className="break-words text-sm">{interaction.data.permission}</p>
          <p className="text-xs text-copy-muted">
            Only this operation can be allowed once. Unrestricted or always access is not available.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              className={control}
              disabled={busy || !interaction.data.once_allowed}
              onClick={() => onReply({ reply: "once" })}
              type="button"
            >
              Allow once
            </button>
            <button
              className={control}
              disabled={busy}
              onClick={() => onReply({ reply: "reject" })}
              type="button"
            >
              Reject
            </button>
          </div>
        </>
      ) : (
        <form
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            onReply({ answers });
          }}
        >
          {interaction.data.questions?.map((question, index) => (
            <fieldset className="grid min-w-0 gap-2" key={index} disabled={busy}>
              <legend className="text-sm font-medium">
                {question.header}: {question.question}
              </legend>
              {question.options.map((option) => (
                <label className="flex min-h-11 items-center gap-2 text-sm" key={option.label}>
                  <input
                    type={question.multiple ? "checkbox" : "radio"}
                    name={`${interaction.id}-${index}`}
                    checked={answers[index]?.includes(option.label) ?? false}
                    onChange={(event) =>
                      update(
                        index,
                        question.multiple
                          ? event.target.checked
                            ? [...(answers[index] ?? []), option.label]
                            : (answers[index] ?? []).filter((value) => value !== option.label)
                          : [option.label],
                      )
                    }
                  />
                  <span>
                    {option.label}
                    <span className="block text-xs text-copy-muted">{option.description}</span>
                  </span>
                </label>
              ))}
              {question.custom !== false ? (
                <label className="grid gap-2 text-sm">
                  Custom answer
                  <input
                    className={control}
                    maxLength={4096}
                    value={
                      custom[index] ??
                      answers[index]?.find(
                        (value) => !question.options.some((option) => option.label === value),
                      ) ??
                      ""
                    }
                    onChange={(event) => {
                      setCustom((current) => ({ ...current, [index]: event.target.value }));
                      update(index, event.target.value ? [event.target.value] : []);
                    }}
                  />
                </label>
              ) : null}
            </fieldset>
          ))}
          <button
            className={control}
            disabled={busy || answers.length === 0 || answers.some((values) => values.length === 0)}
            type="submit"
          >
            Submit answers
          </button>
        </form>
      )}
    </div>
  );
}

export default function ProjectChat({
  projectId,
  csrfToken,
  memory,
  onMemoryChange = ignoreMemory,
  onSessionExpired,
  onDocumentsChanged,
  onCompareProposal,
  onPendingChange,
}: {
  projectId: string;
  csrfToken: string;
  memory?: ChatMemory;
  onMemoryChange?: (snapshot: ChatMemory) => void;
  onSessionExpired: () => void;
  onDocumentsChanged: () => void;
  onCompareProposal: (filename: string, proposalId: string) => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const root = `/api/projects/${encodeURIComponent(projectId)}/chat`;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState("");
  const [history, setHistory] = useState<ChatHistory>({ turns: [], interactions: [] });
  const [events, setEvents] = useState<ChatEvent[]>([]);
  // Props are a revalidated restoration seed, never a mutable shared store.
  const [draftsMemory, setDraftsMemory] = useState<ChatMemory>(
    () => memory ?? { drafts: {}, answers: {} },
  );
  const [connection, setConnection] = useState("Loading conversations…");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [authorized, setAuthorized] = useState(true);
  const [retry, setRetry] = useState(0);
  const scope = useRef<AbortController | null>(null);
  const actionScope = useRef<AbortController | null>(null);
  const actionBusy = useRef(false);
  const historyRegion = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const callbacks = useRef({ onSessionExpired, onDocumentsChanged });
  useLayoutEffect(() => {
    callbacks.current = { onSessionExpired, onDocumentsChanged };
  });
  const draft = draftsMemory.drafts[selected]?.text ?? "";
  const activeTurn = history.turns.find(
    (turn) =>
      !terminalStates.has(turn.state) &&
      !events.some((event) => event.turn_id === turn.id && terminalStates.has(event.type)),
  );
  const pending =
    Object.values(draftsMemory.drafts).some((value) => value.text.length > 0) ||
    Object.values(draftsMemory.answers).some((values) => values.some((value) => value.length));
  useEffect(() => {
    onPendingChange(pending);
  }, [pending, onPendingChange]);
  useEffect(() => {
    onMemoryChange(draftsMemory);
  }, [draftsMemory, onMemoryChange]);
  useLayoutEffect(() => {
    const region = historyRegion.current;
    if (region && follow.current) region.scrollTop = region.scrollHeight;
  }, [events, history]);

  useEffect(() => {
    const controller = new AbortController();
    actionScope.current = controller;
    void apiRequest<{ conversations: Conversation[]; last_conversation_id: string | null }>(root, {
      signal: controller.signal,
    })
      .then((value) => {
        if (controller.signal.aborted) return;
        setConversations(value.conversations);
        setSelected(value.last_conversation_id ?? value.conversations[0]?.id ?? "");
        setConnection(value.conversations.length ? "Connecting…" : "Start a new conversation.");
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        if (failure instanceof ApiError && failure.status === 401) {
          controller.abort();
          scope.current?.abort();
          callbacks.current.onSessionExpired();
        } else {
          setError(failure instanceof Error ? failure.message : "Chat unavailable.");
          setConnection("Disconnected");
        }
      });
    return () => {
      controller.abort();
      scope.current?.abort();
    };
  }, [root, retry]);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    scope.current = controller;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    let collected: ChatEvent[] = [];
    let historyRequest = 0;
    const base = `${root}/${encodeURIComponent(selected)}`;
    follow.current = true;
    async function refreshHistory() {
      const number = ++historyRequest;
      const value = await apiRequest<ChatHistory>(base, { signal: controller.signal });
      if (!controller.signal.aborted && number === historyRequest) setHistory(value);
    }
    function accept(incoming: ChatEvent[]) {
      if (controller.signal.aborted) return;
      const fresh = incoming.filter((event) => event.id > cursor);
      collected = mergeEvents(collected, incoming);
      cursor = collected.at(-1)?.id ?? cursor;
      setEvents(collected);
      if (fresh.some((event) => event.type !== "delta")) void refreshHistory().catch(handleFailure);
      if (fresh.some((event) => event.type === "completed")) callbacks.current.onDocumentsChanged();
    }
    function handleFailure(failure: unknown) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) {
        controller.abort();
        callbacks.current.onSessionExpired();
      } else {
        // The server's unavailable event may mean revocation. Hide private
        // replay until the next authenticated history request succeeds.
        if (failure instanceof ApiError) {
          setAuthorized(false);
          setHistory({ turns: [], interactions: [] });
          setEvents([]);
        }
        setConnection("Disconnected · reconnecting; your draft is kept");
      }
    }
    async function connect() {
      try {
        await refreshHistory(); // Revalidate auth after unavailable/revocation, before showing replay.
        if (!controller.signal.aborted) setAuthorized(true);
        while (!controller.signal.aborted) {
          const page = await apiRequest<{ events: ChatEvent[] }>(`${base}/events?after=${cursor}`, {
            signal: controller.signal,
          });
          accept(page.events);
          if (page.events.length < 64) break;
        }
        if (controller.signal.aborted) return;
        setConnection("Connected");
        await streamChat(`${base}/stream?after=${cursor}`, controller.signal, (event) =>
          accept([event]),
        );
      } catch (failure) {
        handleFailure(failure);
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void connect(), 1000);
    }
    void connect();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [root, selected, retry]);

  async function mutate<T>(
    path: string,
    body?: unknown,
    method: "POST" | "PUT" = "POST",
  ): Promise<T | undefined> {
    const controller = actionScope.current;
    if (!controller || controller.signal.aborted || actionBusy.current || !authorized) return;
    actionBusy.current = true;
    setBusy(true);
    setError("");
    try {
      const value = await apiRequest<T>(path, {
        method,
        csrfToken,
        body,
        signal: controller.signal,
      });
      return controller.signal.aborted ? undefined : value;
    } catch (failure) {
      if (controller.signal.aborted) return;
      if (failure instanceof ApiError && failure.status === 401) {
        controller.abort();
        scope.current?.abort();
        callbacks.current.onSessionExpired();
      } else
        setError(
          failure instanceof Error ? failure.message : "Chat request failed. Your text is kept.",
        );
    } finally {
      actionBusy.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  async function newConversation() {
    const value = await mutate<Conversation>(root, {
      title: `Conversation ${conversations.length + 1}`,
    });
    if (value) {
      setConversations((current) => [...current, value]);
      openConversation(value.id);
    }
  }
  function openConversation(id: string) {
    if (id === selected) return;
    scope.current?.abort();
    setEvents([]);
    setHistory({ turns: [], interactions: [] });
    setConnection("Connecting…");
    setSelected(id);
  }
  async function selectConversation(id: string) {
    // Serialize preference writes, so a late response cannot change last-used tab.
    const value = await mutate(`${root}/${id}/last-used`, undefined, "PUT");
    if (value) openConversation(id);
  }
  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!selected || busy || activeTurn || !draft.trim() || !draftsMemory.drafts[selected]) return;
    const sending = draftsMemory.drafts[selected];
    const value = await mutate<ChatTurn>(`${root}/${selected}/turns`, {
      request_id: sending.requestId,
      prompt: sending.text,
    });
    if (value) {
      setDraftsMemory((current) => {
        if (current.drafts[selected]?.requestId !== sending.requestId) return current;
        const drafts = { ...current.drafts };
        delete drafts[selected];
        return { ...current, drafts };
      });
      setHistory((current) => ({
        ...current,
        turns: [...current.turns.filter((turn) => turn.id !== value.id), value],
      }));
    }
  }
  async function reply(interaction: Interaction, answer: unknown) {
    const previous = draftsMemory.replies?.[interaction.id];
    const reservation =
      previous && JSON.stringify(previous.answer) === JSON.stringify(answer)
        ? previous
        : { requestId: crypto.randomUUID(), answer };
    setDraftsMemory((current) => ({
      ...current,
      replies: { ...current.replies, [interaction.id]: reservation },
    }));
    const value = await mutate<{ state: string }>(
      `${root}/${selected}/turns/${interaction.turn_id}/interactions/${interaction.id}/reply`,
      { request_id: reservation.requestId, answer },
    );
    if (value) {
      setDraftsMemory((current) => {
        const answers = { ...current.answers };
        delete answers[interaction.id];
        return { ...current, answers };
      });
      setHistory((current) => ({
        ...current,
        interactions: current.interactions.map((item) =>
          item.id === interaction.id ? { ...item, state: value.state } : item,
        ),
      }));
    }
  }

  if (!authorized)
    return (
      <section aria-label="Project conversation" className="rounded-xl border border-line p-4">
        <p role="status">Revalidating chat access. Private history and drafts are hidden.</p>
      </section>
    );
  return (
    <section
      aria-label="Project conversation"
      className="grid min-w-0 gap-4 rounded-xl border border-line bg-surface p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">Conversations</h4>
        <button
          className={control}
          disabled={busy}
          onClick={() => void newConversation()}
          type="button"
        >
          New conversation
        </button>
      </div>
      <div
        aria-label="Conversation tabs"
        role="tablist"
        className="flex min-w-0 gap-2 overflow-x-auto"
      >
        {conversations.map((conversation, index) => (
          <button
            aria-selected={selected === conversation.id}
            aria-controls={`chat-history-${projectId}`}
            id={`chat-tab-${conversation.id}`}
            role="tab"
            tabIndex={selected === conversation.id ? 0 : -1}
            className={`${control} shrink-0 ${selected === conversation.id ? "border-accent text-accent" : "text-copy-muted"}`}
            aria-disabled={busy}
            key={conversation.id}
            onClick={() => void selectConversation(conversation.id)}
            onKeyDown={(event) => {
              if (busy) return;
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const next =
                conversations[
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? conversations.length - 1
                      : (index + (event.key === "ArrowRight" ? 1 : -1) + conversations.length) %
                        conversations.length
                ];
              if (next) {
                document.getElementById(`chat-tab-${next.id}`)?.focus();
                void selectConversation(next.id);
              }
            }}
            type="button"
          >
            {conversation.title}
          </button>
        ))}
      </div>
      <p className="text-xs text-copy-muted" role="status">
        {connection}
        {activeTurn ? ` · ${activeTurn.state}` : ""}
      </p>
      {error ? (
        <div role="alert" className="text-sm text-red-200">
          {error}
          <button
            className={`${control} mt-2`}
            onClick={() => {
              setEvents([]);
              setHistory({ turns: [], interactions: [] });
              setConnection("Connecting…");
              setRetry((current) => current + 1);
            }}
            type="button"
          >
            Reconnect chat
          </button>
        </div>
      ) : null}
      <div
        role="tabpanel"
        aria-labelledby={selected ? `chat-tab-${selected}` : undefined}
        id={`chat-history-${projectId}`}
        tabIndex={0}
        ref={historyRegion}
        onScroll={() => {
          const region = historyRegion.current;
          if (region)
            follow.current = region.scrollHeight - region.scrollTop - region.clientHeight < 80;
        }}
        className="grid max-h-[32rem] min-h-40 min-w-0 content-start gap-4 overflow-y-auto rounded-lg bg-canvas p-3 focus-visible:outline-2 focus-visible:outline-accent"
      >
        {!history.turns.length ? (
          <p className="text-sm text-copy-muted">
            Plan with tech-lead. Saved drafts are shared across conversations; histories are
            separate.
          </p>
        ) : null}
        {history.turns.map((turn) => {
          const turnEvents = events.filter((event) => event.turn_id === turn.id);
          const proposals = turnEvents.flatMap((event) =>
            event.type === "proposals" && Array.isArray(event.data.items)
              ? (event.data.items as { id: string; state: string; filename: string }[])
              : [],
          );
          return (
            <article className="grid min-w-0 gap-3" key={turn.id}>
              <p className="text-xs font-semibold text-copy-muted">You</p>
              <p className="break-words whitespace-pre-wrap text-sm">{turn.prompt}</p>
              <p className="text-xs font-semibold text-accent">tech-lead · {turn.state}</p>
              <p className="break-words whitespace-pre-wrap text-sm leading-6">
                {turnEvents
                  .filter((event) => event.type === "delta")
                  .map((event) => String(event.data.text ?? ""))
                  .join("")}
              </p>
              {turnEvents
                .filter((event) => event.type === "failed" || event.type === "interrupted")
                .map((event) => (
                  <p className="text-sm text-amber-100" key={event.id}>
                    Turn {event.type}: {String(event.data.reason ?? "connection interrupted")}. No
                    automatic resubmission.
                  </p>
                ))}
              {history.interactions
                .filter(
                  (interaction) =>
                    interaction.turn_id === turn.id &&
                    interaction.state === "pending" &&
                    turn.state === "running",
                )
                .map((interaction) => (
                  <InteractionCard
                    key={interaction.id}
                    interaction={interaction}
                    initialAnswers={draftsMemory.answers[interaction.id]}
                    busy={busy}
                    onReply={(answer) => void reply(interaction, answer)}
                    onDraft={(answers) =>
                      setDraftsMemory((current) => ({
                        ...current,
                        answers: { ...current.answers, [interaction.id]: answers },
                      }))
                    }
                  />
                ))}
              {history.interactions
                .filter(
                  (interaction) =>
                    interaction.turn_id === turn.id && interaction.state === "replying",
                )
                .map((interaction) => (
                  <p className="text-xs text-copy-muted" key={interaction.id}>
                    Reply queued · waiting for worker acknowledgement
                  </p>
                ))}
              {history.interactions
                .filter(
                  (interaction) =>
                    interaction.turn_id === turn.id &&
                    !["pending", "replying"].includes(interaction.state),
                )
                .map((interaction) => (
                  <p className="text-xs text-copy-muted" key={interaction.id}>
                    {interaction.kind === "question"
                      ? interaction.data.questions?.map((question) => question.question).join(" · ")
                      : "Permission request"}{" "}
                    · {interaction.state}
                  </p>
                ))}
              {proposals.map((proposal) => (
                <div className="rounded-lg border border-line p-3 text-sm" key={proposal.id}>
                  <p>
                    {proposal.filename} ·{" "}
                    {proposal.state === "conflict"
                      ? "Conflict — your saved edit was kept"
                      : "Agent draft imported — human approval required"}
                  </p>
                  <button
                    className={`${control} mt-2`}
                    onClick={() => onCompareProposal(proposal.filename, proposal.id)}
                    type="button"
                  >
                    {proposal.state === "conflict"
                      ? "Compare conflict proposal"
                      : "Review agent draft"}
                  </button>
                </div>
              ))}
            </article>
          );
        })}
      </div>
      <form className="grid gap-2" onSubmit={(event) => void send(event)}>
        <label htmlFor={`chat-composer-${projectId}`} className="text-sm font-medium">
          Message tech-lead
        </label>
        <textarea
          id={`chat-composer-${projectId}`}
          className={`${control} min-h-28 resize-y`}
          maxLength={32768}
          value={draft}
          disabled={!selected}
          onChange={(event) => {
            const text = event.target.value;
            const requestId = crypto.randomUUID();
            setDraftsMemory((current) => ({
              ...current,
              drafts: { ...current.drafts, [selected]: { text, requestId } },
            }));
          }}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              (event.ctrlKey || event.metaKey) &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            className={`${control} border-accent bg-accent/10 text-accent`}
            disabled={!selected || busy || Boolean(activeTurn) || !draft.trim()}
            type="submit"
          >
            Send
          </button>
          {activeTurn ? (
            <button
              className={control}
              disabled={busy || activeTurn.state === "cancelling"}
              onClick={() =>
                void mutate<ChatTurn>(`${root}/${selected}/turns/${activeTurn.id}/abort`).then(
                  (value) => {
                    if (value)
                      setHistory((current) => ({
                        ...current,
                        turns: current.turns.map((turn) => (turn.id === value.id ? value : turn)),
                      }));
                  },
                )
              }
              type="button"
            >
              Stop
            </button>
          ) : null}
          <span className="text-xs text-copy-muted">
            Ctrl / ⌘ + Enter sends. Enter adds a line.
          </span>
        </div>
      </form>
    </section>
  );
}
