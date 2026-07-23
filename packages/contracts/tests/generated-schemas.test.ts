import { readFile } from "node:fs/promises";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { validChatRequest, validSseEvents } from "./fixtures.js";

const readGeneratedSchema = async (fileName: string): Promise<object> =>
  JSON.parse(
    await readFile(new URL(`../generated/v1/${fileName}`, import.meta.url), "utf8"),
  ) as object;

const createAjv = () => {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  return ajv;
};

describe("generated JSON Schema artifacts", () => {
  it("validates valid and malformed chat request examples", async () => {
    const validate = createAjv().compile(await readGeneratedSchema("chat-request.schema.json"));
    const missingQuestion: Record<string, unknown> = { ...validChatRequest };
    delete missingQuestion.question;

    expect(validate(validChatRequest)).toBe(true);
    expect(validate(missingQuestion)).toBe(false);
  });

  it("validates every normalized SSE event", async () => {
    const validate = createAjv().compile(await readGeneratedSchema("chat-sse-event.schema.json"));

    for (const event of validSseEvents) {
      expect(validate(event), JSON.stringify(validate.errors)).toBe(true);
    }

    expect(validate({ ...validSseEvents[0], event: "unknown" })).toBe(false);
  });
});
