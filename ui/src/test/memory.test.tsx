import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryPanel } from "../components/MemoryPanel";
import { RelatedResearch } from "../components/RelatedResearch";
import type { MemoryItem } from "../types";

afterEach(cleanup);

const item: MemoryItem = {
  id: "m1",
  user_id: "demo",
  session_id: "s1",
  topic: "AI in journalism",
  summary: "AI is spreading.",
  key_findings: ["Adoption is growing."],
  source_urls: [],
  suggested_topics: [],
  created_at: "2026-10-20T10:00:00Z",
  expires_at: new Date(Date.now() + 100 * 86_400_000).toISOString(),
};

describe("MemoryPanel", () => {
  it("starts a suggested topic and forgets a memory", () => {
    const onSuggest = vi.fn();
    const onForget = vi.fn();
    render(
      <MemoryPanel items={[item]} suggestions={["AI and local news"]} onSuggest={onSuggest} onForget={onForget} />,
    );
    fireEvent.click(screen.getByText("AI and local news"));
    expect(onSuggest).toHaveBeenCalledWith("AI and local news");
    fireEvent.click(screen.getByText("Forget"));
    expect(onForget).toHaveBeenCalledWith("m1");
    expect(screen.getByText(/forgotten automatically in 100 days/)).toBeTruthy();
  });

  it("renders nothing when there is no memory", () => {
    const { container } = render(
      <MemoryPanel items={[]} suggestions={[]} onSuggest={vi.fn()} onForget={vi.fn()} />,
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("RelatedResearch", () => {
  it("opens a related past session", () => {
    const onOpen = vi.fn();
    render(
      <RelatedResearch
        title="From past research"
        onOpen={onOpen}
        matches={[{ ...item, similarity: 0.41 }]}
      />,
    );
    expect(screen.getByText(/similarity 0.41/)).toBeTruthy();
    fireEvent.click(screen.getByText("AI in journalism"));
    expect(onOpen).toHaveBeenCalledWith("s1");
  });
});
