import { describe, expect, it } from "vitest";
import {
  canvasEdges,
  changeCanvasNodes,
  changeCanvasViewport,
  createCanvasState,
  moveCanvasCard,
  selectCanvasCard,
  switchCanvasBoard,
  updateCanvasBoard,
  MAX_CANVAS_ZOOM,
} from "./canvasState";
import { sampleHierarchy, sampleLayouts } from "./canvasSeeds";

describe("sample canvas state", () => {
  it("moves only visual coordinates and rejects topology/content replacement events", () => {
    const state = createCanvasState();
    const board = state.boards.ideas;
    const hierarchy = structuredClone(sampleHierarchy);
    const edges = canvasEdges("ideas");
    const selected = selectCanvasCard(board, "ideas-shape");
    const moved = moveCanvasCard(selected, 20, -20);
    const attemptedEdit = changeCanvasNodes(moved, [
      { type: "remove", id: "ideas-root" },
      { type: "add", item: { ...board.nodes[0], id: "unexpected" } },
      { type: "replace", id: "ideas-shape", item: { ...board.nodes[0], id: "ideas-shape" } },
    ]);

    expect(attemptedEdit).toBe(moved);
    expect(moved.nodes.find((node) => node.id === "ideas-shape")?.position).toEqual({
      x: 400,
      y: 280,
    });
    expect(moved.nodes.map((node) => ({ id: node.id, data: node.data }))).toEqual(
      board.nodes.map((node) => ({ id: node.id, data: node.data })),
    );
    expect(moved.nodes.find((node) => node.id === "ideas-root")).toEqual(board.nodes[0]);
    expect(board.nodes.find((node) => node.id === "ideas-shape")?.position).toEqual({
      x: 380,
      y: 300,
    });
    expect(sampleHierarchy).toEqual(hierarchy);
    expect(canvasEdges("ideas")).toEqual(edges);
    expect(moved.viewport).toBe(board.viewport);
  });

  it("retains independent positions, selection and controlled viewport across tab switches", () => {
    const original = createCanvasState();
    let state = updateCanvasBoard(original, "ideas", (board) =>
      changeCanvasViewport(moveCanvasCard(selectCanvasCard(board, "ideas-root"), 40, 20), {
        x: -155,
        y: 82,
        zoom: 0.9,
      }),
    );
    const ideas = state.boards.ideas;
    state = switchCanvasBoard(state, "journey");
    state = updateCanvasBoard(state, "journey", (board) =>
      changeCanvasViewport(moveCanvasCard(selectCanvasCard(board, "journey-explore"), -20, 60), {
        x: 73,
        y: -50,
        zoom: 0.4,
      }),
    );
    const journey = state.boards.journey;
    state = switchCanvasBoard(state, "ideas");

    expect(state.boards.ideas).toBe(ideas);
    expect(state.boards.ideas.viewport).toEqual({ x: -155, y: 82, zoom: 0.9 });
    expect(state.boards.ideas.nodes.filter((node) => node.selected).map((node) => node.id)).toEqual(
      ["ideas-root"],
    );
    expect(state.boards.journey).toBe(journey);
    expect(state.boards.release).toBe(original.boards.release);
    expect(switchCanvasBoard(state, "missing")).toBe(state);
    const fresh = createCanvasState();
    expect(fresh.boards.ideas.viewport).toEqual(sampleLayouts.ideas.viewport);
    expect(fresh.boards.ideas.nodes[0].position).toEqual({ x: 0, y: 150 });
    expect(fresh.boards.ideas.nodes.some((node) => node.selected)).toBe(false);
  });

  it("keeps finite views and single selection when library events arrive", () => {
    const original = createCanvasState().boards.ideas;
    const selected = changeCanvasNodes(original, [
      { type: "select", id: "ideas-root", selected: true },
      { type: "select", id: "ideas-shape", selected: true },
      { type: "dimensions", id: "ideas-shape", dimensions: { width: 300, height: 250 } },
    ]);
    expect(selected.nodes.filter((node) => node.selected).map((node) => node.id)).toEqual([
      "ideas-shape",
    ]);
    expect(selected.nodes.find((node) => node.id === "ideas-shape")?.measured).toEqual({
      width: 300,
      height: 250,
    });
    expect(
      changeCanvasNodes(selected, [
        { type: "position", id: "ideas-root", position: { x: NaN, y: 1 } },
      ]),
    ).toBe(selected);
    expect(changeCanvasViewport(selected, { x: Infinity, y: 0, zoom: 1 })).toBe(selected);
    expect(changeCanvasViewport(selected, { x: 0, y: 0, zoom: 500 }).viewport.zoom).toBe(
      MAX_CANVAS_ZOOM,
    );
    expect(selectCanvasCard(selected, "missing")).toBe(selected);
    const cleared = selectCanvasCard(selected, "");
    expect(moveCanvasCard(cleared, 20, 0)).toBe(cleared);
  });
});
