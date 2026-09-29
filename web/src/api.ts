export type RequestOptions = {
  method?: "GET" | "POST" | "PUT";
  csrfToken?: string;
  body?: unknown;
  signal?: AbortSignal;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload?: unknown,
  ) {
    super(message);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .filter(isRecord)
      .map((issue) => (typeof issue.msg === "string" ? issue.msg : null))
      .filter((message): message is string => message !== null);
    if (messages.length) return messages.join(" ");
  }
  return null;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers({ Accept: "application/json" });
  if (options.csrfToken) {
    headers.set("X-CSRF-Token", options.csrfToken);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch {
    throw new ApiError("Impostr could not be reached. Check the connection and try again.", 0);
  }

  if (!response.ok) {
    let detail = "The request could not be completed.";
    let errorPayload: unknown;
    try {
      const payload: unknown = await response.json();
      errorPayload = payload;
      if (isRecord(payload)) {
        detail = detailMessage(payload.detail) ?? detail;
      }
    } catch {
      // Keep the response generic when the server does not return JSON.
    }
    throw new ApiError(detail, response.status, errorPayload);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
