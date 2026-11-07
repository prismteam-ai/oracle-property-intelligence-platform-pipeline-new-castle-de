import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";
import type { VercelRequest, VercelResponse } from "@vercel/node";

const MODEL_ID = "gpt-5-nano";
const MAX_ROWS = 16;
const MAX_CHARS_PER_ROW = 700;

const SYSTEM = `You help a roofing sales rep in New Castle County, Delaware decide which properties to call.
Use only the evidence JSON. Never invent BBB ratings, license matches, sale dates, contractors, or roof ages.

Write for a person, not a database:
- Start with one or two plain sentences that answer the question. Do not begin with a label such as "Answer" or "Answer directly", and do not describe the evidence. Use the retrieval item's match_count for the total matched parcels and its shown_count for how many property lines you list.
- If match_count is larger than shown_count, say so plainly, for example "Showing 8 of 2,830 matched parcels."
- Then list up to 6 properties as "- ADDRESS, CITY: the facts (parcel PRCLID)". Each property line must use its "facts" array in the evidence: state the open permit days when a permit is open, and the roof age or that the roof age is unknown. Copy the facts; do not add or change numbers. Write "license name match" only where the facts say so, and never call a license match a confirmed identity.
- Never print field names, JSON keys, or the word null. Use the facts text only, in plain words, for example "open 3,005 days" and not days_open. Do not write a summary phrase such as "roof ages listed" unless property lines follow it.
- Name a citation limit only when it changes the answer to the question asked, in one short sentence. Do not add a limit sentence otherwise. The page shows the full citations separately.
- Do not offer to narrow the list or ask a follow-up question.
- No headings and no bold. Keep it under 180 words.`;

interface AskBody {
  question?: unknown;
  evidence?: unknown;
}

export function evidenceText(evidence: unknown[]): string {
  return evidence
    .slice(0, MAX_ROWS)
    .map((item) => JSON.stringify(item).slice(0, MAX_CHARS_PER_ROW))
    .join("\n");
}

export function prepareAsk(body: AskBody):
  | { ok: true; question: string; evidence: string }
  | { ok: false; status: number; error: string } {
  const question = String(body.question ?? "").trim().slice(0, 2000);
  const evidence = Array.isArray(body.evidence) ? body.evidence : [];
  if (!question) return { ok: false, status: 400, error: "A question is required." };
  return { ok: true, question, evidence: evidenceText(evidence) };
}

export default async function handler(req: VercelRequest, res: VercelResponse): Promise<void> {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    res.status(405).json({ error: "POST only" });
    return;
  }
  if (!process.env.OPENAI_API_KEY) {
    res.status(500).json({ error: "OpenAI key is not configured on the server." });
    return;
  }
  const prepared = prepareAsk((req.body ?? {}) as AskBody);
  if (!prepared.ok) {
    res.status(prepared.status).json({ error: prepared.error });
    return;
  }

  try {
    const result = await generateText({
      model: openai(MODEL_ID),
      system: SYSTEM,
      prompt: `Question: ${prepared.question}\n\nEvidence:\n${prepared.evidence}`,
      maxOutputTokens: 8000,
      providerOptions: { openai: { reasoningEffort: "minimal" } },
    });
    const answer = result.text.trim();
    res.status(200).json({
      model: result.response.modelId || MODEL_ID,
      provider: "OpenAI via Vercel AI SDK",
      answer: answer || "The model returned no text.",
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "The model request failed.";
    res.status(502).json({ error: message, model: MODEL_ID });
  }
}
