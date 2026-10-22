import type { Command, MemoryItem, MemoryMatch, Mode, Session, SessionSummary } from "./types";

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
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const user = (userId: string) => `/api/users/${encodeURIComponent(userId)}`;

export const api = {
  health: () => request<{ status: string; offline: boolean }>("/api/health"),

  listSessions: (userId: string) =>
    request<SessionSummary[]>(`/api/sessions?user_id=${encodeURIComponent(userId)}`),

  createSession: (userId: string, topic: string, mode: Mode, recencyDays: number) =>
    request<Session>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, topic, mode, recency_days: recencyDays }),
    }),

  deleteSession: (sessionId: string) =>
    request<void>(`/api/sessions/${sessionId}`, { method: "DELETE" }),

  sendCommand: (sessionId: string, command: Command) =>
    request<Session>(`/api/sessions/${sessionId}/commands`, {
      method: "POST",
      body: JSON.stringify(command),
    }),

  reportUrl: (sessionId: string) => `/api/sessions/${sessionId}/report.md`,

  // Long-term memory
  memory: (userId: string) => request<MemoryItem[]>(`${user(userId)}/memory`),
  forget: (userId: string, itemId: string) =>
    request<void>(`${user(userId)}/memory/${itemId}`, { method: "DELETE" }),
  related: (userId: string, topic: string) =>
    request<MemoryMatch[]>(`${user(userId)}/related?topic=${encodeURIComponent(topic)}`),
  suggestions: (userId: string) => request<string[]>(`${user(userId)}/suggestions`),
};
