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
  // 迷你图表数据
  const miniChartData = ref({})
  // 上证指数数据
  const shIndex = ref(null)

  const loading = ref(false)
  const searching = ref(false)
  const error = ref(null)
  const searchResults = ref([])
  const refreshing = ref(false)
  const loaded = ref(false)

  const auth = useAuthStore()

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
      }))
      // 同步实时行情
      const rt = {}
      for (const it of items) {
        if (it.price != null || it.change_pct != null) {
          rt[it.code] = {
            price: it.price, change_pct: it.change_pct, change: it.change,
            high: it.high, low: it.low, pre_close: it.pre_close,
            turnover: it.turnover, pe: it.pe, pb: it.pb,
            turnover_rate: it.turnover_rate,
          }
        }
      }
      realtimeData.value = rt
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
  }

  function isInWatchlist(code) {
    return watchlist.value.some(s => s.code === code)
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
      const indices = response.data.indices || []
      const sh = indices.find(idx => idx.code === '000001' || idx.name.includes('上证'))
      if (sh) shIndex.value = sh
    } catch (e) {
      console.error('Failed to fetch SH index:', e)
    }
  }

  async function fetchRealtimeData() {
    // 行情已随 /overview 一并返回
    await loadWatchlist()
  }

  async function fetchMiniChartData(code) {
    try {
      const endDate = new Date()
      const startDate = new Date(endDate.getTime() - 90 * 24 * 60 * 60 * 1000)
      const response = await axios.get('/api/market/history', {
        params: {
          symbol: code,
          start: startDate.toISOString().split('T')[0],
          end: endDate.toISOString().split('T')[0],
        },
      })
      if (response.data && response.data.length > 0) {
        miniChartData.value[code] = response.data.map(item => ({
          datetime: item.datetime, open: parseFloat(item.open), close: parseFloat(item.close),
          high: parseFloat(item.high), low: parseFloat(item.low), volume: item.volume,
        }))
      }
    } catch (e) {
      console.error(`Failed to fetch mini chart for ${code}:`, e)
    }
  }

  async function fetchAllMiniChartData() {
    for (const stock of watchlist.value) {
      await fetchMiniChartData(stock.code)
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
  })

  // 初始化：加载本账户验证记录 + 自选股
  loadVerifications()
  loadWatchlist()

  return {
    watchlist, watchlistVerifications, realtimeData, miniChartData, shIndex,
    loading, searching, refreshing, error, searchResults, loaded,
    loadWatchlist, loadVerifications, searchStock, addToWatchlist, removeFromWatchlist, isInWatchlist,
    addVerification, removeVerification, fetchStockInfo, verifyWatchlist,
    fetchShIndex, fetchRealtimeData, fetchMiniChartData, fetchAllMiniChartData,
    getStockInfo, refreshAll, loadFromStorage, saveToStorage,
  }
})
