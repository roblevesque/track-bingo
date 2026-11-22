// Prints parseFooter(text) for each text in the JSON array given as the first argument.
import { parseFooter } from "../../app/static/footer_md.js";
import { readFileSync } from "node:fs";
const texts = JSON.parse(readFileSync(process.argv[2], "utf8"));
console.log(JSON.stringify(texts.map((t) => parseFooter(t))));
