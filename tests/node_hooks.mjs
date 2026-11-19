// Node resolver hook for the tests: map the bare specifier "three" to the vendored copy (the browser uses an import map).
import { pathToFileURL } from "node:url";
import { resolve as pathResolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const target = pathToFileURL(pathResolve(dirname(fileURLToPath(import.meta.url)), "../twin/web/vendor/three.module.js")).href;
export async function resolve(specifier, context, next) {
  if (specifier === "three") return { url: target, shortCircuit: true };
  return next(specifier, context);
}
