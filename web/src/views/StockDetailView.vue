<template>
  <div class="stock-detail">
    <!-- 顶部导航 -->
    <header class="detail-header">
      <div class="header-left">
        <button class="back-btn" @click="$router.back()">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="15 18 9 12 15 6"></polyline>
          </svg>
        </button>
        <div class="stock-info">
          <h1>{{ stockName }}</h1>
          <span class="stock-code">{{ symbol }}</span>
        </div>
      </div>
      <div class="header-actions">
        <button class="download-btn" @click="downloadData" :disabled="downloading">
          <svg v-if="downloading" class="spinner" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="23 4 23 10 17 10"></polyline>
            <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
          </svg>
          <span v-else>{{ hasData ? '更新数据' : '下载数据' }}</span>
        </button>
        <button class="toggle-watchlist" @click="toggleWatchlist">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" :fill="isInWatchlist ? '#e63946' : 'none'"></path>
          </svg>
        </button>
      </div>
    </header>

    <!-- 价格卡片 -->
    <div class="price-card">
      <div class="price-main">
        <span :class="['current-price', priceClass]">{{ currentPrice }}</span>
        <span :class="['price-change', priceClass]">{{ priceChange }}</span>
        <span :class="['price-change-pct', priceClass]">{{ priceChangePct }}</span>
      </div>
      <div class="price-grid">
        <div class="price-item">
          <span class="label">今开</span>
          <span class="value">{{ openPrice }}</span>
        </div>
        <div class="price-item">
          <span class="label">最高</span>
          <span class="value">{{ highPrice }}</span>
        </div>
        <div class="price-item">
          <span class="label">最低</span>
          <span class="value">{{ lowPrice }}</span>
        </div>
        <div class="price-item">
          <span class="label">昨收</span>
          <span class="value">{{ prevClose }}</span>
        </div>
      </div>
    </div>

    <!-- 周期选择器 -->
    <div class="period-tabs">
      <button 
        v-for="period in periods" 
        :key="period.key"
        :class="['period-tab', activePeriod === period.key ? 'active' : '']"
        @click="changePeriod(period.key)"
      >
        {{ period.label }}
      </button>
    </div>

    <!-- K线图表 -->
    <div class="chart-container">
      <div v-if="loading" class="chart-loading">
        <span class="spinner"></span>
        <span>加载中...</span>
      </div>
      <div v-else-if="!hasData && !loading" class="chart-empty">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path>
          <polyline points="10 17 15 12 10 7"></polyline>
          <line x1="15" y1="12" x2="3" y2="12"></line>
        </svg>
        <p>暂无历史数据</p>
        <p class="hint">点击右上角"下载数据"获取历史行情</p>
      </div>
      <div v-else ref="chartRef" class="chart"></div>
    </div>

    <!-- 成交量图表 -->
    <div v-if="hasData" class="volume-container" ref="volumeRef"></div>

    <!-- 底部导航 -->
    <nav class="bottom-nav">
      <button class="nav-tab" @click="$router.push('/')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect>
        </svg>
        <span>首页</span>
      </button>
      <button class="nav-tab" @click="$router.push('/market-hub')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line>
        </svg>
        <span>市场</span>
      </button>
      <button class="nav-tab active" @click="$router.push('/watchlist')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path>
        </svg>
        <span>自选</span>
      </button>
      <button class="nav-tab" @click="$router.push('/live')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect width="18" height="18" x="3" y="4" rx="2"></rect><line x1="3" x2="21" y1="10" y2="10"></line>
        </svg>
        <span>交易</span>
      </button>
      <button class="nav-tab" @click="$router.push('/news')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"></path><path d="M18 14h-8"></path><path d="M15 18h-5"></path><path d="M10 6h8v4h-8V6Z"></path>
        </svg>
        <span>资讯</span>
      </button>
    </nav>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'

const route = useRoute()
const router = useRouter()
const watchlistStore = useWatchlistStore()

const symbol = computed(() => route.query.symbol || '000001')
const stockName = ref('--')
const loading = ref(false)
const downloading = ref(false)
const hasData = ref(false)
const activePeriod = ref('1y')
const chartRef = ref(null)
const volumeRef = ref(null)
let chartInstance = null
let volumeChartInstance = null

const periods = [
  { key: '1d', label: '日', days: 1 },
  { key: '1w', label: '周', days: 7 },
  { key: '1m', label: '月', days: 30 },
  { key: '3m', label: '季', days: 90 },
  { key: '1y', label: '年', days: 365 },
  { key: 'all', label: '全部', days: 3650 },
]

const isInWatchlist = computed(() => watchlistStore.isInWatchlist(symbol.value))

// 模拟实时数据
const currentPrice = ref('--')
const priceChange = ref('--')
const priceChangePct = ref('--')
const openPrice = ref('--')
const highPrice = ref('--')
const lowPrice = ref('--')
const prevClose = ref('--')
const priceClass = ref('')

const chartData = ref([])

const loadStockMeta = async () => {
  try {
    const response = await axios.get(`/api/stock-analysis/${symbol.value}/overview`)
    if (response.data) {
      const data = response.data
      stockName.value = data.name || '--'
      if (data.price !== undefined) {
        currentPrice.value = data.price.toFixed(2)
      }
      if (data.change_pct !== undefined) {
        const pct = parseFloat(data.change_pct)
        priceClass.value = pct >= 0 ? 'up' : 'down'
        priceChangePct.value = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'
        if (data.change !== undefined) {
          priceChange.value = (data.change >= 0 ? '+' : '') + data.change.toFixed(2)
        }
      }
      if (data.high !== undefined) {
        highPrice.value = data.high.toFixed(2)
      }
      if (data.low !== undefined) {
        lowPrice.value = data.low.toFixed(2)
      }
      if (data.open !== undefined) {
        openPrice.value = data.open.toFixed(2)
      }
      if (data.previous_close !== undefined) {
        prevClose.value = data.previous_close.toFixed(2)
      }
    }
  } catch (error) {
    console.error('Failed to load stock meta:', error)
  }
}

const loadChartData = async () => {
  loading.value = true
  try {
    // 先尝试本地数据
    const period = periods.find(p => p.key === activePeriod.value)
    const endDate = new Date()
    const startDate = new Date(endDate.getTime() - period.days * 24 * 60 * 60 * 1000)
    
    try {
      const response = await axios.get('/api/market/history', {
        params: {
          symbol: symbol.value,
          start: startDate.toISOString().split('T')[0],
          end: endDate.toISOString().split('T')[0],
        }
      })
      
      if (response.data && response.data.length > 0) {
        chartData.value = response.data
        hasData.value = true
        renderChart()
      } else {
        hasData.value = false
      }
    } catch (error) {
      console.log('Local data not available, will prompt for download')
      hasData.value = false
    }
  } catch (error) {
    console.error('Failed to load chart data:', error)
    hasData.value = false
  } finally {
    loading.value = false
  }
}

const downloadData = async () => {
  downloading.value = true
  try {
    const endDate = new Date()
    const startDate = new Date(endDate.getTime() - 3650 * 24 * 60 * 60 * 1000)
    
    await axios.post('/api/market/download', {
      symbol: symbol.value,
      start: startDate.toISOString().split('T')[0],
      end: endDate.toISOString().split('T')[0],
      interval: '1d',
    })
    
    await loadChartData()
  } catch (error) {
    console.error('Failed to download data:', error)
    alert('下载数据失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    downloading.value = false
  }
}

const toggleWatchlist = () => {
  if (isInWatchlist.value) {
    if (confirm('确定要从自选股中移除吗?')) {
      watchlistStore.removeFromWatchlist(symbol.value)
    }
  } else {
    watchlistStore.addToWatchlist({
      code: symbol.value,
      name: stockName.value,
    })
  }
}

const changePeriod = (key) => {
  activePeriod.value = key
  loadChartData()
}

const renderChart = () => {
  if (!chartRef.value || chartData.value.length === 0) return
  
  nextTick(() => {
    if (chartInstance) {
      chartInstance.dispose()
    }
    
    chartInstance = echarts.init(chartRef.value)
    
    const dates = chartData.value.map(d => d.datetime || d.date)
    const values = chartData.value.map(d => [
      parseFloat(d.open),
      parseFloat(d.close),
      parseFloat(d.low),
      parseFloat(d.high),
    ])
    const volumes = chartData.value.map(d => parseFloat(d.volume) || 0)
    
    const upColor = '#ef4444'
    const downColor = '#22c55e'
    
    const option = {
      backgroundColor: 'transparent',
      animation: false,
      grid: [
        {
          left: '10%',
          right: '8%',
          top: '8%',
          height: '50%',
        },
        {
          left: '10%',
          right: '8%',
          top: '63%',
          height: '16%',
        },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          scale: true,
          boundaryGap: false,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          min: 'dataMin',
          max: 'dataMax',
        },
        {
          type: 'category',
          gridIndex: 1,
          data: dates,
          scale: true,
          boundaryGap: false,
          axisLine: { lineStyle: { color: '#333' } },
          axisLabel: {
            color: '#666',
            fontSize: 10,
          },
          axisTick: { show: false },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          splitNumber: 5,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: {
            color: '#666',
            fontSize: 10,
          },
          splitLine: {
            lineStyle: { color: '#222', type: 'dashed' },
          },
        },
        {
          scale: true,
          gridIndex: 1,
          splitNumber: 2,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          splitLine: {
            lineStyle: { color: '#222', type: 'dashed' },
          },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: 0,
          end: 100,
        },
      ],
      series: [
        {
          type: 'candlestick',
          name: 'K线',
          data: values,
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
          },
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes.map((v, i) => {
            const isUp = values[i][1] >= values[i][0]
            return {
              value: v,
              itemStyle: {
                color: isUp ? upColor : downColor,
                opacity: 0.8,
              },
            }
          }),
        },
      ],
    }
    
    chartInstance.setOption(option)
    
    window.addEventListener('resize', handleResize)
  })
}

const handleResize = () => {
  if (chartInstance) {
    chartInstance.resize()
  }
}

watch(() => symbol.value, () => {
  loadStockMeta()
  loadChartData()
})

onMounted(() => {
  loadStockMeta()
  loadChartData()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) {
    chartInstance.dispose()
  }
})
</script>

<style scoped>
.stock-detail {
  min-height: 100vh;
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
  padding-bottom: 70px;
  display: flex;
  flex-direction: column;
}

.detail-header {
  background: linear-gradient(135deg, #e63946 0%, #d62828 100%);
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.back-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  border-radius: 8px;
  padding: 6px;
  color: white;
  cursor: pointer;
}

.stock-info h1 {
  font-size: 18px;
  font-weight: 700;
  color: white;
  margin: 0;
}

.stock-code {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  margin-left: 8px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.download-btn {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  color: white;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}

.download-btn:disabled {
  opacity: 0.6;
}

.toggle-watchlist {
  background: rgba(255, 255, 255, 0.15);
  border: none;
  border-radius: 8px;
  padding: 6px;
  color: white;
  cursor: pointer;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.price-card {
  background: rgba(255, 255, 255, 0.05);
  margin: 16px;
  padding: 16px;
  border-radius: 12px;
}

.price-main {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 16px;
}

.current-price {
  font-size: 28px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
}

.current-price.up {
  color: #ef4444;
}

.current-price.down {
  color: #22c55e;
}

.price-change {
  font-size: 16px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.price-change.up,
.price-change-pct.up {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.price-change.down,
.price-change-pct.down {
  color: #22c55e;
  background: rgba(34, 197, 94, 0.15);
  padding: 2px 8px;
  border-radius: 4px;
}

.price-change-pct {
  font-size: 16px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
}

.price-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.price-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.price-item .label {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}

.price-item .value {
  font-size: 14px;
  color: white;
  font-family: 'JetBrains Mono', monospace;
}

.period-tabs {
  display: flex;
  gap: 4px;
  margin: 0 16px 12px;
  background: rgba(255, 255, 255, 0.05);
  padding: 4px;
  border-radius: 8px;
}

.period-tab {
  flex: 1;
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.period-tab.active {
  background: rgba(255, 255, 255, 0.15);
  color: white;
}

.chart-container {
  flex: 1;
  margin: 0 16px 8px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  min-height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chart {
  width: 100%;
  height: 300px;
}

.chart-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: rgba(255, 255, 255, 0.5);
}

.chart-loading .spinner {
  width: 24px;
  height: 24px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  border-top-color: #e63946;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.chart-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: rgba(255, 255, 255, 0.4);
  text-align: center;
  padding: 40px 20px;
}

.chart-empty p {
  margin: 0;
  font-size: 14px;
}

.chart-empty .hint {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
}

.volume-container {
  margin: 0 16px 16px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  height: 100px;
}

.bottom-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  background: rgba(26, 26, 46, 0.95);
  backdrop-filter: blur(10px);
  padding: 8px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  z-index: 50;
}

.nav-tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 4px 0;
}

.nav-tab:hover {
  color: rgba(255, 255, 255, 0.7);
}

.nav-tab.active {
  color: #e63946;
}

.nav-tab span {
  font-size: 10px;
}

@media (min-width: 768px) {
  .stock-detail {
    max-width: 600px;
    margin: 0 auto;
    box-shadow: 0 0 30px rgba(0, 0, 0, 0.3);
  }
  
  .bottom-nav {
    display: none;
  }
}
</style>