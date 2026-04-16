import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";
import { execFileSync } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

describe("vystak", () => {
  it("exports version", () => {
    expect(VERSION).toBe("0.0.1");
  });

  it("prints hello vystak", () => {
    const cli = resolve(__dirname, "../dist/cli.js");
    const output = execFileSync("node", [cli], { encoding: "utf-8" }).trim();
    expect(output).toBe(`hello vystak v${VERSION}`);
  });
});
