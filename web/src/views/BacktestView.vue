<template>
  <div class="bt-view">

    <!-- ── Config card ─────────────────────────────────────────────────── -->
    <div class="cfg-card card">
      <div class="cfg-grid">

        <!-- Strategy -->
        <div class="cfg-col">
          <div class="cfg-label">策略</div>
          <select class="select-base" v-model="form.strategy">
            <option v-for="s in strategies" :key="s.module_path" :value="s.module_path">
              {{ s.display_name || s.name }}
            </option>
          </select>
          <div v-if="selectedStrategy" class="strategy-meta">
            <span :class="['badge', catBadge(selectedStrategy.category)]">{{ selectedStrategy.category_label }}</span>
            <span class="meta-txt">{{ selectedStrategy.suitable }}</span>
          </div>
        </div>

        <!-- Symbol search -->
        <div class="cfg-col cfg-col-wide" ref="pickerRef">
          <div class="cfg-label">股票标的</div>
          <div class="sym-box" @click="focusInput">
            <span v-for="sym in symbolList" :key="sym" class="sym-tag">
              <b>{{ sym }}</b>
              <span v-if="nameMap[sym]" class="sym-name">{{ nameMap[sym] }}</span>
              <button class="tag-x" @click.stop="removeSymbol(sym)">×</button>
            </span>
            <input
              ref="symInput"
              class="sym-input"
              v-model="symQ"
              placeholder="输入代码或名称搜索…"
              @input="onInput"
              @focus="showDrop = true"
              @keydown.enter.prevent="pickFirst"
              @keydown.escape="closeDrop"
            />
          </div>
          <!-- dropdown -->
          <div v-if="showDrop && (dropItems.length || (!symQ.trim() && recentItems.length))" class="sym-drop">
            <!-- Recent AI picks (when no query) -->
            <template v-if="!symQ.trim() && recentItems.length">
              <div class="drop-section-label">最近AI推荐</div>
              <div
                v-for="item in recentItems" :key="item.code + item.date"
                class="drop-row"
                @mousedown.prevent="pickItem(item)"
              >
                <span class="dr-code">{{ item.code }}</span>
                <span class="dr-name">{{ item.name }}</span>
                <span class="dr-date">{{ item.date }}</span>
                <span class="dr-tag ai-tag">AI精选</span>
              </div>
            </template>
            <!-- Search results (when typing) -->
            <template v-if="symQ.trim()">
              <div
                v-for="item in dropItems" :key="item.code"
                class="drop-row"
                @mousedown.prevent="pickItem(item)"
              >
                <span class="dr-code">{{ item.code }}</span>
                <span class="dr-name">{{ item.name }}</span>
                <span v-if="item.hasData" class="dr-tag">本地</span>
                <span class="dr-mkt">{{ item.mkt }}</span>
              </div>
            </template>
          </div>
        </div>

        <!-- Date range -->
        <div class="cfg-col">
          <div class="cfg-label">时间区间</div>
          <div class="preset-row">
            <button v-for="p in presets" :key="p.l"
              :class="['pre-chip', activePreset===p.l && 'active']"
              @click="applyPreset(p)">{{ p.l }}</button>
          </div>
          <div class="date-row">
            <input type="date" class="input date-in" v-model="form.start" @change="activePreset=''" />
            <span class="date-dash">—</span>
            <input type="date" class="input date-in" v-model="form.end" @change="activePreset=''" />
          </div>
        </div>

        <!-- Capital -->
        <div class="cfg-col">
          <div class="cfg-label">初始资金</div>
          <div class="cap-row">
            <input type="number" class="input" v-model.number="form.capital" style="flex:1;min-width:0" />
            <span class="cap-unit">元</span>
          </div>
          <label class="risk-toggle">
            <input type="checkbox" v-model="form.enable_risk" />
            <span>启用风控</span>
          </label>
        </div>

        <!-- Run -->
        <div class="cfg-col cfg-run">
          <button class="btn-primary run-btn" @click="run" :disabled="running">
            <span v-if="running" class="spinner spinner-sm"></span>
            <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            {{ running ? '运行中…' : '运行回测' }}
          </button>
          <div v-if="job" class="job-meta">
            <span :class="['badge', stBadge(job.status)]">{{ stLabel(job.status) }}</span>
          </div>
        </div>

      </div>
    </div>

    <!-- ── Results ────────────────────────────────────────────────────── -->

    <!-- Empty -->
    <div v-if="!job && !running" class="empty-card card">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
      <p>选择策略和股票，点击运行回测</p>
      <p class="empty-sub">支持全部内置策略，缺少数据时自动下载</p>
    </div>

    <template v-if="job">

      <!-- Metrics -->
      <div v-if="job.summary" class="metrics-row">
        <div class="mc" v-for="m in metrics" :key="m.label">
          <div class="mc-val" :class="m.cls">{{ m.value }}</div>
          <div class="mc-lbl">{{ m.label }}</div>
        </div>
      </div>

      <!-- K-line + signals -->
      <div v-if="klineOpt" class="card chart-wrap">
        <div class="chart-hd">
          <span class="chart-title">{{ symbolList[0] }} · K线 + 交易信号</span>
          <div class="chart-legend">
            <span class="leg"><i class="leg-dot" style="background:#ef4444"></i>开仓买入</span>
            <span class="leg"><i class="leg-dot" style="background:#22c55e"></i>平仓卖出</span>
          </div>
        </div>
        <v-chart :option="klineOpt" autoresize style="height:500px" />
      </div>

      <!-- Equity -->
      <div v-if="equityOpt" class="card chart-wrap">
        <div class="chart-hd">
          <span class="chart-title">净值曲线</span>
          <span class="chart-sub">初始 ¥{{ form.capital.toLocaleString() }}</span>
        </div>
        <v-chart :option="equityOpt" autoresize style="height:180px" />
      </div>

      <!-- Loading -->
      <div v-if="isRunning" class="card info-row">
        <span class="spinner"></span>
        <span class="text-2">策略计算中，请稍候…</span>
      </div>

      <!-- Report -->
      <div v-if="job.status==='done' && job.has_report" class="card info-row">
        <a :href="`/api/optimizer/report/${job.job_id}`" target="_blank" class="report-link">
          查看完整回测报告（含月度热力图）→
        </a>
      </div>

      <!-- Error -->
      <div v-if="job.status==='error'" class="err-box">
        <div class="err-msg">{{ job.error }}</div>
        <div v-if="dlMsg" class="dl-msg">
          <span v-if="downloading" class="spinner spinner-sm"></span>
          {{ dlMsg }}
        </div>
      </div>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()

// ── State ─────────────────────────────────────────────────────────────────────
const strategies  = ref([])
const running     = ref(false)
const downloading = ref(false)
const dlMsg       = ref('')
const job         = ref(null)
const extraBars   = ref([])
const activePreset = ref('1Y')
let pollTimer = null

const symbolList  = ref(['000001'])
const symQ        = ref('')
const nameMap     = ref({})
const localSyms   = ref(new Set())
const recentItems = ref([])   // recent AI-recommended stocks
const showDrop    = ref(false)
const symInput    = ref(null)
const pickerRef   = ref(null)

const form = ref({ strategy: '', start: '', end: '', capital: 1000000, enable_risk: false })

const presets = [
  { l: '1M', m: 1 }, { l: '3M', m: 3 }, { l: '6M', m: 6 },
  { l: '1Y', m: 12 }, { l: '2Y', m: 24 }, { l: '3Y', m: 36 },
]

// ── Dropdown ──────────────────────────────────────────────────────────────────
function inferMkt(c) {
  if (c.startsWith('6')) return 'SSE'
  if (c.startsWith('0') || c.startsWith('3')) return 'SZSE'
  if (c.startsWith('8') || c.startsWith('4')) return 'BSE'
  return ''
}

const dropItems = computed(() => {
  const q = symQ.value.trim().toLowerCase()
  if (!q) return []
  const out = []
  for (const [code, name] of Object.entries(nameMap.value)) {
    if (code.startsWith(q) || name.toLowerCase().includes(q)) {
      out.push({ code, name, hasData: localSyms.value.has(code), mkt: inferMkt(code) })
      if (out.length >= 10) break
    }
  }
  return out
})

function onInput() { showDrop.value = true }
function closeDrop() { showDrop.value = false; symQ.value = '' }
function focusInput() { nextTick(() => symInput.value?.focus()) }

function pickItem(item) {
  if (!symbolList.value.includes(item.code)) symbolList.value.push(item.code)
  symQ.value = ''; showDrop.value = false
  nextTick(() => symInput.value?.focus())
}

function pickFirst() {
  const q = symQ.value.trim()
  if (!q) return
  if (/^\d+$/.test(q)) { pickItem({ code: q, name: nameMap.value[q] || q }); return }
  if (dropItems.value.length) pickItem(dropItems.value[0])
}

function removeSymbol(s) { symbolList.value = symbolList.value.filter(x => x !== s) }

function onDocClick(e) {
  if (!pickerRef.value?.contains(e.target)) showDrop.value = false
}

// ── Form ──────────────────────────────────────────────────────────────────────
function applyPreset(p) {
  const end = new Date(), start = new Date()
  start.setMonth(start.getMonth() - p.m)
  form.value.start = start.toISOString().slice(0, 10)
  form.value.end   = end.toISOString().slice(0, 10)
  activePreset.value = p.l
}

const selectedStrategy = computed(() => strategies.value.find(s => s.module_path === form.value.strategy))
const isRunning = computed(() => job.value?.status === 'running' || job.value?.status === 'queued')

// ── Metrics ───────────────────────────────────────────────────────────────────
const metrics = computed(() => {
  const s = job.value?.summary
  if (!s) return []
  const pct = v => v != null ? (v * 100).toFixed(2) + '%' : '-'
  return [
    { label: '总收益率', value: pct(s.total_return),  cls: s.total_return >= 0 ? 'pos' : 'neg' },
    { label: '最大回撤', value: pct(s.max_drawdown),  cls: 'neg' },
    { label: '夏普比率', value: s.sharpe_ratio?.toFixed(2) ?? '-', cls: '' },
    { label: '胜率',     value: pct(s.win_rate),      cls: '' },
    { label: '交易次数', value: job.value.trade_count ?? '-', cls: '' },
    { label: '最终净值', value: '¥' + Math.round(s.final_equity || 0).toLocaleString(), cls: '' },
    { label: '均持天数', value: s.avg_hold_days ? s.avg_hold_days + 'd' : '-', cls: '' },
    { label: '最长持仓', value: s.max_hold_days ? s.max_hold_days + 'd' : '-', cls: '' },
    { label: '最佳单笔', value: s.best_trade_pct != null ? (s.best_trade_pct>0?'+':'') + s.best_trade_pct.toFixed(2)+'%' : '-', cls: s.best_trade_pct > 0 ? 'pos' : '' },
    { label: '最差单笔', value: s.worst_trade_pct != null ? s.worst_trade_pct.toFixed(2)+'%' : '-', cls: s.worst_trade_pct < 0 ? 'neg' : '' },
  ]
})

// ── K-line chart ──────────────────────────────────────────────────────────────
const klineOpt = computed(() => {
  const bars = job.value?.bars?.length ? job.value.bars : extraBars.value
  if (!bars?.length) return null

  const dates   = bars.map(b => b.date)
  const candles = bars.map(b => [b.open, b.close, b.low, b.high])
  const volumes = bars.map(b => ({
    value: b.volume,
    itemStyle: { color: b.close >= b.open ? '#ef444488' : '#22c55e88' },
  }))

  // Trade markers from round trips
  const markData = []
  for (const rt of (job.value?.round_trips || [])) {
    const bi = dates.indexOf(rt.entry_date)
    const si = dates.indexOf(rt.exit_date)
    if (bi >= 0 && bars[bi]) {
      markData.push({
        coord: [bi, bars[bi].low],
        symbol: 'triangle', symbolSize: 14, symbolRotate: 0,
        itemStyle: { color: '#ef4444' },
        label: {
          show: true, position: 'bottom', lineHeight: 14,
          formatter: `开多\n${rt.entry_price}`,
          color: '#ef4444', fontSize: 9, fontWeight: 700,
        },
      })
    }
    if (si >= 0 && bars[si]) {
      const sign = rt.pnl_pct >= 0 ? '+' : ''
      const clr  = rt.pnl_pct >= 0 ? '#22c55e' : '#f87171'
      markData.push({
        coord: [si, bars[si].high],
        symbol: 'triangle', symbolSize: 14, symbolRotate: 180,
        itemStyle: { color: clr },
        label: {
          show: true, position: 'top', lineHeight: 14,
          formatter: `平多\n${sign}${rt.pnl_pct}%`,
          color: clr, fontSize: 9, fontWeight: 700,
        },
      })
    }
  }

  const n = dates.length
  const startVal = Math.max(0, n - 120)
  return {
    backgroundColor: 'transparent', animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#374151' } },
      backgroundColor: '#1e2537', borderColor: '#2d3748',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: params => {
        const k = params.find(p => p.seriesName === 'K')
        const v = params.find(p => p.seriesName === 'Vol')
        if (!k) return ''
        const [o, c, lo, h] = k.data
        const chg = ((c - o) / o * 100).toFixed(2)
        const col = c >= o ? '#ef4444' : '#22c55e'
        return `<b>${k.name}</b><br/>
          开 ${o} &nbsp; 收 <span style="color:${col};font-weight:700">${c}</span><br/>
          高 ${h} &nbsp; 低 ${lo}<br/>
          涨跌 <span style="color:${col}">${chg >= 0 ? '+' : ''}${chg}%</span>
          &nbsp; 量 ${v ? (v.data.value/1e4).toFixed(0)+'万' : '-'}`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      { type: 'inside', xAxisIndex: [0,1], startValue: startVal, endValue: n - 1 },
      { type: 'slider', xAxisIndex: [0,1], height: 20, bottom: 2,
        startValue: startVal, endValue: n - 1,
        borderColor: 'transparent', fillerColor: 'rgba(59,130,246,0.15)',
        handleStyle: { color: '#3b82f6' }, textStyle: { color: '#6b7280' } },
    ],
    grid: [
      { top: 16, left: 68, right: 16, bottom: 92 },
      { top: '76%', left: 68, right: 16, bottom: 32 },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
        axisLine: { lineStyle: { color: '#1f2937' } }, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
        axisLine: { lineStyle: { color: '#1f2937' } },
        axisLabel: { color: '#6b7280', fontSize: 10,
          interval: Math.max(0, Math.floor(n / 6) - 1) } },
    ],
    yAxis: [
      { type: 'value', scale: true, gridIndex: 0,
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 }, axisLine: { show: false } },
      { type: 'value', gridIndex: 1, splitNumber: 2, splitLine: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 9,
          formatter: v => v >= 1e8 ? (v/1e8).toFixed(0)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : v } },
    ],
    series: [
      {
        name: 'K', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
        data: candles,
        itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' },
        markPoint: { data: markData },
      },
      {
        name: 'Vol', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes, barMaxWidth: 8,
      },
    ],
  }
})

// ── Equity ────────────────────────────────────────────────────────────────────
const equityOpt = computed(() => {
  const ec = job.value?.equity_curve
  if (!ec?.length) return null
  const initial = form.value.capital
  const last = ec[ec.length - 1]?.equity ?? initial
  const isPos = last >= initial
  return {
    backgroundColor: 'transparent', animation: false,
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>¥${p[0].value?.toLocaleString()}` },
    grid: { left: 72, right: 16, top: 10, bottom: 28 },
    xAxis: { type: 'category', data: ec.map(d => d.date), axisLabel: { color: '#4b5563', fontSize: 10 }, axisLine: { lineStyle: { color: '#1f2937' } } },
    yAxis: { type: 'value', axisLabel: { color: '#4b5563', fontSize: 10, formatter: v => '¥'+(v/1e4).toFixed(0)+'w' }, splitLine: { lineStyle: { color: '#111827' } } },
    series: [{
      type: 'line', data: ec.map(d => d.equity), smooth: true, symbol: 'none',
      lineStyle: { color: isPos ? '#3b82f6' : '#f87171', width: 2 },
      areaStyle: { color: { type: 'linear', x:0, y:0, x2:0, y2:1, colorStops: [
        { offset: 0, color: isPos ? 'rgba(59,130,246,0.2)' : 'rgba(248,113,113,0.2)' },
        { offset: 1, color: 'rgba(0,0,0,0)' },
      ]}},
    }],
  }
})

// ── Helpers ───────────────────────────────────────────────────────────────────
function catBadge(c) {
  return { trend_following:'badge-blue', mean_reversion:'badge-green', adaptive:'badge-purple', ml:'badge-amber' }[c] || 'badge-gray'
}
function stBadge(s) {
  return { done:'badge-green', running:'badge-blue', error:'badge-red', queued:'badge-amber' }[s] || 'badge-gray'
}
function stLabel(s) {
  return { done:'完成', running:'运行中', error:'失败', queued:'排队' }[s] || s
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function downloadAndRetry() {
  downloading.value = true; dlMsg.value = '正在下载数据…'
  try {
    const sym = symbolList.value[0]
    const res = await axios.post('/api/market/download', { symbol: sym, start: form.value.start, end: form.value.end })
    dlMsg.value = `下载完成 ${res.data.bars} 条，重新运行…`
    await run()
  } catch (e) {
    dlMsg.value = '下载失败: ' + (e.response?.data?.detail || e.message)
  }
  downloading.value = false
}

async function fetchExtraBars() {
  try {
    const sym = symbolList.value[0]
    const res = await axios.get(`/api/market/bars/${sym}`, { params: { start: form.value.start, end: form.value.end } })
    extraBars.value = (res.data.bars || []).map(b => ({
      date: (b.datetime || b.date || '').slice(0, 10),
      open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume,
    }))
  } catch {}
}

async function run() {
  if (running.value || !symbolList.value.length) return
  running.value = true; job.value = null; extraBars.value = []; dlMsg.value = ''
  clearInterval(pollTimer)
  try {
    const res = await axios.post('/api/backtest/run', {
      strategy: form.value.strategy,
      symbols: symbolList.value,
      start: form.value.start, end: form.value.end,
      initial_capital: form.value.capital, enable_risk: form.value.enable_risk,
      params: { symbol: symbolList.value[0] },
    })
    job.value = res.data
    pollTimer = setInterval(poll, 1500)
  } catch (e) {
    running.value = false
    alert('提交失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function poll() {
  if (!job.value) return
  try {
    const res = await axios.get(`/api/backtest/${job.value.job_id}`)
    job.value = res.data
    if (res.data.status === 'error' && res.data.error?.includes('No bar data')) {
      clearInterval(pollTimer); running.value = false
      await downloadAndRetry()
    } else if (['done', 'error'].includes(res.data.status)) {
      clearInterval(pollTimer); running.value = false
      if (res.data.status === 'done' && !res.data.bars?.length) fetchExtraBars()
    }
  } catch {}
}

onMounted(async () => {
  applyPreset({ l: '1Y', m: 12 })
  document.addEventListener('click', onDocClick)

  const symParam = route.query.symbols || route.query.symbol
  if (symParam) symbolList.value = symParam.split(',').map(s => s.trim()).filter(Boolean)

  try {
    const res = await axios.get('/api/strategy/')
    strategies.value = res.data
    const match = route.query.strategy ? res.data.find(s => s.module_path === route.query.strategy) : null
    form.value.strategy = match?.module_path || res.data[0]?.module_path || ''
  } catch {}

  try { nameMap.value = (await axios.get('/api/market/meta/names')).data.names || {} } catch {}
  try { localSyms.value = new Set((await axios.get('/api/market/symbols')).data.symbols || []) } catch {}

  // Load recent AI-recommended stocks for quick picker
  try {
    const today30 = new Date(); today30.setDate(today30.getDate() - 30)
    const from = today30.toISOString().slice(0, 10)
    const pr = await axios.get('/api/predictions/', { params: { limit: 30, date_from: from } })
    const seen = new Set()
    recentItems.value = (pr.data.predictions || [])
      .filter(p => { if (seen.has(p.code)) return false; seen.add(p.code); return true })
      .slice(0, 15)
      .map(p => ({ code: p.code, name: p.name || p.code, date: p.date, hasData: localSyms.value.has(p.code) }))
  } catch {}
})

onUnmounted(() => {
  clearInterval(pollTimer)
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.bt-view { padding: 20px; display: flex; flex-direction: column; gap: 14px; }

/* Config card */
.cfg-card { padding: 18px 20px 14px; }
.cfg-grid {
  display: grid;
  grid-template-columns: 180px 1fr 230px 160px auto;
  gap: 20px;
  align-items: start;
}
.cfg-col { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.cfg-col-wide { min-width: 0; }
.cfg-label { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }

/* Strategy */
.strategy-meta { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin-top: 2px; }
.meta-txt { font-size: 11px; color: var(--text-3); line-height: 1.3; }

/* Symbol picker */
.sym-box {
  display: flex; flex-wrap: wrap; gap: 5px; align-items: center;
  border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--bg-elevated); padding: 5px 10px; min-height: 38px;
  cursor: text; transition: border-color 0.15s; position: relative;
}
.sym-box:focus-within { border-color: var(--accent); }
.sym-tag {
  display: inline-flex; align-items: center; gap: 3px;
  background: var(--accent-dim); color: var(--accent);
  border-radius: 5px; padding: 2px 6px; font-size: 12px;
}
.sym-name { font-size: 11px; opacity: 0.75; }
.tag-x { background: none; border: none; color: inherit; cursor: pointer; padding: 0 0 0 2px; font-size: 14px; opacity: 0.55; line-height: 1; }
.tag-x:hover { opacity: 1; }
.sym-input { border: none; outline: none; background: transparent; color: var(--text-1); font-size: 13px; min-width: 140px; flex: 1; }
.sym-input::placeholder { color: var(--text-3); }

/* Dropdown */
.sym-drop {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 50;
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius-md); box-shadow: 0 8px 28px rgba(0,0,0,0.3);
  max-height: 260px; overflow-y: auto;
}
.drop-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; cursor: pointer; border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}
.drop-row:last-child { border-bottom: none; }
.drop-row:hover { background: var(--bg-hover); }
.dr-code { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--accent); min-width: 52px; }
.dr-name { flex: 1; font-size: 13px; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dr-tag { font-size: 10px; background: #16a34a22; color: #4ade80; padding: 1px 5px; border-radius: 3px; white-space: nowrap; }
.dr-mkt  { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); }
.dr-date { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); margin-left: auto; margin-right: 4px; }
.ai-tag  { background: #4338ca22; color: #818cf8; }
.drop-section-label {
  padding: 6px 12px 4px;
  font-size: 10px; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
}

/* Date */
.preset-row { display: flex; gap: 4px; flex-wrap: wrap; }
.pre-chip {
  background: var(--bg-elevated); border: 1px solid var(--border);
  color: var(--text-3); border-radius: 20px; padding: 2px 8px;
  font-size: 11px; cursor: pointer; transition: all 0.12s;
}
.pre-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.pre-chip:hover:not(.active) { color: var(--text-1); }
.date-row { display: flex; align-items: center; gap: 4px; }
.date-in { flex: 1; padding: 5px 6px; font-size: 12px; min-width: 0; }
.date-dash { color: var(--text-3); flex-shrink: 0; }

/* Capital */
.cap-row { display: flex; align-items: center; gap: 6px; }
.cap-unit { font-size: 12px; color: var(--text-3); flex-shrink: 0; }
.risk-toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; margin-top: 6px; }

/* Run */
.cfg-run { padding-top: 18px; gap: 8px; }
.run-btn { width: 120px; justify-content: center; gap: 5px; padding: 9px 0; font-size: 13px; }
.job-meta { display: flex; align-items: center; gap: 6px; }

/* Empty */
.empty-card {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 64px; text-align: center; color: var(--text-2);
}
.empty-card svg { opacity: 0.25; margin-bottom: 4px; }
.empty-sub { font-size: 12px; color: var(--text-3); }

/* Metrics row */
.metrics-row {
  display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px;
}
.mc { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px 10px; }
.mc-val { font-size: 17px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.mc-lbl { font-size: 10px; color: var(--text-3); margin-top: 3px; white-space: nowrap; }

/* Chart */
.chart-wrap { overflow: hidden; }
.chart-hd { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px 4px; }
.chart-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.chart-sub { font-size: 11px; color: var(--text-3); }
.chart-legend { display: flex; gap: 12px; }
.leg { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-3); }
.leg-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }

/* Info/error */
.info-row { display: flex; align-items: center; gap: 10px; padding: 14px 16px; }
.err-box { background: #1e1010; border: 1px solid #7f1d1d; border-radius: var(--radius-md); padding: 14px 16px; }
.err-msg { font-size: 13px; color: #fca5a5; }
.dl-msg { font-size: 12px; color: var(--text-2); margin-top: 6px; display: flex; align-items: center; gap: 6px; }
.report-link { color: var(--accent); font-size: 13px; text-decoration: none; }
.report-link:hover { text-decoration: underline; }

.pos { color: var(--success); }
.neg { color: var(--danger); }

@media (max-width: 1200px) {
  .cfg-grid { grid-template-columns: 170px 1fr 210px; }
  .cfg-col:nth-child(4), .cfg-col:nth-child(5) { grid-column: auto; }
  .metrics-row { grid-template-columns: repeat(5, 1fr); }
}
@media (max-width: 768px) {
  .bt-view { padding: 12px; }
  .cfg-grid { grid-template-columns: 1fr 1fr; }
  .cfg-col:nth-child(1), .cfg-col:nth-child(2) { grid-column: 1 / -1; }
  .metrics-row { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 480px) {
  .cfg-grid { grid-template-columns: 1fr; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
