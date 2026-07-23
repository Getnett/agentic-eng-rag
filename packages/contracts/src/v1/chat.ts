import { z } from "zod";

import {
  MAX_CHAT_HISTORY_MESSAGES,
  MAX_CHAT_MESSAGE_CHARACTERS,
  MAX_QUESTION_CHARACTERS,
} from "./constants.js";
import { ContractVersionSchema } from "./common.js";

export const WidgetKeySchema = z
  .string()
  .min(16)
  .max(128)
  .regex(/^[A-Za-z0-9_-]+$/);

export const VisitorSessionIdSchema = z
  .string()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9_-]+$/);

export const ChatHistoryMessageSchema = z.strictObject({
  role: z.enum(["user", "assistant"]),
  content: z.string().min(1).max(MAX_CHAT_MESSAGE_CHARACTERS),
});

export const ChatRequestSchema = z
  .strictObject({
    contract_version: ContractVersionSchema,
    widget_key: WidgetKeySchema,
    visitor_session_id: VisitorSessionIdSchema,
    history: z.array(ChatHistoryMessageSchema).max(MAX_CHAT_HISTORY_MESSAGES),
    question: z.string().min(1).max(MAX_QUESTION_CHARACTERS),
  })
  .meta({ title: "Chat request" });

export type ChatHistoryMessage = z.infer<typeof ChatHistoryMessageSchema>;
export type ChatRequest = z.infer<typeof ChatRequestSchema>;
