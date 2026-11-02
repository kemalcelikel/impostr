import "@testing-library/jest-dom/vitest";
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactFlowInstance, ReactFlowProps } from "@xyflow/react";
import CardCanvas from "./CardCanvas";
import { createCanvasState, type CanvasNode } from "./canvasState";

const flowMock = vi.hoisted(() => ({
  props: null as ReactFlowProps<CanvasNode> | null,
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  fitView: vi.fn(),
}));

// Exercise the controlled event contract, not React Flow's pointer/SVG renderer.
vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  const { useEffect } = await import("react");
  return {
    ...actual,
    Background: () => null,
    ReactFlow: function MockReactFlow(props: ReactFlowProps<CanvasNode>) {
      flowMock.props = props;
      const { onInit } = props;
      useEffect(() => {
        const instance: Pick<ReactFlowInstance<CanvasNode>, "zoomIn" | "zoomOut" | "fitView"> = {
          zoomIn: flowMock.zoomIn,
          zoomOut: flowMock.zoomOut,
          fitView: flowMock.fitView,
        };
        // Only the view controls used by CardCanvas exist in this renderer mock.
        // Convert to the full instance solely at the test-only onInit boundary.
        onInit?.(instance as unknown as ReactFlowInstance<CanvasNode>);
      }, [onInit]);
      return <div data-testid="mock-flow" />;
    },
  };
});

function renderCanvas() {
  function ControlledCanvas() {
    const [state, setState] = useState(createCanvasState);
    return <CardCanvas state={state} onChange={setState} />;
  }
  return render(<ControlledCanvas />);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  flowMock.props = null;
});

describe("CardCanvas controlled interaction", () => {
  it("retains drag/selection/viewport callbacks separately for each board and ignores deletion", () => {
    renderCanvas();
    const initialNodes = flowMock.props!.nodes!;
    const initialEdges = flowMock.props!.edges!;
    act(() => {
      flowMock.props!.onNodesChange!([
        { type: "position", id: "ideas-root", position: { x: 125, y: -40 } },
        { type: "select", id: "ideas-root", selected: true },
        { type: "remove", id: "ideas-shape" },
      ]);
      flowMock.props!.onViewportChange!({ x: -100, y: 54, zoom: 0.8 });
    });
    expect(screen.getByRole("combobox", { name: "Select a sample card" })).toHaveValue(
      "ideas-root",
    );
    expect(screen.getByLabelText("Canvas zoom")).toHaveTextContent("80%");
    expect(flowMock.props!.nodes).toHaveLength(initialNodes.length);
    expect(flowMock.props!.edges).toEqual(initialEdges);

    fireEvent.click(screen.getByRole("tab", { name: "Journey tree" }));
    expect(screen.getByRole("combobox")).toHaveValue("");
    expect(screen.getByLabelText("Canvas zoom")).toHaveTextContent("60%");
    act(() => flowMock.props!.onViewportChange!({ x: 77, y: -35, zoom: 0.45 }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "journey-arrive" } });
    fireEvent.click(screen.getByRole("button", { name: "Move selected card right" }));
    expect(flowMock.props!.nodes!.find((node) => node.id === "journey-arrive")?.position).toEqual({
      x: 400,
      y: 100,
    });

    fireEvent.click(screen.getByRole("tab", { name: "Idea tree" }));
    expect(flowMock.props!.viewport).toEqual({ x: -100, y: 54, zoom: 0.8 });
    expect(flowMock.props!.defaultViewport).toEqual(flowMock.props!.viewport);
    expect(flowMock.props!.nodes!.find((node) => node.id === "ideas-root")?.position).toEqual({
      x: 125,
      y: -40,
    });
    expect(screen.getByRole("combobox")).toHaveValue("ideas-root");
    fireEvent.click(screen.getByRole("tab", { name: "Journey tree" }));
    expect(flowMock.props!.viewport).toEqual({ x: 77, y: -35, zoom: 0.45 });
    expect(screen.getByRole("combobox")).toHaveValue("journey-arrive");
    expect(initialNodes[0].position).toEqual({ x: 0, y: 150 });
  });

  it("supports keyboard tabs and scoped movement/pan keys without taking over input or shortcuts", () => {
    renderCanvas();
    const firstTab = screen.getByRole("tab", { name: "Idea tree" });
    firstTab.focus();
    fireEvent.keyDown(firstTab, { key: "End" });
    const lastTab = screen.getByRole("tab", { name: "Release tree" });
    expect(lastTab).toHaveFocus();
    expect(lastTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute(
      "id",
      lastTab.getAttribute("aria-controls"),
    );
    fireEvent.keyDown(lastTab, { key: "ArrowRight" });
    expect(firstTab).toHaveFocus();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ideas-root" } });
    const moveGroup = screen.getByRole("group", { name: "Move selected card with arrow keys" });
    fireEvent.keyDown(moveGroup, { key: "ArrowDown" });
    expect(flowMock.props!.nodes![0].position).toEqual({ x: 0, y: 170 });
    fireEvent.keyDown(moveGroup, { key: "ArrowDown", ctrlKey: true });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    expect(flowMock.props!.nodes![0].position).toEqual({ x: 0, y: 170 });
    const viewport = screen.getByRole("group", { name: "Canvas viewport" });
    viewport.focus();
    fireEvent.keyDown(viewport, { key: " " });
    expect(flowMock.props!.nodesDraggable).toBe(false);
    fireEvent.keyUp(viewport, { key: " " });
    expect(flowMock.props!.nodesDraggable).toBe(true);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: " " });
    expect(flowMock.props!.nodesDraggable).toBe(true);
    fireEvent.keyDown(viewport, { key: " ", ctrlKey: true });
    expect(flowMock.props!.nodesDraggable).toBe(true);
    expect(flowMock.props).toMatchObject({
      deleteKeyCode: null,
      nodesConnectable: false,
      edgesReconnectable: false,
      panActivationKeyCode: null,
      zoomActivationKeyCode: null,
      panOnScroll: true,
      zoomOnPinch: true,
      zoomOnDoubleClick: false,
      disableKeyboardA11y: true,
    });
    expect(
      flowMock.props!.nodes!.every(
        (node) => node.dragHandle === ".canvas-card-header" && node.deletable === false,
      ),
    ).toBe(true);
    expect(flowMock.fitView).not.toHaveBeenCalled();
  });

  it("uses visible zoom and explicit Fit view controls, never automatic fitting", () => {
    renderCanvas();
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Fit view" }));
    expect(flowMock.zoomIn).toHaveBeenCalledOnce();
    expect(flowMock.zoomOut).toHaveBeenCalledOnce();
    expect(flowMock.fitView).toHaveBeenCalledWith({ padding: 0.15, minZoom: 0.25, maxZoom: 1.5 });
    act(() => flowMock.props!.onViewportChange!({ x: 1, y: 2, zoom: 1.5 }));
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
    expect(screen.getByLabelText("Canvas zoom")).toHaveTextContent("150%");
  });
});
