import { z } from "zod";

export const evidenceSchema = z.object({
  chunk_id: z.string(), document_id: z.string(), score: z.number(), rank: z.number(),
  source_type: z.string(), source_date: z.string(), available_at: z.string(), title: z.string(),
  locator: z.string(), polarity: z.enum(["support", "contradict", "context"]),
  text: z.string(), url: z.string(),
});
export const responseSchema = z.object({
  request_id: z.string(), answer: z.string(), insufficient_evidence: z.boolean(),
  facts: z.object({
    period_start: z.string(), period_end: z.string(), case_count: z.number().nullable(),
    ror: z.number().nullable(), prr: z.number().nullable(),
    cells: z.object({a: z.number(), b: z.number(), c: z.number(), d: z.number()}).nullable(),
    status: z.enum(["available", "insufficient_data"]), reason: z.string().nullable(),
    drug: z.string().nullable(), event: z.string().nullable(), dataset_id: z.string(),
    source_releases: z.array(z.string()),
  }),
  citations: z.array(evidenceSchema), retrieved_evidence_ids: z.array(z.string()),
  retrieval: z.object({top_k: z.number(), returned: z.number(), collection: z.string(),
    config_version: z.string(), query_model_revision: z.string()}),
  data_window: z.object({lookback_months: z.number(), window_start: z.string(), as_of_date: z.string(),
    cutoff_date: z.string(), dataset_id: z.string(), coverage: z.record(z.string(), z.unknown())}),
  warnings: z.array(z.string()),
  session_id: z.string().nullable().optional(),
  cache_status: z.enum(["hit", "miss", "disabled"]).optional(),
});
export type Investigation = z.infer<typeof responseSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Question = {question: string; drug?: string; event?: string; cutoff_date?: string};

export function sourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && ["pubmed.ncbi.nlm.nih.gov", "dailymed.nlm.nih.gov", "www.fda.gov"].includes(url.hostname) ? url.href : null;
  } catch { return null; }
}
