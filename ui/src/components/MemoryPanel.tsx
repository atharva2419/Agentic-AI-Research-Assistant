import type { MemoryItem } from "../types";

interface Props {
  items: MemoryItem[];
  suggestions: string[];
  onForget: (itemId: string) => void;
  onSuggest: (topic: string) => void;
}

function daysUntil(iso: string): number {
  return Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 86_400_000));
}

/** Long-term memory: suggested next topics, and what the agent remembers (with Forget). */
export function MemoryPanel({ items, suggestions, onForget, onSuggest }: Props) {
  if (items.length === 0 && suggestions.length === 0) return null;
  return (
    <section className="card memory">
      {suggestions.length > 0 && (
        <>
          <h2>Suggested next topics</h2>
          <div className="options">
            {suggestions.map((topic) => (
              <button key={topic} className="chip" onClick={() => onSuggest(topic)}>
                {topic}
              </button>
            ))}
          </div>
        </>
      )}
      {items.length > 0 && (
        <details>
          <summary>What the agent remembers ({items.length})</summary>
          <ul>
            {items.map((item) => (
              <li key={item.id}>
                <div className="row">
                  <strong>{item.topic}</strong>
                  <button className="small" onClick={() => onForget(item.id)}>
                    Forget
                  </button>
                </div>
                <p className="hint">
                  {item.key_findings.length} findings · forgotten automatically in{" "}
                  {daysUntil(item.expires_at)} days
                </p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
