import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { NewSessionForm } from "./components/NewSessionForm";
import { SessionList } from "./components/SessionList";
import { SessionView } from "./components/SessionView";
import type { SessionSummary } from "./types";

export function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [suggestedTopic, setSuggestedTopic] = useState("");

  const refresh = useCallback(() => {
    api.listSessions().then(setSessions).catch(() => undefined);
  }, []);

  useEffect(() => {
    api.health().then((h) => setOffline(h.offline)).catch(() => undefined);
    refresh();
    const timer = setInterval(refresh, 4000); // keeps statuses in the sidebar fresh
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <div className="app">
      <aside>
        <header className="brand">
          <span className="logo">◆</span> Research Assistant
          {offline && (
            <span className="badge" title="Generated sources and answers; no API keys, no cost">
              offline demo
            </span>
          )}
        </header>
        <NewSessionForm
          suggestedTopic={suggestedTopic}
          onCreated={(session) => {
            setSelectedId(session.id);
            refresh();
          }}
        />
        <SessionList sessions={sessions} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>
      <main>
        {selectedId ? (
          <SessionView key={selectedId} sessionId={selectedId} onSuggestTopic={setSuggestedTopic} />
        ) : (
          <div className="empty card">
            <h1>Start a research session</h1>
            <p>
              Give the agent a topic. It asks clarifying questions if needed, plans sub-tasks,
              searches for recent sources, filters out outdated or irrelevant ones, summarizes,
              cross-checks for contradictions, and writes a cited report.
            </p>
            <p className="hint">
              Every decision appears in the live action log with its reason. In supervised mode
              you approve the plan before any searching starts.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
