import type { MemoryMatch } from "../types";

interface Props {
  matches: MemoryMatch[];
  title: string;
  onOpen?: (sessionId: string) => void;
}

/** Past sessions related to the current topic. Shown as context, never as evidence. */
export function RelatedResearch({ matches, title, onOpen }: Props) {
  if (matches.length === 0) return null;
  return (
    <div className="related">
      <strong>{title}</strong>
      <ul>
        {matches.map((m) => (
          <li key={m.session_id}>
            {onOpen ? (
              <button className="link" onClick={() => onOpen(m.session_id)}>
                {m.topic}
              </button>
            ) : (
              m.topic
            )}{" "}
            <span className="hint">
              ({new Date(m.created_at).toLocaleDateString()}, similarity {m.similarity.toFixed(2)})
            </span>
            {m.key_findings[0] && <div className="hint">“{m.key_findings[0]}”</div>}
          </li>
        ))}
      </ul>
    </div>
  );
}
