import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { STATUS_LABEL, formatCost, isWorking } from "../format";
import { useSessionStream } from "../sessionStream";
import type { Command } from "../types";
import { LogPanel } from "./LogPanel";
import { PlanPanel } from "./PlanPanel";
import { QuestionsPanel } from "./QuestionsPanel";
import { ReportPanel } from "./ReportPanel";
import { SourcesPanel } from "./SourcesPanel";

type Tab = "log" | "sources" | "report";

interface Props {
  sessionId: string;
  onSuggestTopic: (topic: string) => void;
}

export function SessionView({ sessionId, onSuggestTopic }: Props) {
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
          {!["done", "failed"].includes(session.status) && (
            <button
              disabled={busy}
              onClick={() => send({ type: session.paused ? "resume" : "pause" })}
            >
              {session.paused ? "Resume" : "Pause"}
            </button>
          )}
        </div>
      </header>

      {error && <p className="card error">{error}</p>}
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
          busy={busy}
          onApprove={() => send({ type: "approve_plan" })}
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
