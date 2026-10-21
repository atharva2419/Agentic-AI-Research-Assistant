import { useEffect, useState } from "react";
import type { LogEntry, Session } from "./types";

/** Add a live log entry unless it's already there (a snapshot may have included it). */
export function applyLog(session: Session, entry: LogEntry): Session {
  if (session.log.some((e) => e.seq === entry.seq)) return session;
  return { ...session, log: [...session.log, entry] };
}

/**
 * Subscribe to a session's Server-Sent Events stream.
 *
 * The server sends a `snapshot` (the whole session) on connect and after each step, and a `log`
 * event for every new log entry. EventSource reconnects by itself; the server answers a reconnect
 * with a fresh snapshot, so there is nothing to replay on our side.
 */
export function useSessionStream(sessionId: string | null) {
  const [session, setSession] = useState<Session | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setSession(null);
    if (!sessionId) return;
    const source = new EventSource(`/api/sessions/${sessionId}/events`);
    source.addEventListener("snapshot", (event) => {
      setSession(JSON.parse((event as MessageEvent<string>).data) as Session);
    });
    source.addEventListener("log", (event) => {
      const entry = JSON.parse((event as MessageEvent<string>).data) as LogEntry;
      setSession((current) => (current ? applyLog(current, entry) : current));
    });
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [sessionId]);

  return { session, setSession, connected };
}
