import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlanPanel } from "../components/PlanPanel";
import { SourcesPanel } from "../components/SourcesPanel";
import type { ResearchPlan } from "../types";
import { source } from "./fixtures";

afterEach(cleanup);

const plan: ResearchPlan = {
  version: 1,
  objective: "Understand AI in journalism",
  research_questions: [{ id: "RQ1", text: "How are newsrooms adopting AI?" }],
  subtasks: [
    {
      id: "t1",
      type: "search",
      title: "Adoption",
      query: "AI newsroom adoption",
      search_mode: "news",
      focus: null,
      research_question_ids: ["RQ1"],
      depends_on: [],
      status: "pending",
      origin: "planner",
      note: null,
    },
    {
      id: "t2",
      type: "summarize",
      title: "Summarize",
      query: null,
      search_mode: "general",
      focus: null,
      research_question_ids: [],
      depends_on: ["t1"],
      status: "done",
      origin: "planner",
      note: null,
    },
  ],
  rationale: "Start broad.",
};

function renderPlan(onCommand = vi.fn(), canEdit = true) {
  render(<PlanPanel plan={plan} awaitingApproval canEdit={canEdit} busy={false} onCommand={onCommand} />);
  return onCommand;
}

describe("plan overrides", () => {
  it("skips a pending task", () => {
    const onCommand = renderPlan();
    fireEvent.click(screen.getByText("Skip"));
    expect(onCommand).toHaveBeenCalledWith({ type: "skip_subtask", subtask_id: "t1" });
  });

  it("only offers edit/skip on pending tasks", () => {
    renderPlan();
    expect(screen.getAllByText("Skip")).toHaveLength(1); // t2 is done
  });

  it("edits a search query", () => {
    const onCommand = renderPlan();
    fireEvent.click(screen.getByText("Edit"));
    fireEvent.change(screen.getByLabelText("Query for t1"), { target: { value: "AI newsroom survey 2026" } });
    fireEvent.click(screen.getByText("Save"));
    expect(onCommand).toHaveBeenCalledWith({
      type: "edit_plan",
      edits: [{ id: "t1", query: "AI newsroom survey 2026" }],
    });
  });

  it("adds a search linked to a research question", () => {
    const onCommand = renderPlan();
    fireEvent.click(screen.getByText("+ Add a search"));
    fireEvent.change(screen.getByLabelText("New search query"), { target: { value: "newsroom AI policy" } });
    fireEvent.click(screen.getByLabelText("RQ1"));
    fireEvent.click(screen.getByText("Add search"));
    expect(onCommand).toHaveBeenCalledWith({
      type: "add_subtask",
      query: "newsroom AI policy",
      search_mode: "general",
      research_question_ids: ["RQ1"],
    });
  });

  it("hides controls when the plan can't change", () => {
    renderPlan(vi.fn(), false);
    expect(screen.queryByText("Skip")).toBeNull();
    expect(screen.queryByText("+ Add a search")).toBeNull();
  });
});

describe("source overrides", () => {
  it("excludes a kept source with a reason, and re-includes an excluded one", () => {
    const onCommand = vi.fn();
    const excluded = source("S2", {
      status: "excluded",
      exclusion: { stage: "relevance", reason: "off topic", rule: null },
    });
    render(
      <SourcesPanel
        sources={[source("S1"), excluded]}
        summaries={[]}
        highlightId={null}
        canChange
        busy={false}
        onCommand={onCommand}
      />,
    );
    fireEvent.click(screen.getByText("Exclude"));
    fireEvent.change(screen.getByLabelText("Why exclude S1"), { target: { value: "paywalled" } });
    fireEvent.click(screen.getByText("Confirm"));
    expect(onCommand).toHaveBeenCalledWith({ type: "exclude_source", source_id: "S1", reason: "paywalled" });

    fireEvent.click(screen.getByText("Re-include"));
    expect(onCommand).toHaveBeenCalledWith({ type: "include_source", source_id: "S2" });
  });
});
