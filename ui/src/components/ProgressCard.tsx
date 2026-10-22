import { STATUS_LABEL, formatCost, isWorking } from "../format";
import type { Session } from "../types";

interface Props {
  session: Session;
}

/** Fills the report column until the report exists: where the agent is and what it has so far. */
export function ProgressCard({ session }: Props) {
  const tasks = session.plan?.subtasks ?? [];
  const finished = tasks.filter((t) => ["done", "skipped", "failed"].includes(t.status)).length;
  const kept = session.sources.filter((s) => s.status === "kept").length;
  const excluded = session.sources.length - kept;
  const latest = session.log.filter((e) => e.step !== "state").at(-1);
  const waiting =
    session.status === "awaiting_answers"
      ? "The agent is waiting for your answers (left)."
      : session.status === "awaiting_plan_approval"
        ? "The agent is waiting for you to approve the plan (left)."
        : null;

  return (
    <div className="progress-card">
      <h2>Report</h2>
      <p className="hint">The cited report will appear here when the agent finishes.</p>
      <p className={`status status-${session.status}`}>
        {session.paused ? "Paused" : STATUS_LABEL[session.status]}
        {isWorking(session.status, session.paused) && <span className="spinner" aria-hidden />}
      </p>
      {waiting && <p className="attention-text">{waiting}</p>}
      <dl className="stats">
        <div>
          <dt>Plan</dt>
          <dd>{tasks.length ? `${finished}/${tasks.length} tasks` : "not yet"}</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>
            {kept} kept · {excluded} excluded
          </dd>
        </div>
        <div>
          <dt>Summarized</dt>
          <dd>{session.summaries.length}</dd>
        </div>
        <div>
          <dt>Contradictions</dt>
          <dd>{session.contradictions.length}</dd>
        </div>
        <div>
          <dt>Cost so far</dt>
          <dd>{formatCost(session.budget.cost_usd)}</dd>
        </div>
      </dl>
      {latest && (
        <p className="hint">
          Latest: {latest.action}
          {latest.decision && ` → ${latest.decision}`}
        </p>
      )}
    </div>
  );
}
