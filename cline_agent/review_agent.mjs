// LandGuard extraction REVIEW AGENT, built on the Cline SDK (@cline/sdk, Node 22+).
//
// Role: for fields the extractor marked "unreadable", re-read the page text,
// then either PROPOSE a value with a verbatim quote, or confirm it stays unreadable.
//
// Hard limits (by design: "LLM only extracts, deterministic rules decide"):
//   * It has NO tool that runs rules, creates flags, or touches the ledger.
//   * It can only call propose_correction; Python re-validates every proposal
//     (format check + the quote must be found on the page) before accepting it.
//   * Page text it sees has Aadhaar/PAN numbers already redacted.
//
// [VERIFY] API shape follows docs.cline.bot/sdk/overview and /sdk/tools:
//   new Agent({providerId, modelId, apiKey, tools, maxIterations}), agent.run(prompt),
//   createTool({name, description, inputSchema (JSON Schema), execute}).
//   If a name differs in your installed version, fix it here; nothing else changes.
//
// Usage: node review_agent.mjs <job.json>      prints one line: LANDGUARD_RESULT:{...}

import { readFileSync } from "node:fs";
import { Agent, createTool } from "@cline/sdk";

const jobPath = process.argv[2];
if (!jobPath) {
  console.error("usage: node review_agent.mjs <job.json>");
  process.exit(2);
}
const job = JSON.parse(readFileSync(jobPath, "utf-8"));
const proposals = [];

// ---- tiny format checks (Python re-checks authoritatively) ----------
const FORMATS = {
  date: (v) => /^\d{4}-\d{2}-\d{2}$/.test(String(v)),
  number: (v) => Number.isFinite(Number(String(v).replace(/[,₹\s]/g, ""))),
  ulpin: (v) => /^[A-Z0-9]{14}$/i.test(String(v).replace(/[\s-]/g, "")),
};

const tools = [
  createTool({
    name: "get_field",
    description: "Get the current state of one field: low-confidence candidate value, notes, and where it was seen.",
    inputSchema: {
      type: "object",
      properties: { key: { type: "string", description: "Field key, e.g. property.survey_no" } },
      required: ["key"],
    },
    async execute({ key }) {
      return job.fields[key] ?? { error: `unknown field ${key}` };
    },
  }),
  createTool({
    name: "read_page_text",
    description: "Read the locally extracted text of one page (1-based). May be empty if no local text exists.",
    inputSchema: {
      type: "object",
      properties: { page: { type: "number", description: "1-based page number" } },
      required: ["page"],
    },
    async execute({ page }) {
      const t = job.pages[String(page)];
      return t ? { page, text: t } : { page, text: "", note: "NO_LOCAL_TEXT: cannot verify anything on this page" };
    },
  }),
  createTool({
    name: "validate_field",
    description: "Check whether a value has the right format for a field kind (date | number | ulpin).",
    inputSchema: {
      type: "object",
      properties: { kind: { type: "string" }, value: { type: "string" } },
      required: ["kind", "value"],
    },
    async execute({ kind, value }) {
      const f = FORMATS[kind];
      return { valid: f ? f(value) : true };
    },
  }),
  createTool({
    name: "propose_correction",
    description:
      "Propose a value for an unreadable field. `quote` MUST be copied verbatim from a page's text. " +
      "If you cannot find it with certainty, call this with status 'unreadable' and no value.",
    inputSchema: {
      type: "object",
      properties: {
        key: { type: "string" },
        status: { type: "string", enum: ["read", "unreadable"] },
        value: { type: "string" },
        page: { type: "number" },
        quote: { type: "string", description: "verbatim text from the page that supports the value" },
      },
      required: ["key", "status"],
    },
    async execute(p) {
      proposals.push(p);
      return { recorded: true };
    },
  }),
];

const prompt = `You review a land-deed extraction. These fields could not be read reliably: ${job.keys.join(", ")}.
For each one: call get_field, read the relevant page(s) with read_page_text, then call propose_correction.
Rules: never guess; quote verbatim from the page text; if the text does not clearly support a value,
propose status "unreadable". You cannot decide legal questions and must not comment on title or risk.`;

try {
  const agent = new Agent({
    providerId: process.env.LANDGUARD_CLINE_PROVIDER ?? "anthropic",
    modelId: process.env.LANDGUARD_CLINE_MODEL ?? "claude-sonnet-5-5",
    apiKey: process.env.LANDGUARD_CLINE_API_KEY ?? process.env.ANTHROPIC_API_KEY,
    tools,
    maxIterations: 12,
  });
  await agent.run(prompt);
  console.log("LANDGUARD_RESULT:" + JSON.stringify({ proposals }));
} catch (err) {
  console.log("LANDGUARD_RESULT:" + JSON.stringify({ proposals: [], error: String(err?.message ?? err) }));
  process.exit(0);
}
