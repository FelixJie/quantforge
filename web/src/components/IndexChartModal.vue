<template>
  <Teleport to="body">
    <div class="icm-overlay" @click.self="$emit('close')">
      <div class="icm-modal">
        <!-- ── 头部：指数名 + 实时价 ─────────────────────────── -->
        <div class="icm-head">
          <div class="icm-title">
            <span class="icm-name">{{ index.name }}</span>
            <span class="icm-code mono">{{ index.chart_code }}</span>
          </div>
          <div :class="['icm-quote', quoteCls]">
            <span class="icm-price mono">{{ index.price != null ? index.price.toFixed(2) : '--' }}</span>
            <span class="icm-chg mono">{{ fmtChg(index.change) }}</span>
            <span class="icm-pct mono">{{ fmtPct(index.change_pct) }}</span>
          </div>
          <button class="icm-close" @click="$emit('close')" title="关闭">×</button>
        </div>

        <!-- ── 周期 tabs ─────────────────────────────────────── -->
        <div class="icm-tabs">
          <button v-for="p in periods" :key="p.key"
            :class="['icm-tab', period === p.key ? 'active' : '']"
            @click="setPeriod(p.key)">{{ p.label }}</button>
          <span class="icm-tab-spacer"></span>
          <span v-if="updatedAt" class="icm-updated">{{ updatedAt }} 更新</span>
        </div>

        <!-- ── 图表 ──────────────────────────────────────────── -->
        <div class="icm-chart">
          <div v-if="loading" class="icm-loading"><span class="spinner"></span><span>加载{{ periodLabel }}…</span></div>
          <template v-else>
            <v-chart v-if="period === 'fenshi'" :option="fenshiOption" autoresize class="icm-canvas" />
            <v-chart v-else :option="klineOption" autoresize class="icm-canvas" />
            <div v-if="!bars.length" class="icm-empty">暂无{{ periodLabel }}数据</div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import VChart from '../charts'
import * as TA from '../utils/indicators.js'

const props = defineProps({ index: { type: Object, required: true } })
const emit = defineEmits(['close'])

// 同花顺白底风：红涨绿跌 + 橙黄均价线；白底+浅网格
const UP = '#dc2626', DOWN = '#16a34a', AVG = '#f0a020'
const BG = '#ffffff', GRID = '#eef1f5', AXIS = '#8a94a6', BASE_LINE = '#cbd5e1'
// 左轴点位/右轴涨跌幅刻度按昨收上色（同花顺：上红下绿）
const axisColorBy = base => v => { const n = +v; return n > base ? UP : n < base ? DOWN : AXIS }
const pctColor = v => { const n = +v; return n > 0 ? UP : n < 0 ? DOWN : AXIS }

// 按指数能力拼周期 tab：A股指数全量；恒指无分钟K；美指仅日/周/月K
const periods = computed(() => {
  const out = []
  if (props.index.chart_minute) out.push({ key: 'fenshi', label: '分时' })
  out.push({ key: 'day', label: '日K' }, { key: 'week', label: '周K' }, { key: 'month', label: '月K' })
  if (props.index.chart_mkline) {
    out.push({ key: 'm5', label: '5分' }, { key: 'm15', label: '15分' },
      { key: 'm30', label: '30分' }, { key: 'm60', label: '60分' })
  }
  return out
})

const period = ref('')
const bars = ref([])
const fenshi = ref({ points: [], pre_close: null })
const loading = ref(false)
const updatedAt = ref('')
const zoomStart = ref(60)

const periodLabel = computed(() => periods.value.find(p => p.key === period.value)?.label || 'K线')
const quoteCls = computed(() => {
  const p = props.index.change_pct
  return p > 0 ? 'up' : p < 0 ? 'down' : ''
})

function fmtChg(v) { return v == null ? '--' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) }
function fmtPct(v) { return v == null ? '--' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }

async function loadBars() {
  loading.value = true
  try {
    if (period.value === 'fenshi') {
      const r = await axios.get(`/api/market/minute/${props.index.chart_code}`)
      fenshi.value = { points: r.data.points || [], pre_close: r.data.pre_close }
      bars.value = fenshi.value.points
    } else {
      const r = await axios.get(`/api/market/kline/${props.index.chart_code}`,
        { params: { period: period.value, count: 320 } })
      bars.value = r.data.bars || []
      zoomStart.value = bars.value.length > 120 ? Math.round((1 - 120 / bars.value.length) * 100) : 0
    }
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { bars.value = [] } finally { loading.value = false }
}

function setPeriod(p) { period.value = p; loadBars() }

// 分时盘中 60s 自动刷新（K 线历史不变，无需轮询）
let _timer = null
onMounted(() => {
  period.value = periods.value[0].key
  loadBars()
  _timer = setInterval(() => {
    if (period.value === 'fenshi' && document.visibilityState !== 'hidden') loadBars()
  }, 60000)
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  if (_timer) clearInterval(_timer)
  window.removeEventListener('keydown', onKey)
})
function onKey(e) { if (e.key === 'Escape') emit('close') }

// ── 分时图：价+均价主图(左价/右涨跌幅%) + 量副图 ─────────────────
const fenshiOption = computed(() => {
  const pts = fenshi.value.points
  if (!pts.length) return {}
  const base = fenshi.value.pre_close || pts[0]?.price || 0
  const times = pts.map(p => p.time.length === 4 ? p.time.slice(0, 2) + ':' + p.time.slice(2) : p.time)
  const prices = pts.map(p => p.price)
  // 均价线：点位按成交量加权的累计均价(同花顺口径)，含义正确不受"手/股"单位影响
  let cumPV = 0, cumV = 0
  const avgs = pts.map(p => { const v = p.volume || 0; cumPV += p.price * v; cumV += v; return cumV ? +(cumPV / cumV).toFixed(2) : p.price })
  const isUp = (prices[prices.length - 1] ?? base) >= base
  const range = Math.max(...prices.map(p => Math.abs(p - base)), ...avgs.map(a => Math.abs(a - base)), base * 0.001)
  const main = isUp ? UP : DOWN
  const pctRange = +(range / base * 100).toFixed(2)

  return {
    backgroundColor: BG, animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' },
      backgroundColor: '#fff', borderColor: GRID, textStyle: { color: '#1e293b', fontSize: 11 },
      formatter: ps => {
        const pp = ps.find(x => x.seriesName === '点位'); if (!pp) return ''
        const ap = ps.find(x => x.seriesName === '均价')
        const chg = (pp.value - base) / base * 100
        let h = `${pp.name}<br/>点位 <b style="color:${pp.value >= base ? UP : DOWN}">${pp.value}</b> (${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%)`
        if (ap && ap.value != null) h += `<br/>均价 <b style="color:${AVG}">${ap.value}</b>`
        return h
      } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 60, right: 60, top: 12, height: '62%' },
      { left: 60, right: 60, top: '78%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: times, gridIndex: 0, boundaryGap: false,
        axisLabel: { show: false }, axisLine: { lineStyle: { color: GRID } }, axisTick: { show: false } },
      { type: 'category', data: times, gridIndex: 1, boundaryGap: false,
        axisLabel: { color: AXIS, fontSize: 9 }, axisLine: { lineStyle: { color: GRID } }, axisTick: { show: false } },
    ],
    yAxis: [
      { scale: false, min: +(base - range).toFixed(2), max: +(base + range).toFixed(2), gridIndex: 0,
        splitLine: { lineStyle: { color: GRID } }, axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: axisColorBy(base), fontSize: 10, formatter: v => (+v).toFixed(2) } },
      { scale: true, gridIndex: 1, splitNumber: 2, splitLine: { show: false },
        axisLabel: { color: AXIS, fontSize: 9 }, axisLine: { show: false }, axisTick: { show: false } },
      // 右侧涨跌幅轴(与价格轴同 grid 等比映射，刻度按正负上色)
      { gridIndex: 0, min: -pctRange, max: pctRange, position: 'right', splitLine: { show: false },
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: { color: pctColor, fontSize: 10, formatter: v => `${v >= 0 ? '+' : ''}${(+v).toFixed(2)}%` } },
    ],
    series: [
      { name: '点位', type: 'line', data: prices, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, z: 3,
        lineStyle: { color: main, width: 1.3 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: main + '33' }, { offset: 1, color: main + '00' }] } },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: BASE_LINE, type: 'dashed' }, data: [{ yAxis: base }],
          label: { formatter: `昨收 ${base}`, color: AXIS, fontSize: 9, position: 'insideStartTop' } } },
      { name: '均价', type: 'line', data: avgs, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, z: 2,
        lineStyle: { color: AVG, width: 1 } },
      { name: '量', type: 'bar', data: pts.map(p => p.volume), xAxisIndex: 1, yAxisIndex: 1,
        itemStyle: { color: p => (prices[p.dataIndex] >= (p.dataIndex > 0 ? prices[p.dataIndex - 1] : base) ? UP : DOWN) + '99' } },
    ],
  }
})

// ── K线图：蜡烛 + MA5/10/20 + 量副图 + 缩放 ──────────────────────
const klineOption = computed(() => {
  const b = bars.value
  if (!b.length || period.value === 'fenshi') return {}
  const dates = b.map(x => x.date || x.datetime)
  const candle = b.map(x => [x.open, x.close, x.low, x.high])

  const series = [{
    name: 'K', type: 'candlestick', data: candle, xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
  }]
  const mas = [[5, '#b45309'], [10, '#16a34a'], [20, '#2563eb']]
  for (const [n, color] of mas) {
    series.push({ name: `MA${n}`, type: 'line', data: TA.MA(TA.closes(b), n),
      xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { color, width: 1 } })
  }
  series.push({ name: '量', type: 'bar', data: b.map(x => x.volume), xAxisIndex: 1, yAxisIndex: 1,
    itemStyle: { color: p => (b[p.dataIndex].close >= b[p.dataIndex].open ? UP : DOWN) + '99' } })

  return {
    backgroundColor: BG, animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
      backgroundColor: '#fff', borderColor: GRID, textStyle: { color: '#1e293b', fontSize: 11 },
      formatter: ps => {
        if (!ps?.length) return ''
        let html = `<div style="font-weight:600;margin-bottom:2px">${ps[0].axisValue}</div>`
        for (const p of ps) {
          if (p.seriesName === 'K') {
            const d = p.data
            const c = d[2] >= d[1] ? UP : DOWN
            html += `<div style="color:${c}">开 <b>${d[1]}</b>&nbsp; 收 <b>${d[2]}</b><br/>高 <b>${d[4]}</b>&nbsp; 低 <b>${d[3]}</b></div>`
          } else if (p.value != null && !Array.isArray(p.value)) {
            html += `<div>${p.marker}${p.seriesName} <b>${typeof p.value === 'number' ? p.value.toFixed(2) : p.value}</b></div>`
          }
        }
        return html
      } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 64, right: 16, top: 12, height: '60%' },
      { left: 64, right: 16, top: '76%', height: '14%' },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
        axisLine: { lineStyle: { color: GRID } }, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
        axisLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, fontSize: 10 } },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: GRID } },
        axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { show: false } },
      { scale: true, gridIndex: 1, splitNumber: 2, splitLine: { show: false },
        axisLabel: { color: AXIS, fontSize: 9 }, axisLine: { show: false } },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: zoomStart.value, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1], height: 16, bottom: 6, start: zoomStart.value, end: 100 },
    ],
    series,
  }
})
</script>

<style scoped>
.icm-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center;
  padding: 24px;
}
.icm-modal {
  width: min(960px, 100%); max-height: calc(100vh - 48px);
  display: flex; flex-direction: column;
  background: var(--bg-surface, #fff);
  border: 1px solid var(--border, #e2e8f0);
  border-radius: 12px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.25);
  overflow: hidden;
}

.icm-head {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 18px 10px;
  border-bottom: 1px solid var(--border, #e2e8f0);
}
.icm-title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.icm-name { font-size: 16px; font-weight: 700; color: var(--text-1, #1e293b); }
.icm-code { font-size: 11px; color: var(--text-3, #94a3b8); text-transform: uppercase; }
.icm-quote { display: flex; align-items: baseline; gap: 8px; }
.icm-price { font-size: 18px; font-weight: 700; }
.icm-chg, .icm-pct { font-size: 12.5px; font-weight: 600; }
.icm-quote.up   { color: var(--up, #dc2626); }
.icm-quote.down { color: var(--down, #16a34a); }
.icm-close {
  margin-left: auto; flex-shrink: 0;
  width: 30px; height: 30px; line-height: 1;
  border: 1px solid var(--border, #e2e8f0); border-radius: 8px;
  background: transparent; color: var(--text-2, #64748b);
  font-size: 18px; cursor: pointer; transition: all .15s;
}
.icm-close:hover { color: var(--text-1, #1e293b); border-color: var(--text-3, #94a3b8); }

.icm-tabs {
  display: flex; align-items: center; gap: 4px;
  padding: 8px 18px; border-bottom: 1px solid var(--border, #e2e8f0);
  flex-wrap: wrap;
}
.icm-tab {
  padding: 4px 12px; font-size: 12.5px; border-radius: 6px;
  border: 1px solid transparent; background: transparent;
  color: var(--text-2, #64748b); cursor: pointer; transition: all .15s;
}
.icm-tab:hover { color: var(--text-1, #1e293b); }
.icm-tab.active {
  color: var(--accent, #2563eb); font-weight: 600;
  background: var(--accent-bg, rgba(37, 99, 235, .08));
  border-color: var(--accent-border, rgba(37, 99, 235, .25));
}
.icm-tab-spacer { flex: 1; }
.icm-updated { font-size: 11px; color: var(--text-3, #94a3b8); }

.icm-chart { position: relative; padding: 8px 10px 12px; }
.icm-canvas { height: 440px; width: 100%; }
.icm-loading, .icm-empty {
  height: 440px; display: flex; align-items: center; justify-content: center;
  gap: 8px; color: var(--text-3, #94a3b8); font-size: 13px;
}
.icm-empty { position: absolute; inset: 8px 10px 12px; pointer-events: none; }

@media (max-width: 768px) {
  .icm-overlay { padding: 0; align-items: flex-end; }
  .icm-modal { width: 100%; max-height: 92vh; border-radius: 14px 14px 0 0; }
  .icm-canvas, .icm-loading { height: 340px; }
  .icm-head { padding: 12px 14px 8px; gap: 10px; }
  .icm-price { font-size: 16px; }
  .icm-tabs { padding: 8px 12px; }
}
</style>
