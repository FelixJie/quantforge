<template>
  <div class="dashboard">
    <div class="tab-pane">
    <!-- ── 大盘指数 ─────────────────────────────────────────── -->
    <div v-if="indices.length" class="index-section">
      <div class="index-group">
        <span class="index-group-label">国内</span>
        <div class="index-strip">
          <div v-for="idx in domesticIndices" :key="idx.code" class="idx-card">
            <div class="idx-name">{{ idx.name }}</div>
            <div class="idx-price mono" :class="chgClass(idx.change_pct)">{{ idx.price != null ? idx.price.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-' }}</div>
            <div class="idx-chg" :class="chgClass(idx.change_pct)">
              <span>{{ idx.change != null ? (idx.change >= 0 ? '+' : '') + idx.change.toFixed(2) : '-' }}</span>
              <span>{{ fmtPct(idx.change_pct) }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="index-group" v-if="globalIndices.length">
        <span class="index-group-label">全球</span>
        <div class="index-strip">
          <div v-for="idx in globalIndices" :key="idx.code" class="idx-card">
            <div class="idx-name">{{ idx.name }}</div>
            <div class="idx-price mono" :class="chgClass(idx.change_pct)">{{ idx.price != null ? idx.price.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-' }}</div>
            <div class="idx-chg" :class="chgClass(idx.change_pct)">
              <span>{{ idx.change != null ? (idx.change >= 0 ? '+' : '') + idx.change.toFixed(2) : '-' }}</span>
              <span>{{ fmtPct(idx.change_pct) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stat cards row -->
    <div class="stats-row">
      <!-- AI 今日精选 -->
      <div class="metric-card">
        <div class="metric-label">AI 今日精选</div>
        <div class="metric-value" :style="picks.length ? { color: 'var(--accent)' } : {}">{{ picks.length || '-' }}</div>
        <div class="metric-sub">{{ picksData?.candidate_count ? `从 ${picksData.candidate_count} 只候选` : '今日推荐' }}</div>
      </div>

      <!-- 策略命中率 + 平均收益（合并一框，可选周期）-->
      <div class="metric-card combo">
        <div class="combo-head">
          <span class="metric-label">{{ periodLabel }}策略命中率</span>
          <div class="seg-toggle mini">
            <button v-for="p in periodOpts" :key="p.days"
                    :class="['seg-btn', { active: statPeriod === p.days }]"
                    @click="setStatPeriod(p.days)">{{ p.short }}</button>
          </div>
        </div>
        <div class="combo-body">
          <div class="combo-item">
            <div class="metric-value" :style="recentWR?.win_rate != null ? { color: accColor(recentWR.win_rate) } : {}">{{ recentWR?.win_rate != null ? recentWR.win_rate + '%' : '-' }}</div>
            <div class="metric-sub">命中率{{ recentWR?.evaluated ? ` · ${recentWR.evaluated} 只` : '' }}</div>
          </div>
          <div class="combo-item">
            <div class="metric-value" :style="recentWR?.avg_change != null ? { color: recentWR.avg_change >= 0 ? 'var(--profit)' : 'var(--loss)' } : {}">{{ recentWR?.avg_change != null ? fmtPct(recentWR.avg_change) : '-' }}</div>
            <div class="metric-sub">平均收益</div>
          </div>
        </div>
      </div>

      <!-- 自选股数 + 今日均涨（合并一框）-->
      <div class="metric-card combo">
        <div class="combo-head"><span class="metric-label">自选股</span></div>
        <div class="combo-body">
          <div class="combo-item">
            <div class="metric-value">{{ watchItems.length || '-' }}</div>
            <div class="metric-sub">{{ watchItems.length ? `上涨 ${wlUp} 只` : '未添加自选' }}</div>
          </div>
          <div class="combo-item">
            <div class="metric-value" :style="wlAvg != null ? { color: wlAvg >= 0 ? 'var(--profit)' : 'var(--loss)' } : {}">{{ wlAvg != null ? fmtPct(wlAvg) : '-' }}</div>
            <div class="metric-sub">今日均涨</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 自选走势 ─────────────────────────────────────────── -->
    <div class="panel wl-trend-panel">
      <div class="panel-header">
        <span class="panel-title">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
          自选走势
        </span>
        <div class="panel-actions">
          <div class="view-toggle">
            <button :class="['vt-btn', { active: wlView === 'card' }]" @click="setWlView('card')" title="卡片视图">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
            </button>
            <button :class="['vt-btn', { active: wlView === 'list' }]" @click="setWlView('list')" title="列表视图">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            </button>
          </div>
          <router-link to="/watchlist" class="panel-link" target="_blank" rel="noopener">自选股 →</router-link>
        </div>
      </div>
      <div v-if="wlChartList.length && wlView === 'card'" class="wl-trend-grid">
        <router-link v-for="w in wlChartList" :key="w.code" :to="'/stock/' + w.code" class="wlt-card" target="_blank" rel="noopener">
          <div class="wlt-head">
            <div class="wlt-id">
              <span class="wlt-name">{{ w.name }}</span>
              <span class="wlt-code mono">{{ w.code }}</span>
            </div>
            <span class="wlt-chg" :class="chgClass(w.change_pct)">{{ fmtPct(w.change_pct) }}</span>
          </div>
          <div class="wlt-spark">
            <StockMiniChart v-if="w.chart.length" :data="w.chart" :width="220" :height="44" :color="w.color" :pre-close="w.pre" />
            <span v-else class="wlt-empty">—</span>
          </div>
        </router-link>
      </div>
      <div v-else-if="wlChartList.length" class="wl-trend-list">
        <router-link v-for="w in wlChartList" :key="w.code" :to="'/stock/' + w.code" class="wltl-row" target="_blank" rel="noopener">
          <div class="wltl-id">
            <span class="wltl-name">{{ w.name }}</span>
            <span class="wltl-code mono">{{ w.code }}</span>
          </div>
          <div class="wltl-spark">
            <StockMiniChart v-if="w.chart.length" :data="w.chart" :width="120" :height="28" :color="w.color" :pre-close="w.pre" />
          </div>
          <span class="wltl-price mono">{{ w.price != null ? w.price.toFixed(2) : '-' }}</span>
          <span class="wltl-chg" :class="chgClass(w.change_pct)">{{ fmtPct(w.change_pct) }}</span>
        </router-link>
      </div>
      <div v-else class="empty-state small">
        <p>自选股为空</p>
        <p class="empty-hint">在自选股管理中添加关注标的</p>
      </div>
    </div>

    <!-- ── 榜单条数选择 ─────────────────────────────────────── -->
    <div class="rank-toolbar">
      <span class="rank-toolbar-label">榜单显示</span>
      <div class="seg-toggle">
        <button v-for="n in topOpts" :key="n" :class="['seg-btn', { active: rankTop === n }]" @click="setRankTop(n)">前 {{ n }}</button>
      </div>
    </div>

    <!-- ── 个股 涨幅 / 1分钟涨速 ─────────────────────────────── -->
    <div class="board-grid">
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">个股涨幅</span>
          <span class="panel-meta">实时</span>
        </div>
        <div v-if="loadingGainers" class="list-skeleton">
          <div class="skeleton-row" v-for="i in 6" :key="i"><span class="skeleton w-sm"></span><span class="skeleton"></span><span class="skeleton w-md"></span></div>
        </div>
        <div v-else-if="gainers.length" class="rank-list">
          <router-link v-for="(s, i) in gainers" :key="s.code" :to="'/stock/' + s.code" class="rank-row" target="_blank" rel="noopener">
            <span class="rank-no" :class="'top' + (i < 3 ? i + 1 : 0)">{{ i + 1 }}</span>
            <div class="rank-id"><span class="rank-name">{{ s.name }}</span><span class="rank-code mono">{{ s.code }}</span></div>
            <span class="rank-price mono">{{ s.price != null ? s.price.toFixed(2) : '-' }}</span>
            <span class="rank-val pos">{{ fmtPct(s.change_pct) }}</span>
          </router-link>
        </div>
        <div v-else class="empty-state small"><p>暂无数据</p></div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">个股 1 分钟涨速</span>
          <span class="panel-meta">{{ hasStockSpeed ? '实时涨速' : '暂按涨幅' }}</span>
        </div>
        <div v-if="loadingSpeedStocks" class="list-skeleton">
          <div class="skeleton-row" v-for="i in 6" :key="i"><span class="skeleton w-sm"></span><span class="skeleton"></span><span class="skeleton w-md"></span></div>
        </div>
        <div v-else-if="speedStocks.length" class="rank-list">
          <router-link v-for="(s, i) in speedStocks" :key="s.code" :to="'/stock/' + s.code" class="rank-row" target="_blank" rel="noopener">
            <span class="rank-no" :class="'top' + (i < 3 ? i + 1 : 0)">{{ i + 1 }}</span>
            <div class="rank-id"><span class="rank-name">{{ s.name }}</span><span class="rank-code mono">{{ s.code }}</span></div>
            <span class="rank-price" :class="chgClass(s.change_pct)">{{ fmtPct(s.change_pct) }}</span>
            <span class="rank-val" :class="chgClass(s.speed)">{{ s.speed != null ? fmtPct(s.speed) : '—' }}</span>
          </router-link>
        </div>
        <div v-else class="empty-state small"><p>暂无数据</p></div>
      </div>
    </div>

    <!-- ── 板块榜（概念/行业切换，涨幅/涨速并排两格）──────────── -->
    <div class="board-kind-bar">
      <span class="rank-toolbar-label">板块类型</span>
      <div class="seg-toggle">
        <button :class="['seg-btn', { active: boardKind === 'concept' }]" @click="switchBoardKind('concept')">概念</button>
        <button :class="['seg-btn', { active: boardKind === 'industry' }]" @click="switchBoardKind('industry')">行业</button>
      </div>
    </div>
    <div class="board-grid">
      <!-- 涨幅榜 -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">{{ boardKind === 'concept' ? '概念' : '行业' }}涨幅榜</span>
          <span class="panel-meta">实时</span>
        </div>
        <div v-if="loadingBoardGainers" class="list-skeleton">
          <div class="skeleton-row" v-for="i in 6" :key="i"><span class="skeleton w-sm"></span><span class="skeleton"></span><span class="skeleton w-md"></span></div>
        </div>
        <div v-else-if="boardGainers.length" class="rank-list">
          <router-link
            v-for="(s, i) in boardGainers" :key="s.code || s.name"
            :to="{ path: '/market-hub', query: { sector: boardKind } }"
            class="rank-row" target="_blank" rel="noopener"
          >
            <span class="rank-no" :class="'top' + (i < 3 ? i + 1 : 0)">{{ i + 1 }}</span>
            <div class="rank-id">
              <span class="rank-name">{{ s.name }}</span>
              <span class="rank-code" v-if="s.leader">领涨 {{ s.leader }}</span>
            </div>
            <span class="rank-val pos">{{ fmtPct(s.change_pct) }}</span>
          </router-link>
        </div>
        <div v-else class="empty-state small"><p>暂无数据</p></div>
      </div>

      <!-- 涨速榜 -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">{{ boardKind === 'concept' ? '概念' : '行业' }} 1 分钟涨速</span>
          <span class="panel-meta">{{ hasBoardSpeed ? '实时涨速' : '暂按涨幅' }}</span>
        </div>
        <div v-if="loadingBoardSpeed" class="list-skeleton">
          <div class="skeleton-row" v-for="i in 6" :key="i"><span class="skeleton w-sm"></span><span class="skeleton"></span><span class="skeleton w-md"></span></div>
        </div>
        <div v-else-if="boardSpeedItems.length" class="rank-list">
          <router-link
            v-for="(s, i) in boardSpeedItems" :key="s.code || s.name"
            :to="{ path: '/market-hub', query: { sector: boardKind } }"
            class="rank-row" target="_blank" rel="noopener"
          >
            <span class="rank-no" :class="'top' + (i < 3 ? i + 1 : 0)">{{ i + 1 }}</span>
            <div class="rank-id">
              <span class="rank-name">{{ s.name }}</span>
              <span class="rank-code" v-if="s.leader">领涨 {{ s.leader }}</span>
            </div>
            <span class="rank-price" :class="chgClass(s.change_pct)">{{ fmtPct(s.change_pct) }}</span>
            <span class="rank-val" :class="chgClass(s.speed)">{{ s.speed != null ? fmtPct(s.speed) : '—' }}</span>
          </router-link>
        </div>
        <div v-else class="empty-state small"><p>暂无数据</p></div>
      </div>
    </div>

    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import StockMiniChart from '../components/StockMiniChart.vue'
import { useWatchlistStore } from '../stores/watchlist'

const wlStore = useWatchlistStore()

// 大盘指数（上证/深成/创业板/沪深300 + 港美等），来自 watchlist store
const indices = computed(() => wlStore.indices)

const DOMESTIC_CODES = new Set(['000001','399001','399006','000688','899050','000300','000905','000852'])
const domesticIndices = computed(() => indices.value.filter(i => DOMESTIC_CODES.has(i.code)))
const globalIndices = computed(() => indices.value.filter(i => !DOMESTIC_CODES.has(i.code)))

// 自选走势：每只自选股 → {名称, 涨跌幅, 当日分时曲线, 昨收基准}
const wlChartList = computed(() => wlStore.watchlist.map(s => {
  const rt = wlStore.realtimeData[s.code] || {}
  return {
    code: s.code,
    name: s.name,
    price: rt.price ?? rt.last ?? null,
    change_pct: rt.change_pct ?? null,
    chart: wlStore.miniChartData[s.code] || [],
    pre: wlStore.miniChartPre[s.code] ?? rt.pre_close ?? null,
    // 迷你图：红=涨 绿=跌（A股色序，与组件内着色一致）
    color: rt.change_pct == null ? null : (rt.change_pct >= 0 ? 'red' : 'green'),
  }
}))

// localStorage 小工具（视图/周期/条数偏好持久化）
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) } catch { return d } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ } },
}

const picksData    = ref(null)
const watchItems   = ref([])
const recentWR     = ref(null)   // 策略命中率+平均收益（首页合并卡专用）
const loadingPicks = ref(true)
const loadingWatch = ref(true)

// 命中率/收益统计周期：0=实时(今日开盘价→现价) / 1=昨日 / 3·7·30=持有N个交易日聚合。
// 实时与 3/7/30 走 /strategy-winrate(与荐股页同源口径)，昨日走 /recent-winrate。
const statPeriod = ref(LS.get('home_stat_period', 1))
const periodOpts = [
  { days: 0, short: '实时', label: '实时' },
  { days: 1, short: '昨日', label: '昨日' },
  { days: 3, short: '3日', label: '持有3日' },
  { days: 7, short: '7日', label: '持有7日' },
  { days: 30, short: '30日', label: '持有30日' },
]
const periodLabel = computed(() => (periodOpts.find(p => p.days === statPeriod.value) || periodOpts[0]).label)

// 自选走势视图：card(卡片) / list(列表)，与自选股页两种形态一致
const wlView = ref(LS.get('home_wl_view', 'card'))
function setWlView(v) { wlView.value = v; LS.set('home_wl_view', v) }

// 榜单保留条数（可选 10/15/20/30）
const topOpts = [10, 15, 20, 30]
const rankTop = ref(LS.get('home_rank_top', 15))

// 榜单看板
const gainers        = ref([])
const speedStocks    = ref([])
const boardKind          = ref(LS.get('home_board_kind', 'industry'))  // concept | industry
const boardGainers       = ref([])
const boardSpeedItems    = ref([])
const loadingBoardGainers = ref(true)
const loadingBoardSpeed   = ref(true)
const loadingGainers          = ref(true)
const loadingSpeedStocks      = ref(true)

const picks = computed(() => picksData.value?.picks || [])

// 涨速是否已采样出来（否则为按涨幅回退，盘中约 1 分钟后才有真实涨速）
const hasStockSpeed   = computed(() => speedStocks.value.some(s => s.speed != null))
const hasBoardSpeed   = computed(() => boardSpeedItems.value.some(s => s.speed != null))

// 自选汇总（合并卡用）
const wlUp = computed(() => watchItems.value.filter(w => (w.change_pct ?? 0) > 0).length)
const wlAvg = computed(() => {
  const chg = watchItems.value.filter(w => w.change_pct != null)
  return chg.length ? chg.reduce((s, w) => s + w.change_pct, 0) / chg.length : null
})

function accColor(v) {
  if (v == null) return 'var(--text-1)'
  if (v >= 60) return 'var(--profit)'
  if (v >= 40) return 'var(--accent)'
  return 'var(--loss)'
}
function chgClass(v) { return v == null ? '' : (v >= 0 ? 'pos' : 'neg') }
function fmtPct(v) { return v != null ? (v >= 0 ? '+' : '') + v.toFixed(2) + '%' : '-' }

// A 股交易时段判断（周一~五 9:30–11:30 / 13:00–15:00）。
// 涨速榜只在交易时段才有意义，收盘/周末不空转轮询。
function isTradingHours() {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const hm = now.getHours() * 60 + now.getMinutes()
  return (hm >= 9 * 60 + 30 && hm <= 11 * 60 + 30) || (hm >= 13 * 60 && hm <= 15 * 60)
}
const tradingNow = ref(isTradingHours())

// 实时榜单：涨速依赖后端滚动采样，交易时段持续轮询才能让采样累积出 ~5 分钟前的基准。
let fetchingBoards = false
let boardTick = 0   // 轮询计数：指数每轮刷新；分时曲线每 ~30s(6 轮)重取一次
async function fetchBoards() {
  if (document.hidden) return  // 标签页在后台时不空转轮询
  if (fetchingBoards) return  // 上一轮未完成则跳过，避免轮询重叠堆积
  fetchingBoards = true
  try {
  await Promise.all([
    axios.get('/api/home/gainers', { params: { top: rankTop.value } }).then(r => { gainers.value = r.data?.items || [] }).catch(() => {}).finally(() => { loadingGainers.value = false }),
    axios.get('/api/home/speed/stocks', { params: { top: rankTop.value } }).then(r => { speedStocks.value = r.data?.items || [] }).catch(() => {}).finally(() => { loadingSpeedStocks.value = false }),
    fetchBoardGain(),
    fetchBoardSpeed(),
    // 指数行情随榜单一起轻量刷新；自选行情(含涨跌幅)同步刷新
    wlStore.fetchShIndex().catch(() => {}),
    wlStore.loadWatchlist().catch(() => {}),
  ])
  // 分时曲线较重(minute-batch)，每 ~30s 强制重取一次让曲线延伸
  if (++boardTick % 6 === 0) wlStore.fetchAllMiniChartData(true).catch(() => {})
  } finally {
    fetchingBoards = false
  }
}

// 指标卡里的命中率/收益/自选随实时盘面一起拉一次（轻量、不轮询）。
async function loadStatsExtras() {
  await Promise.all([
    axios.get('/api/ai-picks/daily').then(r => { picksData.value = r.data }).catch(() => {}).finally(() => { loadingPicks.value = false }),
    axios.get('/api/watchlist/overview').then(r => { watchItems.value = r.data?.items || [] }).catch(() => {}).finally(() => { loadingWatch.value = false }),
    fetchRecentWR(),
  ])
}

// 策略命中率 + 平均收益（按所选周期）。
// 昨日(1) 走 /recent-winrate；实时(0)/持有3·7·30日 走 /strategy-winrate 的对应窗口，
// 与 AI 荐股页的「该策略胜率」同源口径（实时=今日开盘价→现价；N日=历史推荐持有N日聚合）。
async function fetchRecentWR() {
  try {
    if (statPeriod.value === 1) {
      const r = await axios.get('/api/predictions/recent-winrate', { params: { days: 1 } })
      recentWR.value = r.data
    } else {
      const r = await axios.get('/api/predictions/strategy-winrate')
      const key = statPeriod.value === 0 ? 'realtime' : String(statPeriod.value)
      const h = (r.data?.horizons || []).find(x => x.key === key)
      recentWR.value = h
        ? { win_rate: h.win_rate, avg_change: h.avg_change, evaluated: h.evaluated }
        : { win_rate: null, avg_change: null, evaluated: 0 }
    }
  } catch { /* 保留旧值 */ }
}

function setStatPeriod(d) {
  if (statPeriod.value === d) return
  statPeriod.value = d
  LS.set('home_stat_period', d)
  fetchRecentWR()
}

// 板块涨幅榜（概念/行业）。轮询时静默刷新，不闪骨架。
async function fetchBoardGain() {
  try {
    const r = await axios.get('/api/home/board-gainers', { params: { kind: boardKind.value, top: rankTop.value } })
    boardGainers.value = r.data?.items || []
  } catch { /* 保留旧值 */ }
  finally { loadingBoardGainers.value = false }
}

// 板块涨速榜（概念/行业）。轮询时静默刷新，不闪骨架。
async function fetchBoardSpeed() {
  try {
    const r = await axios.get('/api/home/board-speed', { params: { kind: boardKind.value, top: rankTop.value } })
    boardSpeedItems.value = r.data?.items || []
  } catch { /* 保留旧值 */ }
  finally { loadingBoardSpeed.value = false }
}

function switchBoardKind(k) {
  if (boardKind.value === k) return
  boardKind.value = k
  LS.set('home_board_kind', k)
  loadingBoardGainers.value = true
  loadingBoardSpeed.value = true
  boardGainers.value = []
  boardSpeedItems.value = []
  fetchBoardGain()
  fetchBoardSpeed()
}

function setRankTop(n) {
  if (rankTop.value === n) return
  rankTop.value = n
  LS.set('home_rank_top', n)
  // 立即按新条数刷新三榜，复用 fetchBoards() 走同样的防重叠逻辑
  // （fetchBoards 内部读取 rankTop.value，故须先设好 rankTop 再调用）
  fetchBoards()
}

// 大盘指数 + 自选走势：指数行情、自选列表、当日分时曲线一次拉齐
async function loadWatchTrends() {
  await Promise.all([
    wlStore.fetchShIndex().catch(() => {}),
    wlStore.loadWatchlist().catch(() => {}),
  ])
  await wlStore.fetchAllMiniChartData().catch(() => {})
}

let boardTimer = null
function startPolling() {
  if (boardTimer) return
  if (!isTradingHours()) return   // 非交易时段不轮询
  boardTimer = setInterval(() => {
    tradingNow.value = isTradingHours()
    if (!tradingNow.value) { stopPolling(); return }  // 收盘自动停
    fetchBoards()
  }, 5000)
}
function stopPolling() {
  if (boardTimer) { clearInterval(boardTimer); boardTimer = null }
}

onMounted(async () => {
  tradingNow.value = isTradingHours()
  await Promise.all([fetchBoards(), loadStatsExtras(), loadWatchTrends()])
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.dashboard { padding: 24px; display: flex; flex-direction: column; gap: 20px; }

.tab-pane { display: flex; flex-direction: column; gap: 20px; animation: pane-in 0.22s ease; }
@keyframes pane-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.stats-row { display: grid; grid-template-columns: 1fr 2fr 1.6fr; gap: 12px; }
/* 首页指标卡：左侧 accent 细条 + 数值垂直收口，区分主次（覆盖全局 .metric-card） */
.stats-row .metric-card { position: relative; padding-left: 16px; }
.stats-row .metric-card::before {
  content: ''; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px;
  border-radius: 0 2px 2px 0; background: var(--accent); opacity: 0.5;
  transition: opacity var(--trans-base);
}
.stats-row .metric-card:hover::before { opacity: 1; }

/* 合并卡（命中率+收益 / 自选股数+均涨）：表头 + 两列指标 */
.metric-card.combo { display: flex; flex-direction: column; gap: 8px; }
.combo-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.combo-body { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.combo-item { display: flex; flex-direction: column; gap: 2px; }
.combo-item .metric-value { font-size: 22px; font-weight: 700; line-height: 1.1; }
.combo-item .metric-sub { font-size: 11px; color: var(--text-3); }
.seg-toggle.mini .seg-btn { padding: 2px 7px; font-size: 11px; }

/* 大盘指数区（国内/全球分组）*/
.index-section { display: flex; flex-direction: column; gap: 8px; }
.index-group { display: flex; align-items: flex-start; gap: 10px; }
.index-group-label { font-size: 11px; font-weight: 600; color: var(--text-3); letter-spacing: 0.05em; writing-mode: vertical-lr; text-orientation: mixed; padding: 6px 0; flex-shrink: 0; min-width: 14px; }
.index-strip { flex: 1; display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 10px; }
.idx-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px 12px; display: flex; flex-direction: column; gap: 3px; }
.idx-name { font-size: 12px; color: var(--text-2); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.idx-price { font-size: 17px; font-weight: 700; letter-spacing: -0.3px; }
.idx-chg { display: flex; justify-content: space-between; font-size: 11.5px; font-weight: 600; font-variant-numeric: tabular-nums; }

/* 自选走势网格 */
.wl-trend-panel { margin-bottom: 0; }
.wl-trend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1px; background: var(--border); }
.wlt-card { background: var(--bg-surface); padding: 12px 14px; text-decoration: none; color: var(--text-1); display: flex; flex-direction: column; gap: 8px; transition: background 0.12s; }
.wlt-card:hover { background: var(--bg-hover); }
.wlt-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.wlt-id { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.wlt-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wlt-code { font-size: 10px; color: var(--text-3); flex-shrink: 0; }
.wlt-chg { font-size: 12.5px; font-weight: 700; flex-shrink: 0; font-variant-numeric: tabular-nums; }
.wlt-spark { display: flex; align-items: center; justify-content: center; height: 44px; }
.wlt-empty { color: var(--text-3); font-size: 12px; }

/* 自选走势·列表视图 */
.wl-trend-list { display: flex; flex-direction: column; }
.wltl-row { display: flex; align-items: center; gap: 12px; padding: 9px 16px; text-decoration: none; color: var(--text-1); border-bottom: 1px solid var(--border); transition: background 0.12s; }
.wltl-row:last-child { border-bottom: none; }
.wltl-row:hover { background: var(--bg-hover); }
.wltl-id { display: flex; align-items: baseline; gap: 6px; width: 160px; min-width: 0; }
.wltl-name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wltl-code { font-size: 10px; color: var(--text-3); flex-shrink: 0; }
.wltl-spark { flex: 1; display: flex; align-items: center; min-width: 0; height: 28px; }
.wltl-price { font-size: 12px; color: var(--text-2); width: 64px; text-align: right; flex-shrink: 0; }
.wltl-chg { font-size: 12.5px; font-weight: 700; width: 64px; text-align: right; flex-shrink: 0; font-variant-numeric: tabular-nums; }

/* 面板右侧操作区（视图切换 / 链接 / 分段开关）*/
.panel-actions { display: flex; align-items: center; gap: 10px; }
.view-toggle { display: inline-flex; gap: 2px; background: var(--bg-hover); padding: 2px; border-radius: 7px; }
.vt-btn { display: inline-flex; align-items: center; justify-content: center; padding: 3px 8px; border: none; background: transparent; color: var(--text-2); border-radius: 5px; cursor: pointer; transition: all 0.12s; }
.vt-btn:hover { color: var(--text-1); }
.vt-btn.active { background: var(--bg-surface); color: var(--accent); box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

/* 榜单条数工具条 */
.rank-toolbar { display: flex; align-items: center; gap: 10px; }
.rank-toolbar-label { font-size: 12px; color: var(--text-2); font-weight: 500; }

/* Panel */
.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-xl); overflow: hidden; margin-bottom: 16px; }
.panel:last-child { margin-bottom: 0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 12px; border-bottom: 1px solid var(--border); }
.panel-title { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; color: var(--text-1); }
.panel-title svg { color: var(--accent); }
.panel-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.panel-link:hover { text-decoration: underline; }
.panel-loading { display: flex; align-items: center; gap: 8px; padding: 20px 16px; color: var(--text-2); font-size: 12px; }

.empty-state { padding: 32px 16px; text-align: center; color: var(--text-2); }
.empty-state.small { padding: 20px 16px; }
.list-skeleton { padding: 4px 4px 8px; }
.empty-state p { font-size: 13px; margin: 0; }
.empty-hint { font-size: 12px; color: var(--text-3); margin-top: 6px !important; }

.panel-meta { font-size: 11px; color: var(--text-3); }

/* 排名榜单（个股涨幅 / 1分钟涨速）*/
.board-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
.board-grid .panel { margin-bottom: 0; }
.rank-list { display: flex; flex-direction: column; max-height: 480px; overflow-y: auto; }
.rank-row { display: flex; align-items: center; gap: 9px; padding: 8px 14px; text-decoration: none; color: var(--text-1); border-bottom: 1px solid var(--border); transition: background 0.12s; }
.rank-row:last-child { border-bottom: none; }
.rank-row:not(.static):hover { background: var(--bg-hover); }
.rank-no { font-size: 11px; font-weight: 700; color: var(--text-3); width: 18px; text-align: center; flex-shrink: 0; }
/* 前三名金银铜徽章 */
.rank-no.top1, .rank-no.top2, .rank-no.top3 {
  color: #fff; border-radius: 50%; width: 18px; height: 18px; line-height: 18px;
}
.rank-no.top1 { background: #f59e0b; }   /* 金 */
.rank-no.top2 { background: #94a3b8; }   /* 银 */
.rank-no.top3 { background: #c2843f; }   /* 铜 */
.rank-id { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.rank-name { font-size: 12.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-code { font-size: 10px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rank-price { font-size: 11.5px; width: 54px; text-align: right; flex-shrink: 0; }
.rank-val { font-size: 12.5px; font-weight: 700; width: 56px; text-align: right; flex-shrink: 0; }

/* 板块类型工具条（概念/行业切换，独立于榜单行）*/
.board-kind-bar { display: flex; align-items: center; gap: 10px; }
.seg-toggle { display: inline-flex; gap: 2px; background: var(--bg-hover); padding: 2px; border-radius: 7px; }
.seg-btn { padding: 3px 12px; border: none; background: transparent; color: var(--text-2); font-size: 12px; font-weight: 600; border-radius: 5px; cursor: pointer; transition: all 0.12s; }
.seg-btn:hover { color: var(--text-1); }
.seg-btn.active { background: var(--bg-surface); color: var(--accent); box-shadow: 0 1px 2px rgba(0,0,0,0.06); }

.pos { color: var(--profit); }
.neg { color: var(--loss); }

@media (max-width: 1180px) {
  .board-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .dashboard { padding: 12px; gap: 14px; }
  .stats-row { grid-template-columns: 1fr; gap: 8px; }
  .board-grid { grid-template-columns: 1fr; }
  .panel-header { padding: 12px 12px 10px; }
  .panel-actions { flex-wrap: wrap; }
  .index-group { flex-direction: column; gap: 6px; }
  .index-group-label { writing-mode: horizontal-tb; padding: 0; }
  .index-strip { grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); }
}
</style>
