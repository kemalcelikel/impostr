import { useCallback, useEffect, useRef, useState } from "react";

type ServiceStatus = "checking" | "ready" | "unavailable";

const statusCopy: Record<ServiceStatus, { label: string; indicator: string; badge: string }> = {
  checking: {
    label: "Checking API and database",
    indicator: "bg-copy-muted",
    badge: "border-line bg-surface-raised text-copy-muted",
  },
  ready: {
    label: "API and database ready",
    indicator: "bg-accent",
    badge: "border-accent/35 bg-accent/10 text-accent",
  },
  unavailable: {
    label: "API or database unavailable",
    indicator: "bg-red-400",
    badge: "border-red-400/35 bg-red-400/10 text-red-300",
  },
};

async function fetchServiceStatus(signal: AbortSignal): Promise<ServiceStatus> {
  try {
    const response = await fetch("/api/health", {
      cache: "no-store",
      signal,
    });

    if (!response.ok) {
      return "unavailable";
    }

    const payload: unknown = await response.json();
    return typeof payload === "object" &&
      payload !== null &&
      "status" in payload &&
      payload.status === "ok"
      ? "ready"
      : "unavailable";
  } catch {
    return "unavailable";
  }
}

function useServiceStatus(): { serviceStatus: ServiceStatus; recheck: () => void } {
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus>("checking");
  const [checkNumber, setCheckNumber] = useState(0);
  const activeRequest = useRef<AbortController | null>(null);

  const recheck = useCallback((): void => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    setServiceStatus("checking");
    setCheckNumber((previous) => previous + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    activeRequest.current = controller;
    void fetchServiceStatus(controller.signal).then((nextStatus) => {
      if (activeRequest.current === controller && !controller.signal.aborted) {
        setServiceStatus(nextStatus);
      }
    });

    return () => {
      controller.abort();
      if (activeRequest.current === controller) {
        activeRequest.current = null;
      }
    };
  }, [checkNumber]);

  return { serviceStatus, recheck };
}

export default function App() {
  const { serviceStatus, recheck } = useServiceStatus();
  const copy = statusCopy[serviceStatus];

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-canvas text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-48 right-[-12rem] size-[32rem] rounded-full bg-accent/5 blur-3xl"
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center justify-between px-5 py-6 sm:px-8">
        <a
          aria-label="Impostr home"
          className="inline-flex items-center gap-3 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
          href="/"
        >
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-xl border border-accent/20 bg-surface-raised text-accent"
          >
            <svg fill="none" height="20" viewBox="0 0 20 20" width="20">
              <path
                d="M4 14.5V5.5h3.25l2.75 4 2.75-4H16v9h-3V9.8l-3 4.1-3-4.1v4.7H4Z"
                fill="currentColor"
              />
            </svg>
          </span>
          <span className="font-semibold tracking-tight text-foreground">Impostr</span>
        </a>

        <span className="hidden font-mono text-[11px] uppercase tracking-[0.18em] text-copy-muted sm:inline">
          Workspace foundation
        </span>
      </header>

      <main className="relative z-10 mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center px-5 pb-14 pt-10 sm:px-8 sm:pb-20 sm:pt-14">
        <div className="grid items-center gap-12 lg:grid-cols-[1.08fr_0.92fr] lg:gap-20">
          <section aria-labelledby="page-title" className="max-w-2xl">
            <p className="flex items-center gap-3 font-mono text-xs font-medium uppercase tracking-[0.16em] text-accent">
              <span aria-hidden="true" className="h-px w-8 bg-accent/70" />
              Private planning workspace
            </p>

            <h1
              className="mt-7 text-balance text-4xl font-semibold leading-[1.08] tracking-[-0.045em] text-foreground sm:text-5xl lg:text-6xl"
              id="page-title"
            >
              Plan clearly.
              <br />
              <span className="text-copy-muted">Build with confidence.</span>
            </h1>

            <p className="mt-6 max-w-xl text-base leading-7 text-copy-muted sm:text-lg sm:leading-8">
              A calm place for project decisions, durable revisions, and thoughtful handoffs. This
              foundation connects the browser to a private API and PostgreSQL through one origin.
            </p>
          </section>

          <section
            aria-labelledby="runtime-title"
            className="rounded-2xl border border-line bg-surface/95 p-5 shadow-2xl shadow-black/20 sm:p-7"
          >
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-5">
              <div>
                <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-copy-muted">
                  Platform status
                </p>
                <h2
                  className="mt-2 text-lg font-medium tracking-tight text-foreground"
                  id="runtime-title"
                >
                  Foundation checks
                </h2>
              </div>
              <span
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[11px] uppercase tracking-wide ${copy.badge}`}
              >
                <span aria-hidden="true" className={`size-1.5 rounded-full ${copy.indicator}`} />
                {serviceStatus === "ready"
                  ? "Ready"
                  : serviceStatus === "checking"
                    ? "Checking"
                    : "Unavailable"}
              </span>
            </div>

            <dl className="divide-y divide-line">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-4">
                <div>
                  <dt className="text-sm font-medium text-foreground">API health</dt>
                  <dd className="mt-1 font-mono text-xs text-copy-muted">/api/health</dd>
                </div>
                <dd className="font-mono text-xs text-copy-muted">Same origin</dd>
              </div>
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-4">
                <div>
                  <dt className="text-sm font-medium text-foreground">Persistence</dt>
                  <dd className="mt-1 font-mono text-xs text-copy-muted">PostgreSQL 17</dd>
                </div>
                <dd className="font-mono text-xs text-copy-muted">Private network</dd>
              </div>
            </dl>

            <p
              aria-live="polite"
              className="mt-2 flex min-h-11 items-center gap-3 rounded-lg bg-surface-raised px-4 py-3 text-sm text-foreground"
              role="status"
            >
              <span
                aria-hidden="true"
                className={`size-2 shrink-0 rounded-full ${copy.indicator}`}
              />
              {copy.label}
            </p>

            <button
              className="mt-4 min-h-10 rounded-lg border border-line bg-surface-raised px-4 py-2 text-sm font-medium text-foreground hover:border-accent/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={serviceStatus === "checking"}
              onClick={recheck}
              type="button"
            >
              {serviceStatus === "checking" ? "Checking…" : "Check again"}
            </button>

            <p className="mt-4 text-xs leading-5 text-copy-muted">
              Readiness confirms a live database query. No project or agent actions are exposed
              here.
            </p>
          </section>
        </div>

        <footer className="mt-16 flex flex-col gap-2 border-t border-line pt-5 font-mono text-[10px] uppercase tracking-[0.14em] text-copy-muted sm:mt-20 sm:flex-row sm:items-center sm:justify-between">
          <span>Application foundation</span>
          <span>Browser · API · PostgreSQL</span>
        </footer>
      </main>
    </div>
  );
}
