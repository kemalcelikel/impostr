import { describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { mergeEvents, streamChat, type ChatEvent } from "./chat";

// chat.py event_page/stream wrap the broker's delta without renaming its type.
const event: ChatEvent = {
  id: 7,
  turn_id: "turn",
  sequence: 3,
  type: "delta",
  data: { text: "café" },
};
describe("durable chat replay", () => {
  it("deduplicates ordered replay without appending duplicate text", () => {
    const merged = mergeEvents(
      [event],
      [event, { ...event, id: 8, sequence: 4, data: { text: " continued" } }],
    );
    expect(merged.map((item) => item.id)).toEqual([7, 8]);
    expect(
      merged
        .filter((item) => item.type === "delta")
        .map((item) => item.data.text)
        .join(""),
    ).toBe("café continued");
  });
  it("delivers complete frames incrementally across UTF-8/chunk boundaries", async () => {
    const bytes = new TextEncoder().encode(
      `id: 7\nevent: chat\ndata: ${JSON.stringify(event)}\n\n`,
    );
    let writer!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        writer = controller;
      },
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(body, { headers: { "Content-Type": "text/event-stream" } }),
        ),
    );
    const accept = vi.fn();
    const controller = new AbortController();
    const streaming = streamChat("/stream", controller.signal, accept);
    writer.enqueue(bytes.slice(0, 35));
    await Promise.resolve();
    expect(accept).not.toHaveBeenCalled();
    writer.enqueue(bytes.slice(35));
    await vi.waitFor(() => expect(accept).toHaveBeenCalledWith(event));
    writer.close();
    await streaming;
    vi.unstubAllGlobals();
  });
  it("distinguishes expired authentication and server unavailability", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    await expect(
      streamChat("/stream", new AbortController().signal, vi.fn()),
    ).rejects.toMatchObject({ status: 401 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("event: unavailable\ndata: {}\n\n", {
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    await expect(
      streamChat("/stream", new AbortController().signal, vi.fn()),
    ).rejects.toBeInstanceOf(ApiError);
    vi.unstubAllGlobals();
  });
});
