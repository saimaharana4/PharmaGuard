import assert from "node:assert/strict";
import {mkdtempSync, mkdirSync, writeFileSync, rmSync} from "node:fs";
import {createRequire} from "node:module";
import {tmpdir} from "node:os";
import {dirname, join, resolve} from "node:path";
import {ESLint} from "eslint";
import {afterAll, describe, expect, it} from "vitest";

const require = createRequire(import.meta.url);
const configRequire = createRequire(require.resolve("eslint-config-next"));
const pluginEntry = configRequire.resolve("@next/eslint-plugin-next");
const pluginRequire = createRequire(pluginEntry);
const {getRootDirs} = pluginRequire(join(dirname(pluginEntry), "utils/get-root-dirs.js"));
const prefix = join(tmpdir(), "pharmaguard-lint-");
const root = mkdtempSync(prefix);
const normalize = (path: string) => path.replace(/\\/g, "/");
for (const name of ["apps/clinical/pages", "apps/reviewer/pages", "tools/review"]) {
  mkdirSync(join(root, name), {recursive: true});
}
writeFileSync(join(root, "apps/clinical/pages/about.tsx"), "export default function About() {}");
writeFileSync(join(root, "apps/not-a-project.txt"), "not a directory");

afterAll(() => {
  assert.ok(resolve(root).startsWith(resolve(prefix)));
  rmSync(root, {recursive: true});
});

describe("Next lint dependency remediation", () => {
  it("loads the pinned replacement through Next's real dependency resolution", () => {
    expect(normalize(pluginRequire.resolve("fast-glob"))).toContain("tinyglobby@0.2.17");
    expect(typeof pluginRequire("fast-glob").globSync).toBe("function");
  });

  it("keeps default root discovery", () => {
    expect(getRootDirs({cwd: root, settings: {}})).toEqual([root]);
  });

  it("keeps wildcard root discovery and excludes matching files", () => {
    const actual = getRootDirs({cwd: root, settings: {next: {rootDir: `${root}/apps/*`}}});
    expect(actual.map((path: string) => normalize(resolve(path))).sort()).toEqual([
      normalize(join(root, "apps/clinical")), normalize(join(root, "apps/reviewer")),
    ].sort());
  });

  it("keeps multiple patterns, brace expansion and Windows separator normalization", () => {
    const actual = getRootDirs({cwd: root, settings: {next: {rootDir: [
      `${root}/apps/*`.replace(/\//g, "\\"), `${normalize(root)}/tools/{review,missing}`,
    ]}}});
    expect(actual.map((path: string) => normalize(resolve(path))).sort()).toEqual([
      normalize(join(root, "apps/clinical")), normalize(join(root, "apps/reviewer")),
      normalize(join(root, "tools/review")),
    ].sort());
  });

  it("still enforces Next internal-link and image rules through the full lint config", async () => {
    const lint = new ESLint({overrideConfig: {settings: {next: {rootDir: `${normalize(root)}/apps/{clinical,reviewer}`}}}});
    const [result] = await lint.lintText(
      'export default function Page(){return <><a href="/about">About</a><img src="/x.png" alt="x" /></>}',
      {filePath: "app/lint-security-fixture.tsx"},
    );
    expect(result.messages.map(m => m.ruleId)).toContain("@next/next/no-html-link-for-pages");
    expect(result.messages.map(m => m.ruleId)).toContain("@next/next/no-img-element");
  });

  it("accepts the correct Next Link implementation", async () => {
    const lint = new ESLint({overrideConfig: {settings: {next: {rootDir: `${normalize(root)}/apps/{clinical,reviewer}`}}}});
    const [result] = await lint.lintText(
      'import Link from "next/link"; export default function Page(){return <Link href="/about">About</Link>}',
      {filePath: "app/lint-security-fixture.tsx"},
    );
    expect(result.messages).toEqual([]);
  });
});
