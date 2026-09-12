const assert = require("node:assert/strict")
const { SeekQueue } = require("./load.cjs")("lib/seekQueue.ts")

let current = 0
let settled = 0
const seeks = []
const player = {
  readyState: 2,
  seeking: false,
  get currentTime() {
    return current
  },
  set currentTime(value) {
    assert.equal(this.seeking, false, "Must not interrupt an active decoder seek")
    this.seeking = true
    current = value
    seeks.push(value)
  },
}
const queue = new SeekQueue(player, () => settled++)
queue.request(1, true)
assert.equal(queue.seeking, true, "The queue owns the in-flight seek")
for (let i = 2; i <= 100; i++) queue.request(i)
assert.deepEqual(seeks, [1], "Drag burst should not start concurrent seeks")
player.seeking = false
queue.flush(true)
assert.deepEqual(seeks, [1, 100], "Release should seek directly to newest target")
player.seeking = false
queue.onSeeked()
assert.equal(settled, 1)
assert.equal(queue.seeking, false)
queue.request(100, true)
assert.equal(settled, 2, "Playing from current frame must not wait for a nonexistent seeked event")
queue.dispose()
queue.request(20, true)
assert.deepEqual(seeks, [1, 100])
console.log("seekQueue: 100 rapid requests coalesced to 2 seeks; no decoder overlap; exact final target.")
