import { expect, test } from "@playwright/test";
import { request as nodeRequest } from "node:http";

const chunk = "33333333-3333-4333-8333-333333333333";
const fixture = {
  request_id: "test-request", answer: `Synthetic test evidence [${chunk}]`, insufficient_evidence: false,
  facts: {period_start: "2024-10-18", period_end: "2026-10-18", case_count: 10, ror: 1.5, prr: 1.4,
    cells: {a: 10, b: 20, c: 30, d: 90}, status: "available", reason: null,
    drug: "semaglutide", event: "pancreatitis", dataset_id: "test-only", source_releases: ["test-only"]},
  citations: [{chunk_id: chunk, document_id: "test-source", score: 0.9, rank: 1, source_type: "pubmed",
    source_date: "2026-01-01", available_at: "2026-01-01", title: "Synthetic browser test evidence",
    locator: "test-only", polarity: "context", text: "Synthetic test fixture. Never a production answer.",
    url: "https://pubmed.ncbi.nlm.nih.gov/"}],
  retrieved_evidence_ids: [chunk],
  retrieval: {top_k: 5, returned: 1, collection: "test-only", config_version: "test-only", query_model_revision: "test-only"},
  data_window: {lookback_months: 24, window_start: "2024-10-18", as_of_date: "2026-10-18", cutoff_date: "2026-10-18", dataset_id: "test-only", coverage: {}}, warnings: ["Test data only."],
};

test.beforeEach(async ({page}) => {
  await page.route("**/api/session", route => route.fulfill({json: {enabled: false}}));
  await page.route("**/api/ready", route => route.fulfill({json: {status: "ready"}}));
  await page.route("**/api/version", route => route.fulfill({json: {git_sha: "test-build"}}));
});

test("question, metrics, citation inspection, and responsive layout", async ({page}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/investigate", route => route.fulfill({json: fixture}));
  await page.goto("/");
  await expect(page.getByRole("heading", {level: 1})).toContainText("Follow the signal");
  await page.screenshot({path:testInfo.outputPath("workspace-empty.png"),fullPage:true});
  await page.getByRole("button", {name: /01.*What does recent evidence/}).click();
  await page.getByRole("button", {name: "Investigate", exact: true}).click();
  await expect(page.getByText("Signal summary", {exact: true})).toBeVisible();
  await page.getByRole("button", {name: "Inspect source 1"}).click();
  await expect(page.getByRole("heading", {name: "Synthetic browser test evidence"})).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("proxy rejects foreign origins and oversized requests", async ({request}) => {
  const foreign = await request.post("/api/investigate", {headers:{Origin:"https://untrusted.example"},data:{question:"test question"}});
  expect(foreign.status()).toBe(403);
  const malformed = await request.post("/api/investigate", {headers:{Origin:"malformed-origin"},data:{question:"test question"}});
  expect(malformed.status()).toBe(403);
  const huge = await request.post("/api/investigate", {headers:{Origin:"http://127.0.0.1:3000"},data:{question:"x".repeat(20000)}});
  expect(huge.status()).toBe(413);
  const chunkedStatus = await new Promise<number>((resolve, reject) => {
    const upload = nodeRequest("http://127.0.0.1:3000/api/investigate", {
      method: "POST", headers: {Origin: "http://127.0.0.1:3000", "Transfer-Encoding": "chunked"},
    }, response => { response.resume(); resolve(response.statusCode ?? 0); });
    upload.on("error", reject);
    upload.write('{"question":"');
    upload.write("x".repeat(20000));
    upload.end('"}');
  });
  expect(chunkedStatus).toBe(413);
});

test("dependency failure exposes retry and request ID", async ({page}) => {
  await page.route("**/api/investigate", route => route.fulfill({status: 503, json: {
    error: {code: "RETRIEVAL_UNAVAILABLE", message: "Evidence retrieval is unavailable.", request_id: "test-error"},
  }}));
  await page.goto("/");
  await page.getByLabel("Ask a drug-safety question").fill("semaglutide pancreatitis");
  await page.getByLabel("Ask a drug-safety question").press("Enter");
  await expect(page.getByRole("alert").filter({hasText: "Investigation unavailable"})).toContainText("test-error");
  await expect(page.getByRole("button", {name: "Retry investigation ↗"})).toBeEnabled();
});

test("abstention keeps absent metrics unavailable", async ({page}) => {
  await page.route("**/api/investigate", route => route.fulfill({json: {...fixture,
    answer: "Insufficient qualifying evidence.", insufficient_evidence: true, citations: [], retrieved_evidence_ids: [],
    facts: {...fixture.facts, case_count: null, ror: null, prr: null, cells: null, status: "insufficient_data", reason: "No comparison population."},
  }}));
  await page.goto("/");
  await page.getByLabel("Ask a drug-safety question").fill("semaglutide pancreatitis");
  await page.getByLabel("Ask a drug-safety question").press("Enter");
  await expect(page.getByText("Insufficient qualifying evidence", {exact: true})).toBeVisible();
  await expect(page.getByText("Unavailable", {exact: true})).toHaveCount(3);
});

test("DailyMed archived evidence opens its exact HTML version in a new tab", async ({page, context}) => {
  const url = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=ee06186f-2aa3-4990-a760-757579d8f77b&version=17";
  await context.route("https://dailymed.nlm.nih.gov/**", route => route.fulfill({
    contentType: "text/html", body: "<h1>Archived label version 17</h1>",
  }));
  await page.route("**/api/investigate", route => route.fulfill({json: {...fixture,
    citations: [{...fixture.citations[0], source_type: "dailymed", url}],
  }}));
  await page.goto("/");
  await page.getByLabel("Ask a drug-safety question").fill("semaglutide label pancreatitis");
  await page.getByLabel("Ask a drug-safety question").press("Enter");
  const popup = page.waitForEvent("popup");
  await page.getByRole("link", {name: /Open versioned source/}).click();
  const tab = await popup;
  await expect(tab).toHaveURL(url);
  await expect(tab.getByRole("heading")).toHaveText("Archived label version 17");
});
