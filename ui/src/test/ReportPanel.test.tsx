import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReportPanel } from "../components/ReportPanel";
import { report, source } from "./fixtures";

afterEach(cleanup);

function renderReport(onCite = vi.fn(), onSuggestTopic = vi.fn()) {
  render(
    <ReportPanel
      report={report()}
      sources={[source("S1")]}
      reportUrl="/api/sessions/abc/report.md"
      onCite={onCite}
      onSuggestTopic={onSuggestTopic}
    />,
  );
}

describe("ReportPanel", () => {
  it("shows citations with the source details as a tooltip", () => {
    const onCite = vi.fn();
    renderReport(onCite);
    const citation = screen.getByRole("button", { name: "S1" });
    expect(citation.getAttribute("title")).toBe("Title S1 — example.com, 2026-06-01");
    fireEvent.click(citation);
    expect(onCite).toHaveBeenCalledWith("S1");
  });

  it("flags statements whose citations could not be verified", () => {
    renderReport();
    expect(screen.getByText("unsupported")).toBeTruthy();
  });

  it("offers suggested topics as one-click new research", () => {
    const onSuggestTopic = vi.fn();
    renderReport(vi.fn(), onSuggestTopic);
    fireEvent.click(screen.getByText("AI and local news"));
    expect(onSuggestTopic).toHaveBeenCalledWith("AI and local news");
  });
});
