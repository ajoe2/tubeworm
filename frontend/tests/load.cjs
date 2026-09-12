// Bundle one TypeScript module from src/ for use in a Node test.
const { buildSync } = require("esbuild")
const { mkdtempSync } = require("node:fs")
const { tmpdir } = require("node:os")
const { join } = require("node:path")

module.exports = function load(relative) {
  const dir = mkdtempSync(join(tmpdir(), "tubeworm-test-"))
  const outfile = join(dir, "module.cjs")
  buildSync({ entryPoints: [join(__dirname, "../src", relative)], outfile, platform: "node", format: "cjs" })
  return require(outfile)
}
