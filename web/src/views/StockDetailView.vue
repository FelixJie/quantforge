<template>
  <div class="detail">
    <!-- 顶栏 -->
    <div class="detail-bar">
      <button class="icon-btn" @click="$router.back()" title="返回">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div class="title-wrap">
        <span class="d-name">{{ q.name || '--' }}</span>
        <span class="d-code mono">{{ plainCode }}</span>
        <span v-if="q.change_pct != null" :class="['d-trend', cls]">{{ q.change_pct >= 0 ? '▲' : '▼' }}</span>
      </div>
      <div class="bar-spacer"></div>
      <button class="icon-btn" :class="{ starred: inList }" @click="toggleWatchlist" :title="inList ? '移出自选' : '加入自选'">
        <svg width="18" height="18" viewBox="0 0 24 24" :fill="inList ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
      </button>
    </div>

    <!-- 行情 + 指标 -->
    <div class="card hero">
      <div class="hero-price">
        <span :class="['big-price', cls]">{{ fmt(q.price) }}</span>
        <div class="chg-col">
          <span :class="['chg', cls]">{{ q.change_amt != null ? (q.change_amt >= 0 ? '+' : '') + q.change_amt.toFixed(2) : '--' }}</span>
          <span :class="['chg-badge', cls]">{{ q.change_pct != null ? (q.change_pct >= 0 ? '+' : '') + q.change_pct.toFixed(2) + '%' : '--' }}</span>
        </div>
      </div>
      <div class="metrics">
        <div class="m"><span class="mk">今开</span><span :class="cmp(q.open)">{{ fmt(q.open) }}</span></div>
        <div class="m"><span class="mk">最高</span><span :class="cmp(q.high)">{{ fmt(q.high) }}</span></div>
        <div class="m"><span class="mk">最低</span><span :class="cmp(q.low)">{{ fmt(q.low) }}</span></div>
        <div class="m"><span class="mk">昨收</span><span class="mv">{{ fmt(q.last_close) }}</span></div>
        <div class="m"><span class="mk">成交额</span><span class="mv">{{ amtWan(q.amount_wan) }}</span></div>
        <div class="m"><span class="mk">换手率</span><span class="mv">{{ pct(q.turnover_pct) }}</span></div>
        <div class="m"><span class="mk">振幅</span><span class="mv">{{ pct(q.amplitude_pct) }}</span></div>
        <div class="m"><span class="mk">量比</span><span class="mv">{{ fmt(q.vol_ratio) }}</span></div>
        <div class="m"><span class="mk">市盈(TTM)</span><span class="mv">{{ fmt(q.pe_ttm) }}</span></div>
        <div class="m"><span class="mk">市净率</span><span class="mv">{{ fmt(q.pb) }}</span></div>
        <div class="m"><span class="mk">总市值</span><span class="mv">{{ capYi(q.mcap_yi) }}</span></div>
        <div class="m"><span class="mk">流通市值</span><span class="mv">{{ capYi(q.float_mcap_yi) }}</span></div>
        <div class="m"><span class="mk">涨停</span><span class="up">{{ fmt(q.limit_up) }}</span></div>
        <div class="m"><span class="mk">跌停</span><span class="down">{{ fmt(q.limit_down) }}</span></div>
      </div>
    </div>

    <!-- K线 -->
    <div class="card kline">
      <div class="kline-head">
        <span class="text-1 fw-600">K线走势</span>
        <div class="period-tabs">
          <button v-for="p in periods" :key="p.key"
            :class="['ptab', klinePeriod === p.key ? 'active' : '']"
            @click="changePeriod(p.key)">{{ p.label }}</button>
        </div>
      </div>
      <div v-if="klineLoading" class="kline-loading"><span class="spinner spinner-sm"></span> 加载K线...</div>
      <div v-else-if="!bars.length" class="kline-empty">暂无K线数据</div>
      <div v-else ref="chartRef" class="chart-box"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'

const route = useRoute()
const watchlistStore = useWatchlistStore()

const plainCode = computed(() => {
  let c = String(route.query.symbol || '000001').toUpperCase()
  return c.replace(/^(SH|SZ|BJ)/, '').replace(/\.(SH|SZ|BJ)$/, '')
})

const q = reactive({})
const bars = ref([])
const klinePeriod = ref('day')
const klineLoading = ref(false)
const chartRef = ref(null)
let chartInstance = null

const periods = [
  { key: 'day', label: '日K', count: 250 },
  { key: 'week', label: '周K', count: 250 },
  { key: 'month', label: '月K', count: 180 },
]

const inList = computed(() => watchlistStore.isInWatchlist(plainCode.value))
const cls = computed(() => (q.change_pct == null ? '' : q.change_pct >= 0 ? 'up' : 'down'))

function cmp(v) {
  if (v == null || q.last_close == null) return 'mv'
  return v > q.last_close ? 'up' : v < q.last_close ? 'down' : 'mv'
}
function fmt(v) { return v != null ? Number(v).toFixed(2) : '--' }
function pct(v) { return v != null ? Number(v).toFixed(2) + '%' : '--' }
function amtWan(v) {
  if (!v) return '--'
  const yuan = v * 10000
  if (yuan >= 1e8) return (yuan / 1e8).toFixed(2) + '亿'
  return (v).toFixed(0) + '万'
}
function capYi(v) {
  if (!v) return '--'
  if (v >= 10000) return (v / 10000).toFixed(2) + '万亿'
  return v.toFixed(0) + '亿'
}

async function loadQuote() {
  try {
    const res = await axios.get(`/api/market/quote/${plainCode.value}`)
    Object.assign(q, res.data)
  } catch (e) {
    console.error('quote load failed', e)
  }
}

async function loadKline() {
  klineLoading.value = true
  try {
    const p = periods.find(x => x.key === klinePeriod.value)
    const res = await axios.get(`/api/market/kline/${plainCode.value}`, {
      params: { period: klinePeriod.value, count: p.count },
    })
    bars.value = res.data.bars || []
    if (bars.value.length) renderChart()
  } catch (e) {
    console.error('kline load failed', e)
    bars.value = []
  } finally {
    klineLoading.value = false
  }
}

function changePeriod(key) {
  klinePeriod.value = key
  loadKline()
}

function toggleWatchlist() {
  if (inList.value) watchlistStore.removeFromWatchlist(plainCode.value)
  else watchlistStore.addToWatchlist({ code: plainCode.value, name: q.name })
}

function renderChart() {
  nextTick(() => {
    if (!chartRef.value) return
    if (chartInstance) chartInstance.dispose()
    chartInstance = echarts.init(chartRef.value)
    const dates = bars.value.map(b => b.datetime)
    const kv = bars.value.map(b => [b.open, b.close, b.low, b.high])
    const vol = bars.value.map(b => b.volume || 0)
    const up = '#f5394c', down = '#20b26c'
    chartInstance.setOption({
      backgroundColor: 'transparent',
      animation: false,
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(14,22,36,0.95)', borderColor: '#1e2e44', textStyle: { color: '#e2eaf4', fontSize: 11 } },
      grid: [
        { left: 56, right: 16, top: 12, height: '62%' },
        { left: 56, right: 16, top: '74%', height: '18%' },
      ],
      xAxis: [
        { type: 'category', data: dates, boundaryGap: true, axisLine: { lineStyle: { color: '#1e2e44' } }, axisLabel: { show: false }, axisTick: { show: false } },
        { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: '#1e2e44' } }, axisLabel: { color: '#344d64', fontSize: 10 }, axisTick: { show: false } },
      ],
      yAxis: [
        { scale: true, splitNumber: 4, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#6a859e', fontSize: 10 }, splitLine: { lineStyle: { color: '#162030' } } },
        { gridIndex: 1, scale: true, splitNumber: 2, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 }],
      series: [
        { type: 'candlestick', data: kv, itemStyle: { color: up, color0: down, borderColor: up, borderColor0: down } },
        { type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vol.map((v, i) => ({ value: v, itemStyle: { color: kv[i][1] >= kv[i][0] ? up : down, opacity: 0.55 } })) },
      ],
    })
  })
}

function onResize() { if (chartInstance) chartInstance.resize() }

watch(plainCode, () => { loadQuote(); loadKline() })

onMounted(() => {
  loadQuote()
  loadKline()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (chartInstance) chartInstance.dispose()
})
</script>

<style scoped>
.detail { padding: 20px 24px; display: flex; flex-direction: column; gap: 14px; }

/* 顶栏 */
.detail-bar { display: flex; align-items: center; gap: 12px; }
.icon-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 1px solid var(--border); background: var(--bg-elevated); color: var(--text-2); border-radius: var(--radius-md); cursor: pointer; transition: all 0.15s; }
.icon-btn:hover { color: var(--text-1); border-color: var(--border-light); }
.icon-btn.starred { color: #f5b301; border-color: rgba(245,179,1,0.4); }
.title-wrap { display: flex; align-items: baseline; gap: 10px; }
.d-name { font-size: 20px; font-weight: 700; color: var(--text-1); }
.d-code { font-size: 13px; color: var(--text-3); }
.d-trend.up { color: var(--up); } .d-trend.down { color: var(--down); }
.bar-spacer { flex: 1; }

/* 卡片 */
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-xl); padding: 16px; }
.fw-600 { font-weight: 600; }

/* 行情 hero */
.hero-price { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 16px; }
.big-price { font-size: 40px; font-weight: 700; font-family: var(--font-mono); line-height: 1; color: var(--text-1); }
.big-price.up { color: var(--up); } .big-price.down { color: var(--down); }
.chg-col { display: flex; flex-direction: column; gap: 4px; padding-bottom: 4px; }
.chg { font-size: 15px; font-weight: 600; font-family: var(--font-mono); }
.chg.up { color: var(--up); } .chg.down { color: var(--down); }
.chg-badge { font-size: 14px; font-weight: 700; font-family: var(--font-mono); padding: 2px 8px; border-radius: 5px; text-align: center; }
.chg-badge.up { color: var(--up); background: rgba(245,57,76,0.14); }
.chg-badge.down { color: var(--down); background: rgba(32,178,108,0.14); }

.metrics { display: grid; grid-template-columns: repeat(7, 1fr); gap: 12px 16px; }
.m { display: flex; flex-direction: column; gap: 3px; }
.mk { font-size: 11px; color: var(--text-3); }
.m > span:last-child, .mv { font-size: 14px; font-family: var(--font-mono); color: var(--text-1); }
.m .up { color: var(--up); } .m .down { color: var(--down); }

/* K线 */
.kline-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.period-tabs { display: flex; gap: 4px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; }
.ptab { padding: 5px 14px; border: none; background: transparent; color: var(--text-3); font-size: 12px; border-radius: calc(var(--radius-md) - 2px); cursor: pointer; transition: all 0.15s; }
.ptab:hover { color: var(--text-1); }
.ptab.active { background: var(--bg-elevated); color: var(--accent); }
.chart-box { width: 100%; height: 420px; }
.kline-loading, .kline-empty { display: flex; align-items: center; justify-content: center; gap: 10px; height: 420px; color: var(--text-3); font-size: 13px; }

@media (max-width: 900px) {
  .metrics { grid-template-columns: repeat(4, 1fr); }
}
@media (max-width: 560px) {
  .metrics { grid-template-columns: repeat(2, 1fr); }
}
</style>
