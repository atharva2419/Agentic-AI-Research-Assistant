import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseKeywords } from "../components/NewSessionForm";
import { ProgressCard } from "../components/ProgressCard";
import { ReportPanel } from "../components/ReportPanel";
import { logEntry, report, session, source } from "./fixtures";

afterEach(cleanup);

describe("ProgressCard (report column before the report exists)", () => {
  it("shows progress instead of an empty column", () => {
    render(
      <ProgressCard
        session={session({
          sources: [source("S1"), source("S2", { status: "excluded" })],
          log: [logEntry(1, "searched 'AI newsroom adoption'")],
        })}
      />,
    );
    expect(screen.getByText("1 kept · 1 excluded")).toBeTruthy();
    expect(screen.getByText(/Latest: searched 'AI newsroom adoption'/)).toBeTruthy();
  });

  it("tells the user when the agent is waiting for them", () => {
    render(<ProgressCard session={session({ status: "awaiting_plan_approval" })} />);
    expect(screen.getByText(/waiting for you to approve the plan/)).toBeTruthy();
  });
});

describe("priority keywords", () => {
  it("parses a comma-separated list", () => {
    expect(parseKeywords(" GA4, hreflang ,, ga4,  headless   CMS ")).toEqual([
      "GA4",
      "hreflang",
      "headless CMS",
    ]);
  });

  it("shows keyword coverage in the report, flagging uncovered ones", () => {
    const onCite = vi.fn();
    render(
      <ReportPanel
        report={{ ...report(), keyword_coverage: { GA4: ["S1"], hreflang: [] } }}
        sources={[source("S1")]}
        reportUrl="/x"
        onCite={onCite}
        onSuggestTopic={vi.fn()}
      />,
    );
    expect(screen.getByText("no source mentions it")).toBeTruthy();
    const citations = screen.getAllByRole("button", { name: "S1" });
    fireEvent.click(citations[citations.length - 1]);
    expect(onCite).toHaveBeenCalledWith("S1");
  });
});
