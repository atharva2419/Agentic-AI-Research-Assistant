import type { ResearchPlan } from "../types";

interface Props {
  plan: ResearchPlan;
  awaitingApproval: boolean;
  busy: boolean;
  onApprove: () => void;
}

const TYPE_LABEL = { search: "Search", summarize: "Summarize", cross_check: "Cross-check" };

export function PlanPanel({ plan, awaitingApproval, busy, onApprove }: Props) {
  return (
    <section className={awaitingApproval ? "card plan attention" : "card plan"}>
      <header className="row">
        <h2>Research plan v{plan.version}</h2>
        {awaitingApproval && (
          <button className="primary" disabled={busy} onClick={onApprove}>
            Approve and start
          </button>
        )}
      </header>
      <p>
        <strong>Objective:</strong> {plan.objective}
      </p>
      <ol className="research-questions">
        {plan.research_questions.map((q) => (
          <li key={q.id}>
            <span className="tag">{q.id}</span> {q.text}
          </li>
        ))}
      </ol>
      <table className="tasks">
        <thead>
          <tr>
            <th>Task</th>
            <th>Type</th>
            <th>What</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {plan.subtasks.map((t) => (
            <tr key={t.id} className={`task-${t.status}`}>
              <td>
                {t.id}
                {t.origin !== "planner" && <span className="tag origin">{t.origin}</span>}
              </td>
              <td>{TYPE_LABEL[t.type]}</td>
              <td>
                {t.query ? <code>{t.query}</code> : t.focus || t.title}
                {t.depends_on.length > 0 && (
                  <span className="hint"> · after {t.depends_on.join(", ")}</span>
                )}
                {t.note && <div className="hint">{t.note}</div>}
              </td>
              <td>
                <span className={`status status-task-${t.status}`}>{t.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">Why this plan: {plan.rationale}</p>
    </section>
  );
}
