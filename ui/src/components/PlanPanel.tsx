import { useState } from "react";
import type { ResearchPlan, SendCommand, SubTask } from "../types";

interface Props {
  plan: ResearchPlan;
  awaitingApproval: boolean;
  canEdit: boolean; // the plan may change in this status (approval, research, coverage, done)
  busy: boolean;
  onCommand: SendCommand;
}

const TYPE_LABEL = { search: "Search", summarize: "Summarize", cross_check: "Cross-check" };

function TaskRow({ task, canEdit, busy, onCommand }: {
  task: SubTask;
  canEdit: boolean;
  busy: boolean;
  onCommand: SendCommand;
}) {
  const [editing, setEditing] = useState(false);
  const [query, setQuery] = useState(task.query ?? "");
  const editable = canEdit && task.status === "pending";

  function saveQuery() {
    onCommand({ type: "edit_plan", edits: [{ id: task.id, query }] });
    setEditing(false);
  }

  return (
    <tr className={`task-${task.status}`}>
      <td>
        {task.id}
        {task.origin !== "planner" && <span className="tag origin">{task.origin}</span>}
      </td>
      <td>{TYPE_LABEL[task.type]}</td>
      <td>
        {editing ? (
          <span className="inline-edit">
            <input
              aria-label={`Query for ${task.id}`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <button disabled={busy || query.trim().length < 3} onClick={saveQuery}>
              Save
            </button>
            <button onClick={() => setEditing(false)}>Cancel</button>
          </span>
        ) : task.query ? (
          <code>{task.query}</code>
        ) : (
          task.focus || task.title
        )}
        {task.depends_on.length > 0 && (
          <span className="hint"> · after {task.depends_on.join(", ")}</span>
        )}
        {task.note && <div className="hint">{task.note}</div>}
      </td>
      <td>
        <span className={`status status-task-${task.status}`}>{task.status}</span>
        {editable && !editing && (
          <span className="task-actions">
            {task.type === "search" && (
              <button className="small" disabled={busy} onClick={() => setEditing(true)}>
                Edit
              </button>
            )}
            <button
              className="small"
              disabled={busy}
              onClick={() => onCommand({ type: "skip_subtask", subtask_id: task.id })}
            >
              Skip
            </button>
          </span>
        )}
      </td>
    </tr>
  );
}

function AddSearchForm({ plan, busy, onCommand }: {
  plan: ResearchPlan;
  busy: boolean;
  onCommand: SendCommand;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<"news" | "general">("general");
  const [questionIds, setQuestionIds] = useState<string[]>([]);

  if (!open) {
    return (
      <button className="small" onClick={() => setOpen(true)}>
        + Add a search
      </button>
    );
  }

  function toggle(id: string) {
    setQuestionIds(questionIds.includes(id) ? questionIds.filter((q) => q !== id) : [...questionIds, id]);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    onCommand({ type: "add_subtask", query: query.trim(), search_mode: mode, research_question_ids: questionIds });
    setQuery("");
    setQuestionIds([]);
    setOpen(false);
  }

  return (
    <form className="add-search" onSubmit={submit}>
      <input
        aria-label="New search query"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search query, e.g. Reuters Institute digital news report 2026"
      />
      <select aria-label="Search mode" value={mode} onChange={(e) => setMode(e.target.value as "news" | "general")}>
        <option value="general">general (studies, reports)</option>
        <option value="news">news (recent events)</option>
      </select>
      <div className="options">
        {plan.research_questions.map((q) => (
          <label key={q.id} className="check" title={q.text}>
            <input type="checkbox" checked={questionIds.includes(q.id)} onChange={() => toggle(q.id)} />
            {q.id}
          </label>
        ))}
      </div>
      <button type="submit" className="primary" disabled={busy || query.trim().length < 3}>
        Add search
      </button>
      <button type="button" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </form>
  );
}

export function PlanPanel({ plan, awaitingApproval, canEdit, busy, onCommand }: Props) {
  return (
    <section className={awaitingApproval ? "card plan attention" : "card plan"}>
      <header className="row">
        <h2>Research plan v{plan.version}</h2>
        {awaitingApproval && (
          <button className="primary" disabled={busy} onClick={() => onCommand({ type: "approve_plan" })}>
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
            <TaskRow key={t.id} task={t} canEdit={canEdit} busy={busy} onCommand={onCommand} />
          ))}
        </tbody>
      </table>
      <p className="hint">Why this plan: {plan.rationale}</p>
      {canEdit && <AddSearchForm plan={plan} busy={busy} onCommand={onCommand} />}
    </section>
  );
}
