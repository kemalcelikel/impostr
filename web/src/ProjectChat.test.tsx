import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectChat from "./ProjectChat";
import { streamChat, type ChatEvent, type ChatMemory, type Interaction } from "./chat";

vi.mock("./chat", async (original) => ({
  ...(await original<typeof import("./chat")>()),
  streamChat: vi.fn(),
}));
let deliver: (event: ChatEvent) => void;
let streamSignal: AbortSignal;
let turnState = "running";
const interaction: Interaction = {
  id: "question",
  turn_id: "turn",
  kind: "question",
  state: "pending",
  data: {
    questions: [
      {
        header: "Plan",
        question: "Proceed?",
        custom: false,
        options: [{ label: "Yes", description: "Synthetic" }],
      },
    ],
  },
};
let interactions: Interaction[];
let replay: ChatEvent[];
let replyState: string;
const fetchMock = vi.fn();
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
beforeEach(() => {
  turnState = "running";
  interactions = [interaction];
  replay = [];
  replyState = "replying";
  vi.mocked(streamChat).mockImplementation(async (_path, signal, accept) => {
    deliver = accept;
    streamSignal = signal;
    await new Promise<void>((resolve) =>
      signal.addEventListener("abort", () => resolve(), { once: true }),
    );
  });
  fetchMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/chat"))
      return json({
        conversations: [
          { id: "first", title: "First" },
          { id: "second", title: "Second" },
        ],
        last_conversation_id: "first",
      });
    if (path.includes("/last-used")) return json({ last_conversation_id: "second" });
    if (path.includes("/events?")) return json({ events: replay, after: replay.at(-1)?.id ?? 0 });
    if (path.endsWith("/reply")) return json({ state: replyState }, 202);
    if (path.endsWith("/turns")) return json({ detail: "Another project turn is active" }, 409);
    return json({
      turns: [
        {
          id: "turn",
          request_id: "request",
          prompt: "Original plan",
          state: turnState,
          created_at: "2026-10-01T10:00:00Z",
        },
      ],
      interactions: turnState === "running" ? interactions : [],
    });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});
function mount(memory: ChatMemory = { drafts: {}, answers: {} }, expired = vi.fn()) {
  const documentsChanged = vi.fn();
  const compareProposal = vi.fn();
  const memoryChanged = vi.fn<(snapshot: ChatMemory) => void>();
  return {
    ...render(
      <ProjectChat
        projectId="project"
        csrfToken=""
        memory={memory}
        onMemoryChange={memoryChanged}
        onSessionExpired={expired}
        onDocumentsChanged={documentsChanged}
        onCompareProposal={compareProposal}
        onPendingChange={vi.fn()}
      />,
    ),
    memory,
    memoryChanged,
    expired,
    documentsChanged,
    compareProposal,
  };
}
describe("project chat", () => {
  it("appends replay without stealing composer focus, keeps separate drafts and aborts old streams", async () => {
    mount();
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(composer, { target: { value: "First unsent" } });
    composer.focus();
    const callsBeforeDelta = fetchMock.mock.calls.length;
    const delta: ChatEvent = {
      id: 3,
      turn_id: "turn",
      sequence: 3,
      type: "delta",
      data: { text: "Incremental" },
    };
    act(() => {
      deliver(delta);
      deliver(delta); // DB replay of an already delivered event must not duplicate text.
      deliver({ id: 4, turn_id: "turn", sequence: 4, type: "delta", data: { text: " answer" } });
    });
    expect(composer).toHaveFocus();
    expect(composer).toHaveValue("First unsent");
    expect(screen.getByText("Incremental answer")).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(callsBeforeDelta);
    const old = streamSignal;
    fireEvent.click(screen.getByRole("tab", { name: "Second" }));
    await waitFor(() => expect(old.aborted).toBe(true));
    expect(composer).toHaveValue("");
    fireEvent.change(composer, { target: { value: "Second unsent" } });
    fireEvent.click(screen.getByRole("tab", { name: "First" }));
    await waitFor(() => expect(composer).toHaveValue("First unsent"));
  });
  it("submits scoped answers, shows queued acknowledgement and has no always permission", async () => {
    mount();
    fireEvent.click(await screen.findByRole("radio", { name: /Yes/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit answers" }));
    expect(await screen.findByText(/Reply queued/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/reply"));
    expect(call).toBeDefined();
    expect(JSON.parse(call![1].body).answer).toEqual({ answers: [["Yes"]] });
    expect(screen.queryByRole("button", { name: /always/i })).not.toBeInTheDocument();
  });
  it("retains failed-send text and idempotency key for explicit retry", async () => {
    turnState = "completed";
    const { memory, memoryChanged } = mount();
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(composer, { target: { value: "Keep this" } });
    const key = memoryChanged.mock.calls.at(-1)![0].drafts.first.requestId;
    fireEvent.keyDown(composer, { key: "Enter", ctrlKey: true });
    expect(await screen.findByText(/Another project turn is active/)).toBeInTheDocument();
    expect(composer).toHaveValue("Keep this");
    expect(memoryChanged.mock.calls.at(-1)![0].drafts.first.requestId).toBe(key);
    expect(memory).toEqual({ drafts: {}, answers: {} });
  });
  it("aborts on auth-generation unmount and ignores late private events", async () => {
    const view = mount();
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    view.unmount();
    expect(streamSignal.aborted).toBe(true);
    act(() =>
      deliver({
        id: 3,
        turn_id: "turn",
        sequence: 3,
        type: "delta",
        data: { text: "Late private text" },
      }),
    );
    expect(screen.queryByText("Late private text")).not.toBeInTheDocument();
  });
  it("restores an immutable emitted draft snapshot without changing the input seed", async () => {
    const seed: ChatMemory = Object.freeze({
      drafts: Object.freeze({}),
      answers: Object.freeze({}),
    });
    const view = mount(seed);
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(composer, { target: { value: "Restore after relogin" } });
    const snapshot = view.memoryChanged.mock.calls.at(-1)![0];
    expect(seed.drafts).toEqual({});
    view.unmount();
    mount(snapshot);
    await waitFor(() =>
      expect(screen.getByLabelText("Message tech-lead")).toHaveValue("Restore after relogin"),
    );
  });
  it("does not clear newer composer state when a successful send completes late", async () => {
    turnState = "completed";
    let finishSend!: (response: Response) => void;
    const pendingSend = new Promise<Response>((resolve) => {
      finishSend = resolve;
    });
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string) =>
      path.endsWith("/turns") ? pendingSend : original(path),
    );
    const view = mount();
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(composer, { target: { value: "Submitted prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.change(composer, { target: { value: "Newer unsent prompt" } });
    await act(async () => {
      finishSend(json({ id: "new-turn", prompt: "Submitted prompt", state: "queued" }, 202));
    });
    expect(composer).toHaveValue("Newer unsent prompt");
    expect(view.memoryChanged.mock.calls.at(-1)![0].drafts.first.text).toBe("Newer unsent prompt");
  });
  it("aborts replay and reports expiry when authenticated history is revoked", async () => {
    const view = mount();
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fetchMock.mockImplementation(async () => json({ detail: "Sign in" }, 401));
    act(() =>
      deliver({
        id: 4,
        turn_id: "turn",
        sequence: 4,
        type: "question",
        data: { ...interaction.data, interaction_id: interaction.id },
      }),
    );
    await waitFor(() => expect(view.expired).toHaveBeenCalledOnce());
    expect(streamSignal.aborted).toBe(true);
  });
  it("renders durable delta replay before streaming and retains partial output on failure", async () => {
    replay = [
      { id: 1, turn_id: "turn", sequence: 1, type: "queued", data: {} },
      {
        id: 2,
        turn_id: "turn",
        sequence: 2,
        type: "started",
        data: { context_reconstructed: false },
      },
      { id: 3, turn_id: "turn", sequence: 3, type: "delta", data: { text: "Saved partial" } },
    ];
    mount();
    expect(await screen.findByText("Saved partial")).toBeInTheDocument();
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    expect(vi.mocked(streamChat).mock.calls[0][0]).toBe(
      "/api/projects/project/chat/first/stream?after=3",
    );
    turnState = "failed";
    act(() => {
      deliver(replay[2]);
      deliver({ id: 4, turn_id: "turn", sequence: 4, type: "delta", data: { text: " output" } });
      deliver({
        id: 5,
        turn_id: "turn",
        sequence: 5,
        type: "failed",
        data: { reason: "native_session_error" },
      });
    });
    expect(await screen.findByText("Saved partial output")).toBeInTheDocument();
    expect(screen.getByText(/Turn failed: native_session_error/)).toBeInTheDocument();
  });
  it("uses the real permission history shape and preserves a replied retry acknowledgement", async () => {
    interactions = [
      {
        id: "permission",
        turn_id: "turn",
        kind: "permission",
        state: "pending",
        data: { permission: "edit", once_allowed: true },
      },
    ];
    replyState = "replied"; // Idempotent retry after the worker already acknowledged.
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Allow once" }));
    expect(await screen.findByText("Permission request · replied")).toBeInTheDocument();
    expect(screen.queryByText(/Reply queued/)).not.toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([path]) =>
      String(path).endsWith("/interactions/permission/reply"),
    );
    expect(call).toBeDefined();
    expect(JSON.parse(call![1].body).answer).toEqual({ reply: "once" });
    expect(screen.queryByRole("button", { name: /always/i })).not.toBeInTheDocument();
  });
  it("handles separate proposal items and the empty completed event from the durable API", async () => {
    const view = mount();
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    turnState = "completed";
    act(() => {
      deliver({
        id: 8,
        turn_id: "turn",
        sequence: 8,
        type: "proposals",
        data: { items: [{ id: "proposal", filename: "PROJECT.md", state: "conflict" }] },
      });
      deliver({ id: 9, turn_id: "turn", sequence: 9, type: "completed", data: {} });
    });
    fireEvent.click(await screen.findByRole("button", { name: "Compare conflict proposal" }));
    expect(view.compareProposal).toHaveBeenCalledWith("PROJECT.md", "proposal");
    expect(view.documentsChanged).toHaveBeenCalledOnce();
  });
});
