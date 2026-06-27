import { ref, watch } from 'vue'

/**
 * 把一个 ref 的值自动持久化到 localStorage，刷新/崩溃恢复后自动还原。
 *
 * 用法（替换普通 ref 即可）：
 *   const search = usePersistentRef('reports:search', '')
 *   const page   = usePersistentRef('reports:page', 1)
 *
 * @param {string} key      存储键（建议带页面前缀，如 'reports:filters'，自动加 'qf:' 命名空间）
 * @param {*}      initial  默认值（无缓存或缓存失效时使用）
 * @param {object} [opts]
 * @param {number} [opts.ttl]      过期毫秒数，超过则忽略缓存用默认值（0=永不过期）
 * @param {string} [opts.version]  结构版本号，改了它旧缓存自动作废（默认 '1'）
 * @returns {import('vue').Ref}
 */
export function usePersistentRef(key, initial, opts = {}) {
  const { ttl = 0, version = '1' } = opts
  const storageKey = `qf:${key}`

  let start = initial
  try {
    const raw = localStorage.getItem(storageKey)
    if (raw) {
      const o = JSON.parse(raw)
      const fresh = !ttl || (Date.now() - (o.t || 0) < ttl)
      if (o && o.v === version && fresh && 'd' in o) start = o.d
    }
  } catch { /* 缓存损坏：退回默认值 */ }

  const r = ref(start)
  watch(r, (val) => {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ v: version, t: Date.now(), d: val }))
    } catch { /* 配额满/隐私模式：静默放弃持久化 */ }
  }, { deep: true })

  return r
}
