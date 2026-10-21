// TypeScript mirrors of the Pydantic models in app/models.py, as the API sends them.
// Kept by hand for readability; a bigger project would generate these from /openapi.json.

export type Status =
  | "created"
  | "clarifying"
  | "awaiting_answers"
  | "planning"
  | "awaiting_plan_approval"
  | "executing"
  | "gap_check"
  | "synthesizing"
  | "done"
  | "failed";

export type Mode = "autonomous" | "supervised";
export type Actor = "agent" | "user" | "system";

export interface ClarifyingQuestion {
  id: string;
  question: string;
  why_it_matters: string;
  suggested_options: string[];
  assumption_if_skipped: string;
  origin: "clarify" | "gap_check";
  answer: string | null;
  skipped: boolean;
}

export interface ResearchQuestion {
  id: string;
  text: string;
}

export interface SubTask {
  id: string;
  type: "search" | "summarize" | "cross_check";
  title: string;
  query: string | null;
  search_mode: "news" | "general";
  focus: string | null;
  research_question_ids: string[];
  depends_on: string[];
  status: "pending" | "running" | "done" | "skipped" | "failed";
  origin: "planner" | "replan" | "user";
  note: string | null;
}

export interface ResearchPlan {
  version: number;
  objective: string;
  research_questions: ResearchQuestion[];
  subtasks: SubTask[];
  rationale: string;
}

export interface Source {
  id: string;
  url: string;
  title: string;
  domain: string;
  published_date: string | null;
  snippet: string;
  found_by: string[];
  status: "kept" | "excluded";
  relevance_score: number | null;
  relevance_reason: string | null;
  exclusion: { stage: "rule" | "relevance" | "user"; reason: string } | null;
}

export interface SourceSummary {
  source_id: string;
  summary: string;
  key_takeaways: string[];
  claims: string[];
  quotes: { text: string; context: string }[];
}

export interface Contradiction {
  id: string;
  topic: string;
  claim_a: string;
  source_a: string;
  claim_b: string;
  source_b: string;
  explanation: string;
  likely_cause: string;
}

export interface CitedStatement {
  text: string;
  source_ids: string[];
  supported: boolean;
}

export interface Report {
  title: string;
  executive_summary: string;
  key_takeaways: CitedStatement[];
  sections: { heading: string; statements: CitedStatement[] }[];
  contradictions: Contradiction[];
  open_questions: string[];
  assumptions: string[];
  limitations: string[];
  suggested_next_topics: string[];
}

export interface Budget {
  searches: number;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  replans: number;
  gap_questions_asked: number;
}

export interface LogEntry {
  seq: number;
  timestamp: string;
  actor: Actor;
  step: string;
  action: string;
  decision: string;
  reason: string;
  details: Record<string, unknown>;
}

export interface Session {
  id: string;
  user_id: string;
  topic: string;
  mode: Mode;
  status: Status;
  paused: boolean;
  settings: { recency_days: number; relevance_threshold: number };
  questions: ClarifyingQuestion[];
  assumptions: string[];
  plan: ResearchPlan | null;
  sources: Source[];
  summaries: SourceSummary[];
  contradictions: Contradiction[];
  report: Report | null;
  budget: Budget;
  log: LogEntry[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionSummary {
  id: string;
  topic: string;
  status: Status;
  mode: Mode;
  created_at: string;
  cost_usd: number;
}

// The commands the API accepts (app/models.py UserCommand). Phase 6 adds the override commands.
export type Command =
  | { type: "answer_questions"; answers: Record<string, string | null> }
  | { type: "approve_plan" }
  | { type: "pause" }
  | { type: "resume" };
