import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { MemoryPanel } from "./components/MemoryPanel";
import { NewSessionForm } from "./components/NewSessionForm";
import { SessionList } from "./components/SessionList";
import { SessionView } from "./components/SessionView";
import type { MemoryItem, SessionSummary } from "./types";

const USER_KEY = "research-assistant-user";

function savedUser(): string {
  try {
    return localStorage.getItem(USER_KEY) || "demo";
  } catch {
    return "demo";
  }
}

export function App() {
  const [userId, setUserId] = useState(savedUser);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [memory, setMemory] = useState<MemoryItem[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [suggestedTopic, setSuggestedTopic] = useState("");

  const refresh = useCallback(() => {
    api.listSessions(userId).then(setSessions).catch(() => undefined);
    api.memory(userId).then(setMemory).catch(() => undefined);
    api.suggestions(userId).then(setSuggestions).catch(() => undefined);
  }, [userId]);

  useEffect(() => {
    api.health().then((h) => setOffline(h.offline)).catch(() => undefined);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(USER_KEY, userId);
    } catch {
      // storage can be unavailable (private mode); the name just won't be remembered
    }
    refresh();
    const timer = setInterval(refresh, 4000); // keeps statuses and memory in the sidebar fresh
    return () => clearInterval(timer);
  }, [userId, refresh]);

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
        <label className="user">
          Researching as
          <input
            aria-label="Your name"
            value={userId}
            onChange={(e) => {
              setUserId(e.target.value.trim() || "demo");
              setSelectedId(null);
            }}
          />
        </label>
        <NewSessionForm
          userId={userId}
          suggestedTopic={suggestedTopic}
          onCreated={(session) => {
            setSelectedId(session.id);
            refresh();
          }}
          onOpenSession={setSelectedId}
        />
        <MemoryPanel
          items={memory}
          suggestions={suggestions}
          onSuggest={setSuggestedTopic}
          onForget={(itemId) => api.forget(userId, itemId).then(refresh)}
        />
        <SessionList sessions={sessions} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>
      <main>
        {selectedId ? (
          <SessionView
            key={selectedId}
            sessionId={selectedId}
            onSuggestTopic={setSuggestedTopic}
            onOpenSession={setSelectedId}
            onDeleted={() => {
              setSelectedId(null);
              refresh();
            }}
          />
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
              you approve the plan before any searching starts. Finished research is remembered
              per user, so related topics build on it.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
