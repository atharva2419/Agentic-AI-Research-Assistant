import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import type { Mode, Session } from "../types";

interface Props {
  suggestedTopic: string;
  onCreated: (session: Session) => void;
}

export function NewSessionForm({ suggestedTopic, onCreated }: Props) {
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState<Mode>("supervised");
  const [recencyDays, setRecencyDays] = useState(365);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (suggestedTopic) setTopic(suggestedTopic);
  }, [suggestedTopic]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.createSession(topic.trim(), mode, recencyDays));
      setTopic("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start the session.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card new-session" onSubmit={submit}>
      <h2>New research</h2>
      <label>
        Topic
        <textarea
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="e.g. impact of AI on journalism"
          rows={3}
          required
          minLength={3}
        />
      </label>
      <fieldset className="mode">
        <legend>Mode</legend>
        <label>
          <input
            type="radio"
            checked={mode === "supervised"}
            onChange={() => setMode("supervised")}
          />
          Supervised <span className="hint">asks you, waits for plan approval</span>
        </label>
        <label>
          <input
            type="radio"
            checked={mode === "autonomous"}
            onChange={() => setMode("autonomous")}
          />
          Autonomous <span className="hint">states assumptions, never waits</span>
        </label>
      </fieldset>
      <label>
        Only sources from the last
        <span className="inline">
          <input
            type="number"
            min={1}
            max={3650}
            value={recencyDays}
            onChange={(e) => setRecencyDays(Number(e.target.value))}
          />
          days
        </span>
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" className="primary" disabled={busy || topic.trim().length < 3}>
        {busy ? "Starting…" : "Start research"}
      </button>
    </form>
  );
}
