import { describe, expect, it } from "vitest";

import { fileToBase64 } from "../../src/lib/api";

describe("fileToBase64", () => {
  it("encodes text file content", async () => {
    const file = new File(["hello"], "sample.txt", { type: "text/plain" });
    const result = await fileToBase64(file);

    expect(result).toBe("aGVsbG8=");
  });
});
