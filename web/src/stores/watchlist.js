import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useWatchlistStore = defineStore('watchlist', () => {
  // 自选股列表
  const watchlist = ref([])
  // 自选股验证记录
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

  // 本地存储键名
  const STORAGE_KEY = 'quantforge-watchlist'
  const VERIFICATION_KEY = 'quantforge-watchlist-verifications'

  // 从本地存储加载
  function loadFromStorage() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        watchlist.value = JSON.parse(saved)
      }
      const verificationsSaved = localStorage.getItem(VERIFICATION_KEY)
      if (verificationsSaved) {
        watchlistVerifications.value = JSON.parse(verificationsSaved)
      }
    } catch (e) {
      console.error('Failed to load watchlist from storage:', e)
    }
  }

  // 保存到本地存储
  function saveToStorage() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(watchlist.value))
      localStorage.setItem(VERIFICATION_KEY, JSON.stringify(watchlistVerifications.value))
    } catch (e) {
      console.error('Failed to save watchlist to storage:', e)
    }
  }

  // 搜索股票
  async function searchStock(query) {
    if (!query || query.trim().length === 0) {
      searchResults.value = []
      return
    }
    
    searching.value = true
    try {
      const sym = query.trim()
      const response = await axios.get(`/api/stock-analysis/${sym}/overview`)
      if (response.data && response.data.symbol) {
        searchResults.value = [{
          code: response.data.symbol,
          name: response.data.name,
          price: response.data.price,
          change: response.data.change_pct
        }]
      } else {
        searchResults.value = []
      }
    } catch (e) {
      console.error('Failed to search stock:', e)
      searchResults.value = []
    } finally {
      searching.value = false
    }
  }

  // 添加股票到自选股
  function addToWatchlist(stock) {
    // 检查是否已存在
    const exists = watchlist.value.find(s => s.code === stock.code)
    if (exists) {
      return false
    }
    watchlist.value.push({
      ...stock,
      addedAt: new Date().toISOString(),
      id: Date.now()
    })
    saveToStorage()
    searchResults.value = []
    return true
  }

  // 从自选股移除
  function removeFromWatchlist(code) {
    watchlist.value = watchlist.value.filter(s => s.code !== code)
    saveToStorage()
  }

  // 检查股票是否在自选股
  function isInWatchlist(code) {
    return watchlist.value.some(s => s.code === code)
  }

  // 添加验证记录
  function addVerification(verification) {
    watchlistVerifications.value.unshift({
      ...verification,
      id: Date.now(),
      createdAt: new Date().toISOString()
    })
    saveToStorage()
  }

  // 删除验证记录
  function removeVerification(id) {
    watchlistVerifications.value = watchlistVerifications.value.filter(v => v.id !== id)
    saveToStorage()
  }

  // 获取股票信息
  async function fetchStockInfo(code) {
    try {
      const response = await axios.get(`/api/stock-analysis/${code}/overview`)
      return response.data
    } catch (e) {
      console.error('Failed to fetch stock info:', e)
      return null
    }
  }

  // 验证自选股表现
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
            params: {
              symbol: stock.code,
              start: startDate,
              end: endDate
            }
          })
          
          const data = response.data
          if (data && data.length > 1) {
            const firstClose = parseFloat(data[0].close)
            const lastClose = parseFloat(data[data.length - 1].close)
            const changePercent = ((lastClose - firstClose) / firstClose * 100).toFixed(2)
            
            results.push({
              code: stock.code,
              name: stock.name,
              startPrice: firstClose,
              endPrice: lastClose,
              changePercent: changePercent,
              period: periodDays,
              startDate: startDate,
              endDate: endDate
            })
          }
        } catch (e) {
          console.error(`Failed to verify ${stock.code}:`, e)
        }
      }

      const verification = {
        periodDays,
        startDate,
        endDate,
        results,
        totalReturn: results.length > 0 ? 
          (results.reduce((sum, r) => sum + parseFloat(r.changePercent), 0) / results.length).toFixed(2) : 0
      }

      addVerification(verification)
      return verification
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  // 获取上证指数数据
  async function fetchShIndex() {
    try {
      const response = await axios.get('/api/market/indices')
      const indices = response.data.indices || []
      const sh = indices.find(idx => idx.code === '000001' || idx.name.includes('上证'))
      if (sh) {
        shIndex.value = sh
      }
    } catch (e) {
      console.error('Failed to fetch SH index:', e)
    }
  }

  // 获取自选股实时行情 - 使用市场行情API
  async function fetchRealtimeData() {
    if (watchlist.value.length === 0) return
    
    refreshing.value = true
    try {
      // 尝试使用个股分析API获取每个股票的实时数据
      for (const stock of watchlist.value) {
        try {
          const response = await axios.get(`/api/stock-analysis/${stock.code}/overview`)
          if (response.data) {
            realtimeData.value[stock.code] = response.data
          }
        } catch (e) {
          console.warn(`Failed to fetch data for ${stock.code}:`, e)
        }
      }
    } catch (e) {
      console.error('Failed to fetch realtime data:', e)
    } finally {
      refreshing.value = false
    }
  }

  // 获取迷你图表数据（最近一段时间的价格）
  async function fetchMiniChartData(code) {
    try {
      const endDate = new Date()
      const startDate = new Date(endDate.getTime() - 90 * 24 * 60 * 60 * 1000)
      
      const response = await axios.get('/api/market/history', {
        params: {
          symbol: code,
          start: startDate.toISOString().split('T')[0],
          end: endDate.toISOString().split('T')[0]
        }
      })
      
      if (response.data && response.data.length > 0) {
        miniChartData.value[code] = response.data.map(item => ({
          datetime: item.datetime,
          open: parseFloat(item.open),
          close: parseFloat(item.close),
          high: parseFloat(item.high),
          low: parseFloat(item.low),
          volume: item.volume
        }))
      }
    } catch (e) {
      console.error(`Failed to fetch mini chart data for ${code}:`, e)
    }
  }

  // 批量获取迷你图表数据
  async function fetchAllMiniChartData() {
    for (const stock of watchlist.value) {
      await fetchMiniChartData(stock.code)
    }
  }

  // 获取股票的综合信息
  function getStockInfo(code) {
    const stock = watchlist.value.find(s => s.code === code)
    const realtime = realtimeData.value[code]
    const chart = miniChartData.value[code]
    
    return {
      ...stock,
      ...realtime,
      chartData: chart
    }
  }

  // 刷新所有数据
  async function refreshAll() {
    await Promise.all([
      fetchShIndex(),
      fetchRealtimeData()
    ])
  }

  // 初始化
  loadFromStorage()

  return {
    watchlist,
    watchlistVerifications,
    realtimeData,
    miniChartData,
    shIndex,
    loading,
    searching,
    refreshing,
    error,
    searchResults,
    searchStock,
    addToWatchlist,
    removeFromWatchlist,
    isInWatchlist,
    addVerification,
    removeVerification,
    fetchStockInfo,
    verifyWatchlist,
    fetchShIndex,
    fetchRealtimeData,
    fetchMiniChartData,
    fetchAllMiniChartData,
    getStockInfo,
    refreshAll,
    loadFromStorage,
    saveToStorage
  }
})