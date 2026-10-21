import type { Status } from "./types";

export const STATUS_LABEL: Record<Status, string> = {
  created: "Starting",
  clarifying: "Checking the topic",
  awaiting_answers: "Waiting for your answers",
  planning: "Planning",
  awaiting_plan_approval: "Waiting for plan approval",
  executing: "Researching",
  gap_check: "Reviewing coverage",
  synthesizing: "Writing the report",
  done: "Done",
  failed: "Failed",
};

export const WAITING: Status[] = ["awaiting_answers", "awaiting_plan_approval"];
export const FINISHED: Status[] = ["done", "failed"];

export function isWorking(status: Status, paused: boolean): boolean {
  return !paused && !WAITING.includes(status) && !FINISHED.includes(status);
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatCost(usd: number): string {
  return `$${usd.toFixed(usd < 0.1 ? 3 : 2)}`;
}
