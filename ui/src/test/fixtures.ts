import type { LogEntry, Report, Session, Source } from "../types";

export function logEntry(seq: number, action = "did something"): LogEntry {
  return {
    seq,
    timestamp: "2026-10-21T10:00:00Z",
    actor: "agent",
    step: "search",
    action,
    decision: "",
    reason: "",
    details: {},
  };
}

export function source(id: string, overrides: Partial<Source> = {}): Source {
  return {
    id,
    url: `https://example.com/${id}`,
    title: `Title ${id}`,
    domain: "example.com",
    published_date: "2026-06-01",
    snippet: "",
    found_by: ["t1"],
    status: "kept",
    relevance_score: 0.9,
    relevance_reason: "on topic",
    exclusion: null,
    ...overrides,
  };
}

export function report(): Report {
  return {
    title: "AI in journalism",
    executive_summary: "AI is spreading through newsrooms.",
    key_takeaways: [
      { text: "Adoption is growing.", source_ids: ["S1"], supported: true },
      { text: "Jobs are disappearing.", source_ids: [], supported: false },
    ],
    sections: [],
    contradictions: [],
    open_questions: [],
    assumptions: ["US focus"],
    limitations: [],
    suggested_next_topics: ["AI and local news"],
  };
}

export function session(overrides: Partial<Session> = {}): Session {
  return {
    id: "abc",
    user_id: "demo",
    topic: "AI in journalism",
    mode: "supervised",
    status: "executing",
    paused: false,
    settings: { recency_days: 365, relevance_threshold: 0.6 },
    questions: [],
    assumptions: [],
    plan: null,
    sources: [],
    summaries: [],
    contradictions: [],
    report: null,
    related_memory: [],
    budget: {
      searches: 0,
      llm_calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      replans: 0,
      gap_questions_asked: 0,
    },
    log: [],
    error: null,
    created_at: "2026-10-21T10:00:00Z",
    updated_at: "2026-10-21T10:00:00Z",
    ...overrides,
  };
}
