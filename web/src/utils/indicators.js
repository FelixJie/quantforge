// 技术指标计算（前端统一计算，适配任意周期的 OHLCV bars）
// bars: [{ datetime|date, open, close, high, low, volume }]

export function closes(bars) { return bars.map(b => b.close) }
export function highs(bars)  { return bars.map(b => b.high) }
export function lows(bars)   { return bars.map(b => b.low) }
export function vols(bars)   { return bars.map(b => b.volume) }

export function MA(data, period) {
  const out = new Array(data.length).fill(null)
  let sum = 0
  for (let i = 0; i < data.length; i++) {
    sum += data[i]
    if (i >= period) sum -= data[i - period]
    if (i >= period - 1) out[i] = +(sum / period).toFixed(3)
  }
  return out
}

export function EMA(data, period) {
  const out = new Array(data.length).fill(null)
  const k = 2 / (period + 1)
  let prev = null
  for (let i = 0; i < data.length; i++) {
    const v = data[i]
    if (v == null) continue
    prev = prev == null ? v : v * k + prev * (1 - k)
    out[i] = +prev.toFixed(3)
  }
  return out
}

// 布林带
export function BOLL(data, period = 20, k = 2) {
  const mid = MA(data, period)
  const upper = new Array(data.length).fill(null)
  const lower = new Array(data.length).fill(null)
  for (let i = period - 1; i < data.length; i++) {
    const slice = data.slice(i - period + 1, i + 1)
    const mean = mid[i]
    const variance = slice.reduce((s, v) => s + (v - mean) ** 2, 0) / period
    const std = Math.sqrt(variance)
    upper[i] = +(mean + k * std).toFixed(3)
    lower[i] = +(mean - k * std).toFixed(3)
  }
  return { mid, upper, lower }
}

// MACD: dif/dea/hist
export function MACD(data, fast = 12, slow = 26, signal = 9) {
  const emaFast = EMA(data, fast)
  const emaSlow = EMA(data, slow)
  const dif = data.map((_, i) =>
    emaFast[i] != null && emaSlow[i] != null ? +(emaFast[i] - emaSlow[i]).toFixed(4) : null)
  const difClean = dif.map(v => v == null ? 0 : v)
  const dea = EMA(difClean, signal)
  const hist = dif.map((v, i) => v != null && dea[i] != null ? +((v - dea[i]) * 2).toFixed(4) : null)
  return { dif, dea, hist }
}

// KDJ
export function KDJ(bars, n = 9, m1 = 3, m2 = 3) {
  const c = closes(bars), h = highs(bars), l = lows(bars)
  const k = new Array(bars.length).fill(null)
  const d = new Array(bars.length).fill(null)
  const j = new Array(bars.length).fill(null)
  let pk = 50, pd = 50
  for (let i = 0; i < bars.length; i++) {
    const lo = Math.min(...l.slice(Math.max(0, i - n + 1), i + 1))
    const hi = Math.max(...h.slice(Math.max(0, i - n + 1), i + 1))
    const rsv = hi === lo ? 0 : ((c[i] - lo) / (hi - lo)) * 100
    pk = (pk * (m1 - 1) + rsv) / m1
    pd = (pd * (m2 - 1) + pk) / m2
    k[i] = +pk.toFixed(2); d[i] = +pd.toFixed(2); j[i] = +(3 * pk - 2 * pd).toFixed(2)
  }
  return { k, d, j }
}

// RSI
export function RSI(data, period = 14) {
  const out = new Array(data.length).fill(null)
  if (data.length < period + 1) return out
  let gain = 0, loss = 0
  for (let i = 1; i <= period; i++) {
    const diff = data[i] - data[i - 1]
    if (diff >= 0) gain += diff; else loss -= diff
  }
  let ag = gain / period, al = loss / period
  out[period] = al === 0 ? 100 : +(100 - 100 / (1 + ag / al)).toFixed(2)
  for (let i = period + 1; i < data.length; i++) {
    const diff = data[i] - data[i - 1]
    ag = (ag * (period - 1) + (diff > 0 ? diff : 0)) / period
    al = (al * (period - 1) + (diff < 0 ? -diff : 0)) / period
    out[i] = al === 0 ? 100 : +(100 - 100 / (1 + ag / al)).toFixed(2)
  }
  return out
}

// SAR（抛物线转向，简化版）
export function SAR(bars, step = 0.02, max = 0.2) {
  const out = new Array(bars.length).fill(null)
  if (!bars.length) return out
  let up = true
  let af = step
  let ep = bars[0].high
  let sar = bars[0].low
  out[0] = +sar.toFixed(3)
  for (let i = 1; i < bars.length; i++) {
    sar = sar + af * (ep - sar)
    if (up) {
      if (bars[i].low < sar) { up = false; sar = ep; ep = bars[i].low; af = step }
      else {
        if (bars[i].high > ep) { ep = bars[i].high; af = Math.min(af + step, max) }
        sar = Math.min(sar, bars[i - 1].low, bars[i].low)
      }
    } else {
      if (bars[i].high > sar) { up = true; sar = ep; ep = bars[i].high; af = step }
      else {
        if (bars[i].low < ep) { ep = bars[i].low; af = Math.min(af + step, max) }
        sar = Math.max(sar, bars[i - 1].high, bars[i].high)
      }
    }
    out[i] = +sar.toFixed(3)
  }
  return out
}
