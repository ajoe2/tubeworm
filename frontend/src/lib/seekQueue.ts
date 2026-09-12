/** Serialize decoder seeks; keep only the newest target while a seek is active. */
export class SeekQueue {
  private pending: number | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private lastSeek = -Infinity
  private inFlight = false
  private disposed = false
  constructor(
    private player: HTMLVideoElement,
    private settled: () => void,
  ) {}
  /** A seek is queued or the decoder is still seeking. */
  get busy() {
    return this.pending != null || this.player.seeking
  }
  /** The current decoder seek was started by this queue (not by the user). */
  get seeking() {
    return this.inFlight
  }
  request(time: number, immediate = false) {
    this.pending = time
    this.flush(immediate)
  }
  flush(immediate = false) {
    if (
      this.disposed ||
      this.pending == null ||
      this.player.readyState === 0 ||
      this.player.seeking
    )
      return
    if (this.timer) {
      clearTimeout(this.timer)
      this.timer = null
    }
    const delay = immediate
      ? 0
      : Math.max(0, 100 - (performance.now() - this.lastSeek))
    if (delay) {
      this.timer = setTimeout(() => {
        this.timer = null
        this.flush()
      }, delay)
      return
    }
    const time = this.pending
    this.pending = null
    if (Math.abs(this.player.currentTime - time) < 0.001) {
      this.settled()
      return
    }
    this.lastSeek = performance.now()
    this.inFlight = true
    this.player.currentTime = time
  }
  onSeeked() {
    this.inFlight = false
    if (this.pending != null) this.flush()
    else this.settled()
  }
  dispose() {
    this.disposed = true
    if (this.timer) clearTimeout(this.timer)
  }
}
