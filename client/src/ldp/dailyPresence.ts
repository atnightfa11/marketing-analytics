// One privatized presence-today bit per UTC day, with memoization
// and a simple in-memory daily epsilon cap

import { rrBit } from './rr'

export type PresenceEnvelope = {
  kind: 'presence_day'
  site_id: string
  day: string         // YYYY-MM-DD in UTC
  bit: 0 | 1          // randomized response outcome
  epsilon_used: number
  sampling_rate: number
  ts_client: number   // ms since epoch
}

const memo = new Map<string, 0 | 1>()
let epsSpentToday = 0
let memoDay = utcDay()

function utcDay(d = new Date()): string {
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function rotateIfNewDay() {
  const d = utcDay()
  if (d !== memoDay) {
    memo.clear()
    epsSpentToday = 0
    memoDay = d
  }
}

export function sendDailyPresence(
  siteId: string,
  epsPerPresence: number,
  samplingRate: number,
  maxDailyEps: number,
  transport: (env: PresenceEnvelope) => void
) {
  rotateIfNewDay()
  if (epsSpentToday + epsPerPresence > maxDailyEps) return

  const key = `presence:${memoDay}`
  let bit: 0 | 1
  if (memo.has(key)) {
    bit = memo.get(key)!
  } else {
    bit = rrBit(1, epsPerPresence)
    memo.set(key, bit)
    epsSpentToday += epsPerPresence
  }

  transport({
    kind: 'presence_day',
    site_id: siteId,
    day: memoDay,
    bit,
    epsilon_used: epsPerPresence,
    sampling_rate: Math.max(0, Math.min(1, samplingRate)),
    ts_client: Date.now()
  })
}
