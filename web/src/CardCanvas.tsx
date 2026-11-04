import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  type NodeProps,
  type ReactFlowInstance,
} from "@xyflow/react";
import { sampleBoards } from "./canvasSeeds";
import { useTheme } from "./theme";
import { Badge, Button, Disclosure, IconButton, Select, TabButton } from "./ui/controls";
import { Icon, type IconName } from "./ui/Icon";
import {
  CARD_MOVE_STEP,
  MAX_CANVAS_ZOOM,
  MIN_CANVAS_ZOOM,
  canvasEdges,
  changeCanvasNodes,
  changeCanvasViewport,
  moveCanvasCard,
  selectCanvasCard,
  switchCanvasBoard,
  updateCanvasBoard,
  type CanvasNode,
  type CanvasState,
  type CanvasUpdate,
} from "./canvasState";

function SampleCard({ data, selected }: NodeProps<CanvasNode>) {
  return (
    <article
      aria-label={`${data.content.title}${selected ? ", selected" : ""}`}
      className="canvas-card w-[300px] overflow-hidden"
      data-selected={selected ? "true" : undefined}
    >
      <Handle isConnectable={false} position={Position.Left} type="target" />
      <header className="canvas-card-header cursor-grab select-none active:cursor-grabbing">
        <div className="flex items-center justify-between gap-2 text-xs text-copy-muted">
          <p>Sample card · {data.content.id}</p>
          <Icon name="grip" />
        </div>
        <h4 className="mt-2 text-base font-semibold leading-6 text-foreground">
          {data.content.title}
        </h4>
      </header>
      <div className="canvas-text canvas-card-body nodrag cursor-text select-text">
        {data.content.body}
      </div>
      <footer className="canvas-text canvas-card-foot nodrag cursor-text select-text">
        {data.content.footer}
      </footer>
      <Handle isConnectable={false} position={Position.Right} type="source" />
    </article>
  );
}

const nodeTypes = { sampleCard: SampleCard };
const moves: { label: string; key: string; dx: number; dy: number; icon: IconName }[] = [
  { label: "left", key: "ArrowLeft", dx: -CARD_MOVE_STEP, dy: 0, icon: "arrowLeft" },
  { label: "up", key: "ArrowUp", dx: 0, dy: -CARD_MOVE_STEP, icon: "arrowUp" },
  { label: "down", key: "ArrowDown", dx: 0, dy: CARD_MOVE_STEP, icon: "arrowDown" },
  { label: "right", key: "ArrowRight", dx: CARD_MOVE_STEP, dy: 0, icon: "arrowRight" },
];

export default function CardCanvas({
  state,
  onChange,
}: {
  state: CanvasState;
  onChange: (update: CanvasUpdate) => void;
}) {
  const id = `canvas-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const { theme } = useTheme();
  const boardId = state.activeBoardId;
  const board = state.boards[boardId];
  const selected = board.nodes.find((node) => node.selected);
  // Override legacy seed paint here, not topology/state. SVG markers and paths
  // inherit the same neutral token, so a theme change needs no board remount.
  const edges = useMemo(
    () =>
      canvasEdges(boardId).map((edge) => ({
        ...edge,
        style: { ...edge.style, stroke: "var(--theme-copy-muted)" },
        markerEnd:
          typeof edge.markerEnd === "object"
            ? { ...edge.markerEnd, color: "var(--theme-copy-muted)" }
            : edge.markerEnd,
      })),
    [boardId],
  );
  const flow = useRef<ReactFlowInstance<CanvasNode> | null>(null);
  const [spacePan, setSpacePan] = useState(false);

  useEffect(() => {
    const releasePan = () => setSpacePan(false);
    window.addEventListener("blur", releasePan);
    return () => window.removeEventListener("blur", releasePan);
  }, []);

  function switchBoard(nextId: string): void {
    setSpacePan(false);
    onChange((current) => switchCanvasBoard(current, nextId));
  }

  function tabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number): void {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    let next: number;
    if (event.key === "ArrowRight") next = (index + 1) % sampleBoards.length;
    else if (event.key === "ArrowLeft")
      next = (index - 1 + sampleBoards.length) % sampleBoards.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = sampleBoards.length - 1;
    else return;
    event.preventDefault();
    switchBoard(sampleBoards[next].id);
    document.getElementById(`${id}-tab-${sampleBoards[next].id}`)?.focus();
  }

  function move(dx: number, dy: number): void {
    onChange((current) =>
      updateCanvasBoard(current, boardId, (value) => moveCanvasCard(value, dx, dy)),
    );
  }

  return (
    <section aria-label="Sample card canvas" className="canvas-surface">
      <header className="workbench-section-heading">
        <h2>Sample boards</h2>
        <Badge icon="canvas">Demo boards</Badge>
      </header>
      <p className="canvas-demo-note">Sample data, not project files or tasks.</p>
      <div className="workbench-panel canvas-panel">
        <div className="canvas-toolbar">
          <div
            aria-label="Sample canvas boards"
            className="workbench-tab-strip canvas-board-tabs"
            role="tablist"
          >
            {sampleBoards.map((sample, index) => (
              <TabButton
                aria-controls={`${id}-panel-${sample.id}`}
                selected={boardId === sample.id}
                className="workbench-tab"
                id={`${id}-tab-${sample.id}`}
                key={sample.id}
                onClick={() => switchBoard(sample.id)}
                onKeyDown={(event) => tabKeyDown(event, index)}
                type="button"
              >
                {sample.title}
              </TabButton>
            ))}
          </div>
          <div aria-label="Canvas view controls" className="canvas-view-controls" role="group">
            <IconButton
              label="Zoom out"
              className="workbench-quiet"
              variant="ghost"
              icon="zoomOut"
              disabled={board.viewport.zoom <= MIN_CANVAS_ZOOM}
              onClick={() => void flow.current?.zoomOut()}
              type="button"
            />
            <output
              aria-label="Canvas zoom"
              className="min-w-14 text-center text-sm tabular-nums text-foreground"
            >
              {Math.round(board.viewport.zoom * 100)}%
            </output>
            <IconButton
              label="Zoom in"
              className="workbench-quiet"
              variant="ghost"
              icon="zoomIn"
              disabled={board.viewport.zoom >= MAX_CANVAS_ZOOM}
              onClick={() => void flow.current?.zoomIn()}
              type="button"
            />
            <Button
              className="workbench-quiet"
              variant="ghost"
              icon="fitView"
              onClick={() =>
                void flow.current?.fitView({
                  padding: 0.15,
                  minZoom: MIN_CANVAS_ZOOM,
                  maxZoom: MAX_CANVAS_ZOOM,
                })
              }
              type="button"
            >
              Fit view
            </Button>
          </div>
        </div>
        <div className="canvas-selection-toolbar">
          <label className="canvas-card-picker" htmlFor={`${id}-selection`}>
            Select a sample card
            <Select
              className="canvas-card-select"
              id={`${id}-selection`}
              onChange={(event) => {
                const cardId = event.target.value;
                onChange((current) =>
                  updateCanvasBoard(current, boardId, (value) => selectCanvasCard(value, cardId)),
                );
              }}
              value={selected?.id ?? ""}
            >
              <option value="">No card selected</option>
              {board.nodes.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.data.content.title}
                </option>
              ))}
            </Select>
          </label>
          <div
            aria-describedby={`${id}-move-help`}
            aria-label="Move selected card with arrow keys"
            className="flex flex-wrap gap-1 rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onKeyDown={(event) => {
              if (
                event.target !== event.currentTarget ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey
              )
                return;
              const direction = moves.find((item) => item.key === event.key);
              if (!direction || !selected) return;
              event.preventDefault();
              move(direction.dx, direction.dy);
            }}
            role="group"
            tabIndex={0}
          >
            {moves.map((direction) => (
              <IconButton
                label={`Move selected card ${direction.label}`}
                className="workbench-quiet"
                variant="ghost"
                icon={direction.icon}
                disabled={!selected}
                key={direction.key}
                onClick={() => move(direction.dx, direction.dy)}
                type="button"
              />
            ))}
          </div>
        </div>
        <div
          className="canvas-board-panel"
          aria-labelledby={`${id}-tab-${boardId}`}
          id={`${id}-panel-${boardId}`}
          role="tabpanel"
        >
          <div
            aria-describedby={`${id}-move-help`}
            aria-label="Canvas viewport"
            className="card-canvas focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onBlur={() => setSpacePan(false)}
            onKeyDown={(event) => {
              // Scoped keys only: never swallow Space in selects/buttons/editors,
              // or subscribe to window-level shortcuts while other UI is active.
              if (
                event.target !== event.currentTarget ||
                event.key !== " " ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey
              )
                return;
              event.preventDefault();
              setSpacePan(true);
            }}
            onKeyUp={(event) => {
              if (event.key === " " && event.target === event.currentTarget) {
                event.preventDefault();
                setSpacePan(false);
              }
            }}
            onPointerDown={(event) => {
              if (
                event.target instanceof Element &&
                !event.target.closest(".canvas-text, button, input, select, textarea, a")
              ) {
                event.currentTarget.focus({ preventScroll: true });
              }
            }}
            role="group"
            tabIndex={0}
          >
            <ReactFlow<CanvasNode>
              key={boardId}
              colorMode={theme}
              defaultViewport={board.viewport}
              deleteKeyCode={null}
              disableKeyboardA11y
              edges={edges}
              edgesFocusable={false}
              edgesReconnectable={false}
              maxZoom={MAX_CANVAS_ZOOM}
              minZoom={MIN_CANVAS_ZOOM}
              multiSelectionKeyCode={null}
              nodes={board.nodes}
              nodesConnectable={false}
              nodesDraggable={!spacePan}
              nodesFocusable={false}
              nodeTypes={nodeTypes}
              noPanClassName={spacePan ? "canvas-no-pan" : "canvas-text"}
              onInit={(instance) => {
                flow.current = instance;
              }}
              onNodesChange={(changes) =>
                onChange((current) =>
                  updateCanvasBoard(current, boardId, (value) => changeCanvasNodes(value, changes)),
                )
              }
              onViewportChange={(viewport) =>
                onChange((current) =>
                  updateCanvasBoard(current, boardId, (value) =>
                    changeCanvasViewport(value, viewport),
                  ),
                )
              }
              panActivationKeyCode={null}
              panOnDrag={[0, 1]}
              panOnScroll
              selectionKeyCode={null}
              selectionOnDrag={false}
              viewport={board.viewport}
              zoomActivationKeyCode={null}
              zoomOnDoubleClick={false}
              zoomOnPinch
              zoomOnScroll={false}
            >
              <Background gap={24} size={1} />
            </ReactFlow>
          </div>
        </div>
        {sampleBoards
          .filter((sample) => sample.id !== boardId)
          .map((sample) => (
            <div
              aria-labelledby={`${id}-tab-${sample.id}`}
              hidden
              id={`${id}-panel-${sample.id}`}
              key={sample.id}
              role="tabpanel"
            />
          ))}
        <footer className="canvas-foot">
          <Disclosure
            className="canvas-controls-details"
            icon="info"
            title="Canvas controls and shortcuts"
          >
            <p className="mt-2 text-xs leading-6 text-copy-muted" id={`${id}-move-help`}>
              Select a card, then use move buttons or focus the move group and press arrow keys (20
              canvas units). Header drag moves cards; body text stays selectable. Pan by background
              drag, middle mouse or scrolling. Focus the canvas and hold Space to pan over cards;
              pinch to zoom. Moving a card changes its position, not its relationships.
            </p>
            <p className="text-xs text-copy-muted">
              Layout changes stay in this page and reset on refresh.
            </p>
          </Disclosure>
        </footer>
      </div>
    </section>
  );
}
