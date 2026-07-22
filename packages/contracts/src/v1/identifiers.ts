import { z } from "zod";

export const RequestIdSchema = z.uuid().meta({ title: "Request ID" });
export const EventIdSchema = z.uuid().meta({ title: "SSE event ID" });
export const ConversationIdSchema = z.uuid().meta({ title: "Conversation ID" });
export const MessageIdSchema = z.uuid().meta({ title: "Message ID" });
export const CitationIdSchema = z.uuid().meta({ title: "Citation ID" });
export const DocumentIdSchema = z.uuid().meta({ title: "Document ID" });
export const ChunkIdSchema = z.uuid().meta({ title: "Chunk ID" });
export const ModelProfileIdSchema = z.uuid().meta({ title: "Model profile ID" });
export const SourceVersionIdSchema = z.uuid().meta({ title: "Source version ID" });

export type RequestId = z.infer<typeof RequestIdSchema>;
export type EventId = z.infer<typeof EventIdSchema>;
export type ConversationId = z.infer<typeof ConversationIdSchema>;
export type MessageId = z.infer<typeof MessageIdSchema>;
export type CitationId = z.infer<typeof CitationIdSchema>;
export type DocumentId = z.infer<typeof DocumentIdSchema>;
export type ChunkId = z.infer<typeof ChunkIdSchema>;
export type ModelProfileId = z.infer<typeof ModelProfileIdSchema>;
export type SourceVersionId = z.infer<typeof SourceVersionIdSchema>;
