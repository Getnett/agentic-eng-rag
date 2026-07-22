import { describe, expect, it } from "vitest";

import { ChatSseEventSchema } from "../src/index.js";
import { validSseEvents } from "./fixtures.js";

describe("ChatSseEventSchema", () => {
  it.each(validSseEvents)("accepts the $event event shape", (event) => {
    expect(ChatSseEventSchema.safeParse(event).success).toBe(true);
  });

  it("rejects an unknown event name", () => {
    expect(
      ChatSseEventSchema.safeParse({
        ...validSseEvents[0],
        event: "answer.finished",
      }).success,
    ).toBe(false);
  });

  it("rejects an error event containing internal details", () => {
    const errorEvent = validSseEvents.find((event) => event.event === "error");
    if (errorEvent?.event !== "error") {
      throw new Error("Error-event fixture is missing");
    }

    expect(
      ChatSseEventSchema.safeParse({
        ...errorEvent,
        data: {
          ...errorEvent.data,
          error: { ...errorEvent.data.error, stack: "internal stack" },
        },
      }).success,
    ).toBe(false);
  });
});
