// Prints, for each text in the JSON file given as argument 1, what parseTime reads (seconds, or null), and
// for each number of milliseconds in argument 2 what formatTime writes.
import { formatTime, parseTime } from "../../app/static/clip_time.js";
import { readFileSync } from "node:fs";
const texts = JSON.parse(readFileSync(process.argv[2], "utf8"));
const millis = JSON.parse(readFileSync(process.argv[3], "utf8"));
console.log(JSON.stringify({ parsed: texts.map(parseTime), formatted: millis.map((ms) => formatTime(ms / 1000)) }));
