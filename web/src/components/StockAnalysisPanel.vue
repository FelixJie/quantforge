<template>
  <div class="sap-wrap">

    <!-- ── Loading ─────────────────────────────────────────────────────── -->
    <div v-if="loadingOverview" class="card loading-card">
      <span class="spinner"></span><span class="text-2">加载中...</span>
    </div>

    <template v-else-if="overview">

      <!-- ── 1. 概览 ───────────────────────────────────────────────────── -->
      <template v-if="!hideOverview">
      <div class="ov-card card">
        <div class="ov-left">
          <div class="ov-name">{{ overview.name }}<span class="ov-code">{{ overview.symbol }}</span></div>
          <div class="ov-price-row">
            <span class="ov-price">{{ fmtPrice(overview.price ?? overview.yesterday_close) }}</span>
            <span :class="['ov-chg', chgClass(overview.change_pct)]">{{ fmtChg(overview.change_pct) }}</span>
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
        </div>
      </div>

      </template><!-- /hideOverview -->

      <!-- ── 2. 技术信号 ───────────────────────────────────────────────── -->
      <div v-if="!loadingTech && technical" :class="['signal-banner', technical.signal]">
        <span class="signal-label">技术信号</span>
        <span class="signal-val">{{ signalText[technical.signal] ?? '-' }}</span>
        <span class="signal-meta">
          支撑 <b>{{ technical.support ?? '-' }}</b> &nbsp;·&nbsp; 压力 <b>{{ technical.resistance ?? '-' }}</b>
        </span>
        <div class="signal-chips">
          <span v-if="lastRsi" :class="['ind-chip', lastRsi > 70 ? 'overbought' : lastRsi < 30 ? 'oversold' : 'neutral-chip']">
            RSI&nbsp;{{ lastRsi.toFixed(1) }}
          </span>
          <span v-if="macdState" :class="['ind-chip', macdState.goldenCross ? 'golden' : macdState.deathCross ? 'death' : macdState.positive ? 'macd-pos' : 'macd-neg']">
            MACD&nbsp;{{ macdState.label }}
          </span>
        </div>
      </div>

      <!-- ── 3. AI综合分析 ──────────────────────────────────────────────── -->
      <div class="section-block card">
        <div class="sec-title-row">
          <span class="sec-title">AI综合分析</span>
          <button v-if="aiResult && !loadingAI" class="btn-ghost btn-sm" @click="runAI">重新分析</button>
        </div>
        <div v-if="loadingAI" class="sec-loading loading-ai">
          <span class="spinner"></span>AI 正在分析 {{ overview.name }}，请稍候...
        </div>
        <template v-else-if="aiResult">
          <!-- Verdict badges -->
          <div v-if="aiResult.verdicts && Object.keys(aiResult.verdicts).length" class="verdict-row">
            <div v-for="(val, key) in aiResult.verdicts" :key="key" :class="['verdict-chip', verdictClass(val)]">
              <span class="vd-dim">{{ { news:'消息面', tech:'技术面', fundamental:'基本面', overall:'综合' }[key] }}</span>
              <span class="vd-val">{{ val }}</span>
            </div>
          </div>
          <div class="ai-result-body">
            <div class="ai-meta-row">
              <span class="text-3 tiny">{{ aiResult.generated_at?.replace('T',' ') }}</span>
            </div>
            <div class="ai-body" v-html="renderMarkdown(aiResult.analysis)"></div>
          </div>
        </template>
        <div v-else class="sec-empty"><span class="spinner"></span></div>
      </div>

      <!-- ── 4. 消息面 ─────────────────────────────────────────────────── -->
      <div class="section-block card">
        <div class="sec-title">消息面</div>

        <!-- Sentiment bar -->
        <div v-if="!loadingNews" class="sentiment-bar">
          <div class="sb-item sb-pos">
            <span class="sb-count">{{ sentimentCounts.positive }}</span>
            <span class="sb-lbl">利好</span>
          </div>
          <div class="sb-track">
            <div class="sb-seg seg-pos" :style="{ flex: sentimentCounts.positive }"></div>
            <div class="sb-seg seg-neu" :style="{ flex: sentimentCounts.neutral }"></div>
            <div class="sb-seg seg-neg" :style="{ flex: sentimentCounts.negative }"></div>
          </div>
          <div class="sb-item sb-neu">
            <span class="sb-count">{{ sentimentCounts.neutral }}</span>
            <span class="sb-lbl">中立</span>
          </div>
          <div class="sb-item sb-neg">
            <span class="sb-count">{{ sentimentCounts.negative }}</span>
            <span class="sb-lbl">利空</span>
          </div>
          <div class="sb-total">共 {{ newsItems.length }} 条</div>
        </div>

        <!-- News list -->
        <div v-if="loadingNews" class="sec-loading"><span class="spinner"></span>加载公告...</div>
        <template v-else-if="newsItems.length">
          <div v-for="item in newsItems" :key="item.title+item.date" class="news-item" @click="item._exp = !item._exp">
            <div class="ni-row">
              <span :class="['sdot', item.sentiment]"></span>
              <span class="ni-title">{{ item.title }}</span>
              <span class="ni-time">{{ item.date }}</span>
            </div>
            <div v-if="item._exp && item.url" class="ni-link">
              <a :href="item.url" target="_blank" class="text-3" style="font-size:11px">查看原文 →</a>
            </div>
          </div>
        </template>
        <div v-else class="sec-empty">暂无公告数据</div>

        <!-- 龙虎榜 -->
        <template v-if="fundamental?.billboard?.length">
          <div class="sub-title" style="margin-top:16px">近期龙虎榜</div>
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
        </template>

        <!-- 十大股东 -->
        <template v-if="fundamental?.holders?.length">
          <div class="sub-title" style="margin-top:16px">十大股东（最新两期）</div>
          <table class="data-table">
            <thead><tr><th>报告期</th><th>股东名称</th><th>类型</th><th>持股(万)</th><th>持股%</th><th>变动</th></tr></thead>
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
        </template>
      </div>

    </template>

    <div v-else-if="!loadingOverview" class="card loading-card"><span class="text-3">暂无数据</span></div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  symbol:      { type: String, required: true },
  hideOverview: { type: Boolean, default: false },
})

// ── State ──────────────────────────────────────────────────────────────────────
const overview    = ref(null)
const technical   = ref(null)
const fundamental = ref(null)
const newsItems   = ref([])
const aiResult    = ref(null)

const loadingOverview = ref(false)
const loadingTech     = ref(false)
const loadingFund     = ref(false)
const loadingNews     = ref(false)
const loadingAI       = ref(false)

const signalText = { bullish: '多头趋势', bearish: '空头趋势', neutral: '震荡整理' }

// ── Computed ───────────────────────────────────────────────────────────────────
const overviewMetrics = computed(() => {
  const o = overview.value
  if (!o) return []
  return [
    { label: 'PE(TTM)', value: o.pe_ttm?.toFixed(2) ?? '-' },
    { label: 'PB',      value: o.pb?.toFixed(2) ?? '-' },
    { label: 'ROE',     value: o.roe ? o.roe + '%' : '-', cls: roeClass(o.roe) },
    { label: '总市值',  value: fmtBillion(o.market_cap) },
    { label: '流通市值', value: fmtBillion(o.circ_cap) },
    { label: '毛利率',  value: o.gross_margin != null ? o.gross_margin.toFixed(1) + '%' : '-' },
  ]
})


const lastRsi = computed(() => {
  const arr = (technical.value?.rsi || []).filter(v => v != null)
  return arr.length ? arr[arr.length - 1] : null
})

const macdState = computed(() => {
  const m = technical.value?.macd
  if (!m) return null
  const hist = (m.hist || []).filter(v => v != null)
  const dif  = (m.dif  || []).filter(v => v != null)
  const dea  = (m.dea  || []).filter(v => v != null)
  if (!hist.length) return null
  const lastHist = hist[hist.length - 1]
  const prevHist = hist.length > 1 ? hist[hist.length - 2] : 0
  const lastDif  = dif.length ? dif[dif.length - 1] : 0
  const lastDea  = dea.length ? dea[dea.length - 1] : 0
  // Detect cross
  const prevDif  = dif.length > 1 ? dif[dif.length - 2] : lastDif
  const prevDea  = dea.length > 1 ? dea[dea.length - 2] : lastDea
  const goldenCross = prevDif <= prevDea && lastDif > lastDea
  const deathCross  = prevDif >= prevDea && lastDif < lastDea
  return {
    hist: lastHist,
    growing: lastHist > prevHist,
    positive: lastHist > 0,
    goldenCross,
    deathCross,
    label: goldenCross ? '金叉' : deathCross ? '死叉' : lastHist > 0 ? '多头' : '空头',
  }
})

const sentimentCounts = computed(() => {
  const items = newsItems.value
  return {
    positive: items.filter(i => i.sentiment === 'positive').length,
    neutral:  items.filter(i => i.sentiment === 'neutral' || !i.sentiment).length,
    negative: items.filter(i => i.sentiment === 'negative').length,
  }
})

// ── Data loading ───────────────────────────────────────────────────────────────
async function loadAll(sym) {
  if (!sym) return
  loadingOverview.value = true
  overview.value = null; technical.value = null; fundamental.value = null
  newsItems.value = []; aiResult.value = null
  try {
    const res = await axios.get(`/api/stock-analysis/${sym}/overview`)
    overview.value = res.data
  } catch {}
  loadingOverview.value = false
  // Load all data in parallel, then auto-trigger AI
  await Promise.all([loadTechnical(sym), loadFundamental(sym), loadNews(sym)])
  runAI()
}

async function loadTechnical(sym) {
  loadingTech.value = true
  try { const r = await axios.get(`/api/stock-analysis/${sym}/technical`, { params: { days: 120 } }); technical.value = r.data } catch {}
  loadingTech.value = false
}

async function loadFundamental(sym) {
  loadingFund.value = true
  try { const r = await axios.get(`/api/stock-analysis/${sym}/fundamental`); fundamental.value = r.data } catch {}
  loadingFund.value = false
}

async function loadNews(sym) {
  loadingNews.value = true
  try { const r = await axios.get(`/api/news/stock/${sym}`, { params: { count: 30 } }); newsItems.value = (r.data.items || []).map(i => ({ ...i, _exp: false })) } catch {}
  loadingNews.value = false
}

async function runAI() {
  loadingAI.value = true; aiResult.value = null
  try { const r = await axios.post(`/api/stock-analysis/${props.symbol}/ai`); aiResult.value = r.data }
  catch (e) { aiResult.value = { analysis: 'AI分析失败: ' + (e.response?.data?.detail || e.message), generated_at: new Date().toISOString(), context: {} } }
  loadingAI.value = false
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmtPrice(v)   { return (v == null || v === 0) ? '-' : Number(v).toFixed(2) }
function fmtChg(v)     { return v == null ? '-' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }
function fmtAmount(v)  { if (!v) return '-'; return v >= 1e8 ? (v/1e8).toFixed(2)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : String(v) }
function fmtBillion(v) { return v ? (v/1e8).toFixed(1)+'亿' : '-' }
function chgClass(v)   { return v == null ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '' }
function roeClass(v)   { return v == null ? '' : v > 15 ? 'pos' : v > 0 ? '' : 'neg' }
const VERDICT_POS = new Set(['利好','看涨','低估','买入'])
const VERDICT_NEG = new Set(['利空','看跌','高估','减仓'])
function verdictClass(v) {
  if (VERDICT_POS.has(v)) return 'vd-pos'
  if (VERDICT_NEG.has(v)) return 'vd-neg'
  return 'vd-neu'
}

function renderMarkdown(text) {
  if (!text) return ''
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^#{1,3}\s+(.+)$/gm, '<h4>$1</h4>')
    .replace(/\n/g, '<br>')
}

watch(() => props.symbol, sym => { if (sym) loadAll(sym) }, { immediate: true })
</script>

<style scoped>
.sap-wrap { display: flex; flex-direction: column; gap: 12px; }

/* ── Overview ── */
.ov-card { display: flex; gap: 24px; padding: 16px 20px; flex-wrap: wrap; }
.ov-left { flex: 1; min-width: 260px; }
.ov-name { font-size: 17px; font-weight: 700; color: var(--text-1); }
.ov-code { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); margin-left: 8px; }
.ov-price-row { display: flex; align-items: baseline; gap: 10px; margin: 6px 0; }
.ov-price { font-size: 26px; font-weight: 700; color: var(--text-1); font-family: var(--font-mono); }
.ov-chg   { font-size: 15px; font-weight: 600; }
.ov-market { font-size: 12px; }
.ov-meta { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--text-2); margin-top: 6px; }
.ov-meta b { color: var(--text-1); }
.ov-right { display: flex; flex-wrap: wrap; gap: 10px; align-content: flex-start; }
.ov-metric { background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 7px 12px; text-align: center; min-width: 70px; }
.ov-metric-val { display: block; font-size: 15px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.ov-metric-lbl { font-size: 10px; color: var(--text-3); margin-top: 2px; }

/* ── Signal banner ── */
.signal-banner { display: flex; align-items: center; gap: 14px; padding: 10px 18px; border-radius: var(--radius-md); border: 1px solid var(--border); flex-wrap: wrap; }
.signal-banner.bullish { background: #16a34a18; border-color: #16a34a44; }
.signal-banner.bearish { background: #ef444418; border-color: #ef444444; }
.signal-banner.neutral { background: var(--bg-surface); }
.signal-label { font-size: 10px; color: var(--text-3); font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.signal-val { font-size: 14px; font-weight: 700; }
.signal-banner.bullish .signal-val { color: var(--success); }
.signal-banner.bearish .signal-val { color: var(--danger); }
.signal-meta { font-size: 12px; color: var(--text-2); flex: 1; }
.signal-chips { display: flex; gap: 6px; margin-left: auto; }
.ind-chip { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 10px; white-space: nowrap; }
.ind-chip.neutral-chip { background: var(--bg-elevated); color: var(--text-2); }
.ind-chip.overbought   { background: #ef444418; color: var(--danger); }
.ind-chip.oversold     { background: #16a34a18; color: var(--success); }
.ind-chip.golden  { background: #f59e0b22; color: #f59e0b; }
.ind-chip.death   { background: #6b728022; color: #9ca3af; }
.ind-chip.macd-pos { background: #16a34a18; color: var(--success); }
.ind-chip.macd-neg { background: #ef444418; color: var(--danger); }

/* ── Section blocks ── */
.section-block { padding: 16px 18px; }
.sec-title { font-size: 13px; font-weight: 700; color: var(--text-1); margin-bottom: 12px; }
.sec-title-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.sec-title-row .sec-title { margin-bottom: 0; }
.sec-loading { display: flex; align-items: center; gap: 8px; padding: 12px 0; color: var(--text-3); font-size: 13px; }
.loading-ai  { padding: 20px 0; }
.sec-empty   { font-size: 12px; color: var(--text-3); padding: 12px 0; }
.sub-title { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; margin: 14px 0 8px; }

/* ── Fundamentals ── */
.fund-metrics { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 4px; }
.fund-card { background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 10px 14px; min-width: 90px; text-align: center; }
.fund-val  { font-size: 18px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.fund-lbl  { font-size: 10px; color: var(--text-3); margin-top: 3px; }
.fund-hint { font-size: 10px; color: var(--text-2); margin-top: 2px; }

/* ── Tables ── */
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th { color: var(--text-3); font-weight: 600; text-align: left; padding: 5px 8px; border-bottom: 1px solid var(--border); font-size: 10px; text-transform: uppercase; letter-spacing: 0.03em; }
.data-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }
.td-ts { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); white-space: nowrap; }
.type-chip { font-size: 10px; color: var(--accent); background: var(--accent-dim); padding: 1px 5px; border-radius: 6px; }
.fw-600 { font-weight: 600; }
.mono   { font-family: var(--font-mono); }

/* ── Sentiment bar ── */
.sentiment-bar {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 12px; padding: 10px 14px;
  background: var(--bg-elevated); border-radius: var(--radius-sm);
}
.sb-item  { display: flex; flex-direction: column; align-items: center; gap: 2px; min-width: 36px; }
.sb-count { font-size: 18px; font-weight: 700; font-family: var(--font-mono); }
.sb-lbl   { font-size: 10px; color: var(--text-3); }
.sb-pos .sb-count { color: #ef4444; }
.sb-neu .sb-count { color: var(--text-3); }
.sb-neg .sb-count { color: #22c55e; }
.sb-track { flex: 1; height: 8px; border-radius: 4px; overflow: hidden; display: flex; gap: 2px; background: var(--bg-card); }
.sb-seg   { height: 100%; border-radius: 4px; transition: flex 0.3s; min-width: 4px; }
.seg-pos  { background: #ef4444; }
.seg-neu  { background: #6b7280; }
.seg-neg  { background: #22c55e; }
.sb-total { font-size: 11px; color: var(--text-3); white-space: nowrap; }

/* ── News AI ── */
.news-ai-box {
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  margin-bottom: 12px; overflow: hidden;
}
.news-ai-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
}
.news-ai-label { font-size: 11px; font-weight: 700; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.04em; }
.news-ai-loading { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-3); }
.news-ai-body {
  padding: 10px 14px; font-size: 12px; line-height: 1.8;
  color: var(--text-1); white-space: pre-wrap;
}
.news-ai-body :deep(strong) { font-weight: 700; color: var(--accent); }
.news-ai-body :deep(h4) { font-size: 12px; font-weight: 700; margin: 8px 0 3px; color: var(--text-1); }
.news-ai-placeholder { padding: 12px 14px; font-size: 12px; color: var(--text-3); font-style: italic; }

/* ── News list ── */
.news-item { padding: 9px 0; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.news-item:last-of-type { border-bottom: none; }
.news-item:hover { background: var(--bg-hover); margin: 0 -4px; padding-left: 4px; padding-right: 4px; border-radius: 4px; }
.ni-row   { display: flex; align-items: flex-start; gap: 8px; }
.ni-title { flex: 1; font-size: 12px; color: var(--text-1); line-height: 1.45; }
.ni-time  { font-size: 11px; color: var(--text-3); flex-shrink: 0; white-space: nowrap; }
.ni-link  { padding-left: 15px; margin-top: 4px; }
.sdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.sdot.positive { background: #ef4444; }
.sdot.negative { background: #22c55e; }
.sdot.neutral  { background: var(--text-3); }

/* ── AI section ── */
.verdict-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.verdict-chip {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 8px 16px; border-radius: var(--radius-md);
  border: 1px solid var(--border); min-width: 72px;
}
.vd-pos { background: #16a34a14; border-color: #16a34a44; }
.vd-neg { background: #ef444414; border-color: #ef444444; }
.vd-neu { background: var(--bg-elevated); }
.vd-dim { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
.vd-val { font-size: 14px; font-weight: 700; }
.vd-pos .vd-val { color: var(--success); }
.vd-neg .vd-val { color: var(--danger); }
.vd-neu .vd-val { color: var(--text-2); }

.ai-result-body { display: flex; flex-direction: column; gap: 10px; }
.ai-meta-row { display: flex; align-items: center; gap: 10px; }
.ai-body { font-size: 13px; line-height: 1.8; color: var(--text-1); white-space: pre-wrap; }
.ai-body :deep(strong) { font-weight: 700; color: var(--accent); }
.ai-body :deep(h4) { font-size: 13px; font-weight: 700; margin: 10px 0 4px; }

.loading-card { display: flex; align-items: center; gap: 10px; padding: 24px; }
.btn-sm { padding: 5px 14px; font-size: 12px; }
.btn-xs { padding: 3px 10px; font-size: 11px; }
.tiny   { font-size: 11px; }
.pos { color: var(--success); }
.neg { color: var(--danger); }
</style>
