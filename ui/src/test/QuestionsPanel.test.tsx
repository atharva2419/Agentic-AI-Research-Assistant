import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QuestionsPanel } from "../components/QuestionsPanel";
import type { ClarifyingQuestion } from "../types";

afterEach(cleanup);

function question(id: string, text: string): ClarifyingQuestion {
  return {
    id,
    question: text,
    why_it_matters: "It changes the sources.",
    suggested_options: ["US", "EU"],
    assumption_if_skipped: "Global coverage",
    origin: "clarify",
    answer: null,
    skipped: false,
  };
}

describe("QuestionsPanel", () => {
  it("sends picked options and null for skipped questions", () => {
    const onSubmit = vi.fn();
    render(
      <QuestionsPanel
        questions={[question("q1", "Which region?"), question("q2", "Which angle?")]}
        busy={false}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getAllByText("EU")[0]);
    fireEvent.click(screen.getByText("Continue"));
    expect(onSubmit).toHaveBeenCalledWith({ q1: "EU", q2: null });
  });

  it("shows what the agent will assume if a question is skipped", () => {
    render(<QuestionsPanel questions={[question("q1", "Which region?")]} busy={false} onSubmit={vi.fn()} />);
    expect(screen.getByText(/If skipped, the agent assumes: Global coverage/)).toBeTruthy();
  });
});
