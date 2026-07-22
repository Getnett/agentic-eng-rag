import { z } from "zod";

import { ContractVersionSchema } from "./common.js";
import {
  ChunkIdSchema,
  ConversationIdSchema,
  ModelProfileIdSchema,
  RequestIdSchema,
  SourceVersionIdSchema,
} from "./identifiers.js";

export const InternalTraceContextSchema = z
  .strictObject({
    contract_version: ContractVersionSchema,
    request_id: RequestIdSchema,
    conversation_id: ConversationIdSchema.nullable(),
    model_profile_id: ModelProfileIdSchema,
    source_version_ids: z.array(SourceVersionIdSchema).max(100),
    retrieved_chunk_ids: z.array(ChunkIdSchema).max(100),
  })
  .meta({ title: "Internal trace context" });

export type InternalTraceContext = z.infer<typeof InternalTraceContextSchema>;
