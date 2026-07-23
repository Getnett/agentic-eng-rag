import { describe, expect, it } from "vitest";

import { ChatRequestSchema, MAX_CHAT_HISTORY_MESSAGES } from "../src/index.js";
import { validChatRequest } from "./fixtures.js";

describe("ChatRequestSchema", () => {
  it("accepts a valid versioned chat request", () => {
    expect(ChatRequestSchema.safeParse(validChatRequest).success).toBe(true);
  });

  it("rejects a request with a missing question", () => {
    const missingQuestion: Record<string, unknown> = { ...validChatRequest };
    delete missingQuestion.question;

    expect(ChatRequestSchema.safeParse(missingQuestion).success).toBe(false);
  });

  it("rejects history beyond the public limit", () => {
    const oversizedHistory = {
      ...validChatRequest,
      history: Array.from({ length: MAX_CHAT_HISTORY_MESSAGES + 1 }, () => ({
        role: "user",
        content: "Follow-up question",
      })),
    };

    expect(ChatRequestSchema.safeParse(oversizedHistory).success).toBe(false);
  });

  it("rejects unknown fields", () => {
    expect(
      ChatRequestSchema.safeParse({ ...validChatRequest, provider_api_key: "secret" }).success,
    ).toBe(false);
  });
});
