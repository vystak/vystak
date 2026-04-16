import { describe, it, expect } from "vitest";
import { VERSION } from "../src/index.js";

describe("@vystak/provider-docker", () => {
  it("re-exports core version", () => {
    expect(VERSION).toBe("0.1.0");
  });
});
