import { STATUS_LABEL, formatCost } from "../format";
import type { SessionSummary } from "../types";

interface Props {
  sessions: SessionSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function SessionList({ sessions, selectedId, onSelect }: Props) {
  if (sessions.length === 0) return null;
  return (
    <nav className="card session-list">
      <h2>Sessions</h2>
      <ul>
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              className={s.id === selectedId ? "selected" : ""}
              onClick={() => onSelect(s.id)}
            >
              <span className="topic">{s.topic}</span>
              <span className={`status status-${s.status}`}>{STATUS_LABEL[s.status]}</span>
              <span className="hint">
                {s.mode} · {formatCost(s.cost_usd)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
