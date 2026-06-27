<script setup>
import { ref, computed, onMounted } from 'vue'

const loading = ref(true)
const err = ref('')
const data = ref(null)

async function load() {
  loading.value = true; err.value = ''
  try {
    const token = localStorage.getItem('token')
    const res = await fetch('/api/morning/summary', {
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
const mkBreadth = computed(() => data.value?.market?.breadth || null)
const trendCls = (label) => ({
  '多头排列': 'strong-up', '偏多': 'mild-up',
  '空头排列': 'strong-down', '偏弱': 'mild-down',
}[label] || 'neutral')
</script>

<template>
  <div class="morning">
    <div class="page-head">
      <h1>每日晨报 <span v-if="data" class="date">{{ data.date }}</span></h1>
      <button class="btn-ghost" @click="load" :disabled="loading">刷新</button>
    </div>

    <p v-if="err" class="err">加载失败：{{ err }}</p>
    <p v-else-if="loading" class="muted">加载中…</p>

    <template v-else>
    <!-- 今日总览（置顶 AI 综合，「总分」结构的「总」）-->
    <section class="card overview" v-if="data.overview?.ok">
      <div class="panel-header"><h2>🧭 今日总览</h2>
        <span v-if="data.overview.pending" class="muted">总览生成中，稍后刷新…</span>
      </div>
      <ul v-if="data.overview.text" class="ai-lines lead">
        <li v-for="(line, i) in textToLines(data.overview.text)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <!-- 大盘速览（全宽，开篇必看）-->
    <section class="card market" v-if="data.market?.ok">
      <div class="panel-header"><h2>🌅 大盘速览</h2>
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
      <div class="idx-row ext" v-if="data.market.overseas?.length">
        <span class="ext-label muted">隔夜外盘</span>
        <div class="idx" v-for="i in data.market.overseas" :key="i.code">
          <span class="idx-name">{{ i.name }}</span>
          <span class="idx-chg mono" :class="cls(i.change_pct)">{{ pct(i.change_pct) }}</span>
        </div>
      </div>
    </section>

    <!-- 市场情绪（全宽）-->
    <section class="card sentiment" v-if="data.sentiment?.ok">
      <div class="panel-header"><h2>🧭 市场情绪</h2>
        <span v-if="data.sentiment.label" class="senti-tag" :class="data.sentiment.level">
          {{ data.sentiment.label }} {{ data.sentiment.score != null ? data.sentiment.score : '' }}
        </span>
        <span v-else-if="data.sentiment.pending" class="muted">研判生成中，稍后刷新…</span>
      </div>
      <ul v-if="data.sentiment.ai_view" class="ai-lines">
        <li v-for="(line, i) in textToLines(data.sentiment.ai_view)" :key="i">{{ line }}</li>
      </ul>
      <div v-if="data.sentiment.hot_themes?.length" class="themes">
        <span class="chip" v-for="t in data.sentiment.hot_themes" :key="t">{{ t }}</span>
      </div>
      <ul v-if="data.sentiment.headlines?.length" class="headlines">
        <li v-for="(h, i) in data.sentiment.headlines" :key="i">{{ h }}</li>
      </ul>
    </section>

    <!-- 大盘走势 & 外盘研判（全宽）-->
    <section class="card analysis" v-if="data.analysis?.ok">
      <div class="panel-header"><h2>📈 大盘走势 &amp; 外盘研判</h2>
        <span v-if="data.analysis.pending" class="muted">研判生成中，稍后刷新…</span>
      </div>
      <table v-if="data.analysis.trend?.length" class="data-table trend-table">
        <thead>
          <tr><th>指数</th><th>形态</th><th class="num">现价</th><th class="num">近5日</th><th class="num">近20日</th><th class="num">20日线</th><th class="num">连阳/跌</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in data.analysis.trend" :key="t.name">
            <td>{{ t.name }}</td>
            <td><span class="trend-tag" :class="trendCls(t.label)">{{ t.label }}</span></td>
            <td class="mono num">{{ t.price ?? '—' }}</td>
            <td class="mono num" :class="cls(t.chg5)">{{ pct(t.chg5) }}</td>
            <td class="mono num" :class="cls(t.chg20)">{{ pct(t.chg20) }}</td>
            <td class="mono num" :class="t.above_ma20 ? 'up' : 'down'">{{ t.above_ma20 ? '站上' : '跌破' }}</td>
            <td class="mono num" :class="t.streak > 0 ? 'up' : t.streak < 0 ? 'down' : ''">
              {{ t.streak > 0 ? t.streak + '连阳' : t.streak < 0 ? (-t.streak) + '连跌' : '—' }}
            </td>
          </tr>
        </tbody>
      </table>
      <ul v-if="data.analysis.ai_view" class="ai-lines">
        <li v-for="(line, i) in textToLines(data.analysis.ai_view)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <!-- 每日复盘总结（公众号 + 机构选股，全宽）-->
    <section class="card review" v-if="data.review?.ok">
      <div class="panel-header"><h2>📝 每日复盘总结</h2>
        <span v-if="data.review.pending" class="muted">汇总生成中，稍后刷新…</span>
        <span v-else-if="data.review.empty" class="muted">今日暂无分析/总结类内容</span>
        <span v-else-if="data.review.sources" class="muted">综合 {{ data.review.sources }} 篇 · {{ (data.review.from || []).join('、') }}</span>
      </div>
      <ul v-if="data.review.summary" class="ai-lines">
        <li v-for="(line, i) in textToLines(data.review.summary)" :key="i">{{ line }}</li>
      </ul>
    </section>

    <div class="grid">
      <!-- 自选异动 -->
      <section class="card">
        <div class="panel-header"><h2>📊 自选异动</h2>
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

      <!-- 今日AI选股 -->
      <section class="card">
        <div class="panel-header"><h2>🤖 今日 AI 选股</h2>
          <span class="muted">{{ data.picks?.generated_at?.slice(0,16) || '' }}</span></div>
        <ol v-if="data.picks?.picks?.length" class="picks">
          <li v-for="(p, i) in data.picks.picks" :key="i">
            <b>{{ p.name || p.symbol }}</b>
            <span class="muted">{{ p.reason || p.one_liner || '' }}</span>
          </li>
        </ol>
        <p v-else class="muted">暂无今日选股。</p>
      </section>

      <!-- 昨日信号结算 -->
      <section class="card">
        <div class="panel-header"><h2>📈 信号结算</h2></div>
        <div v-if="data.verify?.ok" class="stats">
          <div class="stat"><span class="muted">累计胜率</span>
            <b class="mono">{{ data.verify.overall?.win_rate ?? '—' }}</b></div>
          <div class="stat"><span class="muted">样本数</span>
            <b class="mono">{{ data.verify.overall?.total ?? '—' }}</b></div>
        </div>
        <p v-else class="muted">暂无结算数据。</p>
      </section>

      <!-- 数据源健康 -->
      <section class="card">
        <div class="panel-header"><h2>🩺 数据源</h2></div>
        <ul class="health">
          <li v-for="s in data.data_health?.sources || []" :key="s.name">
            <span :class="['dot', s.ok === true ? 'g' : s.ok === false ? 'r' : 'y']"></span>
            {{ s.name }} {{ s.ok === true ? '正常' : s.ok === false ? '异常' : (s.note || '未知') }}
          </li>
        </ul>
      </section>
    </div>
    </template>
  </div>
</template>

<style scoped>
.morning { padding: 16px 20px; }
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.page-head h1 { font-size: 18px; }
.date { color: var(--text-3); font-size: 14px; margin-left: 8px; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.market, .sentiment, .analysis, .review, .overview { margin-bottom: 16px; }
.review .ai-view { margin-top: 6px; }
/* 今日总览：置顶强调卡 */
.overview { border-left: 3px solid var(--accent, #2563eb); background: var(--bg-surface); }
.overview .lead { font-size: 14.5px; line-height: 1.75; }

/* 走势 & 外盘研判 */
.trend-table th { font-size: 12px; color: var(--text-3); font-weight: 500; text-align: left; padding: 4px; border-bottom: 1px solid var(--border); }
.trend-table td.num, .trend-table th.num { text-align: right; }
.trend-tag { font-size: 12px; padding: 1px 8px; border-radius: 10px; font-weight: 600; }
.trend-tag.strong-up { color: #dc2626; background: rgba(220,38,38,.14); }
.trend-tag.mild-up { color: #dc2626; background: rgba(220,38,38,.07); }
.trend-tag.strong-down { color: #16a34a; background: rgba(22,163,74,.14); }
.trend-tag.mild-down { color: #16a34a; background: rgba(22,163,74,.07); }
.trend-tag.neutral { color: var(--text-3); background: var(--bg-hover, rgba(127,127,127,.12)); }
.analysis .ai-view { margin-top: 10px; }

/* 大盘速览 */
.idx-row { display: flex; flex-wrap: wrap; gap: 18px 28px; align-items: center; }
.idx-row.ext { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); }
.ext-label { font-size: 12px; margin-right: 4px; }
.idx { display: flex; flex-direction: column; gap: 2px; min-width: 92px; }
.idx-name { font-size: 12px; color: var(--text-3); }
.idx-price { font-size: 16px; font-weight: 600; }
.idx-chg { font-size: 13px; }
.idx-row.ext .idx { flex-direction: row; align-items: baseline; gap: 6px; min-width: 0; }
.idx-row.ext .idx-name { font-size: 13px; color: var(--text-2, var(--text-3)); }

/* 市场情绪 */
.senti-tag { font-size: 12px; padding: 2px 10px; border-radius: 12px; font-weight: 600; }
.senti-tag.bullish, .senti-tag.mild_bullish { color: #dc2626; background: rgba(220,38,38,.12); }
.senti-tag.bearish, .senti-tag.mild_bearish { color: #16a34a; background: rgba(22,163,74,.12); }
.senti-tag.neutral { color: var(--text-3); background: var(--bg-hover, rgba(127,127,127,.12)); }
.ai-view { font-size: 14px; line-height: 1.6; margin: 4px 0 10px; white-space: pre-line; }
.ai-lines { list-style: none; padding: 0; margin: 4px 0 10px; display: flex; flex-direction: column; gap: 6px; }
.ai-lines li { font-size: 14px; line-height: 1.6; padding-left: 14px; position: relative; }
.ai-lines li::before { content: '›'; position: absolute; left: 0; color: var(--accent); font-weight: 700; }
.ai-lines.lead li { font-size: 14.5px; }
.themes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font-size: 12px; padding: 2px 9px; border-radius: 12px; background: var(--bg-hover, rgba(127,127,127,.1)); color: var(--text-2, var(--text-3)); }
.headlines { list-style: none; padding: 0; margin: 0; }
.headlines li { font-size: 13px; padding: 3px 0; color: var(--text-2, var(--text-3)); position: relative; padding-left: 12px; }
.headlines li::before { content: '·'; position: absolute; left: 2px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.panel-header h2 { font-size: 14px; }
.data-table { width: 100%; border-collapse: collapse; }
.data-table td { padding: 6px 4px; border-bottom: 1px solid var(--border); font-size: 13px; }
.mono { font-family: var(--font-mono, Consolas), monospace; }
.up { color: #dc2626; } .down { color: #16a34a; }
.picks { margin: 0; padding-left: 18px; }
.picks li { padding: 4px 0; font-size: 13px; }
.picks .muted { margin-left: 6px; }
.stats { display: flex; gap: 24px; }
.stat { display: flex; flex-direction: column; gap: 4px; }
.stat b { font-size: 21px; }
.health { list-style: none; padding: 0; margin: 0; }
.health li { padding: 4px 0; font-size: 13px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.dot.g { background: #16a34a; } .dot.r { background: #dc2626; } .dot.y { background: #d97706; }
.muted { color: var(--text-3); font-size: 13px; }
.err { color: #dc2626; }
@media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
</style>
