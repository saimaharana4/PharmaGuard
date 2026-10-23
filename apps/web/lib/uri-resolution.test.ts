import {createRequire} from "node:module";
import {describe, expect, it} from "vitest";

const require = createRequire(import.meta.url);
const eslintRequire = createRequire(require.resolve("eslint"));
const ajvEntry = eslintRequire.resolve("ajv");
const ajvRequire = createRequire(ajvEntry);
const Ajv = eslintRequire("ajv");

describe("lint schema URI resolution", () => {
  it("loads the pinned maintained resolver through the actual Ajv dependency", () => {
    expect(ajvRequire.resolve("uri-js").replace(/\\/g, "/")).toContain("fast-uri@4.2.2");
    for (const method of ["parse", "serialize", "resolve"]) {
      expect(typeof ajvRequire("uri-js")[method]).toBe("function");
    }
  });

  it("preserves relative, absolute and fragment schema references", () => {
    const ajv = new Ajv();
    ajv.addSchema({$id: "https://schemas.example.test/defs.json", definitions: {
      title: {type: "string", minLength: 2},
    }});
    const validate = ajv.compile({$id: "https://schemas.example.test/root.json", type: "object",
      definitions: {count: {type: "integer", minimum: 0}},
      required: ["title", "count"], additionalProperties: false,
      properties: {title: {$ref: "defs.json#/definitions/title"}, count: {$ref: "#/definitions/count"}},
    });
    expect(validate({title: "Safe", count: 2})).toBe(true);
    expect(validate({title: "x", count: -1})).toBe(false);
    expect(validate({title: "Safe", count: 2, extra: true})).toBe(false);
  });

  it("continues to reject invalid schemas and missing references", () => {
    const ajv = new Ajv();
    expect(() => ajv.compile({type: "invalid-type"})).toThrow();
    expect(() => ajv.compile({$ref: "https://missing.example.test/schema"})).toThrow();
  });
});
