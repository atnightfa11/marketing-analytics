// Minimal SDK surface that uses the collector and daily presence
import { sendDailyPresence, PresenceEnvelope } from './ldp/dailyPresence'
import { setupFlush, enqueue } from './collector/eventCollector'

type Config = {
  siteId: string
  origin: string
  uploadToken: string
  endpoint: string
  epsPresence?: number
  maxDailyEps?: number
  samplingRate?: number
}

let cfg: Config
let flusher: { flush: () => void } | null = null
let debug = false

export function enableDebug(on = true) {
  debug = on
}

export function configure(c: Config) {
  cfg = {
    epsPresence: 0.5,
    maxDailyEps: 1.0,
    samplingRate: 1.0,
    ...c
  }
  flusher = setupFlush({
    siteId: cfg.siteId,
    origin: cfg.origin,
    uploadToken: cfg.uploadToken,
    endpoint: cfg.endpoint
  })
  if (debug) console.log('[ldp] configured', { site: cfg.siteId })
}

export function sendPresence() {
  if (!cfg) return
  sendDailyPresence(
    cfg.siteId,
    cfg.epsPresence!,
    cfg.samplingRate!,
    cfg.maxDailyEps!,
    (env: PresenceEnvelope) => enqueue(env)
  )
}

export function flush() {
  if (flusher) flusher.flush()
}
