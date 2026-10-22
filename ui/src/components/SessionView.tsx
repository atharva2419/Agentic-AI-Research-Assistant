import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { STATUS_LABEL, formatCost, isWorking } from "../format";
import { useSessionStream } from "../sessionStream";
import type { Command, Status } from "../types";
import { LogPanel } from "./LogPanel";
import { PlanPanel } from "./PlanPanel";
import { QuestionsPanel } from "./QuestionsPanel";
import { RelatedResearch } from "./RelatedResearch";
import { ReportPanel } from "./ReportPanel";
import { SourcesPanel } from "./SourcesPanel";

type Tab = "log" | "sources" | "report";

// Mirrors PLAN_CHANGEABLE in app/orchestrator/overrides.py.
const PLAN_CHANGEABLE: Status[] = ["awaiting_plan_approval", "executing", "gap_check", "done"];

function RecencyControl({ days, busy, onApply }: {
  days: number;
  busy: boolean;
  onApply: (days: number) => void;
}) {
  const [value, setValue] = useState(days);
  useEffect(() => setValue(days), [days]);
  return (
    <span className="inline-edit" title="Re-checks every source already found against the new window">
      <label>
        Window{" "}
        <input
          aria-label="Date window in days"
          type="number"
          min={1}
          max={3650}
          value={value}
          onChange={(e) => setValue(Number(e.target.value))}
        />{" "}
        days
      </label>
      <button disabled={busy || value === days || value < 1} onClick={() => onApply(value)}>
        Apply
      </button>
    </span>
  );
}

interface Props {
  sessionId: string;
  onSuggestTopic: (topic: string) => void;
  onOpenSession: (sessionId: string) => void;
  onDeleted: () => void;
}

export function SessionView({ sessionId, onSuggestTopic, onOpenSession, onDeleted }: Props) {
  const { session, setSession, connected } = useSessionStream(sessionId);
  const [tab, setTab] = useState<Tab>("log");
  const [highlight, setHighlight] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasReport = Boolean(session?.report);
  useEffect(() => {
    if (hasReport) setTab("report");
  }, [hasReport]);

  if (!session) return <p className="hint">Connecting…</p>;

  async function send(command: Command) {
    setBusy(true);
    setError(null);
    try {
      setSession(await api.sendCommand(sessionId, command));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The command could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  function cite(sourceId: string) {
    setHighlight(sourceId);
    setTab("sources");
  }

  async function remove() {
    if (!window.confirm("Delete this session, its report and what the agent remembers from it?")) {
      return;
    }
    try {
      await api.deleteSession(sessionId);
      onDeleted();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The session could not be deleted.");
    }
  }

  const pending = session.questions.filter((q) => q.answer === null && !q.skipped);
  const working = isWorking(session.status, session.paused);
  const kept = session.sources.filter((s) => s.status === "kept").length;
  const { budget } = session;

  return (
    <div className="session">
      <header className="card session-header">
        <div>
          <h1>{session.topic}</h1>
          <p className="hint">
            {session.mode} mode · sources from the last {session.settings.recency_days} days
            {!connected && " · reconnecting…"}
          </p>
        </div>
        <div className="status-block">
          <span className={`status status-${session.status}`}>
            {session.paused ? "Paused" : STATUS_LABEL[session.status]}
            {working && <span className="spinner" aria-hidden />}
          </span>
          <p className="hint">
            {budget.searches} searches · {budget.llm_calls} AI calls · {formatCost(budget.cost_usd)}
          </p>
          <button className="small danger" onClick={remove}>
            Delete session
          </button>
          {session.status !== "failed" && (
            <div className="controls">
              {session.status !== "done" && (
                <button
                  disabled={busy}
                  onClick={() => send({ type: session.paused ? "resume" : "pause" })}
                >
                  {session.paused ? "Resume" : "Pause"}
                </button>
              )}
              {session.status !== "done" && (
                // Mode only affects what the agent waits for, so it means nothing once done.
                <button
                  disabled={busy}
                  title="Autonomous: never waits for you. Supervised: asks and waits for plan approval."
                  onClick={() =>
                    send({
                      type: "set_mode",
                      mode: session.mode === "supervised" ? "autonomous" : "supervised",
                    })
                  }
                >
                  Switch to {session.mode === "supervised" ? "autonomous" : "supervised"}
                </button>
              )}
              <RecencyControl
                days={session.settings.recency_days}
                busy={busy}
                onApply={(days) => send({ type: "set_recency", recency_days: days })}
              />
            </div>
          )}
        </div>
      </header>
      {session.status === "executing" && session.report && (
        <p className="card notice">
          Revising the report after your change. The previous version stays visible until the new
          one is ready.
        </p>
      )}

      {error && <p className="card error">{error}</p>}
      {session.related_memory.length > 0 && (
        <div className="card">
          <RelatedResearch
            matches={session.related_memory}
            title="From past research (used as context for planning, not as evidence):"
            onOpen={onOpenSession}
          />
        </div>
      )}
      {session.error && <p className="card error">Session failed: {session.error}</p>}

      {session.status === "awaiting_answers" && pending.length > 0 && (
        <QuestionsPanel
          key={pending.map((q) => q.id).join()}
          questions={pending}
          busy={busy}
          onSubmit={(answers) => send({ type: "answer_questions", answers })}
        />
      )}

      {session.assumptions.length > 0 && (
        <div className="card assumptions">
          <strong>Working assumptions:</strong>
          <ul>
            {session.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {session.plan && (
        <PlanPanel
          plan={session.plan}
          awaitingApproval={session.status === "awaiting_plan_approval"}
          canEdit={PLAN_CHANGEABLE.includes(session.status)}
          busy={busy}
          onCommand={send}
        />
      )}

      <section className="card">
        <nav className="tabs">
          <button className={tab === "log" ? "active" : ""} onClick={() => setTab("log")}>
            Action log ({session.log.length})
          </button>
          <button className={tab === "sources" ? "active" : ""} onClick={() => setTab("sources")}>
            Sources ({kept} kept / {session.sources.length - kept} excluded)
          </button>
          <button
            className={tab === "report" ? "active" : ""}
            onClick={() => setTab("report")}
            disabled={!session.report}
          >
            Report
          </button>
        </nav>
        {tab === "log" && <LogPanel log={session.log} />}
        {tab === "sources" && (
          <SourcesPanel
            sources={session.sources}
            summaries={session.summaries}
            highlightId={highlight}
            canChange={session.status !== "failed"}
            busy={busy}
            onCommand={send}
          />
        )}
        {tab === "report" && session.report && (
          <ReportPanel
            report={session.report}
            sources={session.sources}
            reportUrl={api.reportUrl(session.id)}
            onCite={cite}
            onSuggestTopic={onSuggestTopic}
          />
        )}
      </section>
    </div>
  );
}
