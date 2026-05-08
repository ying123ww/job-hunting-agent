import { afterEach, describe, expect, it, vi } from "vitest";

import { api, fileToBase64 } from "../../src/lib/api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fileToBase64", () => {
  it("encodes text file content", async () => {
    const file = {
      arrayBuffer: async () => new TextEncoder().encode("hello").buffer,
    } as File;
    const result = await fileToBase64(file);

    expect(result).toBe("aGVsbG8=");
  });
});

describe("resume api helpers", () => {
  it("requests resume source", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        source: "\\documentclass{article}",
        last_saved_at: null,
        last_compiled_at: null,
        last_compile_status: "not_run",
        last_compile_error_summary: null,
        last_resume_document_id: null,
        compiler_available: false,
        pdf_exists: false,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.getResumeSource();

    expect(response.source).toContain("\\documentclass");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/resume/source", expect.any(Object));
  });

  it("requests resume compile log as text", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => "compile output",
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await api.getResumeCompileLog();

    expect(response).toBe("compile output");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/resume/compile-log", expect.any(Object));
  });
});
