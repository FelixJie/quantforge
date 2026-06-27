<template>
  <div class="compare">
    <!-- 顶栏 -->
    <div class="cmp-head">
      <div>
        <h2 class="cmp-title">个股对比</h2>
        <p class="cmp-sub text-3">最多同时对比 6 只个股，横向看清行情、估值、技术、动量与机构目标价。</p>
      </div>
    </div>

    <!-- 选股输入区 -->
    <div class="card pick-card">
      <div class="pick-row">
        <div class="search-wrap">
          <input
            class="input"
            v-model="kw"
            placeholder="输入代码或名称添加，如 600519 / 贵州茅台"
            @input="onSearch"
            @keyup.enter="addFirstMatch"
          />
          <div v-if="suggests.length" class="suggest-pop">
            <div
              v-for="s in suggests"
              :key="s.symbol"
              class="suggest-item"
              @click="addStock(s.symbol, s.name)"
            >
              <span class="sg-name">{{ s.name }}</span>
              <span class="sg-code mono text-3">{{ s.symbol }}</span>
            </div>
          </div>
        </div>
        <button class="btn-ghost wl-toggle" @click="toggleWlPanel">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
          从自选选择
        </button>
        <select class="input period-sel" v-model.number="days">
          <option :value="60">近 60 日</option>
          <option :value="120">近 120 日</option>
          <option :value="180">近 180 日</option>
          <option :value="250">近 1 年</option>
        </select>
        <button class="btn-primary" :disabled="picked.length < 2 || loading" @click="runCompare">
          <span v-if="loading" class="spinner spinner-sm"></span>
          {{ loading ? '对比中...' : '开始对比' }}
        </button>
      </div>

      <!-- 自选股勾选面板 -->
      <div v-if="showWlPanel" class="wl-panel">
        <div class="wl-panel-head">
          <span class="wl-panel-title">从自选股加入对比（已选 {{ picked.length }}/6）</span>
          <button class="link-btn" @click="showWlPanel = false">收起</button>
        </div>
        <div v-if="!wlList.length" class="wl-panel-empty text-3">
          自选股为空，先到「自选」页添加。
        </div>
        <div v-else class="wl-grid">
          <button
            v-for="s in wlList"
            :key="s.code"
            :class="['wl-pick', { on: isPicked(s.code) }]"
            :disabled="!isPicked(s.code) && picked.length >= 6"
            @click="toggleFromWl(s)"
          >
            <span class="wl-pick-name">{{ s.name }}</span>
            <span class="wl-pick-code mono text-3">{{ s.code }}</span>
            <span v-if="isPicked(s.code)" class="wl-pick-on">✓</span>
          </button>
        </div>
      </div>

      <!-- 已选标签 -->
      <div v-if="picked.length" class="chip-row">
        <span v-for="p in picked" :key="p.symbol" class="pick-chip">
          {{ p.name }}<span class="mono text-3">{{ p.symbol }}</span>
          <button class="chip-x" @click="removeStock(p.symbol)">×</button>
        </span>
      </div>
      <div v-else class="chip-empty text-3">还没有选择股票。也可以快速添加示例：
        <button class="link-btn" @click="loadDemo">茅台 vs 五粮液</button>
      </div>
    </div>

    <!-- 结果区 -->
    <template v-if="result">
      <!-- 归一化走势叠加 -->
      <div class="card chart-card">
        <div class="sec-title-row">
          <span class="sec-title">区间走势对比</span>
          <span class="text-3 tiny">首日基准 = 100，反映区间相对涨跌</span>
        </div>
        <v-chart v-if="chartOption" class="cmp-chart" :option="chartOption" autoresize />
      </div>

      <!-- 对比表 -->
      <div class="card table-card">
        <div class="sec-title-row"><span class="sec-title">详细对比</span></div>
        <div class="table-scroll">
          <table class="cmp-table">
            <thead>
              <tr>
                <th class="metric-col">指标</th>
                <th v-for="s in stocks" :key="s.symbol">
                  <div class="th-name">{{ s.name }}</div>
                  <div class="th-code mono text-3">{{ s.symbol }}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              <template v-for="grp in rowGroups" :key="grp.label">
                <tr class="grp-row"><td :colspan="stocks.length + 1">{{ grp.label }}</td></tr>
                <tr v-for="row in grp.rows" :key="row.field">
                  <td class="metric-col">{{ row.label }}</td>
                  <td
                    v-for="s in stocks"
                    :key="s.symbol"
                    :class="cellClass(row, s)"
                  >
                    <span class="cell-val">{{ renderCell(row, s) }}</span>
                    <span v-if="rankOf(row.field, s.symbol) === 1" class="best-dot" title="最优">★</span>
                  </td>
                </tr>
              </template>

              <!-- 风险提示 -->
              <tr class="grp-row"><td :colspan="stocks.length + 1">风险提示</td></tr>
              <tr>
                <td class="metric-col">主要风险</td>
                <td v-for="s in stocks" :key="s.symbol" class="risk-cell">
                  <template v-if="s.risk_items && s.risk_items.length">
                    <div v-for="(r, i) in s.risk_items" :key="i" class="risk-line">· {{ r }}</div>
                  </template>
                  <span v-else class="text-3">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else-if="!loading" class="empty-hint card">
      选择至少 2 只股票后点击「开始对比」。
    </div>
  </div>
</template>

<script setup>
import VChart from '../charts'
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'

const route = useRoute()
const watchlistStore = useWatchlistStore()
const kw = ref('')
const suggests = ref([])
const picked = ref([])          // [{symbol, name}]
const days = ref(180)
const loading = ref(false)
const result = ref(null)

// ── 从自选股选择 ──────────────────────────────────────────
const showWlPanel = ref(false)
const wlList = computed(() => watchlistStore.watchlist || [])
function isPicked(code) {
  return picked.value.some(p => p.symbol === String(code).trim().toUpperCase())
}
function toggleWlPanel() {
  showWlPanel.value = !showWlPanel.value
  if (showWlPanel.value && !wlList.value.length) watchlistStore.loadWatchlist()
}
function toggleFromWl(s) {
  if (isPicked(s.code)) removeStock(String(s.code).trim().toUpperCase())
  else addStock(s.code, s.name)
}

const stocks = computed(() => (result.value?.stocks || []).filter(s => s.ok))
const ranks = computed(() => result.value?.ranks || {})

// 涨红跌绿（A股惯例）
const upDown = (v) => (v == null ? '' : v >= 0 ? 'c-up' : 'c-down')

let searchTimer = null
function onSearch() {
  clearTimeout(searchTimer)
  const q = kw.value.trim()
  if (!q) { suggests.value = []; return }
  searchTimer = setTimeout(async () => {
    try {
      const { data } = await axios.get(`/api/market/search/${encodeURIComponent(q)}`)
      suggests.value = (data || []).slice(0, 8)
    } catch { suggests.value = [] }
  }, 250)
}

function addStock(symbol, name) {
  symbol = String(symbol).trim().toUpperCase()
  if (!symbol) return
  if (picked.value.some(p => p.symbol === symbol)) { kw.value=''; suggests.value=[]; return }
  if (picked.value.length >= 6) { alert('最多对比 6 只股票'); return }
  picked.value.push({ symbol, name: name || symbol })
  kw.value = ''
  suggests.value = []
}

function addFirstMatch() {
  if (suggests.value.length) {
    addStock(suggests.value[0].symbol, suggests.value[0].name)
  } else if (/^\d{6}$/.test(kw.value.trim())) {
    addStock(kw.value.trim(), kw.value.trim())
  }
}

function removeStock(symbol) {
  picked.value = picked.value.filter(p => p.symbol !== symbol)
}

function loadDemo() {
  picked.value = [
    { symbol: '600519', name: '贵州茅台' },
    { symbol: '000858', name: '五粮液' },
  ]
}

// 从 URL 预填（如自选股「加入对比」跳转：?symbols=600519,000858&names=贵州茅台,五粮液）
onMounted(() => {
  const raw = route.query.symbols
  if (!raw) return
  const syms = String(raw).split(',').map(s => s.trim()).filter(Boolean)
  const names = String(route.query.names || '').split(',').map(s => s.trim())
  syms.slice(0, 6).forEach((sym, i) => addStock(sym, names[i] || sym))
  if (picked.value.length >= 2) runCompare()
})

async function runCompare() {
  if (picked.value.length < 2) return
  loading.value = true
  result.value = null
  try {
    const { data } = await axios.post('/api/stock-compare', {
      symbols: picked.value.map(p => p.symbol),
      days: days.value,
    })
    result.value = data
  } catch (e) {
    alert('对比失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

// ── 表格行定义 ──────────────────────────────────────────────
const rowGroups = [
  { label: '行情', rows: [
    { field: 'price',             label: '最新价',     fmt: 'price' },
    { field: 'change_pct',        label: '当日涨跌',   fmt: 'pct', color: 'updown' },
    { field: 'period_change_pct', label: '区间涨跌',   fmt: 'pct', color: 'updown' },
    { field: 'turnover_rate',     label: '换手率',     fmt: 'pct' },
    { field: 'amplitude',         label: '振幅',       fmt: 'pct' },
    { field: 'vol_ratio',         label: '量比',       fmt: 'num2' },
  ]},
  { label: '估值', rows: [
    { field: 'pe_ttm',       label: 'PE(TTM)',  fmt: 'num2' },
    { field: 'pb',           label: '市净率',    fmt: 'num2' },
    { field: 'roe',          label: 'ROE',      fmt: 'pct' },
    { field: 'gross_margin', label: '毛利率',    fmt: 'pct' },
    { field: 'market_cap',   label: '总市值',    fmt: 'yi' },
    { field: 'circ_cap',     label: '流通市值',  fmt: 'yi' },
  ]},
  { label: '技术面', rows: [
    { field: 'signal',     label: '趋势信号', fmt: 'signal' },
    { field: 'rsi',        label: 'RSI(14)',  fmt: 'num1' },
    { field: 'macd_hist',  label: 'MACD柱',   fmt: 'num3', color: 'updown' },
    { field: 'support',    label: '支撑位',   fmt: 'price' },
    { field: 'resistance', label: '压力位',   fmt: 'price' },
  ]},
  { label: '动量与买卖点', rows: [
    { field: 'momentum_score', label: '动量评分', fmt: 'num1' },
    { field: 'momentum_state', label: '动量状态', fmt: 'state' },
    { field: 'buy_price',      label: '参考买点', fmt: 'price' },
    { field: 'stop_price',     label: '止损位',   fmt: 'price' },
    { field: 'target_price',   label: '技术目标', fmt: 'price' },
  ]},
  { label: '机构一致预期', rows: [
    { field: 'consensus_median', label: '一致目标价', fmt: 'price' },
    { field: 'consensus_upside', label: '上行空间',   fmt: 'pct', color: 'updown' },
    { field: 'consensus_count',  label: '研报数',     fmt: 'int' },
    { field: 'rating_top',       label: '主流评级',   fmt: 'text' },
    { field: 'risk_level',       label: '风险等级',   fmt: 'risk' },
  ]},
]

const signalText = { bullish: '看涨', bearish: '看跌', neutral: '震荡' }
const stateText  = { buy: '买入', sell: '卖出', strong: '强势', weak: '弱势', hold: '持有', neutral: '中性' }

function fmtNum(v, d) { return v == null ? '—' : Number(v).toFixed(d) }
function fmtPct(v)    { return v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }
function fmtYi(v)     { return v == null ? '—' : (v / 1e8).toFixed(1) + '亿' }

function renderCell(row, s) {
  const v = s[row.field]
  switch (row.fmt) {
    case 'price': return v == null ? '—' : Number(v).toFixed(2)
    case 'pct':   return fmtPct(v)
    case 'num1':  return fmtNum(v, 1)
    case 'num2':  return fmtNum(v, 2)
    case 'num3':  return fmtNum(v, 3)
    case 'int':   return v == null ? '—' : v
    case 'yi':    return fmtYi(v)
    case 'signal': return signalText[v] || '—'
    case 'state':  return stateText[v] || (v ?? '—')
    case 'risk':   return v || '—'
    case 'text':   return v || '—'
    default:       return v ?? '—'
  }
}

function cellClass(row, s) {
  const cls = ['data-cell']
  const v = s[row.field]
  if (row.color === 'updown') cls.push(upDown(v))
  if (row.fmt === 'signal') cls.push(v === 'bullish' ? 'c-up' : v === 'bearish' ? 'c-down' : '')
  if (row.fmt === 'risk') {
    cls.push(v === '高' ? 'c-up' : v === '中' ? 'c-warn' : v === '低' ? 'c-down' : '')
  }
  if (rankOf(row.field, s.symbol) === 1) cls.push('is-best')
  return cls
}

function rankOf(field, symbol) {
  return ranks.value[field]?.[symbol] ?? null
}

// ── 走势叠加图 ──────────────────────────────────────────────
const palette = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#7c3aed', '#0891b2']

const chartOption = computed(() => {
  const list = stocks.value
  if (!list.length) return null
  // 用最长的日期序列作为 X 轴
  let dates = []
  list.forEach(s => { if ((s.norm_dates || []).length > dates.length) dates = s.norm_dates })
  if (!dates.length) return null

  const series = list.map((s, i) => ({
    name: s.name,
    type: 'line',
    showSymbol: false,
    smooth: true,
    lineWidth: 1.6,
    data: alignSeries(s.norm_dates, s.norm_series, dates),
    lineStyle: { color: palette[i % palette.length] },
    itemStyle: { color: palette[i % palette.length] },
  }))

  return {
    tooltip: { trigger: 'axis' },
    legend: { data: list.map(s => s.name), top: 0, textStyle: { color: '#64748b' } },
    grid: { left: 48, right: 16, top: 36, bottom: 32 },
    xAxis: { type: 'category', data: dates, boundaryGap: false,
             axisLabel: { color: '#94a3b8', fontSize: 10 } },
    yAxis: { type: 'value', scale: true, name: '基准100',
             axisLabel: { color: '#94a3b8', fontSize: 10 },
             splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } } },
    series,
  }
})

// 把每只股票的归一化序列对齐到统一日期轴（缺失补 null）
function alignSeries(sDates, sVals, axis) {
  if (!sDates || !sVals) return axis.map(() => null)
  const map = new Map()
  sDates.forEach((d, i) => map.set(d, sVals[i]))
  return axis.map(d => (map.has(d) ? map.get(d) : null))
}
</script>

<style scoped>
.compare { max-width: 1280px; margin: 0 auto; padding: 4px; }

.cmp-head { margin-bottom: 14px; }
.cmp-title { font-size: 20px; font-weight: 700; color: var(--text-1); margin: 0; }
.cmp-sub { font-size: 13px; margin: 4px 0 0; }

.pick-card { padding: 16px; margin-bottom: 16px; }
.pick-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.search-wrap { position: relative; flex: 1; min-width: 240px; }
.period-sel { width: 130px; flex-shrink: 0; }

.btn-ghost {
  display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0;
  padding: 8px 14px; border: 1px solid var(--border, #e2e8f0);
  background: var(--bg-card, #fff); color: var(--text-2, #64748b);
  border-radius: 8px; font-size: 13px; cursor: pointer; transition: all .15s;
}
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
.wl-toggle svg { color: #f59e0b; }

.wl-panel {
  margin-top: 12px; padding: 12px; background: var(--bg-hover, #f8fafc);
  border: 1px solid var(--border, #e2e8f0); border-radius: 10px;
}
.wl-panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.wl-panel-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.wl-panel-empty { font-size: 13px; padding: 8px 2px; }
.wl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; max-height: 240px; overflow-y: auto; }
.wl-pick {
  position: relative; display: flex; flex-direction: column; gap: 2px; text-align: left;
  padding: 8px 10px; background: var(--bg-card, #fff);
  border: 1px solid var(--border, #e2e8f0); border-radius: 8px; cursor: pointer; transition: all .15s;
}
.wl-pick:hover:not(:disabled) { border-color: var(--accent); }
.wl-pick.on { border-color: var(--accent); background: var(--accent-dim); }
.wl-pick:disabled { opacity: .45; cursor: not-allowed; }
.wl-pick-name { font-size: 13px; font-weight: 500; color: var(--text-1); }
.wl-pick-code { font-size: 11px; }
.wl-pick-on { position: absolute; top: 6px; right: 8px; color: var(--accent); font-weight: 700; font-size: 12px; }

.suggest-pop {
  position: absolute; z-index: 30; top: calc(100% + 4px); left: 0; right: 0;
  background: var(--bg-card, #fff); border: 1px solid var(--border, #e2e8f0);
  border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.12); overflow: hidden;
}
.suggest-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 12px; cursor: pointer; font-size: 13px;
}
.suggest-item:hover { background: var(--bg-hover, #f1f5f9); }
.sg-name { color: var(--text-1); font-weight: 500; }

.chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.pick-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 8px 5px 11px; background: var(--accent-dim);
  border: 1px solid var(--accent); border-radius: 16px; font-size: 13px; color: var(--text-1);
}
.chip-x { border: none; background: none; cursor: pointer; font-size: 16px; line-height: 1;
  color: var(--text-3, #94a3b8); padding: 0 2px; }
.chip-x:hover { color: var(--up); }
.chip-empty { margin-top: 12px; font-size: 13px; }
.link-btn { border: none; background: none; color: var(--accent); cursor: pointer; padding: 0; font-size: 13px; }
.link-btn:hover { text-decoration: underline; }

.chart-card, .table-card { padding: 16px; margin-bottom: 16px; }
.sec-title-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 12px; }
.sec-title { font-size: 15px; font-weight: 600; color: var(--text-1); }
.tiny { font-size: 11px; }
.cmp-chart { height: 320px; width: 100%; }

.table-scroll { overflow-x: auto; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td {
  padding: 9px 14px; text-align: right; white-space: nowrap;
  border-bottom: 1px solid var(--border, #eef2f6);
}
.cmp-table thead th { position: sticky; top: 0; background: var(--bg-card, #fff); z-index: 2; }
.metric-col { text-align: left !important; color: var(--text-2, #64748b); font-weight: 500; }
.th-name { font-weight: 700; color: var(--text-1); }
.th-code { font-size: 11px; font-weight: 400; }

.grp-row td {
  text-align: left; background: var(--bg-hover, #f8fafc);
  font-weight: 600; font-size: 12px; color: var(--text-2, #64748b);
  letter-spacing: .5px; padding: 6px 14px;
}
.data-cell { font-variant-numeric: tabular-nums; position: relative; }
.is-best { font-weight: 700; }
.best-dot { color: #f59e0b; font-size: 11px; margin-left: 3px; }

.c-up   { color: var(--up, #dc2626); }
.c-down { color: var(--down, #16a34a); }
.c-warn { color: #d97706; }

.risk-cell { text-align: left !important; white-space: normal; max-width: 240px; }
.risk-line { font-size: 12px; color: var(--text-2, #64748b); line-height: 1.5; }

.empty-hint { padding: 40px; text-align: center; color: var(--text-3, #94a3b8); }
</style>
