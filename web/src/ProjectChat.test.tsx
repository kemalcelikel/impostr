import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProjectChat from "./ProjectChat";
import {
  streamChat,
  type ChatEvent,
  type ChatMemory,
  type ChatTurn,
  type Interaction,
} from "./chat";

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
let uploaded: {
  id: string;
  filename: string;
  status: string;
  original_size: number;
  original_sha256: string;
  native_available: boolean;
}[];
let turnFailure: { detail: string } | null;
let successfulTurn: unknown;
let savedReceipt: ChatTurn["submission"];
let savedReferences: ChatTurn["references"];
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
  uploaded = [];
  turnFailure = { detail: "Another project turn is active" };
  successfulTurn = null;
  savedReceipt = undefined;
  savedReferences = undefined;
  vi.mocked(streamChat).mockImplementation(async (_path, signal, accept) => {
    deliver = accept;
    streamSignal = signal;
    await new Promise<void>((resolve) =>
      signal.addEventListener("abort", () => resolve(), { once: true }),
    );
  });
  fetchMock.mockImplementation(async (path: string, options?: RequestInit) => {
    if (path.endsWith("/chat"))
      return json({
        conversations: [
          { id: "first", title: "First" },
          { id: "second", title: "Second" },
        ],
        last_conversation_id: "first",
      });
    if (path.includes("/last-used")) return json({ last_conversation_id: "second" });
    if (path.includes("/attachments/upload")) {
      const filename =
        new URL(path, "http://localhost").searchParams.get("filename") ?? "guide.pdf";
      const item = {
        id: filename === "guide.pdf" ? "pdf-1" : "pdf-2",
        filename,
        status: "stored",
        original_size: filename === "guide.pdf" ? 1_234 : 432,
        original_sha256: filename === "guide.pdf" ? "a".repeat(64) : "b".repeat(64),
        native_available: true,
      };
      uploaded.push(item);
      expect(options?.headers).toMatchObject({ "Content-Type": "application/pdf" });
      return json(item, 201);
    }
    if (path.includes("/attachments") && options?.method === "DELETE") {
      uploaded = [];
      return new Response(null, { status: 204 });
    }
    if (path.endsWith("/raw"))
      return new Response(new Blob(["%PDF-1.7"], { type: "application/pdf" }));
    if (path.includes("/attachments")) return json({ attachments: uploaded, next_after: null });
    if (path.includes("/events?")) return json({ events: replay, after: replay.at(-1)?.id ?? 0 });
    if (path.endsWith("/reply")) return json({ state: replyState }, 202);
    if (path.endsWith("/turns")) {
      if (successfulTurn) return json(successfulTurn, 202);
      return json(turnFailure ?? { detail: "Another project turn is active" }, 409);
    }
    return json({
      turns: [
        {
          id: "turn",
          request_id: "request",
          prompt: "Original plan",
          state: turnState,
          created_at: "2026-10-01T10:00:00Z",
          submission: savedReceipt,
          references: savedReferences,
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
  it("uploads, orders, sends and deletes native PDFs", async () => {
    turnState = "completed";
    successfulTurn = {
      id: "turn-pdf",
      request_id: "request-pdf",
      prompt: "Review this",
      state: "queued",
      selections: [
        {
          attachment_id: "pdf-2",
          expected_sha256: "b".repeat(64),
          reference_kind: "native-original-v1",
        },
      ],
      references: [
        {
          attachment_id: "pdf-2",
          filename: "appendix.pdf",
          original_size: 432,
          kind: "native-original-v1",
          availability: "available",
        },
      ],
      submission: {
        status: "sent",
        reconciliation_pending: false,
        reference_kind: "native-original-v1",
        meaning: "Submission only",
      },
    };
    mount();
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" })] },
    });
    expect(await screen.findByText("1,234 bytes · Stored")).toBeInTheDocument();
    const oldCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const oldRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    const createObjectURL = vi.fn(() => "blob:original-pdf");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectURL });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      fireEvent.click(screen.getByRole("button", { name: "Download guide.pdf" }));
      await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce());
      await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledOnce());
      expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/raw"))).toBe(true);
    } finally {
      anchorClick.mockRestore();
      if (oldCreate) Object.defineProperty(URL, "createObjectURL", oldCreate);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (oldRevoke) Object.defineProperty(URL, "revokeObjectURL", oldRevoke);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    }
    fireEvent.click(screen.getByRole("button", { name: "Attach guide.pdf" }));
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "appendix.pdf", { type: "application/pdf" })] },
    });
    expect(await screen.findByText("432 bytes · Stored")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Attach appendix.pdf" }));
    fireEvent.click(screen.getByRole("button", { name: "Move appendix.pdf earlier" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Remove guide.pdf from ordered send selection" }),
    );
    fireEvent.change(composer, { target: { value: "Review this" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Original PDF sent to Azure/)).toBeInTheDocument();
    const request = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/turns"));
    expect(request).toBeDefined();
    expect(JSON.parse(request![1].body).selections).toEqual([
      {
        attachment_id: "pdf-2",
        expected_sha256: "b".repeat(64),
        reference_kind: "native-original-v1",
      },
    ]);
    expect(screen.getByText("appendix.pdf · 432 bytes original PDF reference")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delete guide.pdf" }));
    expect(
      await screen.findByText("guide.pdf deleted. Prior sends cannot be retracted."),
    ).toBeInTheDocument();
  });
  it("retains exact prompt, selections and request identity after allowance rejection", async () => {
    turnState = "completed";
    turnFailure = {
      detail: "Chat context does not fit: remove selections or start a new conversation",
    };
    mount();
    const composer = await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Attach guide.pdf" }));
    fireEvent.change(composer, { target: { value: "Keep my question" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/Chat context does not fit/)).toBeInTheDocument();
    expect(composer).toHaveValue("Keep my question");
    const first = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/turns"));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/turns"))).toHaveLength(
        2,
      ),
    );
    const turns = fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/turns"));
    expect(JSON.parse(turns[0]![1].body)).toEqual(JSON.parse(turns[1]![1].body));
    expect(JSON.parse(turns[0]![1].body).request_id).toBeTruthy();
    expect(first).toBe(turns[0]);
  });
  it("retains a conversation's attachment selection while switching tabs", async () => {
    mount();
    await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Attach guide.pdf" }));
    fireEvent.click(screen.getByRole("tab", { name: "Second" }));
    await waitFor(() =>
      expect(screen.queryByText("Selected, in send order")).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("tab", { name: "First" }));
    expect(await screen.findByText("Selected, in send order")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("1,234 bytes · Selected")).toHaveLength(2));
    expect(
      screen.getByRole("button", { name: "Remove guide.pdf from ordered send selection" }),
    ).toBeInTheDocument();
  });
  it("locks ordered selection while deleting a selected PDF", async () => {
    turnState = "completed";
    mount();
    await screen.findByLabelText("Message tech-lead");
    await waitFor(() => expect(vi.mocked(streamChat)).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "guide.pdf", { type: "application/pdf" })] },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Attach guide.pdf" }));

    let finishDelete: (response: Response) => void = () => {};
    const pendingDelete = new Promise<Response>((resolve) => {
      finishDelete = resolve;
    });
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string, options?: RequestInit) =>
      path.includes("/attachments/") && options?.method === "DELETE"
        ? pendingDelete
        : original(path, options),
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete guide.pdf" }));
    const removeSelection = await screen.findByRole("button", {
      name: "Remove guide.pdf from ordered send selection",
    });
    await waitFor(() => expect(removeSelection).toBeDisabled());
    fireEvent.click(removeSelection);
    await act(async () => finishDelete(json({ status: "deleted" })));

    expect(
      await screen.findByText("guide.pdf deleted. Prior sends cannot be retracted."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Ordered selected PDFs")).not.toBeInTheDocument();
  });
  it("expires the session rather than exposing a denied attachment response", async () => {
    turnState = "completed";
    const expired = vi.fn();
    const view = mount({ drafts: {}, answers: {} }, expired);
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path: string, options?: RequestInit) =>
      path.includes("/attachments/upload")
        ? Promise.resolve(json({ detail: "Sign in" }, 401))
        : original(path, options),
    );
    await screen.findByLabelText("Upload a PDF");
    fireEvent.change(screen.getByLabelText("Upload a PDF"), {
      target: { files: [new File(["%PDF-1.7"], "private.pdf", { type: "application/pdf" })] },
    });
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());
    expect(screen.queryByText("private.pdf stored. It has not been sent.")).not.toBeInTheDocument();
    view.unmount();
  });
  it.each([
    {
      submission: { status: "failed-before-send", reconciliation_pending: false } as const,
      label: "Not sent (receipt confirms no model submission)",
    },
    {
      submission: { status: "uncertain", reconciliation_pending: true } as const,
      label: "Uncertain · checking receipt",
    },
  ])(
    "uses the recorded $submission.status receipt and marks unavailable history",
    async ({ submission, label }) => {
      turnState = "completed";
      savedReceipt = submission;
      savedReferences = [
        {
          attachment_id: "old-pdf",
          filename: "deleted.pdf",
          original_size: 123,
          kind: "native-original-v1",
          availability: "unavailable",
        },
      ];
      mount();
      expect(await screen.findByText(label)).toBeInTheDocument();
      expect(
        screen.getByText("deleted.pdf · 123 bytes historical reference; original unavailable"),
      ).toBeInTheDocument();
    },
  );
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
