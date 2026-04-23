<template>
  <div class="vd-wrap">

    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <div class="vd-header card">
      <button class="back-btn" @click="$router.back()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
        返回
      </button>
      <div class="vd-spacer"></div>
      <div class="vd-header-meta">
        <div class="hm-item"><span class="hm-lbl">预测日期</span><span class="hm-val">{{ pred.date }}</span></div>
        <div class="hm-item"><span class="hm-lbl">策略</span><span class="hm-val">{{ pred.strategy_name || pred.strategy || '-' }}</span></div>
        <div class="hm-item"><span class="hm-lbl">置信度</span><span class="hm-val">{{ pred.confidence }}%</span></div>
        <div class="hm-item"><span class="hm-lbl">风险</span><span :class="['risk-badge', 'r-' + (pred.risk_level||'中')]">{{ pred.risk_level || '-' }}</span></div>
      </div>
    </div>

    <!-- ── Stock overview ───────────────────────────────────────────────── -->
    <div v-if="stockOverview" class="ov-card card">
      <div class="ov-left">
        <div class="ov-name-row">
          <span class="ov-name">{{ stockOverview.name }}</span>
          <span class="ov-code">{{ pred.code }}</span>
          <span class="ov-market">{{ stockOverview.market }}</span>
        </div>
        <div class="ov-price-row">
          <span class="ov-price">{{ fmtPrice(stockOverview.price ?? stockOverview.yesterday_close) }}</span>
          <span :class="['ov-chg', chgClass(stockOverview.change_pct)]">{{ fmtChg(stockOverview.change_pct) }}</span>
        </div>
        <div class="ov-meta">
          <span>今开 <b>{{ fmtPrice(stockOverview.open) }}</b></span>
          <span>昨收 <b>{{ fmtPrice(stockOverview.yesterday_close) }}</b></span>
          <span>最高 <b class="pos">{{ fmtPrice(stockOverview.high) }}</b></span>
          <span>最低 <b class="neg">{{ fmtPrice(stockOverview.low) }}</b></span>
          <span>成交额 <b>{{ fmtAmount(stockOverview.turnover_amount) }}</b></span>
          <span>换手率 <b>{{ stockOverview.turnover_rate?.toFixed(2) ?? '-' }}%</b></span>
        </div>
      </div>
      <div class="ov-right">
        <div class="ov-metric" v-for="m in ovMetrics" :key="m.label">
          <span class="ov-metric-val" :class="m.cls">{{ m.value }}</span>
          <span class="ov-metric-lbl">{{ m.label }}</span>
        </div>
      </div>
    </div>

    <!-- ── Status banner ──────────────────────────────────────────────── -->
    <div v-if="detailBars.length" :class="['status-banner', 'sb-' + finalStatus]">

      <!-- Status + dates -->
      <div class="sb-main">
        <div :class="['sb-badge', 'sbb-' + finalStatus]">
          <span class="sbb-icon">{{ { target:'✓', stop:'✗', open:'◷' }[finalStatus] }}</span>
          {{ { target:'已达目标', stop:'已止损', open:'进行中' }[finalStatus] }}
        </div>
        <div class="sb-dates">
          <span>买入日 <b>{{ entryDate || '-' }}</b></span>
          <span v-if="triggerDate">· 结算日 <b>{{ triggerDate }}</b></span>
          <span>· 持仓 <b>{{ holdDays }}天</b></span>
        </div>
      </div>

      <!-- Final return — big number -->
      <div class="sb-return">
        <div :class="['sb-pct', finalReturn >= 0 ? 'pos' : 'neg']">
          {{ finalReturn >= 0 ? '+' : '' }}{{ finalReturn.toFixed(2) }}%
        </div>
        <div class="sb-pct-lbl">{{ finalStatus === 'open' ? '当前收益' : '最终收益' }}</div>
      </div>

      <!-- Price targets -->
      <div class="sb-prices">
        <div class="sb-p">
          <span class="sb-pl">买入</span>
          <span class="sb-pv">{{ actualBuyPrice }}</span>
        </div>
        <div class="sb-p">
          <span class="sb-pl">目标</span>
          <span class="sb-pv sb-tgt">{{ pred.target_price }} <em>+{{ pred.target_pct?.toFixed(1) }}%</em></span>
        </div>
        <div class="sb-p">
          <span class="sb-pl">止损</span>
          <span class="sb-pv sb-stp">{{ pred.stop_price }} <em>-{{ pred.stop_pct?.toFixed(1) }}%</em></span>
        </div>
      </div>

      <!-- Progress bar (current vs target/stop range) -->
      <div class="sb-progress" v-if="actualBuyPrice && pred.target_price && pred.stop_price">
        <div class="sbp-label sbl-stop">止损</div>
        <div class="sbp-track">
          <div class="sbp-fill" :style="progressStyle"></div>
          <div class="sbp-needle" :style="needleStyle" :title="'当前 ' + currentPrice"></div>
        </div>
        <div class="sbp-label sbl-target">目标</div>
      </div>

    </div>

    <!-- ── K-line chart ───────────────────────────────────────────────── -->
    <div class="card chart-wrap">
      <div class="chart-hd">
        <span class="chart-title">K线走势（推荐前后上下文）</span>
        <div style="display:flex;align-items:center;gap:14px">
          <div class="chart-legend" v-if="actualBuyPrice">
            <span class="leg-item"><i class="leg-dash" style="border-color:#fbbf24"></i>推荐日</span>
            <span class="leg-item"><i class="leg-dash" style="border-color:#9ca3af"></i>买入 {{ actualBuyPrice }}</span>
            <span class="leg-item"><i class="leg-dash" style="border-color:#22c55e"></i>目标 {{ pred.target_price }}</span>
            <span class="leg-item"><i class="leg-dash" style="border-color:#ef4444"></i>止损 {{ pred.stop_price }}</span>
          </div>
          <span style="font-size:10px;color:var(--accent)">点击K线查看分时</span>
        </div>
      </div>
      <div v-if="loadingChart" class="chart-loading"><span class="spinner"></span>加载行情…</div>
      <v-chart v-else-if="klineOpt" :option="klineOpt" autoresize style="height:420px" @click="onKlineClick" />
      <div v-else class="chart-empty">暂无行情数据</div>
    </div>

    <!-- ── Intraday modal ─────────────────────────────────────────────── -->
    <div v-if="intradayDate" class="intraday-overlay" @click.self="intradayDate=null">
      <div class="intraday-modal">
        <div class="intraday-head">
          <div class="intraday-title">
            <span class="iday-name">{{ pred.name }}</span>
            <span class="iday-date">{{ intradayDate }} · 1分钟分时</span>
          </div>
          <div v-if="intradayBars.length" class="intraday-stats">
            <span :class="['istat', intradayChg >= 0 ? 'up' : 'dn']">
              {{ intradayClose }} &nbsp;<b>{{ intradayChg >= 0 ? '+' : '' }}{{ intradayChg.toFixed(2) }}%</b>
            </span>
            <span class="istat-item">高 <b class="up">{{ intradayHigh }}</b></span>
            <span class="istat-item">低 <b class="dn">{{ intradayLow }}</b></span>
            <span class="istat-item">量 <b>{{ intradayVol }}</b></span>
          </div>
          <button class="iday-close" @click="intradayDate=null">✕</button>
        </div>
        <div v-if="loadingIntraday" class="intraday-loading"><span class="spinner"></span><span>加载分时数据...</span></div>
        <template v-else-if="intradayOption">
          <v-chart :option="intradayOption" autoresize style="height:260px" />
          <v-chart :option="intradayVolOption" autoresize style="height:80px" />
        </template>
        <div v-else class="iday-empty">
          <div>该日分时数据暂未缓存</div>
          <div style="font-size:11px;margin-top:6px;color:#4b5563">系统将在后台自动获取，稍后重试</div>
        </div>
      </div>
    </div>

    <!-- ── Daily returns table ─────────────────────────────────────────── -->
    <div class="card" v-if="detailBars.length">
      <div class="tbl-hd">
        <span class="tbl-title">逐日持仓追踪</span>
        <span class="tbl-note">买入价 {{ actualBuyPrice }}，共追踪 {{ detailBars.length }} 个交易日</span>
      </div>
      <div class="daily-wrap">
        <table class="daily-tbl">
          <thead>
            <tr>
              <th>#</th><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th>
              <th>较买入%</th><th>当日涨跌</th><th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(b, i) in detailBars" :key="b.date"
              :class="['dtr', b.isTriggerDay && 'dtr-trigger', b.isAfterLock && 'dtr-dim']">
              <td class="dt-idx">{{ i + 1 }}</td>
              <td class="dt-date">{{ b.date }}</td>
              <td class="dt-mono">{{ b.open }}</td>
              <td class="dt-mono" :class="!b.isAfterLock && 'td-high'">{{ b.high }}</td>
              <td class="dt-mono" :class="!b.isAfterLock && 'td-low'">{{ b.low }}</td>
              <td class="dt-mono" :class="!b.isAfterLock && (b.dayChg >= 0 ? 'td-up' : 'td-dn')">{{ b.close }}</td>
              <td :class="['dt-pct', b.vsBuy >= 0 ? 'td-up' : 'td-dn']">
                {{ b.vsBuy >= 0 ? '+' : '' }}{{ b.vsBuy.toFixed(2) }}%
                <span v-if="b.isTriggerDay" class="locked-tag">锁定</span>
              </td>
              <td :class="b.isAfterLock ? 'dt-dim' : (b.dayChg >= 0 ? 'td-up' : 'td-dn')">
                {{ b.dayChg >= 0 ? '+' : '' }}{{ b.dayChg.toFixed(2) }}%
              </td>
              <td>
                <span v-if="b.tradeStatus === 'target'" class="status-chip st-hit">达目标</span>
                <span v-else-if="b.tradeStatus === 'stop'" class="status-chip st-stp">触止损</span>
                <span v-else class="status-chip st-open">持仓中</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Individual stock analysis ─────────────────────────────────── -->
    <StockAnalysisPanel v-if="pred.code" :symbol="pred.code" :hide-overview="true" />

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import StockAnalysisPanel from '../components/StockAnalysisPanel.vue'

const route = useRoute()

const pred           = ref({})
const stockOverview  = ref(null)
const detailBars     = ref([])
const allContextBars = ref([])   // broader set including pre-prediction context
const loadingChart   = ref(false)
const entryDate      = ref('')
const triggerDate    = ref(null)
const finalStatus    = ref('open')
const finalReturn    = ref(0)
const actualBuyPrice = ref(null)

// Intraday
const intradayDate    = ref(null)
const intradayBars    = ref([])
const loadingIntraday = ref(false)

// ── Derived ────────────────────────────────────────────────────────────────────
const currentPrice = computed(() => detailBars.value[detailBars.value.length - 1]?.close ?? actualBuyPrice.value)
const holdDays     = computed(() => {
  const activeBars = detailBars.value.filter(b => !b.isAfterLock)
  return activeBars.length || detailBars.value.length
})

// Progress bar: map current price into [stop, target] range 0→100
const progressStyle = computed(() => {
  const buy = actualBuyPrice.value
  const tgt = pred.value.target_price
  const stp = pred.value.stop_price
  if (!buy || !tgt || !stp) return {}
  const range = tgt - stp
  const cur   = finalStatus.value === 'open' ? (currentPrice.value || buy) : (finalStatus.value === 'target' ? tgt : stp)
  const pct   = Math.min(100, Math.max(0, (cur - stp) / range * 100))
  const color = finalStatus.value === 'target' ? '#22c55e' : finalStatus.value === 'stop' ? '#ef4444' : '#3b82f6'
  return { width: pct + '%', background: color }
})

const needleStyle = computed(() => {
  const buy = actualBuyPrice.value
  const tgt = pred.value.target_price
  const stp = pred.value.stop_price
  if (!buy || !tgt || !stp) return {}
  const range = tgt - stp
  const cur   = finalStatus.value === 'open' ? (currentPrice.value || buy) : (finalStatus.value === 'target' ? tgt : stp)
  const pct   = Math.min(100, Math.max(0, (cur - stp) / range * 100))
  return { left: pct + '%' }
})

// ── Overview helpers ──────────────────────────────────────────────────────────
function fmtPrice(v)   { return (v == null || v === 0) ? '-' : Number(v).toFixed(2) }
function fmtChg(v)     { return v == null ? '-' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }
function fmtAmount(v)  { if (!v) return '-'; return v >= 1e8 ? (v/1e8).toFixed(2)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : String(v) }
function fmtBillion(v) { return v ? (v/1e8).toFixed(1)+'亿' : '-' }
function chgClass(v)   { return v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '' }

const ovMetrics = computed(() => {
  const o = stockOverview.value
  if (!o) return []
  return [
    { label: 'PE(TTM)', value: o.pe_ttm?.toFixed(2) ?? '-' },
    { label: 'PB',      value: o.pb?.toFixed(2) ?? '-' },
    { label: 'ROE',     value: o.roe ? o.roe + '%' : '-', cls: o.roe > 15 ? 'pos' : o.roe > 0 ? '' : 'neg' },
    { label: '总市值',   value: fmtBillion(o.market_cap) },
    { label: '流通市值', value: fmtBillion(o.circ_cap) },
    { label: '毛利率',   value: o.gross_margin != null ? o.gross_margin.toFixed(1) + '%' : '-' },
  ]
})

async function loadOverview(sym) {
  if (!sym) return
  try {
    const r = await axios.get(`/api/stock-analysis/${sym}/overview`)
    stockOverview.value = r.data
  } catch {}
}

function outLabel(o) {
  return { hit_target: '达目标', hit_stop: '触止损', positive: '正收益', negative: '负收益', neutral: '持平', open: '待验证' }[o] || '待验证'
}

// ── Intraday computed ──────────────────────────────────────────────────────────
const intradayBaseline = computed(() => intradayBars.value[0]?.open || 0)
const intradayClose    = computed(() => { const b = intradayBars.value; return b.length ? b[b.length-1].close : 0 })
const intradayChg      = computed(() => { const base = intradayBaseline.value; return base ? ((intradayClose.value - base) / base * 100) : 0 })
const intradayHigh     = computed(() => intradayBars.value.length ? Math.max(...intradayBars.value.map(b => b.high)) : 0)
const intradayLow      = computed(() => intradayBars.value.length ? Math.min(...intradayBars.value.map(b => b.low)) : 0)
const intradayVol      = computed(() => { const t = intradayBars.value.reduce((s,b)=>s+b.volume,0); return t>=1e4?(t/1e4).toFixed(0)+'万手':t.toFixed(0)+'手' })

function calcVwap(bars) {
  let cumVol = 0, cumTurnover = 0
  return bars.map(b => { const avg=(b.open+b.close+b.high+b.low)/4; cumVol+=b.volume; cumTurnover+=avg*b.volume; return cumVol?+(cumTurnover/cumVol).toFixed(3):null })
}

const intradayOption = computed(() => {
  if (!intradayBars.value.length) return null
  const bars=intradayBars.value, times=bars.map(b=>b.datetime?.slice(11,16)||b.datetime)
  const closes=bars.map(b=>b.close), base=intradayBaseline.value, vwap=calcVwap(bars)
  const isUp=intradayClose.value>=base
  const priceRange=Math.max(Math.abs(intradayHigh.value-base),Math.abs(intradayLow.value-base))
  const yMin=+(base-priceRange*1.1).toFixed(2), yMax=+(base+priceRange*1.1).toFixed(2)
  const mainColor=isUp?'#ef4444':'#22c55e'
  return {
    backgroundColor:'#0f1117', animation:false,
    tooltip:{ trigger:'axis', axisPointer:{type:'cross',crossStyle:{color:'#4b5563'}}, backgroundColor:'#1a2234', borderColor:'#2d3748', textStyle:{color:'#e2e8f0',fontSize:12},
      formatter:params=>{const cp=params.find(p=>p.seriesName==='分时');const vp=params.find(p=>p.seriesName==='VWAP');if(!cp)return'';const chg=((cp.value-base)/base*100);return`<b>${cp.name}</b><br/>价格 <b style="color:${cp.value>=base?'#ef4444':'#22c55e'}">${cp.value}</b> (${chg>=0?'+':''}${chg.toFixed(2)}%)<br/>均价 <b style="color:#f6ad55">${vp?.value??'-'}</b>`}},
    grid:{top:12,left:72,right:60,bottom:24},
    xAxis:{type:'category',data:times,boundaryGap:false,axisLine:{lineStyle:{color:'#2d3748'}},axisLabel:{color:'#6b7280',fontSize:10}},
    yAxis:[
      {type:'value',scale:false,min:yMin,max:yMax,position:'left',splitLine:{lineStyle:{color:'#1a2234',type:'dashed'}},axisLabel:{color:'#9ca3af',fontSize:10},axisLine:{show:false}},
      {type:'value',scale:false,min:yMin,max:yMax,position:'right',splitLine:{show:false},axisLabel:{color:'#9ca3af',fontSize:10,formatter:v=>{const p=((v-base)/base*100);return(p>=0?'+':'')+p.toFixed(1)+'%'}},axisLine:{show:false}},
    ],
    series:[
      {name:'分时',type:'line',data:closes,showSymbol:false,lineStyle:{color:mainColor,width:1.5},
       areaStyle:{color:{type:'linear',x:0,y:0,x2:0,y2:1,colorStops:[{offset:0,color:isUp?'rgba(239,68,68,0.15)':'rgba(34,197,94,0.15)'},{offset:1,color:'rgba(0,0,0,0)'}]}},
       markLine:{silent:true,symbol:'none',lineStyle:{type:'solid',color:'#4b5563',width:1},label:{show:true,position:'insideStartTop',formatter:`昨收 ${base}`,color:'#6b7280',fontSize:9},data:[{yAxis:base}]}},
      {name:'VWAP',type:'line',data:vwap,showSymbol:false,lineStyle:{color:'#f6ad55',width:1}},
    ],
  }
})

const intradayVolOption = computed(() => {
  if (!intradayBars.value.length) return null
  const bars=intradayBars.value, times=bars.map(b=>b.datetime?.slice(11,16)||b.datetime), base=intradayBaseline.value
  return {
    backgroundColor:'#0f1117',animation:false,
    tooltip:{trigger:'axis',backgroundColor:'#1a2234',borderColor:'#2d3748',textStyle:{color:'#e2e8f0',fontSize:11},formatter:p=>`${p[0].name}<br/>量 <b>${(p[0].value/1e4).toFixed(1)}万手</b>`},
    grid:{top:4,left:72,right:60,bottom:24},
    xAxis:{type:'category',data:times,boundaryGap:false,axisLine:{lineStyle:{color:'#2d3748'}},axisLabel:{color:'#6b7280',fontSize:9}},
    yAxis:{type:'value',splitLine:{show:false},axisLabel:{color:'#6b7280',fontSize:9,formatter:v=>v>=1e4?(v/1e4).toFixed(0)+'w':v}},
    series:[{type:'bar',data:bars.map(b=>b.volume),barMaxWidth:6,itemStyle:{color:p=>bars[p.dataIndex]?.close>=base?'rgba(239,68,68,0.8)':'rgba(34,197,94,0.8)'}}],
  }
})

async function onKlineClick(params) {
  if (!params?.name || !pred.value.code) return
  intradayDate.value = params.name
  intradayBars.value = []
  loadingIntraday.value = true
  try {
    const res = await axios.get(`/api/market/intraday/${pred.value.code}`, { params: { klt: 1, date: params.name } })
    intradayBars.value = res.data.bars || []
  } catch {}
  loadingIntraday.value = false
}

// ── K-line chart ──────────────────────────────────────────────────────────────
const klineOpt = computed(() => {
  // Use broader context bars (pre + post prediction), fall back to detailBars
  const bars = allContextBars.value.length ? allContextBars.value : detailBars.value
  if (!bars.length) return null

  const dates   = bars.map(b => b.date)
  const candles = bars.map(b => [b.open, b.close, b.low, b.high])
  const volumes = bars.map(b => ({
    value: b.volume,
    itemStyle: { color: b.close >= b.open ? '#ef444488' : '#22c55e88' },
  }))

  const buy     = actualBuyPrice.value
  const tgt     = pred.value.target_price
  const stp     = pred.value.stop_price
  const predDate = pred.value.date

  // Horizontal price lines
  const hLines = []
  if (buy) hLines.push({ yAxis: buy, lineStyle: { color: '#9ca3af', type: 'dashed', width: 1.5 }, label: { formatter: `买入 ${buy}`, color: '#9ca3af', fontSize: 10, position: 'insideEndTop' } })
  if (tgt) hLines.push({ yAxis: tgt, lineStyle: { color: '#22c55e', type: 'dashed', width: 1.5 }, label: { formatter: `目标 ${tgt}`, color: '#22c55e', fontSize: 10, position: 'insideEndTop' } })
  if (stp) hLines.push({ yAxis: stp, lineStyle: { color: '#ef4444', type: 'dashed', width: 1.5 }, label: { formatter: `止损 ${stp}`, color: '#ef4444', fontSize: 10, position: 'insideEndTop' } })

  // Vertical line at recommendation date (find nearest trading day if exact date not in series)
  const markerDate = predDate && (dates.includes(predDate) ? predDate : dates.find(d => d >= predDate))
  if (markerDate) {
    hLines.push({ xAxis: markerDate, lineStyle: { color: '#fbbf24', type: 'solid', width: 2, opacity: 0.8 }, label: { formatter: '推荐日', color: '#fbbf24', fontSize: 10, position: 'insideEndTop' } })
  }

  // Mark trigger day
  const markPoints = []
  const trigIdx = triggerDate.value ? dates.indexOf(triggerDate.value) : -1
  if (trigIdx >= 0) {
    const clr = finalStatus.value === 'target' ? '#22c55e' : '#ef4444'
    const lbl = finalStatus.value === 'target' ? '达目标' : '止损'
    markPoints.push({
      coord: [trigIdx, finalStatus.value === 'target' ? bars[trigIdx].high : bars[trigIdx].low],
      symbol: 'pin', symbolSize: 22,
      itemStyle: { color: clr },
      label: { show: true, formatter: lbl, color: '#fff', fontSize: 9, fontWeight: 700 },
    })
  }

  // DataZoom: default to showing from ~20 days before prediction date
  const predIdx    = predDate ? Math.max(0, dates.indexOf(predDate) - 20) : 0
  const startValue = predIdx

  return {
    backgroundColor: 'transparent', animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: '#374151' } },
      backgroundColor: '#1e2537', borderColor: '#2d3748',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: params => {
        const k = params.find(p => p.seriesName === 'K')
        if (!k) return ''
        const [o, c, lo, h] = k.data
        const dayChg = ((c - o) / o * 100).toFixed(2)
        const vsBuy  = buy ? ((c - buy) / buy * 100).toFixed(2) : null
        const col    = c >= o ? '#ef4444' : '#22c55e'
        return `<b>${k.name}</b><br/>
          开 ${o} &nbsp; 收 <span style="color:${col};font-weight:700">${c}</span><br/>
          高 ${h} &nbsp; 低 ${lo}<br/>
          当日 <span style="color:${col}">${dayChg >= 0 ? '+' : ''}${dayChg}%</span>
          ${vsBuy !== null ? `&nbsp; 较买入 <span style="color:${c >= buy ? '#ef4444' : '#22c55e'}">${vsBuy >= 0 ? '+' : ''}${vsBuy}%</span>` : ''}`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], startValue, endValue: dates.length - 1 },
      { type: 'slider', xAxisIndex: [0, 1], height: 20, bottom: 2, startValue, endValue: dates.length - 1,
        borderColor: 'transparent', fillerColor: 'rgba(59,130,246,0.15)',
        handleStyle: { color: '#3b82f6' }, textStyle: { color: '#6b7280' } },
    ],
    grid: [
      { top: 16, left: 72, right: 16, bottom: 80 },
      { top: '78%', left: 72, right: 16, bottom: 32 },
    ],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
        axisLine: { lineStyle: { color: '#1f2937' } }, axisLabel: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true,
        axisLine: { lineStyle: { color: '#1f2937' } },
        axisLabel: { color: '#6b7280', fontSize: 10 } },
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
        markLine: hLines.length ? { silent: true, symbol: 'none', data: hLines } : undefined,
        markPoint: markPoints.length ? { data: markPoints } : undefined,
      },
      {
        name: 'Vol', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: volumes, barMaxWidth: 8,
      },
    ],
  }
})

// ── Data loading ──────────────────────────────────────────────────────────────
async function loadDetail() {
  const code = pred.value.code
  if (!code) return
  loadingChart.value = true
  try {
    const res = await axios.get(`/api/stock-analysis/${code}/technical`, { params: { days: 180 } })
    const allBars  = res.data?.bars || []
    const predDate = pred.value.date || ''

    // Store full context for K-line chart (includes pre-prediction history)
    allContextBars.value = allBars

    // Entry: first bar AFTER prediction date (simulate buying next day)
    const entryIdx = allBars.findIndex(b => b.date > predDate)
    if (entryIdx < 0) { loadingChart.value = false; return }

    const bars = allBars.slice(entryIdx, entryIdx + 60)
    entryDate.value = bars[0].date

    const buyPrice = pred.value.buy_price || bars[0].open || bars[0].close
    actualBuyPrice.value = buyPrice

    const tgt = pred.value.target_price
    const stp = pred.value.stop_price

    let triggered = false
    let locStatus = null
    let locReturn = 0
    let locDate   = null

    const processed = bars.map((b, i) => {
      let isTriggerDay = false
      let isAfterLock  = triggered

      if (!triggered) {
        if (stp && b.low <= stp) {
          triggered = true; locStatus = 'stop'
          locReturn = (stp - buyPrice) / buyPrice * 100
          locDate = b.date; isTriggerDay = true
        } else if (tgt && b.high >= tgt) {
          triggered = true; locStatus = 'target'
          locReturn = (tgt - buyPrice) / buyPrice * 100
          locDate = b.date; isTriggerDay = true
        }
        isAfterLock = false
      } else {
        isAfterLock = !isTriggerDay
      }

      return {
        ...b,
        vsBuy:       triggered ? locReturn : (b.close - buyPrice) / buyPrice * 100,
        dayChg:      i === 0 ? 0 : (b.close - bars[i-1].close) / bars[i-1].close * 100,
        tradeStatus: triggered ? locStatus : 'open',
        isTriggerDay,
        isAfterLock,
      }
    })

    detailBars.value  = processed
    finalStatus.value = locStatus || 'open'
    finalReturn.value = triggered ? locReturn : (processed[processed.length - 1]?.vsBuy ?? 0)
    triggerDate.value = locDate

    // Pre-fetch and cache intraday data for all tracking days
    prefetchIntraday(code, processed.map(b => b.date))

  } catch {}
  loadingChart.value = false
}

async function prefetchIntraday(code, dates) {
  if (!code || !dates.length) return
  try {
    await axios.post('/api/market/prefetch-intraday', { symbol: code, dates, klt: 1 })
  } catch {}
}

onMounted(() => {
  try {
    const raw = sessionStorage.getItem('verifyPred')
    if (raw) pred.value = JSON.parse(raw)
  } catch {}

  if (!pred.value.code && route.query.code) {
    pred.value = {
      code: route.query.code, name: route.query.name || route.query.code,
      date: route.query.date || '',
      buy_price:    parseFloat(route.query.buy)        || null,
      target_price: parseFloat(route.query.target)     || null,
      stop_price:   parseFloat(route.query.stop)       || null,
      target_pct:   parseFloat(route.query.target_pct) || null,
      stop_pct:     parseFloat(route.query.stop_pct)   || null,
      confidence:   parseFloat(route.query.confidence) || null,
      risk_level:   route.query.risk    || null,
      outcome:      route.query.outcome || 'open',
    }
  }

  loadDetail()
  loadOverview(pred.value.code)
})
</script>

<style scoped>
.vd-wrap { padding: 20px; display: flex; flex-direction: column; gap: 14px; }

/* ── Header ── */
.vd-header { padding: 14px 18px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.back-btn {
  display: flex; align-items: center; gap: 6px;
  background: var(--bg-elevated); border: 1px solid var(--border);
  color: var(--text-2); border-radius: var(--radius-md); padding: 6px 12px;
  font-size: 13px; cursor: pointer; transition: all 0.12s; flex-shrink: 0;
}
.back-btn:hover { color: var(--text-1); border-color: var(--text-3); }
.vd-stock  { display: flex; align-items: center; gap: 8px; }
.vd-name   { font-size: 18px; font-weight: 700; color: var(--text-1); }
.vd-code   { font-size: 13px; color: var(--text-3); font-family: var(--font-mono); }
.vd-spacer { flex: 1; }
.vd-header-meta { display: flex; gap: 20px; flex-wrap: wrap; }
.hm-item { display: flex; flex-direction: column; gap: 2px; }
.hm-lbl  { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
.hm-val  { font-size: 13px; font-weight: 600; color: var(--text-1); }
.risk-badge { padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.r-低 { background: #14532d33; color: #4ade80; }
.r-中 { background: #78350f33; color: #fbbf24; }
.r-高 { background: #7f1d1d33; color: #f87171; }

/* ── Status banner ── */
.status-banner {
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  padding: 18px 22px;
  display: grid;
  grid-template-columns: auto 1fr auto;
  grid-template-rows: auto auto;
  gap: 14px 24px;
  align-items: center;
}
.sb-open   { background: linear-gradient(135deg, rgba(59,130,246,0.08) 0%, var(--bg-card) 60%); border-color: #1d4ed844; }
.sb-target { background: linear-gradient(135deg, rgba(34,197,94,0.1) 0%, var(--bg-card) 60%);  border-color: #15803d44; }
.sb-stop   { background: linear-gradient(135deg, rgba(239,68,68,0.1) 0%, var(--bg-card) 60%);  border-color: #b91c1c44; }

.sb-main  { display: flex; flex-direction: column; gap: 6px; }
.sb-badge {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 15px; font-weight: 700; padding: 5px 14px;
  border-radius: 20px; width: fit-content;
}
.sbb-open   { background: #1d4ed822; color: #60a5fa; }
.sbb-target { background: #15803d22; color: #4ade80; }
.sbb-stop   { background: #b91c1c22; color: #f87171; }
.sbb-icon   { font-size: 13px; }

.sb-dates   { font-size: 12px; color: var(--text-3); display: flex; gap: 6px; flex-wrap: wrap; }
.sb-dates b { color: var(--text-2); }

.sb-return      { text-align: center; }
.sb-pct         { font-size: 36px; font-weight: 800; font-family: var(--font-mono); line-height: 1; }
.sb-pct-lbl     { font-size: 11px; color: var(--text-3); margin-top: 4px; text-align: center; }

.sb-prices      { display: flex; flex-direction: column; gap: 6px; }
.sb-p           { display: flex; align-items: center; gap: 8px; }
.sb-pl          { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; width: 28px; }
.sb-pv          { font-size: 13px; font-weight: 600; color: var(--text-1); font-family: var(--font-mono); }
.sb-pv em       { font-style: normal; font-size: 11px; margin-left: 4px; }
.sb-tgt em      { color: #4ade80; }
.sb-stp em      { color: #f87171; }

/* Progress bar */
.sb-progress {
  grid-column: 1 / -1;
  display: flex; align-items: center; gap: 8px;
}
.sbp-label  { font-size: 10px; font-weight: 600; flex-shrink: 0; }
.sbl-stop   { color: #f87171; }
.sbl-target { color: #4ade80; }
.sbp-track  {
  flex: 1; height: 6px; background: var(--bg-elevated);
  border-radius: 3px; position: relative; overflow: visible;
}
.sbp-fill   { height: 100%; border-radius: 3px; transition: width 0.4s; }
.sbp-needle {
  position: absolute; top: 50%; transform: translate(-50%, -50%);
  width: 12px; height: 12px; background: #fff;
  border-radius: 50%; border: 2px solid #6b7280;
  box-shadow: 0 0 0 2px rgba(0,0,0,0.3);
  transition: left 0.4s;
}

/* ── Chart ── */
.chart-wrap  { overflow: hidden; }
.chart-hd    { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px 4px; }
.chart-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.chart-legend { display: flex; gap: 14px; }
.leg-item    { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-3); }
.leg-dash    { display: inline-block; width: 20px; height: 0; border-top: 2px dashed; }
.chart-loading { display: flex; align-items: center; gap: 8px; padding: 60px; justify-content: center; color: var(--text-3); }
.chart-empty   { padding: 60px; text-align: center; color: var(--text-3); font-size: 13px; }

/* ── Table ── */
.tbl-hd    { display: flex; align-items: center; gap: 10px; padding: 14px 16px 10px; border-bottom: 1px solid var(--border); }
.tbl-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.tbl-note  { font-size: 11px; color: var(--text-3); }

.daily-wrap { overflow-y: auto; max-height: 500px; }
.daily-tbl  { width: 100%; border-collapse: collapse; font-size: 12px; }
.daily-tbl th {
  position: sticky; top: 0; background: var(--bg-elevated);
  color: var(--text-3); font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.03em; font-weight: 600; padding: 8px 10px;
  text-align: left; border-bottom: 1px solid var(--border);
}
.daily-tbl td { padding: 7px 10px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.daily-tbl tr:last-child td { border-bottom: none; }

/* Row states */
.dtr:hover td          { background: var(--bg-hover); }
.dtr-trigger td        { background: rgba(250,204,21,0.06) !important; }
.dtr-dim td            { opacity: 0.42; }

.dt-idx  { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); width: 28px; }
.dt-date { font-family: var(--font-mono); color: var(--text-3); font-size: 11px; white-space: nowrap; }
.dt-mono { font-family: var(--font-mono); }
.dt-pct  { font-weight: 700; font-family: var(--font-mono); }
.dt-dim  { color: var(--text-3) !important; }
.td-high { color: #f87171; }
.td-low  { color: #4ade80; }
.td-up   { color: #ef4444; }
.td-dn   { color: #22c55e; }

.locked-tag {
  display: inline-block; margin-left: 5px;
  font-size: 9px; padding: 1px 4px; border-radius: 3px;
  background: #78350f44; color: #fbbf24; font-weight: 700;
  vertical-align: middle;
}

.status-chip { padding: 2px 7px; border-radius: 8px; font-size: 10px; font-weight: 600; }
.st-hit  { background: #14532d33; color: #4ade80; }
.st-stp  { background: #7f1d1d33; color: #f87171; }
.st-open { background: var(--bg-elevated); color: var(--text-3); }

/* ── Intraday modal ── */
.intraday-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 200; display: flex; align-items: center; justify-content: center; padding: 20px; backdrop-filter: blur(2px); }
.intraday-modal { width: 100%; max-width: 720px; background: #0f1117; border: 1px solid #1f2937; border-radius: 10px; overflow: hidden; box-shadow: 0 32px 80px rgba(0,0,0,0.7); }
.intraday-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; background: #111827; border-bottom: 1px solid #1f2937; gap: 12px; flex-wrap: wrap; }
.intraday-title { display: flex; flex-direction: column; gap: 2px; }
.iday-name  { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.iday-date  { font-size: 11px; color: #6b7280; }
.intraday-stats { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; flex: 1; justify-content: flex-end; }
.istat { font-size: 13px; font-weight: 700; }
.istat-item { font-size: 12px; color: #9ca3af; }
.istat-item b { color: #e2e8f0; }
.iday-close { background: none; border: 1px solid #374151; color: #9ca3af; border-radius: 6px; padding: 3px 9px; cursor: pointer; font-size: 13px; }
.iday-close:hover { color: #e2e8f0; }
.intraday-loading { display: flex; align-items: center; gap: 10px; padding: 60px; justify-content: center; background: #0f1117; color: #6b7280; }
.iday-empty { padding: 40px; text-align: center; color: #6b7280; background: #0f1117; }
.up { color: #ef4444; }
.dn { color: #22c55e; }

/* ── Overview card ── */
.ov-card { display: flex; gap: 24px; padding: 16px 20px; flex-wrap: wrap; }
.ov-left { flex: 1; min-width: 260px; }
.ov-name-row { display: flex; align-items: center; gap: 8px; }
.ov-name   { font-size: 18px; font-weight: 700; color: var(--text-1); }
.ov-code   { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }
.ov-market { font-size: 11px; color: var(--text-3); padding: 1px 6px; border: 1px solid var(--border); border-radius: 4px; }
.ov-price-row { display: flex; align-items: baseline; gap: 10px; margin: 6px 0 4px; }
.ov-price { font-size: 28px; font-weight: 800; color: var(--text-1); font-family: var(--font-mono); }
.ov-chg   { font-size: 15px; font-weight: 600; }
.ov-meta  { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-2); }
.ov-meta b { color: var(--text-1); }
.ov-right { display: flex; flex-wrap: wrap; gap: 10px; align-content: flex-start; }
.ov-metric { background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 7px 12px; text-align: center; min-width: 72px; }
.ov-metric-val { display: block; font-size: 15px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.ov-metric-lbl { font-size: 10px; color: var(--text-3); margin-top: 2px; }

.pos { color: var(--success); }
.neg { color: var(--danger); }

@media (max-width: 900px) {
  .status-banner { grid-template-columns: 1fr 1fr; }
  .sb-progress   { grid-column: 1 / -1; }
  .vd-header-meta { display: none; }
}
@media (max-width: 600px) {
  .vd-wrap { padding: 12px; }
  .status-banner { grid-template-columns: 1fr; }
  .sb-pct { font-size: 28px; }
}
</style>
