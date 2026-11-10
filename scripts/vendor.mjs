import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("static/vendor", { recursive: true });
copyFileSync("node_modules/htmx.org/dist/htmx.min.js", "static/vendor/htmx.min.js");
copyFileSync("node_modules/htmx.org/LICENSE", "static/vendor/HTMX-LICENSE.txt");

