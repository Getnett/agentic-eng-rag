import { z } from "zod";

import { ChatRequestSchema } from "./chat.js";
import { CursorPageInfoSchema } from "./common.js";
import { AdminErrorEnvelopeSchema, PublicErrorEnvelopeSchema } from "./errors.js";
import { ChatSseEventSchema } from "./events.js";
import { InternalTraceContextSchema } from "./trace.js";

export const CONTRACT_SCHEMA_FILES = {
  "chat-request.schema.json": ChatRequestSchema,
  "chat-sse-event.schema.json": ChatSseEventSchema,
  "cursor-page-info.schema.json": CursorPageInfoSchema,
  "public-error-envelope.schema.json": PublicErrorEnvelopeSchema,
  "admin-error-envelope.schema.json": AdminErrorEnvelopeSchema,
  "internal-trace-context.schema.json": InternalTraceContextSchema,
} as const;

export const buildJsonSchemaDocuments = (): Readonly<Record<string, object>> =>
  Object.fromEntries(
    Object.entries(CONTRACT_SCHEMA_FILES).map(([fileName, schema]) => {
      const generated = z.toJSONSchema(schema, {
        target: "draft-2020-12",
        reused: "ref",
      });

      return [
        fileName,
        {
          $schema: "https://json-schema.org/draft/2020-12/schema",
          $id: `urn:rag-support:contracts:v1:${fileName}`,
          ...generated,
        },
      ];
    }),
  );
