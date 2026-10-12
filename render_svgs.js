"use strict";

const fs = require("fs");
const path = require("path");
const sharp = require("C:/Users/86131/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp");

async function main() {
  const out = path.join(__dirname, "output");
  for (const name of ["workflow", "design_distribution", "capacity_value_curve"]) {
    const source = path.join(out, `${name}.svg`);
    const target = path.join(out, `${name}.png`);
    await sharp(fs.readFileSync(source)).resize({ width: 2200 }).png().toFile(target);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
