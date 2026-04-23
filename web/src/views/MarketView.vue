<template>
  <div class="market-view">
    <!-- Toolbar -->
    <div class="toolbar card">
      <div class="search-group">
        <input v-model="symbol" @keydown.enter="load" placeholder="股票代码，如 000001 / 600519" class="input symbol-input" />
        <span class="exchange-badge" v-if="detectedExchange">{{ detectedExchange }}</span>
      </div>

      <div class="view-toggle">
        <button :class="['toggle-btn', viewMode === 'daily' ? 'active' : '']" @click="switchMode('daily')">日K分析</button>
        <button :class="['toggle-btn', viewMode === 'intraday' ? 'active' : '']" @click="switchMode('intraday')">今日分时</button>
      </div>

      <template v-if="viewMode === 'daily'">
        <div class="preset-group">
          <button v-for="p in presets" :key="p.label"
            :class="['preset-btn', activePreset === p.label ? 'active' : '']"
            @click="applyPreset(p)">{{ p.label }}</button>
        </div>
        <div class="date-group">
          <input type="date" v-model="startDate" class="input date-input" @change="activePreset = ''" />
          <span class="text-3">—</span>
          <input type="date" v-model="endDate" class="input date-input" @change="activePreset = ''" />
        </div>
      </template>

      <template v-if="viewMode === 'intraday'">
        <div class="klt-group">
          <button v-for="k in kltOptions" :key="k.value"
            :class="['preset-btn', klt === k.value ? 'active' : '']"
            @click="klt = k.value; loadIntraday()">{{ k.label }}</button>
        </div>
      </template>

      <button class="btn-primary" @click="load" :disabled="loading">
        <span v-if="loading" class="spinner spinner-sm"></span>
        {{ loading ? '加载中...' : '查询' }}
      </button>
    </div>

    <!-- Download prompt -->
    <div v-if="downloadMsg" class="card" style="padding:12px 16px;display:flex;align-items:center;gap:10px">
      <span v-if="downloading" class="spinner spinner-sm"></span>
      <span class="text-2" style="font-size:13px">{{ downloadMsg }}</span>
    </div>

    <!-- ══ DAILY MODE ══ -->
    <template v-if="viewMode === 'daily'">
      <!-- Indicator controls -->
      <div v-if="bars.length" class="indicators-bar card">
        <span class="ind-label">均线</span>
        <button v-for="ma in maOptions" :key="ma.key"
          :class="['ind-btn', indicators[ma.key] ? 'active' : '']"
          :style="indicators[ma.key] ? { borderColor: ma.color, color: ma.color, background: ma.color + '1a' } : {}"
          @click="indicators[ma.key] = !indicators[ma.key]">{{ ma.label }}</button>
        <button :class="['ind-btn', indicators.boll ? 'active' : '']"
          :style="indicators.boll ? { borderColor:'#a78bfa', color:'#a78bfa', background:'#a78bfa1a' } : {}"
          @click="indicators.boll = !indicators.boll">BOLL</button>
        <span class="ind-sep"></span>
        <span class="ind-label">副图</span>
        <button v-for="s in subOptions" :key="s.key"
          :class="['ind-btn', subIndicator === s.key ? 'active' : '']"
          :style="subIndicator === s.key ? { borderColor: s.color, color: s.color, background: s.color + '1a' } : {}"
          @click="subIndicator = subIndicator === s.key ? '' : s.key">{{ s.label }}</button>
      </div>

      <!-- K-line chart -->
      <div v-if="klineOption" class="chart-card card">
        <div class="chart-header">
          <span class="text-1 fw-600">{{ symbol }} · 日K</span>
          <span v-if="bars.length" class="text-3" style="font-size:11px">{{ bars[0]?.datetime }} — {{ bars[bars.length-1]?.datetime }}</span>
        </div>
        <v-chart :option="klineOption" autoresize style="height:400px" @click="onChartClick" />
      </div>

      <!-- Sub-chart: MACD or RSI -->
      <div v-if="subOption && bars.length" class="chart-card card">
        <div class="chart-header">
          <span class="text-2" style="font-size:12px">{{ subOption.label }}</span>
        </div>
        <v-chart :option="subChartOption" autoresize style="height:180px" />
      </div>

      <!-- Volume -->
      <div v-if="volumeOption" class="chart-card card">
        <v-chart :option="volumeOption" autoresize style="height:120px" />
      </div>

      <!-- Click detail panel -->
      <div v-if="selectedBar" class="bar-detail card">
        <div class="bar-detail-row">
          <div class="bar-detail-item"><div class="bar-detail-label">日期</div><div class="bar-detail-val mono">{{ selectedBar.datetime }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">开盘</div><div class="bar-detail-val mono">{{ selectedBar.open.toFixed(2) }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">最高</div><div class="bar-detail-val mono pos">{{ selectedBar.high.toFixed(2) }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">最低</div><div class="bar-detail-val mono neg">{{ selectedBar.low.toFixed(2) }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">收盘</div><div class="bar-detail-val mono" :class="selectedBar.close >= selectedBar.open ? 'pos' : 'neg'">{{ selectedBar.close.toFixed(2) }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">成交量</div><div class="bar-detail-val mono">{{ fmtVol(selectedBar.volume) }}</div></div>
          <div class="bar-detail-item"><div class="bar-detail-label">涨跌</div><div class="bar-detail-val mono" :class="selectedBar.close >= selectedBar.open ? 'pos' : 'neg'">{{ ((selectedBar.close/selectedBar.open - 1)*100).toFixed(2) }}%</div></div>
          <div class="bar-detail-item">
            <button class="btn-intraday" @click="viewIntradayForDate(selectedBar.datetime)">
              <span v-if="intradayLoadingDate === selectedBar.datetime" class="spinner spinner-sm"></span>
              <span v-else>📈 查看分时</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Stats row -->
      <div v-if="bars.length" class="stats-row">
        <div class="stat card">
          <div class="stat-label">数据条数</div>
          <div class="stat-value">{{ bars.length }}</div>
        </div>
        <div class="stat card">
          <div class="stat-label">区间最高</div>
          <div class="stat-value pos">{{ Math.max(...bars.map(b => b.high)).toFixed(2) }}</div>
        </div>
        <div class="stat card">
          <div class="stat-label">区间最低</div>
          <div class="stat-value neg">{{ Math.min(...bars.map(b => b.low)).toFixed(2) }}</div>
        </div>
        <div class="stat card">
          <div class="stat-label">区间涨幅</div>
          <div class="stat-value" :class="periodReturn >= 0 ? 'pos' : 'neg'">{{ (periodReturn * 100).toFixed(2) }}%</div>
        </div>
        <div class="stat card">
          <div class="stat-label">平均成交量</div>
          <div class="stat-value">{{ avgVolume }}</div>
        </div>
      </div>
    </template>

    <!-- ══ INTRADAY MODE ══ -->
    <template v-if="viewMode === 'intraday'">
      <div v-if="intradayLoading" class="card" style="padding:40px;display:flex;align-items:center;justify-content:center;gap:12px">
        <span class="spinner"></span><span class="text-2">加载分时数据...</span>
      </div>

      <div v-if="intradayBars.length && !intradayLoading">
        <div class="chart-card card">
          <div class="chart-header">
            <span class="text-1 fw-600">{{ symbol }} · {{ kltOptions.find(k=>k.value===klt)?.label }}</span>
            <span class="text-3" style="font-size:11px">{{ intradayDate || intradayBars[0]?.datetime?.slice(0,10) }}</span>
          </div>
          <v-chart :option="intradayOption" autoresize style="height:350px" @click="onIntradayClick" />
        </div>

        <div class="chart-card card">
          <v-chart :option="intradayVolumeOption" autoresize style="height:100px" />
        </div>

        <!-- Intraday click detail -->
        <div v-if="selectedIntraday" class="bar-detail card">
          <div class="bar-detail-row">
            <div class="bar-detail-item"><div class="bar-detail-label">时间</div><div class="bar-detail-val mono">{{ selectedIntraday.datetime.slice(11) }}</div></div>
            <div class="bar-detail-item"><div class="bar-detail-label">开盘</div><div class="bar-detail-val mono">{{ selectedIntraday.open.toFixed(2) }}</div></div>
            <div class="bar-detail-item"><div class="bar-detail-label">最高</div><div class="bar-detail-val mono pos">{{ selectedIntraday.high.toFixed(2) }}</div></div>
            <div class="bar-detail-item"><div class="bar-detail-label">最低</div><div class="bar-detail-val mono neg">{{ selectedIntraday.low.toFixed(2) }}</div></div>
            <div class="bar-detail-item"><div class="bar-detail-label">收盘</div><div class="bar-detail-val mono" :class="selectedIntraday.close >= selectedIntraday.open ? 'pos' : 'neg'">{{ selectedIntraday.close.toFixed(2) }}</div></div>
            <div class="bar-detail-item"><div class="bar-detail-label">成交量</div><div class="bar-detail-val mono">{{ fmtVol(selectedIntraday.volume) }}</div></div>
          </div>
        </div>

        <!-- Intraday stats -->
        <div class="stats-row">
          <div class="stat card"><div class="stat-label">今日开盘</div><div class="stat-value mono">{{ intradayBars[0]?.open.toFixed(2) }}</div></div>
          <div class="stat card"><div class="stat-label">最新价</div><div class="stat-value mono" :class="intradayReturn >= 0 ? 'pos' : 'neg'">{{ intradayBars[intradayBars.length-1]?.close.toFixed(2) }}</div></div>
          <div class="stat card"><div class="stat-label">今日涨跌</div><div class="stat-value" :class="intradayReturn >= 0 ? 'pos' : 'neg'">{{ (intradayReturn * 100).toFixed(2) }}%</div></div>
          <div class="stat card"><div class="stat-label">日内最高</div><div class="stat-value pos">{{ Math.max(...intradayBars.map(b=>b.high)).toFixed(2) }}</div></div>
          <div class="stat card"><div class="stat-label">日内最低</div><div class="stat-value neg">{{ Math.min(...intradayBars.map(b=>b.low)).toFixed(2) }}</div></div>
        </div>
      </div>

      <div v-if="!intradayBars.length && !intradayLoading && !loading" class="empty-state card">
        <p>暂无分时数据（非交易时段可能无今日数据）</p>
        <p class="empty-hint">请先在"日K分析"模式下下载历史数据</p>
      </div>
    </template>

    <!-- Error -->
    <div v-if="error" class="error-box">{{ error }}</div>

    <!-- Empty state -->
    <div v-if="!bars.length && !intradayBars.length && !loading && !intradayLoading && !downloadMsg && !error" class="empty-state card">
      <div class="empty-icon">📈</div>
      <p>输入股票代码查询行情数据</p>
      <p class="empty-hint">支持沪深两市，如 000001（平安银行）、600519（贵州茅台）</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import axios from 'axios'

const symbol      = ref('000001')
const startDate   = ref('')
const endDate     = ref('')
const bars        = ref([])
const loading     = ref(false)
const downloading = ref(false)
const error       = ref('')
const downloadMsg = ref('')
const activePreset = ref('1Y')
const selectedBar = ref(null)
const viewMode    = ref('daily')  // 'daily' | 'intraday'

// Intraday state
const intradayBars    = ref([])
const intradayLoading = ref(false)
const intradayLoadingDate = ref('')  // tracks which date is loading for the button spinner
const intradayDate    = ref('')      // currently displayed intraday date
const klt             = ref(5)
const selectedIntraday = ref(null)

// Indicator controls
const indicators = reactive({ ma5: true, ma10: false, ma20: true, ma60: false, boll: false })
const subIndicator = ref('')  // 'macd' | 'rsi' | ''

const maOptions = [
  { key: 'ma5',  label: 'MA5',  color: '#f6ad55', period: 5  },
  { key: 'ma10', label: 'MA10', color: '#68d391', period: 10 },
  { key: 'ma20', label: 'MA20', color: '#63b3ed', period: 20 },
  { key: 'ma60', label: 'MA60', color: '#9f7aea', period: 60 },
]
const subOptions = [
  { key: 'macd', label: 'MACD', color: '#f6ad55' },
  { key: 'rsi',  label: 'RSI',  color: '#68d391'  },
]
const kltOptions = [
  { value: 5,  label: '5分' },
  { value: 15, label: '15分' },
  { value: 30, label: '30分' },
  { value: 60, label: '60分' },
]

const presets = [
  { label: '1M', months: 1 }, { label: '3M', months: 3 },
  { label: '6M', months: 6 }, { label: '1Y', months: 12 },
  { label: '2Y', months: 24 }, { label: '3Y', months: 36 },
]

const detectedExchange = computed(() => {
  const s = symbol.value.trim()
  if (s.startsWith('6')) return 'SSE'
  if (s.startsWith('0') || s.startsWith('3')) return 'SZSE'
  if (s.startsWith('8') || s.startsWith('4')) return 'BSE'
  return ''
})

const periodReturn = computed(() => {
  if (bars.value.length < 2) return 0
  return bars.value[bars.value.length - 1].close / bars.value[0].open - 1
})

const avgVolume = computed(() => {
  if (!bars.value.length) return '-'
  const avg = bars.value.reduce((s, b) => s + b.volume, 0) / bars.value.length
  return avg > 1e6 ? (avg / 1e6).toFixed(1) + 'M' : (avg / 1e4).toFixed(0) + 'W'
})

const intradayReturn = computed(() => {
  if (intradayBars.value.length < 1) return 0
  const first = intradayBars.value[0].open
  const last = intradayBars.value[intradayBars.value.length - 1].close
  return (last - first) / first
})

const subOption = computed(() => subOptions.find(s => s.key === subIndicator.value) || null)

function applyPreset(p) {
  const end = new Date(), start = new Date()
  start.setMonth(start.getMonth() - p.months)
  startDate.value = start.toISOString().slice(0, 10)
  endDate.value = end.toISOString().slice(0, 10)
  activePreset.value = p.label
}

function fmtVol(v) {
  if (!v) return '0'
  return v > 1e6 ? (v / 1e6).toFixed(1) + 'M' : (v / 1e4).toFixed(0) + 'W'
}

function switchMode(m) {
  viewMode.value = m
  if (m === 'intraday' && symbol.value) loadIntraday()   // no date = latest session
}

function load() {
  if (viewMode.value === 'daily') loadDaily()
  else loadIntraday()
}

// Check if last bar date is stale (last trading day before today, skip weekends)
function isStale(lastDateStr) {
  if (!lastDateStr) return false
  const last = new Date(lastDateStr)
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  // Move back to last trading day (skip Saturday=6, Sunday=0)
  const prev = new Date(today)
  prev.setDate(prev.getDate() - 1)
  while (prev.getDay() === 0 || prev.getDay() === 6) prev.setDate(prev.getDate() - 1)
  return last < prev
}

async function loadDaily() {
  if (!symbol.value.trim()) return
  loading.value = true; error.value = ''; bars.value = []; selectedBar.value = null; downloadMsg.value = ''
  try {
    const res = await axios.get(`/api/market/bars/${symbol.value.trim()}`, {
      params: { start: startDate.value, end: endDate.value }
    })
    bars.value = res.data.bars || []
    if (!bars.value.length) { loading.value = false; await downloadThenLoad(); return }

    // Stale check: if last bar is behind last trading day, trigger incremental download
    const lastDate = bars.value[bars.value.length - 1]?.datetime?.slice(0, 10)
    if (isStale(lastDate)) {
      loading.value = false
      const nextDay = new Date(lastDate)
      nextDay.setDate(nextDay.getDate() + 1)
      const startStr = nextDay.toISOString().slice(0, 10)
      await downloadThenLoad(startStr)
      return
    }
  } catch (e) {
    if (e.response?.status === 404) { loading.value = false; await downloadThenLoad(); return }
    error.value = e.response?.data?.detail || '加载失败'
  }
  loading.value = false
}

async function downloadThenLoad(fromDate) {
  downloading.value = true
  const sym = symbol.value.trim()
  const start = fromDate || startDate.value
  downloadMsg.value = fromDate
    ? `检测到数据滞后，正在补充下载 ${sym} 从 ${fromDate} 至今的数据...`
    : `正在从东方财富下载 ${sym} 数据...`
  try {
    const res = await axios.post('/api/market/download', { symbol: sym, start, end: endDate.value })
    downloadMsg.value = `已下载 ${res.data.bars} 条数据 (${res.data.start} ~ ${res.data.end})`
    await loadDaily()
  } catch (e) {
    downloadMsg.value = '下载失败: ' + (e.response?.data?.detail || e.message)
  }
  downloading.value = false
}

async function loadIntraday(targetDate) {
  if (!symbol.value.trim()) return
  intradayLoading.value = true; error.value = ''; intradayBars.value = []; selectedIntraday.value = null
  const params = { klt: klt.value }
  if (targetDate) params.date = targetDate
  try {
    const res = await axios.get(`/api/market/intraday/${symbol.value.trim()}`, { params })
    intradayBars.value = res.data.bars || []
    intradayDate.value = res.data.date || targetDate || ''
  } catch (e) {
    error.value = e.response?.data?.detail || '分时数据加载失败'
  }
  intradayLoading.value = false
}

async function viewIntradayForDate(date) {
  intradayLoadingDate.value = date
  viewMode.value = 'intraday'
  await loadIntraday(date)
  intradayLoadingDate.value = ''
}

function onChartClick(params) {
  if (params.componentType !== 'series' || params.seriesType !== 'candlestick') return
  const idx = params.dataIndex
  if (idx != null && bars.value[idx]) selectedBar.value = bars.value[idx]
}

function onIntradayClick(params) {
  const idx = params.dataIndex
  if (idx != null && intradayBars.value[idx]) selectedIntraday.value = intradayBars.value[idx]
}

// ── Chart computations ──────────────────────────────────────────────────────

function computeMA(data, period) {
  return data.map((_, i) => {
    if (i < period - 1) return null
    return +(data.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period).toFixed(3)
  })
}

function computeBOLL(closes, period = 20, k = 2) {
  const mid = computeMA(closes, period)
  const upper = [], lower = []
  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) { upper.push(null); lower.push(null); continue }
    const slice = closes.slice(i - period + 1, i + 1)
    const mean = slice.reduce((a, b) => a + b, 0) / period
    const std = Math.sqrt(slice.reduce((s, v) => s + (v - mean) ** 2, 0) / period)
    upper.push(+(mean + k * std).toFixed(3))
    lower.push(+(mean - k * std).toFixed(3))
  }
  return { upper, mid, lower }
}

function computeMACD(closes, fast = 12, slow = 26, signal = 9) {
  function ema(data, period) {
    const k = 2 / (period + 1)
    const result = [null]
    let prev = data[0]
    for (let i = 1; i < data.length; i++) {
      const val = data[i] * k + prev * (1 - k)
      result.push(+val.toFixed(4))
      prev = val
    }
    return result
  }
  const emaFast = ema(closes, fast)
  const emaSlow = ema(closes, slow)
  const dif = closes.map((_, i) => emaFast[i] != null && emaSlow[i] != null ? +(emaFast[i] - emaSlow[i]).toFixed(4) : null)
  const nonNull = dif.filter(v => v != null)
  const sigArr = ema(nonNull, signal)
  const dea = dif.map((v, i) => {
    if (v == null) return null
    const idx = dif.slice(0, i + 1).filter(x => x != null).length - 1
    return sigArr[idx] ?? null
  })
  const macd = dif.map((v, i) => v != null && dea[i] != null ? +((v - dea[i]) * 2).toFixed(4) : null)
  return { dif, dea, macd }
}

function computeRSI(closes, period = 14) {
  const result = Array(closes.length).fill(null)
  for (let i = period; i < closes.length; i++) {
    let gain = 0, loss = 0
    for (let j = i - period + 1; j <= i; j++) {
      const diff = closes[j] - closes[j - 1]
      if (diff > 0) gain += diff; else loss -= diff
    }
    const avgGain = gain / period, avgLoss = loss / period
    result[i] = avgLoss === 0 ? 100 : +(100 - 100 / (1 + avgGain / avgLoss)).toFixed(2)
  }
  return result
}

const klineOption = computed(() => {
  if (!bars.value.length) return null
  const closes = bars.value.map(b => b.close)
  const dates = bars.value.map(b => b.datetime)
  const ohlc = bars.value.map(b => [b.open, b.close, b.low, b.high])

  const series = [
    { name: 'K线', type: 'candlestick', data: ohlc,
      itemStyle: { color: '#f56565', color0: '#48bb78', borderColor: '#f56565', borderColor0: '#48bb78' } },
  ]

  const legendData = ['K线']

  for (const ma of maOptions) {
    if (indicators[ma.key]) {
      series.push({ name: ma.label, type: 'line', data: computeMA(closes, ma.period), smooth: true, symbol: 'none', lineStyle: { color: ma.color, width: 1.5 }, z: 10 })
      legendData.push(ma.label)
    }
  }

  if (indicators.boll) {
    const boll = computeBOLL(closes)
    series.push({ name: 'BOLL上', type: 'line', data: boll.upper, smooth: true, symbol: 'none', lineStyle: { color: '#a78bfa', width: 1, type: 'dashed' }, z: 10 })
    series.push({ name: 'BOLL中', type: 'line', data: boll.mid, smooth: true, symbol: 'none', lineStyle: { color: '#a78bfa', width: 1.5 }, z: 10 })
    series.push({ name: 'BOLL下', type: 'line', data: boll.lower, smooth: true, symbol: 'none', lineStyle: { color: '#a78bfa', width: 1, type: 'dashed' }, z: 10 })
    legendData.push('BOLL上', 'BOLL中', 'BOLL下')
  }

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: legendData, textStyle: { color: '#a0aec0', fontSize: 11 }, top: 4, itemWidth: 14 },
    grid: { left: 65, right: 20, top: 36, bottom: 60 },
    dataZoom: [
      { type: 'inside', start: Math.max(0, 100 - Math.round(9000 / bars.value.length)), end: 100 },
      { type: 'slider', start: 60, end: 100, height: 20, bottom: 8, borderColor: '#2d3748', fillerColor: 'rgba(99,179,237,0.15)', handleStyle: { color: '#63b3ed' }, textStyle: { color: '#718096' } },
    ],
    xAxis: { type: 'category', data: dates, axisLabel: { color: '#718096', fontSize: 11 }, axisLine: { lineStyle: { color: '#2d3748' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#718096', fontSize: 11 }, axisLine: { lineStyle: { color: '#2d3748' } }, splitLine: { lineStyle: { color: '#1a2035' } } },
    series,
  }
})

const volumeOption = computed(() => {
  if (!bars.value.length) return null
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 65, right: 20, top: 8, bottom: 36 },
    dataZoom: [{ type: 'inside', start: 60, end: 100 }],
    xAxis: { type: 'category', data: bars.value.map(b => b.datetime), axisLabel: { color: '#718096', fontSize: 10 }, axisLine: { lineStyle: { color: '#2d3748' } } },
    yAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (v/1e4).toFixed(0)+'W' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    series: [{ type: 'bar', data: bars.value.map(b => ({ value: b.volume, itemStyle: { color: b.close >= b.open ? '#48bb78' : '#f56565', opacity: 0.75 } })) }],
  }
})

const subChartOption = computed(() => {
  if (!bars.value.length || !subIndicator.value) return null
  const closes = bars.value.map(b => b.close)
  const dates = bars.value.map(b => b.datetime)

  if (subIndicator.value === 'macd') {
    const { dif, dea, macd } = computeMACD(closes)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      grid: { left: 65, right: 20, top: 8, bottom: 36 },
      dataZoom: [{ type: 'inside', start: 60, end: 100 }],
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#718096', fontSize: 10 }, axisLine: { lineStyle: { color: '#2d3748' } } },
      yAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10 }, splitLine: { lineStyle: { color: '#1a2035' } } },
      series: [
        { name: 'DIF', type: 'line', data: dif, smooth: true, symbol: 'none', lineStyle: { color: '#f6ad55', width: 1.5 } },
        { name: 'DEA', type: 'line', data: dea, smooth: true, symbol: 'none', lineStyle: { color: '#63b3ed', width: 1.5 } },
        { name: 'MACD', type: 'bar', data: macd.map(v => ({ value: v, itemStyle: { color: v >= 0 ? '#48bb78' : '#f56565' } })) },
      ],
    }
  }

  if (subIndicator.value === 'rsi') {
    const rsi = computeRSI(closes)
    return {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      grid: { left: 65, right: 20, top: 8, bottom: 36 },
      dataZoom: [{ type: 'inside', start: 60, end: 100 }],
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#718096', fontSize: 10 }, axisLine: { lineStyle: { color: '#2d3748' } } },
      yAxis: { type: 'value', min: 0, max: 100, axisLabel: { color: '#718096', fontSize: 10 }, splitLine: { lineStyle: { color: '#1a2035' } } },
      series: [
        { name: 'RSI(14)', type: 'line', data: rsi, smooth: true, symbol: 'none', lineStyle: { color: '#68d391', width: 1.5 },
          markLine: { silent: true, data: [{ yAxis: 70, lineStyle: { color: '#f56565', type: 'dashed' } }, { yAxis: 30, lineStyle: { color: '#48bb78', type: 'dashed' } }] } },
      ],
    }
  }
  return null
})

const intradayOption = computed(() => {
  if (!intradayBars.value.length) return null
  const times = intradayBars.value.map(b => b.datetime.slice(11, 16))
  const closes = intradayBars.value.map(b => b.close)
  const opens = intradayBars.value.map(b => b.open)
  const base = opens[0]

  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, formatter: p => `${p[0].name}<br/>价格: ¥${p[0].value?.toFixed(2)}` },
    grid: { left: 65, right: 20, top: 16, bottom: 36 },
    dataZoom: [{ type: 'inside' }],
    xAxis: { type: 'category', data: times, axisLabel: { color: '#718096', fontSize: 10 }, axisLine: { lineStyle: { color: '#2d3748' } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#718096', fontSize: 11 }, axisLine: { lineStyle: { color: '#2d3748' } }, splitLine: { lineStyle: { color: '#1a2035' } } },
    series: [{
      type: 'line', data: closes, smooth: false, symbol: 'circle', symbolSize: 3,
      lineStyle: { color: '#3b82f6', width: 2 },
      itemStyle: { color: '#3b82f6' },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(59,130,246,0.25)' }, { offset: 1, color: 'rgba(59,130,246,0)' }] } },
      markLine: { silent: true, data: [{ yAxis: base, lineStyle: { color: '#718096', type: 'dashed', width: 1 } }] },
    }],
  }
})

const intradayVolumeOption = computed(() => {
  if (!intradayBars.value.length) return null
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 65, right: 20, top: 4, bottom: 28 },
    xAxis: { type: 'category', data: intradayBars.value.map(b => b.datetime.slice(11, 16)), axisLabel: { color: '#718096', fontSize: 10 }, axisLine: { lineStyle: { color: '#2d3748' } } },
    yAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (v/1e4).toFixed(0)+'W' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    series: [{ type: 'bar', data: intradayBars.value.map(b => ({ value: b.volume, itemStyle: { color: b.close >= b.open ? '#48bb78' : '#f56565', opacity: 0.75 } })) }],
  }
})

// Init
applyPreset({ label: '1Y', months: 12 })
loadDaily()
</script>

<style scoped>
.market-view { padding: 24px; display: flex; flex-direction: column; gap: 12px; }

.toolbar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 12px 16px;
}

.symbol-input { width: 200px; padding-right: 58px; }
.search-group { position: relative; display: flex; align-items: center; }
.exchange-badge { position: absolute; right: 8px; font-family: var(--font-mono); font-size: 10px; background: var(--accent-dim); color: var(--accent); padding: 2px 6px; border-radius: 3px; pointer-events: none; }

.view-toggle { display: flex; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 2px; }
.toggle-btn { padding: 4px 12px; font-size: 12px; border: none; background: transparent; color: var(--text-3); border-radius: calc(var(--radius-md) - 2px); cursor: pointer; transition: all 0.12s; }
.toggle-btn.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(0,0,0,0.3); }

.preset-group { display: flex; gap: 4px; flex-wrap: wrap; }
.preset-btn { background: var(--bg-elevated); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; padding: 4px 9px; font-size: 12px; cursor: pointer; transition: all 0.12s; }
.preset-btn.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.preset-btn:hover:not(.active) { background: var(--bg-hover); }

.klt-group { display: flex; gap: 4px; }

.date-group { display: flex; align-items: center; gap: 6px; }
.date-input { padding: 6px 8px; font-size: 12px; width: 130px; }

/* Indicator bar */
.indicators-bar {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  padding: 8px 14px;
}
.ind-label { font-size: 11px; color: var(--text-3); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.ind-sep { width: 1px; height: 16px; background: var(--border); margin: 0 4px; }
.ind-btn { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-elevated); color: var(--text-3); cursor: pointer; transition: all 0.12s; }
.ind-btn:hover { color: var(--text-1); }

/* Charts */
.chart-card { padding: 14px; overflow: hidden; }
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.fw-600 { font-weight: 600; }

/* Bar detail */
.bar-detail { padding: 12px 16px; }
.bar-detail-row { display: flex; gap: 20px; flex-wrap: wrap; }
.bar-detail-item { display: flex; flex-direction: column; gap: 2px; }
.bar-detail-label { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
.bar-detail-val { font-size: 14px; font-weight: 600; }

/* Stats */
.stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
.stat { padding: 12px 16px; }
.stat-label { font-size: 11px; color: var(--text-3); margin-bottom: 4px; }
.stat-value { font-size: 18px; font-weight: 700; }

/* Empty */
.empty-state { padding: 60px; text-align: center; }
.empty-icon { font-size: 40px; margin-bottom: 16px; }
.empty-hint { font-size: 12px; color: var(--text-3); margin-top: 6px; }

.btn-intraday { background: var(--accent-dim); color: var(--accent); border: 1px solid var(--accent); border-radius: var(--radius-sm); padding: 4px 10px; font-size: 12px; cursor: pointer; display: flex; align-items: center; gap: 5px; }
.btn-intraday:hover { opacity: 0.85; }

@media (max-width: 768px) {
  .stats-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 480px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
