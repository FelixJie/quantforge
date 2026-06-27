<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

// 模式：morning(开盘前·晨报) / review(收盘后·复盘)。默认按当前时刻：15:00 前看晨报，之后看复盘；
// 路由 /morning、/review 显式指定时优先。
function defaultMode() {
  if (route.path.includes('review')) return 'review'
  if (route.path.includes('morning')) return 'morning'
  return new Date().getHours() < 15 ? 'morning' : 'review'
}
const mode = ref(defaultMode())
const selectedDate = ref('')        // '' = 今日（实时）
const dates = ref([])               // 有存档的历史日期
const zoomImg = ref('')             // 点开放大的图片（隔夜美股小结原图）

const loading = ref(true)
const err = ref('')
const data = ref(null)

async function loadHistory() {
  try {
    const res = await fetch(`/api/${mode.value}/history`)
    if (res.ok) dates.value = (await res.json()).dates || []
  } catch { dates.value = [] }
}

async function load() {
  loading.value = true; err.value = ''
  try {
    const token = localStorage.getItem('token')
    const q = selectedDate.value ? `?date=${selectedDate.value}` : ''
    const res = await fetch(`/api/${mode.value}/summary${q}`, {
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

onMounted(() => { loadHistory(); load() })

const isArchived = computed(() => !!data.value?.archived || !!selectedDate.value)
const isEmpty = computed(() => !!data.value?.empty)

// ── 共用格式化 ──────────────────────────────────────────────
const pct = (v) => (v == null ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%')
const cls = (v) => (v == null ? '' : v >= 0 ? 'up' : 'down')
// 风险等级 → ASCII class（避免中文类名）
const riskLvCls = (lv) => ({ '高': 'lv-high', '中': 'lv-mid', '低': 'lv-low' }[lv] || 'lv-low')
// 新增线索类型 → 徽标配色
const clueCls = (type) => ({
  '订单中标': 'order', '涨价缺口': 'price', '新产品': 'product', '政策事件': 'policy',
}[type] || 'other')
function fmtYi(v) {
  if (v == null) return '—'
  const yi = v / 1e8
  if (yi >= 10000) return (yi / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) + ' 万亿'
  return yi.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 亿'
}
const mkBreadth = computed(() => data.value?.market?.breadth || null)
const trendCls = (label) => ({
  '多头排列': 'strong-up', '偏多': 'mild-up',
  '空头排列': 'strong-down', '偏弱': 'mild-down',
}[label] || 'neutral')

// 复盘三段正文（AI：盘面回顾 / 调研纪要 / 操作建议·看好板块）
const brief = computed(() => data.value?.brief || {})

// 把一段 AI 文本按行拆成要点（剥掉行首的 ·/-/•/数字编号），用于「列干条」渲染
function bulletize(text) {
  if (!text) return []
  return String(text)
    .split(/\n+/)
    .map(s => s
      .replace(/^[\s]*[·•\-*▪◦●○∙‣]+\s*/, '')
      .replace(/^[\s]*\d+[、.\)）]\s*/, '')
      .trim())
    .filter(Boolean)
}
function fmtMoney(v) {
  if (v == null) return '—'
  const a = Math.abs(v)
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (a >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toFixed(0)
}

// 两融
const margin = computed(() => data.value?.margin || null)
const marginTotal = computed(() => (margin.value?.items || []).find(m => m.market === '两市合计') || null)
const marginMarkets = computed(() => (margin.value?.items || []).filter(m => m.market !== '两市合计'))
const MC_W = 280, MC_H = 56, MC_PAD = 3
const marginChart = computed(() => {
  const s = (margin.value?.series || []).slice(-132)
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
  <div class="report">
    <div class="page-head">
      <div class="head-left">
        <h1>{{ mode === 'morning' ? '🌅 每日晨报' : '📕 每日复盘' }}</h1>
        <span class="upd-note muted">{{ mode === 'morning' ? '每日早上 8:00 更新' : '每日晚上 22:00 更新' }}</span>
      </div>
      <div class="head-right">
        <select class="date-sel" v-model="selectedDate" @change="load">
          <option value="">今日（实时）</option>
          <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
        </select>
        <button class="btn-ghost" @click="load" :disabled="loading">刷新</button>
      </div>
    </div>

    <div class="report-meta" v-if="data && !loading && !err">
      <span class="date">{{ data.date }}</span>
      <span class="badge" :class="mode">{{ mode === 'morning' ? '开盘前视角' : '收盘后视角' }}</span>
      <span v-if="isArchived" class="badge arch">历史存档</span>
      <span v-if="data.generated_at" class="muted gen">生成于 {{ data.generated_at.slice(0,16).replace('T',' ') }}</span>
    </div>

    <p v-if="err" class="err">加载失败：{{ err }}</p>
    <p v-else-if="loading" class="muted">加载中…</p>
    <p v-else-if="isEmpty" class="muted empty-note">该日期无{{ mode === 'morning' ? '晨报' : '复盘' }}存档。</p>

    <template v-else-if="data">
    <!-- 大盘收盘速览（复盘，全宽）-->
    <section class="card market" v-if="mode === 'review' && data.market?.ok">
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

    <!-- ───────── 晨报专属板块 ───────── -->
    <template v-if="mode === 'morning'">
      <!-- 隔夜美股（180K「隔夜北美小结」AI 读图分析 + 缩略原图）-->
      <section class="card overnight" v-if="data.overnight_us">
        <div class="panel-header"><h2>🌎 隔夜美股</h2>
          <span class="muted" v-if="data.overnight_us.created_at">{{ data.overnight_us.created_at.slice(5,16).replace('T',' ') }} · 180K</span>
        </div>
        <template v-if="data.overnight_us.ok && !data.overnight_us.empty">
          <p class="overnight-title">{{ data.overnight_us.title }}</p>
          <ul v-if="data.overnight_us.analysis" class="ai-view bullets">
            <li v-for="(b, i) in bulletize(data.overnight_us.analysis)" :key="i">{{ b }}</li>
          </ul>
          <p v-else-if="data.overnight_us.analysis_pending" class="muted">AI 读图分析生成中，稍后刷新…</p>
          <div class="overnight-imgs" v-if="data.overnight_us.images?.length">
            <span class="muted img-hint">原图（点击放大）</span>
            <div class="thumbs">
              <img v-for="(u, i) in data.overnight_us.images" :key="i" :src="u" class="thumb" loading="lazy" referrerpolicy="no-referrer" @click="zoomImg = u" />
            </div>
          </div>
        </template>
        <p v-else class="muted">暂无隔夜北美小结（180K）。</p>
      </section>

      <!-- 一·消息面 -->
      <section class="card brief">
        <div class="brief-head"><span class="brief-no">一</span><h3>消息面</h3>
          <span v-if="data.brief?.pending" class="muted">生成中，稍后刷新…</span></div>
        <ul v-if="data.brief?.news" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(data.brief.news)" :key="i">{{ b }}</li>
        </ul>
        <p v-else-if="!data.brief?.pending" class="muted">暂无消息面汇总。</p>
      </section>

      <!-- 二·调研纪要 -->
      <section class="card brief">
        <div class="brief-head"><span class="brief-no">二</span><h3>调研纪要</h3>
          <span class="muted" v-if="data.brief?.research_count">综合 {{ data.brief.research_count }} 篇</span></div>
        <ul v-if="data.brief?.research" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(data.brief.research)" :key="i">{{ b }}</li>
        </ul>
        <span v-else-if="data.brief?.pending" class="muted">生成中，稍后刷新…</span>
        <p v-else class="muted">上个交易日收盘以来暂无调研纪要。</p>
      </section>

      <!-- 三·操作建议 -->
      <section class="card brief advice">
        <div class="brief-head"><span class="brief-no adv">三</span><h3>操作建议</h3></div>
        <ul v-if="data.brief?.advice" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(data.brief.advice)" :key="i">{{ b }}</li>
        </ul>
        <span v-else-if="data.brief?.pending" class="muted">生成中，稍后刷新…</span>
        <p v-else class="muted">暂无操作建议。</p>
      </section>

      <!-- 今日 AI 选股（动能买点）-->
      <section class="card picks-card">
        <div class="panel-header"><h2>🤖 今日 AI 选股</h2>
          <span class="muted">动能买点{{ data.picks?.generated_at ? ' · ' + data.picks.generated_at.slice(0,16).replace('T',' ') : '' }}</span></div>
        <ol v-if="data.picks?.picks?.length" class="picks">
          <li v-for="(p, i) in data.picks.picks" :key="i">
            <b>{{ p.name || p.symbol }}</b>
            <span class="muted">{{ p.reason || p.one_liner || '' }}</span>
          </li>
        </ol>
        <p v-else class="muted">暂无今日选股。</p>
      </section>
    </template>

    <!-- ───────── 复盘专属板块 ───────── -->
    <template v-else>
      <!-- 一·盘面回顾 -->
      <section class="card brief">
        <div class="brief-head"><span class="brief-no">一</span><h3>盘面回顾</h3>
          <span v-if="brief.pending" class="muted">生成中，稍后刷新…</span></div>
        <ul v-if="brief.review" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(brief.review)" :key="i">{{ b }}</li>
        </ul>
        <p v-else-if="!brief.pending" class="muted">暂无盘面回顾。</p>
      </section>

      <!-- 二·调研纪要（今日收盘到晚 22 点）-->
      <section class="card brief">
        <div class="brief-head"><span class="brief-no">二</span><h3>调研纪要</h3>
          <span class="muted" v-if="brief.research_count">综合 {{ brief.research_count }} 篇</span></div>
        <ul v-if="brief.research" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(brief.research)" :key="i">{{ b }}</li>
        </ul>
        <span v-else-if="brief.pending" class="muted">生成中，稍后刷新…</span>
        <p v-else class="muted">今日收盘以来暂无调研纪要。</p>
      </section>

      <!-- 三·操作建议·看好板块 -->
      <section class="card brief advice">
        <div class="brief-head"><span class="brief-no adv">三</span><h3>操作建议 · 看好板块</h3></div>
        <ul v-if="brief.advice" class="ai-view bullets">
          <li v-for="(b, i) in bulletize(brief.advice)" :key="i">{{ b }}</li>
        </ul>
        <span v-else-if="brief.pending" class="muted">生成中，稍后刷新…</span>
        <p v-else class="muted">暂无操作建议。</p>
      </section>

      <!-- 新增线索（今日事件 / 订单中标 / 涨价缺口 / 新产品 → 受益票）-->
      <section class="card fw clues">
        <div class="fw-head"><span class="fw-no cl">📌</span><h3>新增线索</h3>
          <span class="muted" v-if="data.clues?.count">今日 {{ data.clues.count }} 条事件 → 受益票</span></div>
        <div v-if="data.clues?.clues?.length" class="clue-list">
          <div v-for="(c, i) in data.clues.clues" :key="i" class="clue-row">
            <span class="clue-type" :class="clueCls(c.type)">{{ c.type }}</span>
            <div class="clue-body">
              <div class="clue-event">{{ c.event }}</div>
              <div class="clue-logic muted" v-if="c.logic">{{ c.logic }}</div>
              <div class="clue-stocks">
                <template v-for="(s, j) in c.stocks" :key="j">
                  <a v-if="s.code" class="clue-chip link" :href="`/stock/${s.code}`" target="_blank" rel="noopener">{{ s.name }}</a>
                  <span v-else class="clue-chip dim">{{ s.name }}</span>
                </template>
                <span class="clue-source muted" v-if="c.source">· {{ c.source }}</span>
              </div>
            </div>
          </div>
        </div>
        <p v-else-if="data.clues?.pending" class="muted">线索抽取中，稍后刷新…</p>
        <p v-else class="muted">今日暂无可结构化的新增事件线索。</p>
      </section>

      <!-- 龙虎榜（明细 + 机构净买排行 + 活跃营业部/游资）-->
      <section class="card fw" v-if="data.lhb?.ok">
        <div class="fw-head"><span class="fw-no lhb-no">🏆</span><h3>龙虎榜</h3>
          <span class="muted">{{ data.lhb.date }} · 共 {{ data.lhb.total || data.lhb.items?.length || 0 }} 只 · {{ data.lhb.inst_count }} 只现机构席位</span></div>
        <div v-if="data.lhb.items?.length" class="lhb-scroll">
          <table class="data-table lhb-table">
            <thead><tr><th>名称</th><th class="num">涨幅</th><th class="num">净买入</th><th>上榜原因</th></tr></thead>
            <tbody>
              <tr v-for="it in data.lhb.items" :key="it.code">
                <td>{{ it.name }}<span v-if="it.is_inst" class="inst-badge">机构</span></td>
                <td class="mono num" :class="cls(it.change_pct)">{{ pct(it.change_pct) }}</td>
                <td class="mono num" :class="cls(it.net)">{{ it.net != null ? (it.net >= 0 ? '+' : '') + it.net + '亿' : '—' }}</td>
                <td class="lhb-reason muted">{{ it.reason }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="muted">暂无龙虎榜数据。</p>

        <!-- 知名游资今日动向 -->
        <div v-if="data.lhb.hotmoney?.length" class="lhb-sub">
          <div class="lhb-sub-h">🔥 知名游资今日动向<span class="muted" v-if="data.lhb.depts_date"> · {{ data.lhb.depts_date }}</span></div>
          <div class="dept-list">
            <div v-for="(d, i) in data.lhb.hotmoney" :key="'hm' + i" class="dept-row hm-row">
              <span class="hot-badge">{{ d.hotmoney }}</span>
              <span class="mono" :class="cls(d.net)">{{ d.net != null ? (d.net >= 0 ? '+' : '') + d.net + '亿' : '—' }}</span>
              <span class="muted dept-stocks">{{ (d.stocks || []).join(' ') }}</span>
            </div>
          </div>
        </div>

        <!-- 机构净买排行 -->
        <div v-if="data.lhb.inst_rank?.length" class="lhb-sub">
          <div class="lhb-sub-h">🏛 机构净买排行</div>
          <div class="rank-list">
            <span v-for="(it, i) in data.lhb.inst_rank" :key="it.code" class="rank-chip">
              <b>{{ i + 1 }}.</b> {{ it.name }}
              <span class="mono up">+{{ it.net }}亿</span>
            </span>
          </div>
        </div>

        <!-- 今日活跃营业部（知名游资标注）-->
        <div v-if="data.lhb.active_depts?.length" class="lhb-sub">
          <div class="lhb-sub-h">💹 今日活跃营业部<span class="muted" v-if="data.lhb.depts_date"> · {{ data.lhb.depts_date }}</span></div>
          <div class="dept-list">
            <div v-for="(d, i) in data.lhb.active_depts" :key="i" class="dept-row">
              <span v-if="d.hotmoney" class="hot-badge">{{ d.hotmoney }}</span>
              <span class="dept-name">{{ d.name }}</span>
              <span class="mono" :class="cls(d.net)">{{ d.net != null ? (d.net >= 0 ? '+' : '') + d.net + '亿' : '—' }}</span>
              <span class="muted dept-stocks">{{ (d.stocks || []).join(' ') }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 龙头股票 -->
      <section class="card fw" v-if="data.dragons?.ok">
        <div class="fw-head"><span class="fw-no dr">🐉</span><h3>龙头股票</h3></div>
        <div v-if="data.dragons.leaders?.length" class="dragon-list">
          <div v-for="d in data.dragons.leaders" :key="d.code" class="dragon-row">
            <span class="dragon-tag">{{ d.tag }}</span>
            <b>{{ d.name }}</b><span class="mono muted">{{ d.code }}</span>
            <span class="muted dragon-reason">{{ d.reason }}</span>
          </div>
        </div>
        <p v-else class="muted">暂无龙头数据。</p>
      </section>

      <!-- 自选股梳理 -->
      <section class="card fw">
        <div class="fw-head"><span class="fw-no wl">⭐</span><h3>自选股梳理</h3>
          <span class="muted" v-if="data.watchlist_review?.totals">
            市值 {{ fmtMoney(data.watchlist_review.totals.market_value) }} ·
            <b :class="cls(data.watchlist_review.totals.pnl)">{{ data.watchlist_review.totals.pnl >= 0 ? '+' : '' }}{{ fmtMoney(data.watchlist_review.totals.pnl) }}（{{ pct(data.watchlist_review.totals.pnl_pct) }}）</b>
          </span>
          <span class="muted" v-else-if="data.watchlist_review?.count">{{ data.watchlist_review.count }} 只</span></div>
        <table v-if="data.watchlist_review?.items?.length" class="data-table hold-table">
          <thead><tr><th>名称</th><th class="num">现价</th><th class="num">今日</th><th class="num">成本</th><th class="num">盈亏</th></tr></thead>
          <tbody>
            <tr v-for="h in data.watchlist_review.items" :key="h.code">
              <td>{{ h.name }}</td>
              <td class="mono num">{{ h.price ?? '—' }}</td>
              <td class="mono num" :class="cls(h.change_pct)">{{ pct(h.change_pct) }}</td>
              <td class="mono num">{{ h.cost_price ?? '—' }}</td>
              <td class="mono num" :class="cls(h.pnl_pct)">{{ h.pnl_pct != null ? pct(h.pnl_pct) : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="data.watchlist_review?.note === '未登录'" class="muted">登录后这里梳理你的自选股当日表现与盈亏。</p>
        <p v-else class="muted">自选为空，去自选股页添加后这里自动梳理。</p>
      </section>

      <!-- 自选股风险提示（技术面 + 消息面）-->
      <section class="card fw">
        <div class="fw-head"><span class="fw-no risk">⚠️</span><h3>自选股风险提示</h3>
          <span class="muted" v-if="data.watchlist_risk?.count">{{ data.watchlist_risk.count }} 只有风险信号 / 共查 {{ data.watchlist_risk.checked }} 只</span></div>
        <div v-if="data.watchlist_risk?.items?.length" class="risk-list">
          <div v-for="r in data.watchlist_risk.items" :key="r.code" class="risk-row">
            <div class="risk-head">
              <span class="risk-level" :class="riskLvCls(r.level)">{{ r.level }}</span>
              <b>{{ r.name }}</b><span class="mono muted">{{ r.code }}</span>
              <span class="mono muted" v-if="r.price != null">{{ r.price }}</span>
              <span class="mono" :class="cls(r.change_pct)" v-if="r.change_pct != null">{{ pct(r.change_pct) }}</span>
            </div>
            <div class="risk-tags" v-if="r.tech?.length">
              <span class="risk-dim">技术面</span>
              <span v-for="(t, i) in r.tech" :key="'t' + i" class="risk-tag tech">{{ t }}</span>
            </div>
            <div class="risk-tags" v-if="r.news?.length">
              <span class="risk-dim">消息面</span>
              <span v-for="(n, i) in r.news" :key="'n' + i" class="risk-tag news" :title="n.title">
                {{ n.title }}<small v-if="n.date" class="muted"> · {{ n.date.slice(5) }}</small>
              </span>
            </div>
          </div>
        </div>
        <p v-else-if="data.watchlist_risk?.note === '未登录'" class="muted">登录后这里从技术面、消息面体检你的自选股风险。</p>
        <p v-else class="muted">自选股暂无明显技术面 / 消息面风险信号。</p>
      </section>
    </template>

    <div class="grid review" v-if="mode === 'review'">
      <!-- 连板梯队（复盘）-->
      <section class="card" v-if="mode === 'review' && data.limit?.ok">
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

      <!-- 北向 / 南向（复盘）-->
      <section class="card" v-if="mode === 'review' && data.hsgt?.ok">
        <div class="panel-header"><h2>🌏 北向 / 南向</h2></div>
        <div class="stats">
          <div class="stat"><span class="muted">南向净流入</span>
            <b class="mono" :class="cls(data.hsgt.south_net)">{{ data.hsgt.south_net != null ? (data.hsgt.south_net >= 0 ? '+' : '') + data.hsgt.south_net.toFixed(1) + '亿' : '—' }}</b></div>
        </div>
        <p class="muted note">北向资金已停披露，仅看南向。</p>
      </section>

      <!-- 两市两融（复盘）-->
      <section class="card" v-if="mode === 'review'">
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

      <!-- 选股结算（复盘）-->
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

    <!-- 图片放大遮罩（隔夜美股原图）-->
    <div v-if="zoomImg" class="lightbox" @click="zoomImg = ''">
      <img :src="zoomImg" referrerpolicy="no-referrer" @click.stop />
      <button class="lb-close" @click="zoomImg = ''">✕</button>
    </div>
  </div>
</template>

<style scoped>
.report { padding: 16px 20px; }
.page-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.head-left { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.head-right { display: flex; align-items: center; gap: 10px; }
.page-head h1 { font-size: 18px; }

/* 晨报 / 复盘 分段切换 */
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { background: transparent; border: none; color: var(--text-2, var(--text-3)); padding: 6px 14px; font-size: 13px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button.on { background: var(--accent, #2563eb); color: #fff; font-weight: 600; }

.date-sel { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-1, var(--text-2)); border-radius: 6px; padding: 5px 8px; font-size: 13px; }
.btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-2); padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-ghost:hover { background: var(--bg-hover); }

.report-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.report-meta .date { font-size: 14px; font-weight: 600; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 9px; }
.badge.morning { color: #d97706; background: rgba(217,119,6,.12); }
.badge.review { color: #7c3aed; background: rgba(124,58,237,.12); }
.badge.arch { color: var(--text-3); background: var(--bg-hover, rgba(127,127,127,.14)); }
.gen { font-size: 12px; }
.empty-note { padding: 30px 0; text-align: center; }

.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.grid.review { grid-template-columns: repeat(3, 1fr); }
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.market, .sentiment, .analysis, .review-sum, .overview, .flow { margin-bottom: 16px; }
.review-sum .ai-view { margin-top: 6px; }
.overview { border-left: 3px solid var(--accent, #2563eb); }
.overview .lead { font-size: 14.5px; line-height: 1.75; }
.upd-note { font-size: 12px; }

/* 隔夜美股（180K 隔夜北美小结，AI 读图分析 + 缩略原图）*/
.overnight { margin-bottom: 16px; }
.overnight-title { font-size: 14px; font-weight: 600; color: var(--text-2, var(--text-3)); margin: 2px 0 8px; line-height: 1.5; }
.overnight .ai-view { margin: 4px 0 12px; }
.overnight-imgs { padding-top: 6px; border-top: 1px dashed var(--border); }
.img-hint { font-size: 12px; display: block; margin-bottom: 6px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 8px; }
.thumb { width: 110px; height: 74px; object-fit: cover; object-position: top; border: 1px solid var(--border); border-radius: 6px; cursor: zoom-in; display: block; transition: transform .12s; }
.thumb:hover { transform: scale(1.04); border-color: var(--accent, #2563eb); }

/* 图片放大遮罩 */
.lightbox { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,.82); display: flex; align-items: center; justify-content: center; cursor: zoom-out; padding: 24px; }
.lightbox img { max-width: 96vw; max-height: 94vh; object-fit: contain; cursor: default; border-radius: 4px; box-shadow: 0 8px 40px rgba(0,0,0,.5); }
.lb-close { position: fixed; top: 16px; right: 20px; width: 38px; height: 38px; border-radius: 50%; border: none; background: rgba(255,255,255,.16); color: #fff; font-size: 17px; cursor: pointer; }
.lb-close:hover { background: rgba(255,255,255,.3); }

/* 晨报三部分（消息面 / 调研纪要 / 操作建议）*/
.card.brief { margin-bottom: 14px; }
.brief-head { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; }
.brief-head h3 { font-size: 15px; margin: 0; }
.brief-head .muted { margin-left: auto; font-size: 12px; }
.brief-no { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--accent, #2563eb); color: #fff; font-size: 13px; font-weight: 700; flex-shrink: 0; }
.brief-no.adv { background: #dc2626; }
.brief.advice { border-left: 3px solid #dc2626; }
.brief .ai-view { line-height: 1.75; margin: 4px 0 0; }
.picks-card { margin-bottom: 16px; }

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
.idx-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 4px; }
.ridx-chip { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 6px; background: var(--bg-hover, rgba(127,127,127,.12)); }
.ridx-chip.up { color: #dc2626; } .ridx-chip.down { color: #16a34a; }

/* 行业资金流 */
.flow-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.flow-h { font-size: 12px; font-weight: 600; padding-bottom: 6px; margin-bottom: 2px; border-bottom: 1px solid var(--border); }
.flow-h.up { color: #dc2626; } .flow-h.down { color: #16a34a; }
.flow-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 13px; border-bottom: 1px solid var(--border); }
.flow-row:last-child { border-bottom: none; }
.flow-row .fn { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.flow-row .fa { width: 64px; text-align: right; font-weight: 600; }

/* ═══ 每日复盘框架（9 段）═══ */
.fw-title { font-size: 16px; margin: 22px 0 12px; padding-bottom: 8px; border-bottom: 2px solid var(--accent, #2563eb); }
.card.fw { margin-bottom: 14px; }
.fw-head { display: flex; align-items: center; gap: 9px; margin-bottom: 10px; }
.fw-head h3 { font-size: 15px; margin: 0; }
.fw-head .muted { margin-left: auto; font-size: 12px; }
.fw-no { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; border-radius: 50%; background: var(--accent, #2563eb); color: #fff; font-size: 12px; font-weight: 700; flex-shrink: 0; }
.fw-no.zt { background: transparent; font-size: 16px; }
/* emoji 序号（非数字）的板块标头：透明底大字号 */
.fw-no.lhb-no, .fw-no.dr, .fw-no.wl, .fw-no.cl, .fw-no.risk { background: transparent; font-size: 16px; }
.fw .ai-view { line-height: 1.75; }

/* 新增线索：事件 → 受益票 结构化卡 */
.clues { border-left: 3px solid #0891b2; }
.clue-list { display: flex; flex-direction: column; gap: 11px; margin-top: 6px; }
.clue-row { display: flex; gap: 9px; padding-bottom: 10px; border-bottom: 1px dashed var(--border); }
.clue-row:last-child { border-bottom: none; padding-bottom: 0; }
.clue-type { flex-shrink: 0; align-self: flex-start; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.clue-type.order { color: #15803d; background: rgba(22,163,74,.13); }
.clue-type.price { color: #b91c1c; background: rgba(220,38,38,.12); }
.clue-type.product { color: #1d4ed8; background: rgba(37,99,235,.12); }
.clue-type.policy { color: #a16207; background: rgba(202,138,4,.14); }
.clue-type.other { color: var(--text-3); background: var(--bg-hover, rgba(127,127,127,.14)); }
.clue-body { flex: 1; min-width: 0; }
.clue-event { font-size: 14px; font-weight: 600; line-height: 1.5; }
.clue-logic { font-size: 12.5px; line-height: 1.55; margin-top: 3px; }
.clue-stocks { margin-top: 6px; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.clue-chip { font-size: 12.5px; font-weight: 600; padding: 2px 9px; border-radius: 12px; background: var(--bg-hover, rgba(127,127,127,.12)); }
.clue-chip.link { color: var(--accent, #2563eb); text-decoration: none; background: rgba(37,99,235,.1); }
.clue-chip.link:hover { background: rgba(37,99,235,.2); }
.clue-chip.dim { color: var(--text-3); }
.clue-source { font-size: 11.5px; margin-left: 2px; }

/* 龙虎榜 */
.lhb-scroll { max-height: 460px; overflow-y: auto; overflow-x: auto; -webkit-overflow-scrolling: touch; border: 1px solid var(--border); border-radius: 8px; }
.lhb-scroll .lhb-table { margin: 0; }
.lhb-scroll thead th { position: sticky; top: 0; z-index: 1; background: var(--bg-surface); }
.lhb-table .num { text-align: right; }
.lhb-reason { max-width: 200px; font-size: 12px; }
.hm-row .hot-badge { min-width: 132px; text-align: center; }
.inst-badge { font-size: 10px; font-weight: 600; color: #7c3aed; background: rgba(124,58,237,.12); padding: 1px 5px; border-radius: 4px; margin-left: 6px; }
/* 龙虎榜子块：机构净买排行 / 活跃营业部 */
.lhb-sub { margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border); }
.lhb-sub-h { font-size: 12.5px; font-weight: 600; margin-bottom: 7px; }
.rank-list { display: flex; flex-wrap: wrap; gap: 6px; }
.rank-chip { font-size: 12px; padding: 2px 9px; border-radius: 12px; background: var(--bg-hover, rgba(127,127,127,.1)); }
.rank-chip .up { margin-left: 4px; }
.dept-list { display: flex; flex-direction: column; gap: 6px; }
.dept-row { display: flex; align-items: baseline; gap: 8px; font-size: 12.5px; }
.dept-name { flex-shrink: 0; max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dept-stocks { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.hot-badge { flex-shrink: 0; font-size: 10px; font-weight: 700; color: #ea580c; background: rgba(234,88,12,.14); padding: 1px 6px; border-radius: 4px; }

/* 热点题材 */
.theme-list { display: flex; flex-direction: column; gap: 7px; }
.theme-row { display: flex; align-items: baseline; gap: 8px; font-size: 13px; }
.theme-row b { flex-shrink: 0; }
.theme-tag { flex-shrink: 0; font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 4px; }
.theme-tag.flow { color: #dc2626; background: rgba(220,38,38,.1); }
.theme-tag.limit { color: #ea580c; background: rgba(234,88,12,.1); }
.theme-tag.news { color: #2563eb; background: rgba(37,99,235,.1); }

/* 龙头股票 */
.dragon-list { display: flex; flex-direction: column; gap: 7px; }
.dragon-row { display: flex; align-items: baseline; gap: 8px; font-size: 13px; }
.dragon-tag { flex-shrink: 0; font-size: 11px; font-weight: 600; color: #dc2626; background: rgba(220,38,38,.1); padding: 1px 7px; border-radius: 4px; width: 58px; text-align: center; }
.dragon-reason { font-size: 12px; }

/* 自选股风险提示 */
.risk-list { display: flex; flex-direction: column; gap: 10px; }
.risk-row { padding: 8px 0; border-bottom: 1px dashed var(--border); }
.risk-row:last-child { border-bottom: none; }
.risk-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; font-size: 13px; }
.risk-level { flex-shrink: 0; font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 4px; }
.risk-level.lv-high { color: #fff; background: #dc2626; }
.risk-level.lv-mid { color: #fff; background: #f59e0b; }
.risk-level.lv-low { color: #fff; background: #9ca3af; }
.risk-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 6px; }
.risk-dim { flex-shrink: 0; font-size: 11px; color: var(--text-3); }
.risk-tag { font-size: 12px; padding: 2px 8px; border-radius: 4px; line-height: 1.5; }
.risk-tag.tech { color: #dc2626; background: rgba(220,38,38,.1); }
.risk-tag.news { color: var(--text-2, var(--text-3)); background: var(--bg-2, rgba(148,163,184,.12)); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 持仓 */
.hold-table .num { text-align: right; }

/* 连板梯队 */
.ladders { display: flex; flex-direction: column; gap: 6px; }
.ladder { display: flex; gap: 8px; font-size: 12.5px; }
.ladder .lb { flex-shrink: 0; font-weight: 700; color: #dc2626; width: 52px; }
.ladder .lb small { color: var(--text-3); font-weight: 400; margin-left: 2px; }
.ladder .lb-names { color: var(--text-2, var(--text-3)); line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.note { margin-top: 8px; font-size: 12px; }

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
.themes { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font-size: 12px; padding: 2px 9px; border-radius: 12px; background: var(--bg-hover, rgba(127,127,127,.1)); color: var(--text-2, var(--text-3)); }
.headlines { list-style: none; padding: 0; margin: 0; }
.headlines li { font-size: 13px; padding: 3px 0; color: var(--text-2, var(--text-3)); position: relative; padding-left: 12px; }
.headlines li::before { content: '·'; position: absolute; left: 2px; }

.ai-view { font-size: 14px; line-height: 1.65; margin: 4px 0 10px; white-space: pre-line; }
/* 要点「列干条」渲染 */
.ai-view.bullets { list-style: none; padding: 0; margin: 6px 0 4px; white-space: normal; }
.ai-view.bullets li { position: relative; padding-left: 16px; margin: 0 0 7px; line-height: 1.7; }
.ai-view.bullets li:last-child { margin-bottom: 0; }
.ai-view.bullets li::before { content: '·'; position: absolute; left: 3px; top: -1px; color: var(--accent, #2563eb); font-weight: 800; font-size: 17px; }
.brief.advice .ai-view.bullets li::before { color: #dc2626; }

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
@media (max-width: 900px) { .grid, .grid.review { grid-template-columns: 1fr; } }
</style>
