import { describe, expect, it } from "vitest";
import { applyLog } from "../sessionStream";
import { logEntry, session } from "./fixtures";

describe("applyLog", () => {
  it("appends a new live log entry", () => {
    const updated = applyLog(session({ log: [logEntry(1)] }), logEntry(2));
    expect(updated.log.map((e) => e.seq)).toEqual([1, 2]);
  });

  it("ignores an entry the last snapshot already contained", () => {
    const current = session({ log: [logEntry(1), logEntry(2)] });
    expect(applyLog(current, logEntry(2))).toBe(current);
  });
});
