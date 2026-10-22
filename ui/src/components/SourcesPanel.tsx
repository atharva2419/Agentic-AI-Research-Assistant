import { useEffect, useState } from "react";
import type { SendCommand, Source, SourceSummary } from "../types";

interface Props {
  sources: Source[];
  summaries: SourceSummary[];
  highlightId: string | null;
  canChange: boolean;
  busy: boolean;
  onCommand: SendCommand;
}

const STAGE_LABEL = { rule: "Rule", relevance: "Relevance check", user: "You" };

function ExcludeControl({ source, busy, onCommand }: {
  source: Source;
  busy: boolean;
  onCommand: SendCommand;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) {
    return (
      <button className="small" disabled={busy} onClick={() => setOpen(true)}>
        Exclude
      </button>
    );
  }
  return (
    <span className="inline-edit">
      <input
        aria-label={`Why exclude ${source.id}`}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Why? (optional)"
      />
      <button
        className="small"
        disabled={busy}
        onClick={() => {
          onCommand({ type: "exclude_source", source_id: source.id, reason: reason.trim() || null });
          setOpen(false);
        }}
      >
        Confirm
      </button>
      <button className="small" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </span>
  );
}

function SourceCard({ source, summary, highlighted, canChange, busy, onCommand }: {
  source: Source;
  summary?: SourceSummary;
  highlighted: boolean;
  canChange: boolean;
  busy: boolean;
  onCommand: SendCommand;
}) {
  return (
    <li id={`source-${source.id}`} className={highlighted ? "source highlighted" : "source"}>
      <div className="row">
        <span className="title-line">
          <span className="tag">{source.id}</span>{" "}
          <a href={source.url} target="_blank" rel="noreferrer">
            {source.title}
          </a>
        </span>
        {canChange &&
          (source.status === "kept" ? (
            <ExcludeControl source={source} busy={busy} onCommand={onCommand} />
          ) : (
            <button
              className="small"
              disabled={busy}
              onClick={() => onCommand({ type: "include_source", source_id: source.id })}
            >
              Re-include
            </button>
          ))}
      </div>
      <p className="hint">
        {source.domain} ·{" "}
        {source.published_date ?? <span className="warn">date unknown</span>}
        {source.relevance_score !== null && <> · relevance {source.relevance_score.toFixed(2)}</>}
        {" · found by "}
        {source.found_by.join(", ")}
      </p>
      {source.exclusion ? (
        <p className="exclusion">
          <strong>Excluded ({STAGE_LABEL[source.exclusion.stage]}):</strong>{" "}
          {source.exclusion.reason}
        </p>
      ) : (
        source.relevance_reason && <p className="reason">{source.relevance_reason}</p>
      )}
      {summary && (
        <details>
          <summary>Summary and takeaways</summary>
          <p>{summary.summary}</p>
          <ul>
            {summary.key_takeaways.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
          {summary.quotes.map((q) => (
            <blockquote key={q.text}>
              “{q.text}” <span className="hint">({q.context}, verified in source)</span>
            </blockquote>
          ))}
        </details>
      )}
    </li>
  );
}

/** Every source the agent found, including the ones it excluded and why. The user can exclude
 *  a kept source or bring back an excluded one at any time. */
export function SourcesPanel({ sources, summaries, highlightId, canChange, busy, onCommand }: Props) {
  const byId = new Map(summaries.map((s) => [s.source_id, s]));
  const kept = sources.filter((s) => s.status === "kept");
  const excluded = sources.filter((s) => s.status === "excluded");

  useEffect(() => {
    if (highlightId) {
      document.getElementById(`source-${highlightId}`)?.scrollIntoView?.({ block: "center" });
    }
  }, [highlightId]);

  if (sources.length === 0) return <p className="hint">No sources yet.</p>;
  const card = (s: Source) => (
    <SourceCard
      key={s.id}
      source={s}
      summary={byId.get(s.id)}
      highlighted={s.id === highlightId}
      canChange={canChange}
      busy={busy}
      onCommand={onCommand}
    />
  );
  return (
    <div className="sources">
      <h3>Kept ({kept.length})</h3>
      <ul>{kept.map(card)}</ul>
      <h3>Excluded ({excluded.length})</h3>
      <ul>{excluded.map(card)}</ul>
    </div>
  );
}
