import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { buildJsonSchemaDocuments } from "../src/v1/json-schema.ts";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = resolve(packageRoot, "generated/v1");
const checkOnly = process.argv.includes("--check");
const documents = buildJsonSchemaDocuments();

await mkdir(outputDirectory, { recursive: true });

let stale = false;

for (const [fileName, document] of Object.entries(documents)) {
  const outputPath = resolve(outputDirectory, fileName);
  const serialized = `${JSON.stringify(document, null, 2)}\n`;

  if (checkOnly) {
    const current = await readFile(outputPath, "utf8").catch(() => null);
    if (current !== serialized) {
      console.error(`Generated contract is stale: generated/v1/${fileName}`);
      stale = true;
    }
  } else {
    await writeFile(outputPath, serialized, "utf8");
  }
}

if (stale) {
  process.exitCode = 1;
}
