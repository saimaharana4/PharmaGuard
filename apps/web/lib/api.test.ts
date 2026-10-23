import { afterEach, expect, test, vi } from "vitest";
import { renewSession } from "./api";

afterEach(() => vi.unstubAllGlobals());

test("overlapping startup and submission share one session cookie renewal", async () => {
  let complete!: (value: Response) => void;
  const fetch = vi.fn(() => new Promise<Response>(resolve => {complete = resolve;}));
  vi.stubGlobal("fetch", fetch);
  const startup = renewSession();
  const submission = renewSession();
  expect(fetch).toHaveBeenCalledTimes(1);
  complete(Response.json({enabled: true, history: [{question: "prior", answer: "context"}]}));
  expect(await startup).toEqual(await submission);
});

test("a failed session renewal permits a fresh retry", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(Response.json({enabled: false}));
  vi.stubGlobal("fetch", fetch);
  await expect(renewSession()).rejects.toThrow("offline");
  await expect(renewSession()).resolves.toEqual([]);
  expect(fetch).toHaveBeenCalledTimes(2);
});
