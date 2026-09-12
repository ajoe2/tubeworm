const assert = require('node:assert/strict')
const { buildSync } = require('esbuild')
const { mkdtempSync, rmSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { join } = require('node:path')
const dir = mkdtempSync(join(tmpdir(), 'tubeworm-seek-test-'))
buildSync({ entryPoints: [join(__dirname, '../src/lib/seekQueue.ts')], outfile: join(dir, 'seek.cjs'), platform: 'node', format: 'cjs' })
const { SeekQueue } = require(join(dir, 'seek.cjs'))
let current = 0, settled = 0
const seeks = []
const player = {
  readyState: 2, seeking: false,
  get currentTime() { return current },
  set currentTime(value) {
    assert.equal(this.seeking, false, 'Must not interrupt an active decoder seek')
    this.seeking = true; current = value; seeks.push(value)
  },
}
const queue = new SeekQueue(player, () => settled++)
queue.request(1, true)
for (let i = 2; i <= 100; i++) queue.request(i)
assert.deepEqual(seeks, [1], 'Drag burst should not start concurrent seeks')
player.seeking = false
queue.flush(true)
assert.deepEqual(seeks, [1, 100], 'Release should seek directly to newest target')
player.seeking = false; queue.onSeeked()
assert.equal(settled, 1)
queue.request(100, true)
assert.equal(settled, 2, 'Playing from current frame must not wait for a nonexistent seeked event')
queue.dispose()
queue.request(20, true)
assert.deepEqual(seeks, [1, 100])
rmSync(dir, { recursive: true, force: true })
console.log('Seek queue: 100 rapid requests coalesced to 2 seeks; no decoder overlap; exact final target.')
