import { z } from "zod";

import { CONTRACT_VERSION } from "./constants.js";

export const ContractVersionSchema = z.literal(CONTRACT_VERSION);

export const CursorPageInfoSchema = z.strictObject({
  next_cursor: z.string().min(1).max(512).nullable(),
  has_more: z.boolean(),
});

export const createCursorPageSchema = <ItemSchema extends z.ZodType>(item: ItemSchema) =>
  z.strictObject({
    contract_version: ContractVersionSchema,
    items: z.array(item),
    page: CursorPageInfoSchema,
  });

export type CursorPageInfo = z.infer<typeof CursorPageInfoSchema>;
