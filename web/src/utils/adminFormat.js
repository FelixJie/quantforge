// 管理后台通用格式化助手。集中在此，避免各视图/组件重复定义。

/** 大数压缩：1234 → 1.2K，1200000 → 1.20M。 */
export function fmtK(n) {
  n = n || 0
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

/** 取日期部分：'2026-06-16T10:20:30' → '2026-06-16'。 */
export function fmtDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 10)
}

/** 取「月-日 时:分:秒」：'2026-06-16T10:20:30' → '06-16 10:20:30'。 */
export function fmtTime(s) {
  if (!s) return '—'
  return String(s).replace('T', ' ').slice(5, 19)
}

/** 美元金额，默认 4 位小数。 */
export function fmtUsd(n, digits = 4) {
  return '$' + (Number(n) || 0).toFixed(digits)
}

/**
 * 把数值序列转成内联 SVG sparkline 的 polyline points 字符串。
 * @param {number[]} values 数据点
 * @param {number} w 视图宽
 * @param {number} h 视图高
 * @returns {{ pts: string, area: string, max: number, last: number }}
 */
export function sparkline(values, w = 120, h = 32) {
  const v = (values || []).map(x => Number(x) || 0)
  if (!v.length) return { pts: '', area: '', max: 0, last: 0 }
  const max = Math.max(1, ...v)
  const n = v.length
  const x = i => (n === 1 ? w / 2 : (i / (n - 1)) * w)
  const y = val => h - 2 - (val / max) * (h - 4)
  const pts = v.map((val, i) => `${x(i).toFixed(1)},${y(val).toFixed(1)}`).join(' ')
  const area = `0,${h} ${pts} ${w},${h}`
  return { pts, area, max, last: v[v.length - 1] }
}
