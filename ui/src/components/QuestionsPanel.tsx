import { useState } from "react";
import type { ClarifyingQuestion } from "../types";

interface Props {
  questions: ClarifyingQuestion[];
  busy: boolean;
  onSubmit: (answers: Record<string, string | null>) => void;
}

/** The agent's clarifying questions. Leaving an answer empty skips it: the agent then uses the
 *  stated assumption, which is shown before you decide. */
export function QuestionsPanel({ questions, busy, onSubmit }: Props) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const payload: Record<string, string | null> = {};
    for (const q of questions) payload[q.id] = answers[q.id]?.trim() || null;
    onSubmit(payload);
  }

  return (
    <form className="card questions" onSubmit={submit}>
      <h2>The agent has {questions.length === 1 ? "a question" : "questions"}</h2>
      {questions.map((q) => (
        <div key={q.id} className="question">
          <p className="question-text">{q.question}</p>
          <p className="hint">Why it matters: {q.why_it_matters}</p>
          <div className="options">
            {q.suggested_options.map((option) => (
              <button
                type="button"
                key={option}
                className={answers[q.id] === option ? "chip selected" : "chip"}
                onClick={() => setAnswers({ ...answers, [q.id]: option })}
              >
                {option}
              </button>
            ))}
          </div>
          <input
            aria-label={`Answer to: ${q.question}`}
            value={answers[q.id] ?? ""}
            onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
            placeholder="Pick an option, type your own answer, or leave empty to skip"
          />
          <p className="assumption">If skipped, the agent assumes: {q.assumption_if_skipped}</p>
        </div>
      ))}
      <button type="submit" className="primary" disabled={busy}>
        Continue
      </button>
    </form>
  );
}
