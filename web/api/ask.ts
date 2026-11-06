import { generateText } from "ai";
import { openai } from "@ai-sdk/openai";
import type { VercelRequest, VercelResponse } from "@vercel/node";

const MODEL_ID = "gpt-5-nano";
const MAX_ROWS = 16;
const MAX_CHARS_PER_ROW = 700;

const SYSTEM = `You help a roofing sales rep in New Castle County, Delaware decide which properties to call.
Use only the evidence JSON. Never invent BBB ratings, license matches, sale dates, contractors, or roof ages.

Write for a person, not a database:
- Start with one or two sentences that answer the question directly. Use the retrieval item's match_count for the total number of matched parcels.
- If match_count is larger than the number of property rows you were given, say so plainly, for example "Showing 8 of 2,830 matched parcels."
- Then list up to 6 properties as "- ADDRESS, CITY: the fact that matters (parcel PRCLID)". Use plain words such as "roof about 76 years old, from year built" or "roof permit open 10,007 days, contractor HURLOCK ROOFING CO.".
- Never print field names, JSON keys, or the word null. If a contractor or roof age is missing, say so once in plain words, for example "No contractor is printed on these permits."
- If a citation in the evidence limits the answer, end with one short sentence that names the limit. The page shows the full citations separately.
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
