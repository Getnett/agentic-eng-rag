import { z } from "zod";

import { ContractVersionSchema } from "./common.js";
import { PublicErrorSchema } from "./errors.js";
import {
  CitationIdSchema,
  ConversationIdSchema,
  DocumentIdSchema,
  EventIdSchema,
  MessageIdSchema,
  RequestIdSchema,
} from "./identifiers.js";

const commonDataFields = {
  contract_version: ContractVersionSchema,
  request_id: RequestIdSchema,
};

export const AnswerDeltaEventSchema = z.strictObject({
  event: z.literal("answer.delta"),
  id: EventIdSchema,
  data: z.strictObject({
    ...commonDataFields,
    text: z.string().min(1).max(8_192),
  }),
});

export const CitationEventSchema = z.strictObject({
  event: z.literal("citation"),
  id: EventIdSchema,
  data: z.strictObject({
    ...commonDataFields,
    citation_id: CitationIdSchema,
    document_id: DocumentIdSchema,
    document_title: z.string().min(1).max(300),
    source_url: z.url().nullable(),
    page_number: z.number().int().positive().nullable(),
    heading: z.string().min(1).max(500).nullable(),
  }),
});

export const SupportHandoffSchema = z.strictObject({
  label: z.string().min(1).max(200),
  url: z.url().nullable(),
  email: z.email().nullable(),
});

export const AbstentionEventSchema = z.strictObject({
  event: z.literal("abstention"),
  id: EventIdSchema,
  data: z.strictObject({
    ...commonDataFields,
    reason: z.literal("insufficient_evidence"),
    message: z.string().min(1).max(500),
    handoff: SupportHandoffSchema.nullable(),
  }),
});

export const CompleteEventSchema = z.strictObject({
  event: z.literal("complete"),
  id: EventIdSchema,
  data: z.strictObject({
    ...commonDataFields,
    status: z.enum(["answered", "abstained"]),
    conversation_id: ConversationIdSchema,
    message_id: MessageIdSchema,
  }),
});

export const ErrorEventSchema = z.strictObject({
  event: z.literal("error"),
  id: EventIdSchema,
  data: z.strictObject({
    ...commonDataFields,
    error: PublicErrorSchema,
  }),
});

export const ChatSseEventSchema = z
  .discriminatedUnion("event", [
    AnswerDeltaEventSchema,
    CitationEventSchema,
    AbstentionEventSchema,
    CompleteEventSchema,
    ErrorEventSchema,
  ])
  .meta({ title: "Normalized chat SSE event" });

export type AnswerDeltaEvent = z.infer<typeof AnswerDeltaEventSchema>;
export type CitationEvent = z.infer<typeof CitationEventSchema>;
export type AbstentionEvent = z.infer<typeof AbstentionEventSchema>;
export type CompleteEvent = z.infer<typeof CompleteEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
export type ChatSseEvent = z.infer<typeof ChatSseEventSchema>;
