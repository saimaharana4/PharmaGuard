import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  reporter: [["list"], ["html", {open: "never"}], ["junit", {outputFile: "test-results/playwright-junit.xml", includeProjectInTestName: true}]],
  use: {baseURL: "http://127.0.0.1:3000", trace: "retain-on-failure"},
  webServer: {command: "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1", url: "http://127.0.0.1:3000", reuseExistingServer: !process.env.CI, timeout: 120000},
  projects: [
    {name: "desktop", use: {...devices["Desktop Chrome"]}},
    {name: "mobile", use: {...devices["Pixel 7"]}},
  ],
});
