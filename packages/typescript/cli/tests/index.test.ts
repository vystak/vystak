import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@agentstack/cli", () => {
  it("re-exports core version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
