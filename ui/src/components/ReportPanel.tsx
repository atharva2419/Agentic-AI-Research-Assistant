import type { CitedStatement, Report, Source } from "../types";

interface Props {
  report: Report;
  sources: Source[];
  reportUrl: string;
  onCite: (sourceId: string) => void;
  onSuggestTopic: (topic: string) => void;
}

function Statement({ statement, sources, onCite }: {
  statement: CitedStatement;
  sources: Map<string, Source>;
  onCite: (id: string) => void;
}) {
  return (
    <li className={statement.supported ? "" : "unsupported"}>
      {statement.text}{" "}
      {statement.source_ids.map((id) => {
        const source = sources.get(id);
        const tooltip = source
          ? `${source.title} — ${source.domain}, ${source.published_date ?? "date unknown"}`
          : id;
        return (
          <button key={id} className="cite" title={tooltip} onClick={() => onCite(id)}>
            {id}
          </button>
        );
      })}
      {!statement.supported && (
        <span className="flag" title="A citation could not be verified against collected sources">
          unsupported
        </span>
      )}
    </li>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </>
  );
}

export function ReportPanel({ report, sources, reportUrl, onCite, onSuggestTopic }: Props) {
  const byId = new Map(sources.map((s) => [s.id, s]));
  return (
    <article className="report">
      <header className="row">
        <h2>{report.title}</h2>
        <a className="button" href={reportUrl} download>
          Download .md
        </a>
      </header>
      <p className="summary">{report.executive_summary}</p>

      <h3>Key takeaways</h3>
      <ul className="statements">
        {report.key_takeaways.map((s) => (
          <Statement key={s.text} statement={s} sources={byId} onCite={onCite} />
        ))}
      </ul>

      {report.sections.map((section) => (
        <section key={section.heading}>
          <h3>{section.heading}</h3>
          <ul className="statements">
            {section.statements.map((s) => (
              <Statement key={s.text} statement={s} sources={byId} onCite={onCite} />
            ))}
          </ul>
        </section>
      ))}

      {report.contradictions.length > 0 && (
        <>
          <h3>Contradictions between sources</h3>
          {report.contradictions.map((c) => (
            <div key={c.id} className="contradiction">
              <strong>{c.topic}</strong>
              <p>
                <button className="cite" onClick={() => onCite(c.source_a)}>{c.source_a}</button>{" "}
                {c.claim_a}
              </p>
              <p>
                <button className="cite" onClick={() => onCite(c.source_b)}>{c.source_b}</button>{" "}
                {c.claim_b}
              </p>
              <p className="hint">
                {c.explanation} {c.likely_cause && <>Likely cause: {c.likely_cause}</>}
              </p>
            </div>
          ))}
        </>
      )}

      <List title="Open questions" items={report.open_questions} />
      <List title="Assumptions" items={report.assumptions} />
      <List title="Limitations" items={report.limitations} />

      {Object.keys(report.keyword_coverage).length > 0 && (
        <>
          <h3>Priority keyword coverage</h3>
          <ul className="keyword-coverage">
            {Object.entries(report.keyword_coverage).map(([keyword, ids]) => (
              <li key={keyword}>
                <span className="chip keyword">{keyword}</span>{" "}
                {ids.length === 0 ? (
                  <span className="warn">no source mentions it</span>
                ) : (
                  <>
                    {ids.length} source{ids.length > 1 ? "s" : ""}:{" "}
                    {ids.map((id) => (
                      <button key={id} className="cite" onClick={() => onCite(id)}>
                        {id}
                      </button>
                    ))}
                  </>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {report.suggested_next_topics.length > 0 && (
        <>
          <h3>Suggested next topics</h3>
          <div className="options">
            {report.suggested_next_topics.map((topic) => (
              <button key={topic} className="chip" onClick={() => onSuggestTopic(topic)}>
                {topic}
              </button>
            ))}
          </div>
        </>
      )}
    </article>
  );
}
