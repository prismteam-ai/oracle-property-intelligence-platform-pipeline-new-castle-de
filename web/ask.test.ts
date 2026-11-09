import assert from "node:assert/strict";
import test from "node:test";
import { evidenceText, prepareAsk } from "./api/ask.ts";

test("prepareAsk rejects an empty question", () => {
  const result = prepareAsk({ question: "   ", evidence: [] });
  assert.equal(result.ok, false);
  if (!result.ok) assert.equal(result.status, 400);
});

test("prepareAsk keeps 16 rows and 700 characters each", () => {
  const evidence = Array.from({ length: 20 }, (_, index) => ({
    prclid: String(index),
    note: "x".repeat(900),
  }));
  const result = prepareAsk({ question: "Which roofs are old?", evidence });
  assert.equal(result.ok, true);
  if (!result.ok) return;
  const lines = result.evidence.split("\n");
  assert.equal(lines.length, 16);
  assert.ok(lines.every((line) => line.length <= 700));
  assert.equal(evidenceText(evidence).split("\n").length, 16);
});
