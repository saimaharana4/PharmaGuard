import { responseSchema, type Investigation, type Question } from "./schemas";
import { z } from "zod";

export class ApiError extends Error {
  constructor(message: string, public requestId?: string) { super(message); }
}

const memorySchema = z.object({enabled: z.boolean(), history: z.array(z.object({
  question: z.string(), answer: z.string(),
})).optional()});

type Memory = {question: string; answer: string}[];
let pendingSession: Promise<Memory> | undefined;

export function renewSession(): Promise<Memory> {
  // Initial hydration, submission and the timer must not create competing cookies.
  pendingSession ??= refreshSession().finally(() => { pendingSession = undefined; });
  return pendingSession;
}

async function refreshSession(): Promise<Memory> {
  const response = await fetch("/api/session", {method: "POST", cache: "no-store"});
  // Expired credentials are discarded by the proxy; start fresh, never refresh an expired JWT.
  if (response.status === 401) {
    const fresh = await fetch("/api/session", {method: "POST", cache: "no-store"});
    if (!fresh.ok) throw new ApiError("Anonymous session is unavailable.");
    return memorySchema.parse(await fresh.json()).history ?? [];
  } else if (!response.ok) throw new ApiError("Anonymous session is unavailable.");
  return memorySchema.parse(await response.json()).history ?? [];
}

export async function investigate(question: Question, signal?: AbortSignal): Promise<Investigation> {
  await renewSession();
  const response = await fetch("/api/investigate", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(question), signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.error?.message ?? "The investigation is unavailable. Please retry.", body?.error?.request_id);
  }
  const parsed = responseSchema.safeParse(await response.json());
  if (!parsed.success) throw new ApiError("The service returned an invalid response.");
  return parsed.data;
}
