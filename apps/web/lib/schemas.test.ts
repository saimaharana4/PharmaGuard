import { describe, expect, it } from "vitest";
import { responseSchema, sourceUrl } from "./schemas";

describe("source links", () => {
  it("accepts only canonical source HTTPS hosts", () => {
    expect(sourceUrl("https://pubmed.ncbi.nlm.nih.gov/123/")).toBeTruthy();
    expect(sourceUrl("javascript:alert(1)")).toBeNull();
    expect(sourceUrl("https://pubmed.ncbi.nlm.nih.gov.evil.example/123")).toBeNull();
    expect(sourceUrl("http://pubmed.ncbi.nlm.nih.gov/")).toBeNull();
  });
  it("rejects incomplete investigation responses", () => {
    expect(responseSchema.safeParse({answer: "unsupported"}).success).toBe(false);
  });
});
