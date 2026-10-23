import { defineConfig } from "vitest/config";
export default defineConfig({test: {
  include: ["lib/**/*.test.ts"],
  reporters: ["default", "junit"],
  outputFile: {junit: "unit-test-results/vitest-junit.xml"},
}});
