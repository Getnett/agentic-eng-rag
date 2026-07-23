import { z } from "zod";

import { ContractVersionSchema } from "./common.js";
import { RequestIdSchema } from "./identifiers.js";

export const PublicErrorCodeSchema = z.enum([
  "INVALID_REQUEST",
  "UNAUTHORIZED_WIDGET",
  "ORIGIN_NOT_ALLOWED",
  "RATE_LIMITED",
  "SERVICE_UNAVAILABLE",
  "INTERNAL_ERROR",
]);

export const PublicErrorSchema = z.strictObject({
  code: PublicErrorCodeSchema,
  message: z.string().min(1).max(500),
  retryable: z.boolean(),
});

export const PublicErrorEnvelopeSchema = z
  .strictObject({
    contract_version: ContractVersionSchema,
    request_id: RequestIdSchema,
    error: PublicErrorSchema,
  })
  .meta({ title: "Public error envelope" });

export const AdminErrorDetailSchema = z.strictObject({
  field: z.string().min(1).max(200).nullable(),
  reason: z.string().min(1).max(500),
});

export const AdminErrorSchema = z.strictObject({
  code: z
    .string()
    .min(1)
    .max(100)
    .regex(/^[A-Z][A-Z0-9_]*$/),
  message: z.string().min(1).max(1_000),
  retryable: z.boolean(),
  details: z.array(AdminErrorDetailSchema).max(50),
});

export const AdminErrorEnvelopeSchema = z
  .strictObject({
    contract_version: ContractVersionSchema,
    request_id: RequestIdSchema,
    error: AdminErrorSchema,
  })
  .meta({ title: "Authenticated admin error envelope" });

export type PublicErrorCode = z.infer<typeof PublicErrorCodeSchema>;
export type PublicError = z.infer<typeof PublicErrorSchema>;
export type PublicErrorEnvelope = z.infer<typeof PublicErrorEnvelopeSchema>;
export type AdminError = z.infer<typeof AdminErrorSchema>;
export type AdminErrorEnvelope = z.infer<typeof AdminErrorEnvelopeSchema>;
