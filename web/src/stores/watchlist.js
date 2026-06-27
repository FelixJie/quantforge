import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import axios from 'axios'
import { useAuthStore } from './auth'

export const useWatchlistStore = defineStore('watchlist', () => {
  // 自选股列表（服务端按账户存储）
  const watchlist = ref([])
  // 自选股验证记录（本地，按账户命名空间隔离）
  const watchlistVerifications = ref([])
  // 实时行情数据
  const realtimeData = ref({})
  // 主力资金流(单独异步拉取，push2 间歇失败不阻塞主行情)；字段并入 realtimeData 供列/排序复用
  const fundFlowData = ref({})
  // AI 诊断评分(按需触发，code -> {score,rating,comment,asof})
  const aiDiag = ref({})
  const aiDiagLoading = ref(false)
  // 迷你图表数据
  const miniChartData = ref({})
  // 迷你图昨收基准价(分时图基准线/着色)
  const miniChartPre = ref({})
  // 上证指数数据（兼容旧用法）
  const shIndex = ref(null)
  // 主要指数（上证/深成/创业板 等）— 顶部指数条
  const indices = ref([])

  const loading = ref(false)
  const searching = ref(false)
  const error = ref(null)
  const searchResults = ref([])
  const refreshing = ref(false)
  const loaded = ref(false)
  // 标签
  const tags = ref([])
  let _autoTimer = null

  const auth = useAuthStore()

  // ── 手动排序持久化（按账户存 localStorage，避免后端迁移）─────────────────
  function _orderKey() { return `wl_order_${auth.user?.id || 'anon'}` }
  function _loadOrder() {
    try { return JSON.parse(localStorage.getItem(_orderKey()) || '[]') } catch { return [] }
  }
  function _saveOrder(codes) {
    try { localStorage.setItem(_orderKey(), JSON.stringify(codes)) } catch { /* ignore */ }
  }
  function _persistCurrentOrder() { _saveOrder(watchlist.value.map(s => s.code)) }
  function _applyOrder() {
    const order = _loadOrder()
    if (!order.length) return
    const idx = new Map(order.map((c, i) => [c, i]))
    watchlist.value.sort((a, b) =>
      (idx.has(a.code) ? idx.get(a.code) : Infinity) -
      (idx.has(b.code) ? idx.get(b.code) : Infinity))
  }
  // 按给定 code 顺序重排并持久化
  function reorderWatchlist(codes) {
    const pos = new Map(codes.map((c, i) => [c, i]))
    watchlist.value.sort((a, b) =>
      (pos.has(a.code) ? pos.get(a.code) : Infinity) -
      (pos.has(b.code) ? pos.get(b.code) : Infinity))
    _persistCurrentOrder()
  }

  // ── 验证记录（服务端按账户存储）─────────────────────────────────────────
  async function loadVerifications() {
    if (!auth.token) { watchlistVerifications.value = []; return }
    try {
      const res = await axios.get('/api/watchlist/verifications')
      watchlistVerifications.value = res.data || []
    } catch (e) {
      if (e.response?.status !== 401) console.error('Failed to load verifications:', e)
    }
  }
  // 兼容旧的对外名（不再用 localStorage）
  function loadFromStorage() { loadVerifications() }
  function saveToStorage() {}

  // ── 自选股（服务端 API）────────────────────────────────────────────────
  async function loadWatchlist() {
    if (!auth.token) { watchlist.value = []; return }
    loading.value = true
    try {
      const res = await axios.get('/api/watchlist/overview')
      const items = res.data.items || []
      watchlist.value = items.map(it => ({
        code: it.code, name: it.name, added_at: it.added_at,
        notes: it.notes || '', tags: it.tags || [],
        color: it.color || '', cost_price: it.cost_price ?? null, shares: it.shares ?? null,
        reports: it.reports || null,
      }))
      // 同步实时行情
      const rt = {}
      for (const it of items) {
        if (it.price != null || it.change_pct != null) {
          rt[it.code] = {
            price: it.price, change_pct: it.change_pct, change: it.change,
            open: it.open, high: it.high, low: it.low, pre_close: it.pre_close,
            turnover: it.turnover, pe: it.pe, pb: it.pb,
            turnover_rate: it.turnover_rate,
            amplitude: it.amplitude, vol_ratio: it.vol_ratio,
            market_cap: it.market_cap, float_market_cap: it.float_market_cap,
            limit_up: it.limit_up, limit_down: it.limit_down,
            // 资金流字段(上一轮已拉到的，避免轮询覆盖后丢失)
            ...(fundFlowData.value[it.code] || {}),
          }
        }
      }
      realtimeData.value = rt
      _applyOrder()
      loaded.value = true
    } catch (e) {
      if (e.response?.status !== 401) console.error('Failed to load watchlist:', e)
    } finally {
      loading.value = false
    }
  }

  async function addToWatchlist(stock) {
    if (!stock?.code) return false
    if (watchlist.value.some(s => s.code === stock.code)) return false
    try {
      await axios.post('/api/watchlist/', { code: stock.code, name: stock.name || '' })
      watchlist.value.push({
        code: stock.code, name: stock.name || stock.code,
        added_at: new Date().toISOString(), notes: '', tags: [],
      })
      _persistCurrentOrder()
      searchResults.value = []
      return true
    } catch (e) {
      console.error('Failed to add to watchlist:', e)
      return false
    }
  }

  async function removeFromWatchlist(code) {
    try {
      await axios.delete(`/api/watchlist/${code}`)
    } catch (e) {
      if (e.response?.status !== 404) {
        console.error('Failed to remove from watchlist:', e)
        return
      }
    }
    watchlist.value = watchlist.value.filter(s => s.code !== code)
    delete realtimeData.value[code]
    _persistCurrentOrder()
  }

  // 批量移除（用于多选删除）
  async function batchRemove(codes) {
    const set = new Set(codes)
    await Promise.all([...set].map(c =>
      axios.delete(`/api/watchlist/${c}`).catch(e => {
        if (e.response?.status !== 404) console.error('batch remove failed:', c, e)
      })
    ))
    watchlist.value = watchlist.value.filter(s => !set.has(s.code))
    set.forEach(c => delete realtimeData.value[c])
    _persistCurrentOrder()
  }

  function isInWatchlist(code) {
    return watchlist.value.some(s => s.code === code)
  }

  // ── 标签 / 备注 ───────────────────────────────────────────────────────────
  async function loadTags() {
    if (!auth.token) { tags.value = []; return }
    try {
      const res = await axios.get('/api/watchlist/tags')
      tags.value = res.data || []
    } catch (e) {
      if (e.response?.status !== 401) console.error('Failed to load tags:', e)
    }
  }

  async function setTags(code, tagList) {
    try {
      const res = await axios.put(`/api/watchlist/${code}/tags`, { tags: tagList || [] })
      const item = watchlist.value.find(s => s.code === code)
      if (item) item.tags = res.data.item.tags
      await loadTags()
      return true
    } catch (e) {
      console.error('Failed to set tags:', e)
      return false
    }
  }

  // 单只标色（'' 清除）
  async function setColor(code, color) {
    try {
      const res = await axios.put(`/api/watchlist/${code}/color`, { color: color || '' })
      const item = watchlist.value.find(s => s.code === code)
      if (item) item.color = res.data.item.color || ''
      return true
    } catch (e) {
      console.error('Failed to set color:', e)
      return false
    }
  }

  // 持仓成本/股数（都为空则清空持仓）
  async function setHolding(code, costPrice, shares) {
    try {
      const res = await axios.put(`/api/watchlist/${code}/holding`, {
        cost_price: costPrice ?? null, shares: shares ?? null,
      })
      const item = watchlist.value.find(s => s.code === code)
      if (item) { item.cost_price = res.data.item.cost_price ?? null; item.shares = res.data.item.shares ?? null }
      return true
    } catch (e) {
      console.error('Failed to set holding:', e)
      return false
    }
  }

  async function updateNotes(code, notes) {
    try {
      const res = await axios.put(`/api/watchlist/${code}/notes`, { notes: notes || '' })
      const item = watchlist.value.find(s => s.code === code)
      if (item) item.notes = res.data.item.notes
      return true
    } catch (e) {
      console.error('Failed to update notes:', e)
      return false
    }
  }

  // ── 行情自动刷新（轮询）─────────────────────────────────────────────────
  function startAutoRefresh(ms = 15000) {
    stopAutoRefresh()
    _autoTimer = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (watchlist.value.length) loadWatchlist()
    }, ms)
  }

  function stopAutoRefresh() {
    if (_autoTimer) { clearInterval(_autoTimer); _autoTimer = null }
  }

  // ── 搜索 ────────────────────────────────────────────────────────────────
  async function searchStock(query) {
    if (!query || query.trim().length === 0) { searchResults.value = []; return }
    searching.value = true
    try {
      const sym = query.trim()
      const response = await axios.get(`/api/stock-analysis/${sym}/overview`)
      if (response.data && response.data.symbol) {
        searchResults.value = [{
          code: response.data.symbol, name: response.data.name,
          price: response.data.price, change: response.data.change_pct,
        }]
      } else {
        searchResults.value = []
      }
    } catch (e) {
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  // ── 验证记录 ────────────────────────────────────────────────────────────
  async function addVerification(verification) {
    try {
      const res = await axios.post('/api/watchlist/verifications', {
        periodDays: verification.periodDays,
        startDate: verification.startDate,
        endDate: verification.endDate,
        totalReturn: verification.totalReturn,
        results: verification.results || [],
      })
      watchlistVerifications.value.unshift(res.data)
      return res.data
    } catch (e) {
      console.error('Failed to save verification:', e)
      return null
    }
  }

  async function removeVerification(id) {
    try {
      await axios.delete(`/api/watchlist/verifications/${id}`)
    } catch (e) {
      if (e.response?.status !== 404) { console.error('Failed to remove verification:', e); return }
    }
    watchlistVerifications.value = watchlistVerifications.value.filter(v => v.id !== id)
  }

  async function fetchStockInfo(code) {
    try {
      const response = await axios.get(`/api/stock-analysis/${code}/overview`)
      return response.data
    } catch (e) {
      return null
    }
  }

  async function verifyWatchlist(periodDays = 30) {
    loading.value = true
    error.value = null
    try {
      const now = new Date()
      const endDate = now.toISOString().split('T')[0]
      const startDate = new Date(now.getTime() - periodDays * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
      const results = []
      for (const stock of watchlist.value) {
        try {
          const response = await axios.get('/api/market/history', {
            params: { symbol: stock.code, start: startDate, end: endDate },
          })
          const data = response.data
          if (data && data.length > 1) {
            const firstClose = parseFloat(data[0].close)
            const lastClose = parseFloat(data[data.length - 1].close)
            const changePercent = ((lastClose - firstClose) / firstClose * 100).toFixed(2)
            results.push({
              code: stock.code, name: stock.name, startPrice: firstClose,
              endPrice: lastClose, changePercent, period: periodDays, startDate, endDate,
            })
          }
        } catch (e) {
          console.error(`Failed to verify ${stock.code}:`, e)
        }
      }
      const verification = {
        periodDays, startDate, endDate, results,
        totalReturn: results.length > 0
          ? (results.reduce((sum, r) => sum + parseFloat(r.changePercent), 0) / results.length).toFixed(2)
          : 0,
      }
      const saved = await addVerification(verification)
      return saved || verification
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // ── 上证指数 / 行情 / 迷你图 ─────────────────────────────────────────────
  async function fetchShIndex() {
    try {
      const response = await axios.get('/api/market/indices')
      const list = response.data.indices || []
      indices.value = list
      const sh = list.find(idx => idx.code === '000001' || idx.name.includes('上证'))
      if (sh) shIndex.value = sh
    } catch (e) {
      console.error('Failed to fetch indices:', e)
    }
  }

  async function fetchRealtimeData() {
    // 行情已随 /overview 一并返回
    await loadWatchlist()
  }

  // 分时点 → 迷你图通用结构(复用 close 字段，前端绘制无需区分日/分时)
  function _normalizeMinute(points) {
    return (points || []).map(p => ({
      datetime: p.time, close: parseFloat(p.close), avg: p.avg,
    })).filter(p => Number.isFinite(p.close))
  }

  // 单只迷你走势图 — 当日分时(腾讯→东财→新浪三级回退)
  async function fetchMiniChartData(code) {
    try {
      const { data } = await axios.get(`/api/market/minute/${code}`)
      const pts = _normalizeMinute(data.points)
      if (pts.length) miniChartData.value[code] = pts
      if (data.pre_close != null) miniChartPre.value[code] = data.pre_close
    } catch (e) {
      console.error(`Failed to fetch mini chart for ${code}:`, e)
    }
  }

  // 批量拉取迷你图 — 当日分时批量接口；默认跳过已加载的(force 时盘中重取)
  async function fetchAllMiniChartData(force = false) {
    const codes = watchlist.value
      .map(s => s.code)
      .filter(c => force || !(miniChartData.value[c]?.length))
    if (!codes.length) return
    try {
      const { data } = await axios.post('/api/market/minute-batch', { codes })
      const map = data.data || {}
      const pre = data.pre_close || {}
      const next = { ...miniChartData.value }
      const nextPre = { ...miniChartPre.value }
      for (const code of Object.keys(map)) {
        const pts = _normalizeMinute(map[code])
        if (pts.length) next[code] = pts
        if (pre[code] != null) nextPre[code] = pre[code]
      }
      miniChartData.value = next
      miniChartPre.value = nextPre
    } catch (e) {
      console.error('Failed to batch-fetch minute charts:', e)
    }
  }

  // 主力资金流：单独 POST 拉取，合并进 realtimeData(让列/排序直接用)；失败静默
  async function fetchFundFlow() {
    const codes = watchlist.value.map(s => s.code)
    if (!codes.length) return
    try {
      const { data } = await axios.post('/api/market/fund-flow', { codes })
      const map = data.data || {}
      fundFlowData.value = map
      const next = { ...realtimeData.value }
      for (const code of Object.keys(map)) {
        next[code] = { ...(next[code] || {}), ...map[code] }
      }
      realtimeData.value = next
    } catch (e) {
      console.error('Failed to fetch fund flow:', e)
    }
  }

  // AI 诊断：按需触发(成本较高)，后端批量一次 LLM + 落库 6h 缓存
  async function fetchAiDiagnose(force = false) {
    const codes = watchlist.value.map(s => s.code)
    if (!codes.length || aiDiagLoading.value) return
    aiDiagLoading.value = true
    try {
      const { data } = await axios.post('/api/watchlist/ai-diagnose', { codes, force })
      aiDiag.value = { ...aiDiag.value, ...(data.data || {}) }
    } catch (e) {
      console.error('Failed to fetch AI diagnose:', e)
    } finally {
      aiDiagLoading.value = false
    }
  }

  function getStockInfo(code) {
    const stock = watchlist.value.find(s => s.code === code)
    return { ...stock, ...realtimeData.value[code], chartData: miniChartData.value[code] }
  }

  async function refreshAll() {
    await Promise.all([fetchShIndex(), loadWatchlist()])
  }

  // 账户切换（登录/登出/换号）时重载本账户数据
  watch(() => auth.user?.id, () => {
    loadVerifications()
    loadWatchlist()
    loadTags()
  })

  // 初始化：加载本账户数据
  loadVerifications()
  loadWatchlist()
  loadTags()

  return {
    watchlist, watchlistVerifications, realtimeData, fundFlowData, aiDiag, aiDiagLoading, miniChartData, miniChartPre, shIndex, indices, tags,
    loading, searching, refreshing, error, searchResults, loaded,
    loadWatchlist, loadVerifications, loadTags, setTags, setColor, setHolding, updateNotes,
    startAutoRefresh, stopAutoRefresh,
    searchStock, addToWatchlist, removeFromWatchlist, batchRemove, reorderWatchlist, isInWatchlist,
    addVerification, removeVerification, fetchStockInfo, verifyWatchlist,
    fetchShIndex, fetchRealtimeData, fetchMiniChartData, fetchAllMiniChartData, fetchFundFlow, fetchAiDiagnose,
    getStockInfo, refreshAll, loadFromStorage, saveToStorage,
  }
})
