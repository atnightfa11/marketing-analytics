// 3-minute window buffer, graceful no-op if backend unreachable,
// exponential backoff, circuit breaker, and POST to /api/shuffle

import type { PresenceEnvelope } from '../ldp/dailyPresence'

type Config = {
  siteId: string
  origin: string
  uploadToken: string
  endpoint: string            // e.g., https://api.yourdomain.com/api/shuffle
  backoffBaseMs?: number
}

const state = {
  queue: [] as PresenceEnvelope[],
  sending: false,
  failures: 0,
  breakerOpenUntil: 0
}

const BACKOFF_BASE = 500

export function enqueue(env: PresenceEnvelope) {
  state.queue.push(env)
}

export function setupFlush(config: Config) {
  const backoffBase = config.backoffBaseMs ?? BACKOFF_BASE

  async function flush() {
    if (state.sending) return
    if (Date.now() < state.breakerOpenUntil) return
    if (state.queue.length === 0) return

    state.sending = true
    const batch = state.queue.splice(0, state.queue.length)
    try {
      const res = await fetch(config.endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.uploadToken}`,
          'X-Site-ID': config.siteId,
          'X-Origin': config.origin
        },
        body: JSON.stringify(batch)
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      state.failures = 0
    } catch {
      // Put back into the head of the queue
      state.queue = batch.concat(state.queue)
      state.failures += 1
      if (state.failures >= 10) {
        state.breakerOpenUntil = Date.now() + 5 * 60 * 1000
      }
      const wait = backoffBase * 2 ** Math.min(6, state.failures - 1)
      setTimeout(flush, wait)
    } finally {
      state.sending = false
    }
  }

  // Windowed flush every 3 minutes
  setInterval(flush, 3 * 60 * 1000)
  // Flush on tab hide or unload
  const go = () => flush()
  document.addEventListener('visibilitychange', go)
  window.addEventListener('beforeunload', go)

  return { flush }
}
