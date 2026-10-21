import type { Command, Mode, Session, SessionSummary } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    // FastAPI sends `detail` as a string (our errors) or a list (validation errors).
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    throw new ApiError(response.status, detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; offline: boolean }>("/api/health"),

  listSessions: () => request<SessionSummary[]>("/api/sessions"),

  createSession: (topic: string, mode: Mode, recencyDays: number) =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ topic, mode, recency_days: recencyDays }),
    }),

  sendCommand: (sessionId: string, command: Command) =>
    request<Session>(`/api/sessions/${sessionId}/commands`, {
      method: "POST",
      body: JSON.stringify(command),
    }),

  reportUrl: (sessionId: string) => `/api/sessions/${sessionId}/report.md`,
};
