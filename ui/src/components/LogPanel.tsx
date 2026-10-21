import { useEffect, useRef } from "react";
import { formatTime } from "../format";
import type { LogEntry } from "../types";

interface Props {
  log: LogEntry[];
}

/** The transparent action log: every decision with its reason, newest at the bottom. */
export function LogPanel({ log }: Props) {
  const endRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    // Follow new entries, but only if the user hasn't scrolled up to read older ones.
    const list = listRef.current;
    if (!list) return;
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    if (nearBottom) endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [log.length]);

  return (
    <ol className="log" ref={listRef}>
      {log.map((entry) => (
        <li key={entry.seq} className={`log-entry actor-${entry.actor}`}>
          <span className="time">{formatTime(entry.timestamp)}</span>
          <span className="actor">{entry.actor}</span>
          <span className="step">{entry.step}</span>
          <div className="body">
            <span className="action">{entry.action}</span>
            {entry.decision && <span className="decision"> → {entry.decision}</span>}
            {entry.reason && entry.step !== "state" && <p className="reason">{entry.reason}</p>}
          </div>
        </li>
      ))}
      <div ref={endRef} />
    </ol>
  );
}
