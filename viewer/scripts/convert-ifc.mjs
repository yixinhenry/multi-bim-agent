import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { IfcImporter } from "@thatopen/fragments";

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  throw new Error("Usage: node convert-ifc.mjs <input.ifc> <output.frag>");
}
const viewerDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const importer = new IfcImporter();
importer.wasm.path = `${resolve(viewerDir, "node_modules", "web-ifc")}${sep}`;
importer.wasm.absolute = true;
// Discipline models must retain the same project coordinate system so ARC, STR,
// and MEP remain aligned when loaded into one federated world.
importer.webIfcSettings.COORDINATE_TO_ORIGIN = false;
const bytes = new Uint8Array(await readFile(resolve(inputPath)));
const fragments = await importer.process({ bytes, raw: false });
await writeFile(resolve(outputPath), fragments);
