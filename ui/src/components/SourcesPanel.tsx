import { useEffect } from "react";
import type { Source, SourceSummary } from "../types";

interface Props {
  sources: Source[];
  summaries: SourceSummary[];
  highlightId: string | null;
}

const STAGE_LABEL = { rule: "Rule", relevance: "Relevance check", user: "You" };

function SourceCard({ source, summary, highlighted }: {
  source: Source;
  summary?: SourceSummary;
  highlighted: boolean;
}) {
  return (
    <li id={`source-${source.id}`} className={highlighted ? "source highlighted" : "source"}>
      <div className="row">
        <span className="tag">{source.id}</span>
        <a href={source.url} target="_blank" rel="noreferrer">
          {source.title}
        </a>
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

/** Every source the agent found, including the ones it excluded and why. */
export function SourcesPanel({ sources, summaries, highlightId }: Props) {
  const byId = new Map(summaries.map((s) => [s.source_id, s]));
  const kept = sources.filter((s) => s.status === "kept");
  const excluded = sources.filter((s) => s.status === "excluded");

  useEffect(() => {
    if (highlightId) {
      document.getElementById(`source-${highlightId}`)?.scrollIntoView?.({ block: "center" });
    }
  }, [highlightId]);

  if (sources.length === 0) return <p className="hint">No sources yet.</p>;
  return (
    <div className="sources">
      <h3>Kept ({kept.length})</h3>
      <ul>
        {kept.map((s) => (
          <SourceCard key={s.id} source={s} summary={byId.get(s.id)} highlighted={s.id === highlightId} />
        ))}
      </ul>
      <h3>Excluded ({excluded.length})</h3>
      <ul>
        {excluded.map((s) => (
          <SourceCard key={s.id} source={s} highlighted={s.id === highlightId} />
        ))}
      </ul>
    </div>
  );
}
