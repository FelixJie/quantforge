<script setup>
import { ref, computed, onMounted } from 'vue'

const loading = ref(true)
const err = ref('')
const data = ref(null)

async function load() {
  loading.value = true; err.value = ''
  try {
    const token = localStorage.getItem('token')
    const res = await fetch('/api/review/summary', {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    data.value = await res.json()
  } catch (e) {
    err.value = String(e)
  } finally {
    loading.value = false
  }
}
onMounted(load)

function exportPdf() {
  const prev = document.title
  document.title = `每日复盘_${data.value?.date || new Date().toISOString().slice(0, 10)}`
  const restore = () => { document.title = prev; window.removeEventListener('afterprint', restore) }
  window.addEventListener('afterprint', restore)
  window.print()
}

const pct = (v) => (v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%')
const cls = (v) => (v == null ? '' : v >= 0 ? 'up' : 'down')
// 把 AI 长文本拆成列条：先按换行分段，长段再按句号/感叹号/问号拆句
function textToLines(text) {
  if (!text) return []
  const blocks = text.split(/\n+/).map(s => s.trim()).filter(Boolean)
  const out = []
  for (const block of blocks) {
    if (block.length <= 60) { out.push(block); continue }
    const sents = block.split(/(?<=。|！|？|；)\s*/).map(s => s.trim()).filter(Boolean)
    out.push(...(sents.length > 1 ? sents : [block]))
  }
  return out
}

function fmtFlow(v) {
  if (v == null) return '—'
  const a = Math.abs(v)
  const s = a >= 1 ? a.toFixed(1) + '亿' : (a * 1e4).toFixed(0) + '万'
  return (v >= 0 ? '+' : '-') + s
}
const mkBreadth = computed(() => data.value?.market?.breadth || null)
const idxChipCls = (s) => (String(s).includes('-') ? 'down' : 'up')

// 两融
const margin = computed(() => data.value?.margin || null)
const marginTotal = computed(() => (margin.value?.items || []).find(m => m.market === '两市合计') || null)
const marginMarkets = computed(() => (margin.value?.items || []).filter(m => m.market !== '两市合计'))
function fmtYi(v) {
  if (v == null) return '—'
  const yi = v / 1e8
  if (yi >= 10000) return (yi / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) + ' 万亿'
  return yi.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 亿'
}
const MC_W = 280, MC_H = 56, MC_PAD = 3
const marginChart = computed(() => {
  const s = (margin.value?.series || []).slice(-132)   // 近半年
  if (s.length < 2) return null
  const vals = s.map(d => d.total)
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = max - min || 1
  const n = s.length
  const x = i => MC_PAD + (i / (n - 1)) * (MC_W - 2 * MC_PAD)
  const y = v => MC_PAD + (1 - (v - min) / span) * (MC_H - 2 * MC_PAD)
  const pts = s.map((d, i) => `${x(i).toFixed(1)},${y(d.total).toFixed(1)}`).join(' ')
  const last = s[n - 1].total, first = s[0].total
  return {
    pts,
    area: `${MC_PAD},${MC_H - MC_PAD} ` + pts + ` ${(MC_W - MC_PAD).toFixed(1)},${MC_H - MC_PAD}`,
    up: last >= first,
    chgPct: first ? ((last - first) / first) * 100 : 0,
    spanLabel: `${s[0].date?.slice(5)} 至今`,
  }
})
</script>

<template>
  <div class="review pdf-page">
    <div class="page-head">
      <h1>每日复盘 <span v-if="data" class="date">{{ data.date }}</span>
        <span class="sub-tag">收盘视角</span>
      </h1>
      <div class="head-actions no-print">
        <button class="btn-ghost" @click="exportPdf" :disabled="loading || !data">导出 PDF</button>
        <button class="btn-ghost" @click="load" :disabled="loading">刷新</button>
      </div>
    </div>

    <p v-if="err" class="err">加载失败：{{ err }}</p>
    <p v-else-if="loading" class="muted">加载中…</p>

    <template v-else>
    <!-- 今日复盘总览（置顶 AI 综合，「总分」结构的「总」）-->
    <section class="card overview" v-if="data.overview?.ok">
      <div class="panel-header"><h2>🧭 今日总览</h2>
        <span v-if="data.overview.pending" class="muted">总览生成中，稍后刷新…</span>
      </div>
      <ul v-if="data.overview.text" class="ai-lines lead">
        <li v-for="(line, i) in textToLines(data.overview.text)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <!-- 大盘收盘速览（全宽）-->
    <section class="card market" v-if="data.market?.ok">
      <div class="panel-header"><h2>📉 大盘收盘速览</h2>
        <span class="muted" v-if="mkBreadth">
          涨 <b class="up">{{ mkBreadth.up_count ?? '—' }}</b> /
          跌 <b class="down">{{ mkBreadth.down_count ?? '—' }}</b>
          <template v-if="mkBreadth.limit_up != null"> · 涨停 {{ mkBreadth.limit_up }}</template>
          <template v-if="data.market.turnover?.total_amount != null"> · 成交 {{ data.market.turnover.total_amount }}亿</template>
          <template v-if="data.market.limit?.top_height"> · 最高 {{ data.market.limit.top_height }}板</template>
          <template v-if="data.market.limit?.seal_rate != null"> · 封板率 {{ data.market.limit.seal_rate }}%</template>
        </span>
      </div>
      <div class="idx-row" v-if="data.market.domestic?.length">
        <div class="idx" v-for="i in data.market.domestic" :key="i.code">
          <span class="idx-name">{{ i.name }}</span>
          <span class="idx-price mono" :class="cls(i.change_pct)">{{ i.price ?? '—' }}</span>
          <span class="idx-chg mono" :class="cls(i.change_pct)">{{ pct(i.change_pct) }}</span>
        </div>
      </div>
    </section>

    <!-- AI 每日复盘（全宽）-->
    <section class="card analysis" v-if="data.ai_review?.ok">
      <div class="panel-header"><h2>🔍 AI 每日复盘</h2>
        <span v-if="data.ai_review.pending" class="muted">复盘生成中，稍后刷新…</span>
      </div>
      <div v-if="data.ai_review.indices?.length" class="idx-chips">
        <span v-for="(s, i) in data.ai_review.indices" :key="i" class="ridx-chip" :class="idxChipCls(s)">{{ s }}</span>
      </div>
      <ul v-if="data.ai_review.text" class="ai-lines">
        <li v-for="(line, i) in textToLines(data.ai_review.text)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <!-- 复盘总结（公众号 + 机构选股，全宽）-->
    <section class="card review-sum" v-if="data.review?.ok">
      <div class="panel-header"><h2>📝 复盘总结</h2>
        <span v-if="data.review.pending" class="muted">汇总生成中，稍后刷新…</span>
        <span v-else-if="data.review.empty" class="muted">今日暂无分析/总结类内容</span>
        <span v-else-if="data.review.sources" class="muted">综合 {{ data.review.sources }} 篇 · {{ (data.review.from || []).join('、') }}</span>
      </div>
      <ul v-if="data.review.summary" class="ai-lines">
        <li v-for="(line, i) in textToLines(data.review.summary)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <!-- 行业资金流（全宽，两列）-->
    <section class="card flow" v-if="data.sector_flow?.ok && (data.sector_flow.inflow?.length || data.sector_flow.outflow?.length)">
      <div class="panel-header"><h2>💵 行业资金流</h2><span class="muted">今日 · 主力净额</span></div>
      <div class="flow-cols">
        <div class="flow-col">
          <div class="flow-h up">净流入 TOP</div>
          <div v-for="b in data.sector_flow.inflow" :key="b.name" class="flow-row">
            <span class="fn">{{ b.name }}</span>
            <span class="mono" :class="cls(b.change_pct)">{{ pct(b.change_pct) }}</span>
            <span class="mono up fa">{{ fmtFlow(b.net_flow) }}</span>
          </div>
        </div>
        <div class="flow-col">
          <div class="flow-h down">净流出 TOP</div>
          <div v-for="b in data.sector_flow.outflow" :key="b.name" class="flow-row">
            <span class="fn">{{ b.name }}</span>
            <span class="mono" :class="cls(b.change_pct)">{{ pct(b.change_pct) }}</span>
            <span class="mono down fa">{{ fmtFlow(b.net_flow) }}</span>
          </div>
        </div>
      </div>
    </section>

    <div class="grid">
      <!-- 连板梯队 -->
      <section class="card" v-if="data.limit?.ok">
        <div class="panel-header"><h2>🚀 连板梯队</h2>
          <span class="muted" v-if="data.limit.zt_count != null">涨停 {{ data.limit.zt_count }} · 封板 {{ data.limit.seal_rate ?? '—' }}%</span></div>
        <div v-if="data.limit.ladders?.length" class="ladders">
          <div v-for="l in data.limit.ladders" :key="l.lianban" class="ladder">
            <span class="lb">{{ l.lianban }}板<small>×{{ l.count }}</small></span>
            <span class="lb-names">{{ (l.stocks || []).map(s => s.name).join(' ') }}</span>
          </div>
        </div>
        <p v-else class="muted">当前无涨停（休市/盘前）。</p>
      </section>

      <!-- 北向 / 南向 -->
      <section class="card" v-if="data.hsgt?.ok">
        <div class="panel-header"><h2>🌏 北向 / 南向</h2></div>
        <div class="stats">
          <div class="stat"><span class="muted">南向净流入</span>
            <b class="mono" :class="cls(data.hsgt.south_net)">{{ data.hsgt.south_net != null ? (data.hsgt.south_net >= 0 ? '+' : '') + data.hsgt.south_net.toFixed(1) + '亿' : '—' }}</b></div>
        </div>
        <p class="muted note">北向资金已停披露，仅看南向。</p>
      </section>

      <!-- 两市两融 -->
      <section class="card">
        <div class="panel-header"><h2>💰 两市两融</h2>
          <span class="muted" v-if="marginTotal?.date">{{ marginTotal.date }}</span></div>
        <template v-if="marginTotal">
          <div class="margin-hero">
            <div class="mh-label">两市融资融券余额</div>
            <div class="mh-value mono">{{ fmtYi(marginTotal.total) }}</div>
            <div class="mh-sub">融资 {{ fmtYi(marginTotal.rz) }} · 融券 {{ fmtYi(marginTotal.rq) }}</div>
          </div>
          <div v-if="marginChart" class="margin-trend">
            <svg class="mt-svg" :viewBox="`0 0 ${MC_W} ${MC_H}`" preserveAspectRatio="none">
              <polyline class="mt-area" :class="{ down: !marginChart.up }" :points="marginChart.area" />
              <polyline class="mt-line" :class="{ down: !marginChart.up }" :points="marginChart.pts" />
            </svg>
            <div class="mt-foot">
              <span>{{ marginChart.spanLabel }}</span>
              <span class="mt-chg" :class="marginChart.up ? 'up' : 'down'">
                {{ marginChart.chgPct >= 0 ? '+' : '' }}{{ marginChart.chgPct.toFixed(1) }}%
              </span>
            </div>
          </div>
          <div class="margin-mini">
            <div v-for="m in marginMarkets" :key="m.market" class="mm-row">
              <span class="muted">{{ m.market }}</span>
              <span class="mono">{{ fmtYi(m.total) }}</span>
            </div>
          </div>
        </template>
        <p v-else class="muted">暂无两融数据。</p>
      </section>

      <!-- 自选当日表现 -->
      <section class="card">
        <div class="panel-header"><h2>📊 自选当日</h2>
          <span class="muted">{{ data.watchlist?.count ?? 0 }} 只</span></div>
        <table v-if="data.watchlist?.movers?.length" class="data-table">
          <tbody>
            <tr v-for="m in data.watchlist.movers" :key="m.code">
              <td>{{ m.name || m.code }}</td>
              <td class="mono">{{ m.price ?? '—' }}</td>
              <td class="mono" :class="cls(m.change_pct)">{{ pct(m.change_pct) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">今日自选无显著异动（±3%）。</p>
      </section>

      <!-- 选股结算 -->
      <section class="card">
        <div class="panel-header"><h2>📈 选股结算</h2></div>
        <div v-if="data.verify?.ok" class="stats">
          <div class="stat"><span class="muted">累计胜率</span>
            <b class="mono">{{ data.verify.overall?.win_rate ?? '—' }}</b></div>
          <div class="stat"><span class="muted">样本数</span>
            <b class="mono">{{ data.verify.overall?.total ?? '—' }}</b></div>
        </div>
        <p v-else class="muted">暂无结算数据。</p>
      </section>
    </div>
    </template>
  </div>
</template>

<style scoped>
.review { padding: 16px 20px; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-head h1 { font-size: 18px; display: flex; align-items: center; gap: 8px; }
.head-actions { display: flex; gap: 8px; }
.btn-ghost:disabled { opacity: .5; cursor: default; }
.date { color: var(--text-3); font-size: 14px; }
.sub-tag { font-size: 11px; font-weight: 600; color: #7c3aed; background: rgba(124,58,237,0.12); padding: 2px 8px; border-radius: 9px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.market, .analysis, .review-sum, .overview, .flow { margin-bottom: 16px; }
/* 今日总览：置顶强调卡 */
.overview { border-left: 3px solid var(--accent, #2563eb); }
.overview .lead { font-size: 14.5px; line-height: 1.75; }

/* 行业资金流 */
.flow-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.flow-h { font-size: 12px; font-weight: 600; padding-bottom: 6px; margin-bottom: 2px; border-bottom: 1px solid var(--border); }
.flow-h.up { color: #dc2626; } .flow-h.down { color: #16a34a; }
.flow-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 13px; border-bottom: 1px solid var(--border); }
.flow-row:last-child { border-bottom: none; }
.flow-row .fn { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flow-row .fa { width: 64px; text-align: right; font-weight: 600; }

/* 连板梯队 */
.ladders { display: flex; flex-direction: column; gap: 6px; }
.ladder { display: flex; gap: 8px; font-size: 12.5px; }
.ladder .lb { flex-shrink: 0; font-weight: 700; color: #dc2626; width: 52px; }
.ladder .lb small { color: var(--text-3); font-weight: 400; margin-left: 2px; }
.ladder .lb-names { color: var(--text-2, var(--text-3)); line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.note { margin-top: 8px; font-size: 12px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.panel-header h2 { font-size: 14px; }

/* 大盘速览 */
.idx-row { display: flex; flex-wrap: wrap; gap: 18px 28px; align-items: center; }
.idx { display: flex; flex-direction: column; gap: 2px; min-width: 92px; }
.idx-name { font-size: 12px; color: var(--text-3); }
.idx-price { font-size: 16px; font-weight: 600; }
.idx-chg { font-size: 13px; }

/* AI 复盘 / 复盘总结 */
.ai-view { font-size: 14px; line-height: 1.7; margin: 6px 0 0; white-space: pre-line; }
.ai-lines { list-style: none; padding: 0; margin: 6px 0 0; display: flex; flex-direction: column; gap: 6px; }
.ai-lines li { font-size: 14px; line-height: 1.65; padding-left: 14px; position: relative; }
.ai-lines li::before { content: '›'; position: absolute; left: 0; color: var(--accent); font-weight: 700; }
.ai-lines.lead li { font-size: 14.5px; }
.idx-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.ridx-chip { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: var(--bg-hover, rgba(127,127,127,.12)); }
.ridx-chip.up { color: #dc2626; } .ridx-chip.down { color: #16a34a; }

/* 两融 */
.margin-hero { padding: 4px 0 10px; }
.mh-label { font-size: 11px; color: var(--text-3); }
.mh-value { font-size: 24px; font-weight: 700; color: var(--accent); margin: 4px 0 3px; letter-spacing: -0.5px; }
.mh-sub { font-size: 11px; color: var(--text-3); }
.margin-trend { padding: 0 0 10px; border-bottom: 1px solid var(--border); margin-bottom: 8px; }
.mt-svg { width: 100%; height: 56px; display: block; }
.mt-line { fill: none; stroke: #dc2626; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.mt-line.down { stroke: #16a34a; }
.mt-area { fill: #dc2626; opacity: 0.10; stroke: none; }
.mt-area.down { fill: #16a34a; }
.mt-foot { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-3); margin-top: 2px; }
.mt-chg { font-weight: 600; }
.margin-mini { display: flex; flex-direction: column; }
.mm-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; font-size: 13px; border-bottom: 1px solid var(--border); }
.mm-row:last-child { border-bottom: none; }

.data-table { width: 100%; border-collapse: collapse; }
.data-table td { padding: 6px 4px; border-bottom: 1px solid var(--border); font-size: 13px; }
.mono { font-family: var(--font-mono, Consolas), monospace; }
.up { color: #dc2626; } .down { color: #16a34a; }
.stats { display: flex; gap: 24px; }
.stat { display: flex; flex-direction: column; gap: 4px; }
.stat b { font-size: 21px; }
.muted { color: var(--text-3); font-size: 13px; }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-2); padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-ghost:hover { background: var(--bg-hover); }
.err { color: #dc2626; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) {
  .review { padding: 12px; }
  .flow-cols { grid-template-columns: 1fr; gap: 10px; }
}
</style>
