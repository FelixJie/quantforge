<template>
  <div class="sa-wrap">
    <!-- Search bar -->
    <div class="sa-search card">
      <input class="input sym-input" v-model="symbol" @keydown.enter="loadAll()"
             placeholder="输入股票代码，如 000001 / 600519" maxlength="6" />
      <button class="btn-primary" @click="loadAll()" :disabled="loading || !symbol">
        <span v-if="loading" class="spinner spinner-sm"></span>
        <span v-else>分析</span>
      </button>
      <div class="recent-chips" v-if="history.length && !overview">
        <span class="text-3" style="font-size:11px">最近：</span>
        <button v-for="h in history.slice(0,5)" :key="h.symbol" class="btn-ghost btn-xs" @click="symbol=h.symbol;loadAll()">
          {{ h.symbol }} {{ h.name }}
        </button>
      </div>
    </div>

    <!-- Nothing loaded yet — show history -->
    <div v-if="!overview && !loading">
      <div v-if="history.length" class="history-panel card">
        <div class="history-title">最近查询</div>
        <div class="history-list">
          <div v-for="h in history" :key="h.symbol" class="history-item" @click="symbol=h.symbol;loadAll()">
            <span class="h-code">{{ h.symbol }}</span>
            <span class="h-name">{{ h.name }}</span>
            <span class="h-time text-3">{{ h.queried_at?.slice(0,10) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state card">
        <div class="empty-icon">🔍</div>
        <p>输入股票代码进行综合分析</p>
        <p class="empty-hint">包含消息面、技术面、基本面及 AI 综合研判</p>
      </div>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading && !overview" class="card loading-card">
      <span class="spinner"></span><span class="text-2">加载数据中...</span>
    </div>

    <!-- Main content (loaded) -->
    <template v-if="overview">
      <!-- Overview header card -->
      <div class="ov-card card">
        <div class="ov-left">
          <div class="ov-name">{{ overview.name }}<span class="ov-code">{{ overview.symbol }}</span></div>
          <div class="ov-price-row">
            <span class="ov-price">{{ fmtPrice(overview.price ?? overview.yesterday_close) }}</span>
            <span :class="['ov-chg', chgClass(overview.change_pct)]">
              {{ fmtChg(overview.change_pct) }}
            </span>
            <span class="ov-market text-3">{{ overview.market }}</span>
          </div>
          <div class="ov-meta">
            <span>今开 <b>{{ fmtPrice(overview.open) }}</b></span>
            <span>昨收 <b>{{ fmtPrice(overview.yesterday_close) }}</b></span>
            <span>最高 <b class="pos">{{ fmtPrice(overview.high) }}</b></span>
            <span>最低 <b class="neg">{{ fmtPrice(overview.low) }}</b></span>
            <span>成交额 <b>{{ fmtAmount(overview.turnover_amount) }}</b></span>
            <span>换手率 <b>{{ overview.turnover_rate?.toFixed(2) ?? '-' }}%</b></span>
          </div>
        </div>
        <div class="ov-right">
          <div class="ov-metric" v-for="m in overviewMetrics" :key="m.label">
            <span class="ov-metric-val" :class="m.cls">{{ m.value }}</span>
            <span class="ov-metric-lbl">{{ m.label }}</span>
          </div>
          <button class="btn-ghost btn-sm refresh-btn" @click="refreshAll" title="强制刷新所有数据（忽略缓存）">↻ 刷新</button>
        </div>
      </div>

      <!-- Tab bar -->
      <div class="tab-bar">
        <button v-for="t in tabs" :key="t.key"
          :class="['tab-btn', activeTab === t.key ? 'active' : '']"
          @click="switchTab(t.key)">
          {{ t.label }}
        </button>
      </div>

      <!-- ══ 技术面 ══ -->
      <div v-show="activeTab === 'technical'" class="tab-pane">
        <div v-if="loadingTech" class="card loading-card"><span class="spinner"></span><span class="text-2">加载K线...</span></div>
        <template v-else-if="technical?.bars?.length">
          <!-- Signal banner -->
          <div :class="['signal-banner', technical.signal]">
            <span class="signal-label">趋势信号</span>
            <span class="signal-val">{{ signalText[technical.signal] }}</span>
            <span class="signal-meta">
              支撑 <b>{{ technical.support }}</b> · 压力 <b>{{ technical.resistance }}</b>
            </span>
            <span v-if="lastRsi" :class="['rsi-chip', lastRsi > 70 ? 'overbought' : lastRsi < 30 ? 'oversold' : '']">
              RSI {{ lastRsi?.toFixed(1) }}
            </span>
          </div>

          <!-- Indicator toggles -->
          <div class="ind-bar card">
            <span class="ind-label">均线</span>
            <button v-for="ma in maOptions" :key="ma.key"
              :class="['ind-btn', inds[ma.key] ? 'active' : '']"
              :style="inds[ma.key] ? {borderColor: ma.color, color: ma.color, background: ma.color+'1a'} : {}"
              @click="inds[ma.key] = !inds[ma.key]">{{ ma.label }}</button>
            <button :class="['ind-btn', inds.boll ? 'active' : '']"
              :style="inds.boll ? {borderColor:'#a78bfa',color:'#a78bfa',background:'#a78bfa1a'} : {}"
              @click="inds.boll = !inds.boll">BOLL</button>
            <span class="ind-sep"></span>
            <span class="ind-label">副图</span>
            <button v-for="s in subOptions" :key="s.key"
              :class="['ind-btn', subInd === s.key ? 'active' : '']"
              :style="subInd === s.key ? {borderColor: s.color, color: s.color, background: s.color+'1a'} : {}"
              @click="subInd = subInd === s.key ? '' : s.key">{{ s.label }}</button>
          </div>

          <!-- K-line chart -->
          <div class="chart-card card">
            <div class="chart-header">
              <span class="text-1 fw-600">{{ overview.name }} · 日K ({{ technical.bars.length }}天)</span>
              <div style="display:flex;align-items:center;gap:10px">
                <span class="text-3" style="font-size:11px">{{ technical.bars[0]?.date }} — {{ technical.bars[technical.bars.length-1]?.date }}</span>
                <span class="text-3" style="font-size:10px;color:var(--accent)">点击K线查看当日分时</span>
              </div>
            </div>
            <v-chart :option="klineOption" autoresize style="height:380px" @click="onKlineClick" />
          </div>

          <!-- Intraday modal -->
          <div v-if="intradayDate" class="intraday-overlay" @click.self="intradayDate=null">
            <div class="intraday-modal">
              <!-- Header bar -->
              <div class="intraday-head">
                <div class="intraday-title">
                  <span class="iday-name">{{ overview.name }}</span>
                  <span class="iday-date">{{ intradayDate }} · 5分钟分时</span>
                </div>
                <div v-if="intradayBars.length" class="intraday-stats">
                  <span :class="['istat', intradayChg >= 0 ? 'up' : 'dn']">
                    {{ intradayClose }} &nbsp;
                    <b>{{ intradayChg >= 0 ? '+' : '' }}{{ intradayChg.toFixed(2) }}%</b>
                  </span>
                  <span class="istat-item">高 <b class="up">{{ intradayHigh }}</b></span>
                  <span class="istat-item">低 <b class="dn">{{ intradayLow }}</b></span>
                  <span class="istat-item">量 <b>{{ intradayVol }}</b></span>
                </div>
                <button class="iday-close" @click="intradayDate=null">✕</button>
              </div>

              <div v-if="loadingIntraday" class="intraday-loading">
                <span class="spinner"></span><span class="text-2">加载分时数据...</span>
              </div>
              <template v-else-if="intradayOption">
                <v-chart :option="intradayOption" autoresize style="height:260px" />
                <v-chart :option="intradayVolOption" autoresize style="height:80px" />
              </template>
              <div v-else class="iday-empty">暂无当日分时数据</div>
            </div>
          </div>

          <!-- Sub chart -->
          <div v-if="subChartOption" class="chart-card card">
            <div class="chart-header"><span class="text-2" style="font-size:12px">{{ subInd.toUpperCase() }}</span></div>
            <v-chart :option="subChartOption" autoresize style="height:160px" />
          </div>

          <!-- Volume chart -->
          <div class="chart-card card">
            <v-chart :option="volumeOption" autoresize style="height:100px" />
          </div>
        </template>
        <div v-else class="card empty-card"><span class="text-3">暂无技术数据</span></div>
      </div>

      <!-- ══ 基本面 ══ -->
      <div v-show="activeTab === 'fundamental'" class="tab-pane">
        <div v-if="loadingFund" class="card loading-card"><span class="spinner"></span><span class="text-2">加载中...</span></div>
        <template v-else>
          <!-- Valuation metrics -->
          <div class="fund-metrics">
            <div class="fund-card card" v-for="m in fundMetrics" :key="m.label">
              <div class="fund-val" :class="m.cls">{{ m.value }}</div>
              <div class="fund-lbl">{{ m.label }}</div>
              <div class="fund-hint" v-if="m.hint">{{ m.hint }}</div>
            </div>
          </div>

          <!-- Top 10 holders -->
          <div class="section-card card" v-if="fundamental?.holders?.length">
            <div class="section-title">十大股东（最新两期）</div>
            <table class="data-table">
              <thead><tr><th>报告期</th><th>股东名称</th><th>类型</th><th>持股数(万)</th><th>持股比例</th><th>变动</th></tr></thead>
              <tbody>
                <tr v-for="h in fundamental.holders" :key="h.name+h.report_date">
                  <td class="td-ts">{{ h.report_date }}</td>
                  <td class="fw-600">{{ h.name }}</td>
                  <td><span class="type-chip">{{ h.type }}</span></td>
                  <td class="mono">{{ h.shares ? (h.shares/10000).toFixed(0) : '-' }}</td>
                  <td class="mono">{{ h.pct?.toFixed(2) ?? '-' }}%</td>
                  <td :class="h.change?.includes('增') ? 'pos' : h.change?.includes('减') ? 'neg' : ''">{{ h.change }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- Billboard entries -->
          <div class="section-card card" v-if="fundamental?.billboard?.length">
            <div class="section-title">近期龙虎榜上榜记录</div>
            <table class="data-table">
              <thead><tr><th>日期</th><th>收盘价</th><th>涨跌幅</th><th>上榜原因</th></tr></thead>
              <tbody>
                <tr v-for="b in fundamental.billboard" :key="b.date+b.reason">
                  <td class="td-ts">{{ b.date }}</td>
                  <td class="mono">{{ b.close }}</td>
                  <td :class="chgClass(b.change_pct)">{{ fmtChg(b.change_pct) }}</td>
                  <td class="text-2" style="font-size:12px">{{ b.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="!fundamental?.holders?.length && !fundamental?.billboard?.length" class="card empty-card">
            <span class="text-3">暂无详细基本面数据</span>
          </div>
        </template>
      </div>

      <!-- ══ 消息面 ══ -->
      <div v-show="activeTab === 'news'" class="tab-pane">
        <div v-if="loadingNews" class="card loading-card"><span class="spinner"></span><span class="text-2">加载公告...</span></div>
        <div v-else-if="newsItems.length" class="news-list card">
          <div class="list-header text-3">{{ overview.name }} · {{ newsItems.length }} 条公告</div>
          <div v-for="item in newsItems" :key="item.title+item.date" class="news-item" @click="item._exp = !item._exp">
            <div class="ni-row">
              <span :class="['sdot', item.sentiment]"></span>
              <span class="ni-title">{{ item.title }}</span>
              <span class="ni-time">{{ item.date }} {{ item.time }}</span>
            </div>
            <div v-if="item._exp && item.url" class="ni-link">
              <a :href="item.url" target="_blank" class="text-3" style="font-size:11px">查看原文 →</a>
            </div>
          </div>
        </div>
        <div v-else class="card empty-card"><span class="text-3">暂无公告数据</span></div>
      </div>

      <!-- ══ AI分析 ══ -->
      <div v-show="activeTab === 'ai'" class="tab-pane">
        <div v-if="!aiResult && !loadingAI" class="card ai-start">
          <p class="text-2">点击下方按钮，AI 将综合消息面、技术面、基本面进行深度研判</p>
          <button class="btn-primary" @click="runAI">✨ 开始 AI 分析</button>
        </div>
        <div v-if="loadingAI" class="card loading-card loading-ai">
          <span class="spinner"></span><span class="text-2">AI 正在分析 {{ overview.name }}，请稍候...</span>
        </div>
        <div v-if="aiResult" class="card ai-result">
          <div class="ai-header">
            <span class="ai-badge">✨ AI 综合研判</span>
            <div class="ai-meta">
              <span :class="['sig-chip', aiResult.context?.signal]">{{ signalText[aiResult.context?.signal] }}</span>
              <span class="text-3 tiny">{{ aiResult.generated_at?.replace('T',' ') }}</span>
            </div>
          </div>
          <div class="ai-body" v-html="renderMarkdown(aiResult.analysis)"></div>
          <button class="btn-ghost btn-sm" @click="runAI" :disabled="loadingAI" style="margin-top:12px">重新分析</button>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, reactive, watch } from 'vue'
import { useRoute } from 'vue-router'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import axios from 'axios'

use([CanvasRenderer, CandlestickChart, LineChart, BarChart,
     GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, MarkLineComponent])

const route = useRoute()

// State
const symbol    = ref('')
const loading   = ref(false)
const activeTab = ref('technical')

const overview   = ref(null)
const technical  = ref(null)
const fundamental = ref(null)
const newsItems  = ref([])
const aiResult   = ref(null)
const history    = ref([])

const loadingTech = ref(false)
const loadingFund = ref(false)
const loadingNews = ref(false)
const loadingAI   = ref(false)

// Intraday drill-down
const intradayDate    = ref(null)
const intradayBars    = ref([])
const loadingIntraday = ref(false)

// Indicator state
const inds = reactive({ ma5: true, ma10: false, ma20: true, ma60: false, boll: false })
const subInd = ref('')

const tabs = [
  { key: 'technical',   label: '技术面' },
  { key: 'fundamental', label: '基本面' },
  { key: 'news',        label: '消息面' },
  { key: 'ai',          label: 'AI 分析' },
]

const maOptions = [
  { key: 'ma5',  label: 'MA5',  color: '#f6ad55', period: 5  },
  { key: 'ma10', label: 'MA10', color: '#68d391', period: 10 },
  { key: 'ma20', label: 'MA20', color: '#63b3ed', period: 20 },
  { key: 'ma60', label: 'MA60', color: '#9f7aea', period: 60 },
]
const subOptions = [
  { key: 'macd', label: 'MACD', color: '#f6ad55' },
  { key: 'rsi',  label: 'RSI',  color: '#68d391' },
]
const signalText = { bullish: '多头趋势', bearish: '空头趋势', neutral: '震荡整理' }

// Computed metrics
const overviewMetrics = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { label: 'PE(TTM)', value: o.pe_ttm?.toFixed(2) ?? '-' },
    { label: 'PB',      value: o.pb?.toFixed(2)     ?? '-' },
    { label: 'ROE',     value: o.roe ? o.roe + '%' : '-', cls: roeClass(o.roe) },
    { label: '总市值',  value: fmtBillion(o.market_cap) },
    { label: '流通市值', value: fmtBillion(o.circ_cap) },
    { label: '毛利率',  value: o.gross_margin != null ? o.gross_margin.toFixed(1) + '%' : '-' },
  ]
})

const fundMetrics = computed(() => {
  const o = overview.value
  if (!o) return []
  const pe = o.pe_ttm
  const pb = o.pb
  const roe = o.roe
  return [
    {
      label: '市盈率PE(TTM)', value: pe?.toFixed(2) ?? '-',
      cls: pe == null ? '' : pe < 15 ? 'pos' : pe > 60 ? 'neg' : '',
      hint: pe == null ? '' : pe < 15 ? '低估' : pe > 60 ? '高估' : '合理'
    },
    {
      label: '市净率PB', value: pb?.toFixed(2) ?? '-',
      cls: pb == null ? '' : pb < 1 ? 'pos' : pb > 5 ? 'neg' : '',
      hint: pb == null ? '' : pb < 1 ? '破净' : pb > 5 ? '偏贵' : ''
    },
    {
      label: 'ROE', value: roe != null ? roe + '%' : '-',
      cls: roeClass(roe),
      hint: roe == null ? '' : roe > 20 ? '优秀' : roe > 10 ? '良好' : roe > 0 ? '一般' : '亏损'
    },
    { label: '总股本(亿)', value: o.total_shares ? (o.total_shares/1e8).toFixed(2) : '-' },
    { label: '总市值',     value: fmtBillion(o.market_cap) },
    { label: '流通市值',   value: fmtBillion(o.circ_cap) },
  ]
})

const lastRsi = computed(() => {
  const rsiArr = technical.value?.rsi || []
  const valid = rsiArr.filter(v => v != null)
  return valid.length ? valid[valid.length - 1] : null
})

// ── Chart computations ────────────────────────────────────────────────────────

const klineOption = computed(() => {
  const t = technical.value
  if (!t?.bars?.length) return null
  const bars = t.bars
  const dates = bars.map(b => b.date)
  const candles = bars.map(b => [b.open, b.close, b.low, b.high])

  const series = [{
    name: '日K', type: 'candlestick', data: candles,
    itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' },
  }]

  if (inds.ma5)  series.push(maSeries('MA5',  t.ma?.ma5,  '#f6ad55'))
  if (inds.ma10) series.push(maSeries('MA10', t.ma?.ma10, '#68d391'))
  if (inds.ma20) series.push(maSeries('MA20', t.ma?.ma20, '#63b3ed'))
  if (inds.ma60) series.push(maSeries('MA60', t.ma?.ma60, '#9f7aea'))
  if (inds.boll && t.boll) {
    series.push(maSeries('BOLL上', t.boll.upper, '#a78bfa', 'dashed'))
    series.push(maSeries('BOLL中', t.boll.mid,   '#a78bfa'))
    series.push(maSeries('BOLL下', t.boll.lower, '#a78bfa', 'dashed'))
  }

  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { show: false },
    dataZoom: [
      { type: 'inside', start: 60, end: 100 },
      { type: 'slider', height: 20, bottom: 0, start: 60, end: 100 },
    ],
    grid: { top: 10, left: 60, right: 20, bottom: 50 },
    xAxis: { type: 'category', data: dates, boundaryGap: true,
      axisLabel: { color: '#9ca3af', fontSize: 11 }, axisLine: { lineStyle: { color: '#374151' } } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
      axisLabel: { color: '#9ca3af', fontSize: 11 } },
    series,
  }
})

const subChartOption = computed(() => {
  const t = technical.value
  if (!t || !subInd.value) return null
  const bars = t.bars
  const dates = bars.map(b => b.date)

  if (subInd.value === 'rsi') {
    return {
      backgroundColor: 'transparent', animation: false,
      tooltip: { trigger: 'axis' },
      grid: { top: 10, left: 60, right: 20, bottom: 30 },
      xAxis: { type: 'category', data: dates, show: false },
      yAxis: { type: 'value', min: 0, max: 100, interval: 30,
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
        axisLabel: { color: '#9ca3af', fontSize: 11 } },
      series: [{
        name: 'RSI', type: 'line', data: t.rsi,
        lineStyle: { color: '#68d391', width: 1.5 }, showSymbol: false,
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { type: 'dashed', color: '#6b7280' },
          data: [{ yAxis: 70 }, { yAxis: 30 }],
          label: { formatter: p => p.value, color: '#9ca3af', fontSize: 10 }
        }
      }],
    }
  }

  if (subInd.value === 'macd') {
    const { dif, dea, hist } = t.macd || {}
    return {
      backgroundColor: 'transparent', animation: false,
      tooltip: { trigger: 'axis' },
      grid: { top: 10, left: 60, right: 20, bottom: 30 },
      xAxis: { type: 'category', data: dates, show: false },
      yAxis: { type: 'value', scale: true,
        splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 } },
      series: [
        { name: 'DIF', type: 'line', data: dif, lineStyle: { color: '#63b3ed', width: 1.5 }, showSymbol: false },
        { name: 'DEA', type: 'line', data: dea, lineStyle: { color: '#f6ad55', width: 1.5 }, showSymbol: false },
        {
          name: 'MACD', type: 'bar', data: hist,
          itemStyle: { color: p => p.value >= 0 ? '#ef4444' : '#22c55e' },
        },
      ],
    }
  }
  return null
})

const volumeOption = computed(() => {
  const t = technical.value
  if (!t?.bars?.length) return null
  const bars = t.bars
  return {
    backgroundColor: 'transparent', animation: false,
    tooltip: { trigger: 'axis' },
    grid: { top: 4, left: 60, right: 20, bottom: 30 },
    dataZoom: [{ type: 'inside', start: 60, end: 100 }],
    xAxis: { type: 'category', data: bars.map(b => b.date),
      axisLabel: { color: '#9ca3af', fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { formatter: v => v > 1e4 ? (v/1e4).toFixed(0)+'W' : v, color: '#9ca3af', fontSize: 10 },
      splitLine: { lineStyle: { color: '#1f2937', type: 'dashed' } } },
    series: [{
      type: 'bar', data: bars.map(b => b.volume),
      itemStyle: { color: p => bars[p.dataIndex]?.change_pct >= 0 ? '#ef444466' : '#22c55e66' },
    }],
  }
})

// ── Intraday chart (同花顺 style) ─────────────────────────────────────────────

// Baseline = first bar's open (昨收 proxy)
const intradayBaseline = computed(() => intradayBars.value[0]?.open || 0)

const intradayClose = computed(() => {
  const bars = intradayBars.value
  return bars.length ? bars[bars.length - 1].close : 0
})
const intradayChg = computed(() => {
  const base = intradayBaseline.value
  return base ? ((intradayClose.value - base) / base * 100) : 0
})
const intradayHigh = computed(() => intradayBars.value.length
  ? Math.max(...intradayBars.value.map(b => b.high)) : 0)
const intradayLow = computed(() => intradayBars.value.length
  ? Math.min(...intradayBars.value.map(b => b.low)) : 0)
const intradayVol = computed(() => {
  const total = intradayBars.value.reduce((s, b) => s + b.volume, 0)
  return total >= 1e4 ? (total / 1e4).toFixed(0) + '万手' : total.toFixed(0) + '手'
})

// Compute VWAP (volume-weighted avg price)
function calcVwap(bars) {
  const vwap = []
  let cumVol = 0, cumTurnover = 0
  for (const b of bars) {
    const avgPrice = (b.open + b.close + b.high + b.low) / 4
    cumVol += b.volume
    cumTurnover += avgPrice * b.volume
    vwap.push(cumVol ? +(cumTurnover / cumVol).toFixed(3) : null)
  }
  return vwap
}

const intradayOption = computed(() => {
  if (!intradayBars.value.length) return null
  const bars     = intradayBars.value
  const times    = bars.map(b => b.datetime?.slice(11, 16) || b.datetime)
  const closes   = bars.map(b => b.close)
  const base     = intradayBaseline.value
  const vwap     = calcVwap(bars)
  const isUp     = intradayClose.value >= base

  // Right axis: pct change labels
  const priceRange = Math.max(Math.abs(intradayHigh.value - base), Math.abs(intradayLow.value - base))
  const yMin = +(base - priceRange * 1.1).toFixed(2)
  const yMax = +(base + priceRange * 1.1).toFixed(2)

  const mainColor = isUp ? '#ef4444' : '#22c55e'
  const areaColor = isUp ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)'

  return {
    backgroundColor: '#0f1117', animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#4b5563' }, lineStyle: { color: '#374151' } },
      backgroundColor: '#1a2234', borderColor: '#2d3748',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: params => {
        const cp = params.find(p => p.seriesName === '分时')
        const vp = params.find(p => p.seriesName === 'VWAP')
        if (!cp) return ''
        const chg = ((cp.value - base) / base * 100)
        const sign = chg >= 0 ? '+' : ''
        return `<b>${cp.name}</b><br/>
          价格 <b style="color:${cp.value>=base?'#ef4444':'#22c55e'}">${cp.value}</b>
          &nbsp;(${sign}${chg.toFixed(2)}%)<br/>
          均价 <b style="color:#f6ad55">${vp?.value ?? '-'}</b>`
      }
    },
    grid: { top: 12, left: 72, right: 60, bottom: 24 },
    xAxis: {
      type: 'category', data: times, boundaryGap: false,
      axisLine: { lineStyle: { color: '#2d3748' } },
      axisLabel: { color: '#6b7280', fontSize: 10 },
      splitLine: {
        show: true,
        lineStyle: { color: '#1a2234' },
        interval: (i) => times[i] === '11:30' || times[i] === '13:00' || times[i] === '14:00',
      },
    },
    yAxis: [
      {
        type: 'value', scale: false, min: yMin, max: yMax,
        position: 'left',
        splitLine: { lineStyle: { color: '#1a2234', type: 'dashed' } },
        axisLabel: { color: '#9ca3af', fontSize: 10 },
        axisLine: { show: false },
      },
      {
        type: 'value', scale: false, min: yMin, max: yMax,
        position: 'right',
        splitLine: { show: false },
        axisLabel: {
          color: '#9ca3af', fontSize: 10,
          formatter: v => {
            const p = ((v - base) / base * 100)
            return (p >= 0 ? '+' : '') + p.toFixed(1) + '%'
          },
        },
        axisLine: { show: false },
      },
    ],
    series: [
      {
        name: '分时', type: 'line', data: closes, showSymbol: false,
        lineStyle: { color: mainColor, width: 1.5 },
        areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: areaColor }, { offset: 1, color: 'rgba(0,0,0,0)' }] } },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { type: 'solid', color: '#4b5563', width: 1 },
          label: { show: true, position: 'insideStartTop', formatter: `昨收 ${base}`, color: '#6b7280', fontSize: 9 },
          data: [{ yAxis: base }],
        },
      },
      {
        name: 'VWAP', type: 'line', data: vwap, showSymbol: false,
        lineStyle: { color: '#f6ad55', width: 1, type: 'solid' },
        tooltip: { show: true },
      },
    ],
  }
})

const intradayVolOption = computed(() => {
  if (!intradayBars.value.length) return null
  const bars  = intradayBars.value
  const times = bars.map(b => b.datetime?.slice(11, 16) || b.datetime)
  const base  = intradayBaseline.value
  return {
    backgroundColor: '#0f1117', animation: false,
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a2234', borderColor: '#2d3748',
      textStyle: { color: '#e2e8f0', fontSize: 11 },
      formatter: p => `${p[0].name}<br/>量 <b>${(p[0].value / 1e4).toFixed(1)}万手</b>`,
    },
    grid: { top: 4, left: 72, right: 60, bottom: 24 },
    xAxis: {
      type: 'category', data: times, boundaryGap: false,
      axisLine: { lineStyle: { color: '#2d3748' } },
      axisLabel: { color: '#6b7280', fontSize: 9 },
    },
    yAxis: {
      type: 'value',
      splitLine: { show: false },
      axisLabel: { color: '#6b7280', fontSize: 9, formatter: v => v >= 1e4 ? (v/1e4).toFixed(0)+'w' : v },
    },
    series: [{
      type: 'bar', data: bars.map(b => b.volume), barMaxWidth: 6,
      itemStyle: { color: p => bars[p.dataIndex]?.close >= base ? 'rgba(239,68,68,0.8)' : 'rgba(34,197,94,0.8)' },
    }],
  }
})

async function onKlineClick(params) {
  if (!params?.name || !symbol.value) return
  const date = params.name
  intradayDate.value = date
  intradayBars.value = []
  loadingIntraday.value = true
  try {
    const res = await axios.get(`/api/market/intraday/${symbol.value.trim()}`, { params: { klt: 5, date } })
    intradayBars.value = res.data.bars || []
  } catch {}
  loadingIntraday.value = false
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function loadAll(refresh = false) {
  if (!symbol.value.trim()) return
  const sym = symbol.value.trim()
  loading.value = true
  overview.value = null
  technical.value = null
  fundamental.value = null
  newsItems.value = []
  aiResult.value = null

  try {
    const params = refresh ? { refresh: true } : {}
    const res = await axios.get(`/api/stock-analysis/${sym}/overview`, { params })
    overview.value = res.data
  } catch (e) {
    loading.value = false
    return
  }
  loading.value = false

  // Load history after successful query
  loadHistory()

  // Load tab data in background
  loadTechnical(sym, refresh)
  loadFundamental(sym, refresh)
  loadNews(sym)
}

async function refreshAll() {
  await loadAll(true)
}

async function loadHistory() {
  try {
    const res = await axios.get('/api/stock-analysis/history')
    history.value = res.data.history || []
  } catch {}
}

async function loadTechnical(sym, refresh = false) {
  loadingTech.value = true
  try {
    const params = { days: 180 }
    if (refresh) params.refresh = true
    const res = await axios.get(`/api/stock-analysis/${sym}/technical`, { params })
    technical.value = res.data
  } catch {}
  loadingTech.value = false
}

async function loadFundamental(sym, refresh = false) {
  loadingFund.value = true
  try {
    const params = refresh ? { refresh: true } : {}
    const res = await axios.get(`/api/stock-analysis/${sym}/fundamental`, { params })
    fundamental.value = res.data
  } catch {}
  loadingFund.value = false
}

async function loadNews(sym) {
  loadingNews.value = true
  try {
    const res = await axios.get(`/api/news/stock/${sym}`, { params: { count: 30 } })
    newsItems.value = (res.data.items || []).map(i => ({ ...i, _exp: false }))
  } catch {}
  loadingNews.value = false
}

async function runAI() {
  const sym = symbol.value.trim()
  loadingAI.value = true
  aiResult.value = null
  try {
    const res = await axios.post(`/api/stock-analysis/${sym}/ai`)
    aiResult.value = res.data
  } catch (e) {
    aiResult.value = {
      analysis: 'AI分析失败: ' + (e.response?.data?.detail || e.message),
      generated_at: new Date().toISOString(),
      context: {}
    }
  }
  loadingAI.value = false
}

function switchTab(tab) {
  activeTab.value = tab
  const sym = symbol.value.trim()
  if (tab === 'technical' && !technical.value && sym) loadTechnical(sym)
  if (tab === 'fundamental' && !fundamental.value && sym) loadFundamental(sym)
  if (tab === 'news' && !newsItems.value.length && sym) loadNews(sym)
}

// ── Render helpers ────────────────────────────────────────────────────────────

function maSeries(name, data, color, dash) {
  return {
    name, type: 'line', data,
    lineStyle: { color, width: 1.5, type: dash || 'solid' },
    showSymbol: false, smooth: false,
  }
}

function fmtPrice(v) {
  if (v == null || v === 0) return '-'
  return Number(v).toFixed(2)
}

function fmtChg(v) {
  if (v == null) return '-'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%'
}

function fmtAmount(v) {
  if (!v) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return String(v)
}

function fmtBillion(v) {
  if (!v) return '-'
  return (v / 1e8).toFixed(1) + '亿'
}

function chgClass(v) {
  if (v == null) return ''
  return v > 0 ? 'pos' : v < 0 ? 'neg' : ''
}

function roeClass(v) {
  if (v == null) return ''
  return v > 15 ? 'pos' : v > 0 ? '' : 'neg'
}

function renderMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^#{1,3}\s+(.+)$/gm, '<h4>$1</h4>')
    .replace(/\n/g, '<br>')
}

// Init
loadHistory()
const initSym = route.query.symbol
if (initSym) {
  symbol.value = String(initSym)
  loadAll()
}
</script>

<style scoped>
.sa-wrap { padding: 20px; display: flex; flex-direction: column; gap: 14px; }

/* Search */
.sa-search { display: flex; align-items: center; gap: 10px; padding: 12px 16px; flex-wrap: wrap; }
.sym-input { width: 240px; }
.recent-chips { display: flex; align-items: center; gap: 6px; margin-left: 8px; flex-wrap: wrap; }
.btn-xs { padding: 2px 8px; font-size: 11px; }

/* History panel */
.history-panel { padding: 14px 16px; }
.history-title { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }
.history-list { display: flex; flex-direction: column; gap: 0; }
.history-item { display: flex; align-items: center; gap: 12px; padding: 9px 8px; border-radius: var(--radius-sm); cursor: pointer; transition: background 0.1s; }
.history-item:hover { background: var(--bg-hover); }
.h-code { font-family: var(--font-mono); font-weight: 700; color: var(--accent); font-size: 13px; width: 60px; }
.h-name { font-size: 13px; color: var(--text-1); flex: 1; }
.h-time { font-size: 11px; }

/* Refresh button */
.refresh-btn { align-self: flex-start; margin-top: 4px; }

/* Overview card */
.ov-card { display: flex; gap: 24px; padding: 16px 20px; flex-wrap: wrap; }
.ov-left { flex: 1; min-width: 260px; }
.ov-name { font-size: 18px; font-weight: 700; color: var(--text-1); }
.ov-code { font-size: 13px; color: var(--text-3); font-family: var(--font-mono); margin-left: 8px; }
.ov-price-row { display: flex; align-items: baseline; gap: 10px; margin: 6px 0; }
.ov-price { font-size: 28px; font-weight: 700; color: var(--text-1); font-family: var(--font-mono); }
.ov-chg { font-size: 16px; font-weight: 600; }
.ov-market { font-size: 12px; }
.ov-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-2); margin-top: 6px; }
.ov-meta b { color: var(--text-1); }
.ov-right { display: flex; flex-wrap: wrap; gap: 12px; align-content: flex-start; }
.ov-metric { background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 8px 14px; text-align: center; min-width: 80px; }
.ov-metric-val { display: block; font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.ov-metric-lbl { font-size: 10px; color: var(--text-3); margin-top: 2px; }

/* Tabs */
.tab-bar { display: flex; gap: 4px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 4px; width: fit-content; }
.tab-btn { padding: 6px 18px; border-radius: calc(var(--radius-md) - 2px); font-size: 13px; font-weight: 500; color: var(--text-2); background: transparent; border: none; cursor: pointer; transition: all 0.15s; }
.tab-btn.active { background: var(--accent); color: #fff; }
.tab-btn:hover:not(.active) { background: var(--bg-elevated); color: var(--text-1); }
.tab-pane { display: flex; flex-direction: column; gap: 12px; }

/* Signal banner */
.signal-banner { display: flex; align-items: center; gap: 14px; padding: 10px 16px; border-radius: var(--radius-md); border: 1px solid var(--border); flex-wrap: wrap; }
.signal-banner.bullish { background: #16a34a18; border-color: #16a34a44; }
.signal-banner.bearish { background: #ef444418; border-color: #ef444444; }
.signal-banner.neutral { background: var(--bg-surface); }
.signal-label { font-size: 11px; color: var(--text-3); font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.signal-val { font-size: 14px; font-weight: 700; }
.signal-banner.bullish .signal-val { color: var(--success); }
.signal-banner.bearish .signal-val { color: var(--danger); }
.signal-meta { font-size: 12px; color: var(--text-2); }
.rsi-chip { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; background: var(--bg-elevated); color: var(--text-2); margin-left: auto; }
.rsi-chip.overbought { background: #ef444418; color: var(--danger); }
.rsi-chip.oversold   { background: #16a34a18; color: var(--success); }

/* Indicator bar */
.ind-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 8px 14px; }
.ind-label { font-size: 11px; color: var(--text-3); font-weight: 600; }
.ind-sep { width: 1px; height: 16px; background: var(--border); margin: 0 4px; }
.ind-btn { padding: 3px 10px; font-size: 12px; background: var(--bg-elevated); border: 1px solid var(--border); color: var(--text-2); border-radius: var(--radius-sm); cursor: pointer; transition: all 0.1s; }
.ind-btn.active { font-weight: 600; }

/* Charts */
.chart-card { padding: 12px 14px; }
.chart-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }

/* Fundamental */
.fund-metrics { display: flex; gap: 12px; flex-wrap: wrap; }
.fund-card { padding: 14px 18px; min-width: 110px; text-align: center; }
.fund-val { font-size: 20px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.fund-lbl { font-size: 11px; color: var(--text-3); margin-top: 3px; }
.fund-hint { font-size: 11px; color: var(--text-2); margin-top: 2px; }

/* Tables */
.section-card { padding: 14px 16px; }
.section-title { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { color: var(--text-3); font-weight: 600; text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 11px; }
.data-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }
.td-ts { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }
.type-chip { font-size: 11px; color: var(--accent); background: var(--accent-dim); padding: 1px 6px; border-radius: 8px; }
.fw-600 { font-weight: 600; }
.mono { font-family: var(--font-mono); }

/* News */
.news-list { overflow: hidden; }
.list-header { padding: 8px 14px 6px; border-bottom: 1px solid var(--border); font-size: 12px; }
.news-item { padding: 9px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.news-item:last-child { border-bottom: none; }
.news-item:hover { background: var(--bg-hover); }
.ni-row { display: flex; align-items: flex-start; gap: 8px; }
.ni-title { flex: 1; font-size: 13px; color: var(--text-1); line-height: 1.4; }
.ni-time  { font-size: 11px; color: var(--text-3); flex-shrink: 0; font-family: var(--font-mono); white-space: nowrap; }
.ni-link  { padding-left: 15px; margin-top: 4px; }
.sdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.sdot.positive { background: var(--success); }
.sdot.negative { background: var(--danger); }
.sdot.neutral  { background: var(--text-3); }

/* AI */
.ai-start { padding: 40px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 16px; }
.loading-ai { padding: 40px; justify-content: center; }
.ai-result { padding: 20px; }
.ai-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; flex-wrap: wrap; gap: 8px; }
.ai-badge { font-size: 12px; font-weight: 700; color: #a78bfa; background: #8b5cf618; padding: 4px 10px; border-radius: 6px; }
.ai-meta { display: flex; align-items: center; gap: 10px; }
.sig-chip { font-size: 12px; font-weight: 600; padding: 2px 10px; border-radius: 10px; }
.sig-chip.bullish { background: #16a34a18; color: var(--success); }
.sig-chip.bearish { background: #ef444418; color: var(--danger); }
.sig-chip.neutral { background: var(--bg-elevated); color: var(--text-2); }
.ai-body { font-size: 13px; line-height: 1.8; color: var(--text-1); white-space: pre-wrap; }
.ai-body :deep(strong) { font-weight: 700; color: var(--accent); }
.ai-body :deep(h4) { font-size: 13px; font-weight: 700; margin: 10px 0 4px; color: var(--text-1); }
.tiny { font-size: 11px; }
.btn-sm { padding: 5px 14px; font-size: 12px; }

/* Loading / empty */
.loading-card { display: flex; align-items: center; gap: 10px; padding: 24px; }
.empty-state { padding: 60px; text-align: center; }
.empty-icon { font-size: 36px; margin-bottom: 12px; }
.empty-hint { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.empty-card { padding: 24px; text-align: center; }

/* Color helpers */
.pos { color: var(--success); }
.neg { color: var(--danger); }

/* Intraday overlay */
.intraday-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.7);
  z-index: 200;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
  backdrop-filter: blur(2px);
}
.intraday-modal {
  width: 100%; max-width: 720px;
  background: #0f1117;
  border: 1px solid #1f2937;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 32px 80px rgba(0,0,0,0.7);
}
.intraday-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px;
  background: #111827;
  border-bottom: 1px solid #1f2937;
  gap: 12px;
  flex-wrap: wrap;
}
.intraday-title { display: flex; flex-direction: column; gap: 2px; }
.iday-name  { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.iday-date  { font-size: 11px; color: #6b7280; }
.intraday-stats { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; flex: 1; justify-content: flex-end; }
.istat { font-size: 13px; font-weight: 700; }
.istat-item { font-size: 12px; color: #9ca3af; }
.istat-item b { color: #e2e8f0; }
.iday-close { background: none; border: 1px solid #374151; color: #9ca3af; border-radius: 6px; padding: 3px 9px; cursor: pointer; font-size: 13px; }
.iday-close:hover { color: #e2e8f0; border-color: #6b7280; }
.intraday-loading {
  display: flex; align-items: center; gap: 10px;
  padding: 60px; justify-content: center;
  background: #0f1117;
}
.iday-empty { padding: 40px; text-align: center; color: #6b7280; background: #0f1117; }
.up { color: #ef4444; }
.dn { color: #22c55e; }

@media (max-width: 768px) {
  .intraday-overlay { align-items: flex-end; padding: 0; }
  .intraday-modal { max-width: 100%; border-radius: 12px 12px 0 0; }
  .intraday-stats { gap: 8px; }
}
</style>
