import { describe, expect, it } from "vitest";

import {
  AdminErrorEnvelopeSchema,
  CursorPageInfoSchema,
  InternalTraceContextSchema,
  PublicErrorEnvelopeSchema,
} from "../src/index.js";
import { ids } from "./fixtures.js";

describe("shared contract schemas", () => {
  it("keeps public errors generic", () => {
    const publicError = {
      contract_version: "v1",
      request_id: ids.request,
      error: {
        code: "INVALID_REQUEST",
        message: "The request is invalid.",
        retryable: false,
      },
    };

    expect(PublicErrorEnvelopeSchema.safeParse(publicError).success).toBe(true);
    expect(
      PublicErrorEnvelopeSchema.safeParse({
        ...publicError,
        error: { ...publicError.error, details: [{ field: "question", reason: "missing" }] },
      }).success,
    ).toBe(false);
  });

  it("allows bounded field details for authenticated admin errors", () => {
    expect(
      AdminErrorEnvelopeSchema.safeParse({
        contract_version: "v1",
        request_id: ids.request,
        error: {
          code: "SOURCE_VALIDATION_FAILED",
          message: "The source could not be validated.",
          retryable: false,
          details: [{ field: "url", reason: "Only public HTTPS URLs are supported." }],
        },
      }).success,
    ).toBe(true);
  });

  it("defines cursor pagination", () => {
    expect(
      CursorPageInfoSchema.safeParse({ next_cursor: "next-page", has_more: true }).success,
    ).toBe(true);
  });

  it("requires model-profile and source-version IDs in internal trace context", () => {
    expect(
      InternalTraceContextSchema.safeParse({
        contract_version: "v1",
        request_id: ids.request,
        conversation_id: ids.conversation,
        model_profile_id: ids.modelProfile,
        source_version_ids: [ids.sourceVersion],
        retrieved_chunk_ids: [ids.chunk],
      }).success,
    ).toBe(true);

    expect(
      InternalTraceContextSchema.safeParse({
        contract_version: "v1",
        request_id: ids.request,
        conversation_id: null,
        source_version_ids: [ids.sourceVersion],
        retrieved_chunk_ids: [],
      }).success,
    ).toBe(false);
  });
});
