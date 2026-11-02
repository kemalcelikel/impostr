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
      className={`canvas-card w-[300px] overflow-hidden rounded-xl border bg-surface shadow-lg shadow-black/20 ${selected ? "border-accent ring-2 ring-accent/30" : "border-input-border"}`}
    >
      <Handle isConnectable={false} position={Position.Left} type="target" />
      <header className="canvas-card-header cursor-grab select-none border-b border-line bg-surface-raised px-4 py-3 active:cursor-grabbing">
        <p className="font-mono text-[10px] uppercase tracking-wide text-copy-muted">
          Sample card · {data.content.id}
        </p>
        <h4 className="mt-1 text-sm font-semibold text-foreground">{data.content.title}</h4>
      </header>
      <div className="canvas-text nodrag cursor-text select-text px-4 py-4 text-sm leading-6 text-foreground">
        {data.content.body}
      </div>
      <footer className="canvas-text nodrag cursor-text select-text border-t border-line px-4 py-3 text-xs leading-5 text-copy-muted">
        {data.content.footer}
      </footer>
      <Handle isConnectable={false} position={Position.Right} type="source" />
    </article>
  );
}

const nodeTypes = { sampleCard: SampleCard };
const buttonClass =
  "min-h-11 rounded-lg border border-line bg-surface-raised px-3 py-2 text-sm text-foreground hover:border-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50";
const moves = [
  { label: "left", key: "ArrowLeft", dx: -CARD_MOVE_STEP, dy: 0, symbol: "←" },
  { label: "up", key: "ArrowUp", dx: 0, dy: -CARD_MOVE_STEP, symbol: "↑" },
  { label: "down", key: "ArrowDown", dx: 0, dy: CARD_MOVE_STEP, symbol: "↓" },
  { label: "right", key: "ArrowRight", dx: CARD_MOVE_STEP, dy: 0, symbol: "→" },
];

export default function CardCanvas({
  state,
  onChange,
}: {
  state: CanvasState;
  onChange: (update: CanvasUpdate) => void;
}) {
  const id = `canvas-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const boardId = state.activeBoardId;
  const board = state.boards[boardId];
  const selected = board.nodes.find((node) => node.selected);
  const edges = useMemo(() => canvasEdges(boardId), [boardId]);
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
    <section aria-label="Sample card canvas" className="mt-5 grid min-w-0 gap-4">
      <p className="max-w-3xl text-sm leading-6 text-copy-muted">
        Display-only sample trees, not project files or tasks. Move cards without changing their
        relationships. Boards retain positions, selection and view in memory; refreshing resets
        them.
      </p>
      <div
        aria-label="Sample canvas boards"
        className="flex min-w-0 flex-wrap gap-2"
        role="tablist"
      >
        {sampleBoards.map((sample, index) => (
          <button
            aria-controls={`${id}-panel-${sample.id}`}
            aria-selected={boardId === sample.id}
            className={`${buttonClass} ${boardId === sample.id ? "border-accent/60 bg-accent/10 text-accent" : ""}`}
            id={`${id}-tab-${sample.id}`}
            key={sample.id}
            onClick={() => switchBoard(sample.id)}
            onKeyDown={(event) => tabKeyDown(event, index)}
            role="tab"
            tabIndex={boardId === sample.id ? 0 : -1}
            type="button"
          >
            {sample.title}
          </button>
        ))}
      </div>
      <div
        aria-label="Canvas view controls"
        className="flex min-w-0 flex-wrap items-center gap-2"
        role="group"
      >
        <button
          aria-label="Zoom out"
          className={buttonClass}
          disabled={board.viewport.zoom <= MIN_CANVAS_ZOOM}
          onClick={() => void flow.current?.zoomOut()}
          type="button"
        >
          −
        </button>
        <output
          aria-label="Canvas zoom"
          className="min-w-14 text-center font-mono text-xs text-foreground"
        >
          {Math.round(board.viewport.zoom * 100)}%
        </output>
        <button
          aria-label="Zoom in"
          className={buttonClass}
          disabled={board.viewport.zoom >= MAX_CANVAS_ZOOM}
          onClick={() => void flow.current?.zoomIn()}
          type="button"
        >
          +
        </button>
        <button
          className={buttonClass}
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
        </button>
      </div>
      <div className="flex min-w-0 flex-wrap items-end gap-3">
        <label
          className="grid w-full min-w-0 gap-2 text-sm font-medium sm:w-auto sm:flex-1"
          htmlFor={`${id}-selection`}
        >
          Select a sample card
          <select
            className="min-h-11 w-full min-w-0 rounded-lg border border-input-border bg-canvas px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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
          </select>
        </label>
        <div
          aria-describedby={`${id}-move-help`}
          aria-label="Move selected card with arrow keys"
          className="flex flex-wrap gap-2 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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
            <button
              aria-label={`Move selected card ${direction.label}`}
              className={buttonClass}
              disabled={!selected}
              key={direction.key}
              onClick={() => move(direction.dx, direction.dy)}
              type="button"
            >
              {direction.symbol}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs leading-5 text-copy-muted" id={`${id}-move-help`}>
        Select a card, then use move buttons or focus the move group and press arrow keys (20 canvas
        units). Header drag moves cards; body text stays selectable. Pan by background drag, middle
        mouse or scrolling. Focus the canvas and hold Space to pan over cards; pinch to zoom.
      </p>
      <div aria-labelledby={`${id}-tab-${boardId}`} id={`${id}-panel-${boardId}`} role="tabpanel">
        <div
          aria-describedby={`${id}-move-help`}
          aria-label="Canvas viewport"
          className="card-canvas h-[clamp(24rem,65vh,52rem)] w-full min-w-0 overflow-hidden rounded-xl border border-line bg-canvas focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
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
            colorMode="dark"
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
            <Background color="#2b3b31" gap={24} size={1} />
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
    </section>
  );
}
