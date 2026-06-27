<template>
  <div class="market-hub">

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="hub-tabs">
      <button :class="['hub-tab', tab === 'overview' ? 'active' : '']" @click="switchTab('overview')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
        大盘行情
      </button>
      <button :class="['hub-tab', tab === 'sector' ? 'active' : '']" @click="switchTab('sector')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        行业板块
      </button>
      <button :class="['hub-tab', tab === 'crowding' ? 'active' : '']" @click="switchTab('crowding')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>
        板块拥挤度
      </button>
      <div class="tab-spacer"></div>
      <button class="btn-refresh" @click="refreshCurrent" :disabled="isLoading">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: isLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <!-- ════════════ TAB: 大盘行情 ════════════ -->
    <template v-if="tab === 'overview'">

      <!-- 顶部量能/情绪条 -->
      <div class="pulse-bar panel">
        <div class="pulse-item">
          <span class="pulse-lbl">两市成交</span>
          <span class="pulse-val" v-if="turnover">{{ turnover.total_amount?.toLocaleString() }}<small>亿</small></span>
          <span class="pulse-val muted" v-else>--</span>
          <span class="pulse-sub" v-if="turnover">沪 {{ (turnover.sh_amount/1).toFixed(0) }} · 深 {{ (turnover.sz_amount).toFixed(0) }}</span>
        </div>
        <div class="pulse-sep"></div>
        <div class="pulse-item">
          <span class="pulse-lbl">涨 / 跌</span>
          <span class="pulse-val"><span class="up">{{ breadth?.up_count ?? '--' }}</span> <span class="muted">/</span> <span class="down">{{ breadth?.down_count ?? '--' }}</span></span>
          <span class="pulse-sub">涨跌比 {{ breadth?.advance_decline_ratio?.toFixed(2) ?? '--' }}</span>
        </div>
        <div class="pulse-sep"></div>
        <div class="pulse-item">
          <span class="pulse-lbl">涨停 / 跌停</span>
          <span class="pulse-val"><span class="up">{{ breadth?.limit_up ?? '--' }}</span> <span class="muted">/</span> <span class="down">{{ breadth?.limit_down ?? '--' }}</span></span>
          <span class="pulse-sub" v-if="limitPool?.seal_rate != null">封板率 {{ limitPool.seal_rate }}%</span>
        </div>
        <div class="pulse-sep"></div>
        <div class="pulse-item">
          <span class="pulse-lbl">最高连板</span>
          <span class="pulse-val accent-num">{{ limitPool?.top_height ? limitPool.top_height + '板' : '--' }}</span>
          <span class="pulse-sub" v-if="limitPool">炸板 {{ limitPool.zb_count }}</span>
        </div>
        <div class="pulse-sep"></div>
        <div class="pulse-item">
          <span class="pulse-lbl">情绪温度</span>
          <span class="pulse-val" :class="moodClass">{{ moodLabel }}</span>
          <span class="pulse-sub">{{ moodScore }}°</span>
        </div>
        <div class="pulse-grow"></div>
        <div class="pulse-item pulse-hsgt" v-if="southbound != null">
          <span class="pulse-lbl">南向资金</span>
          <span class="pulse-val" :class="southbound >= 0 ? 'up' : 'down'">{{ southbound >= 0 ? '+' : '' }}{{ southbound.toFixed(1) }}<small>亿</small></span>
        </div>
      </div>

      <!-- Index cards -->
      <div class="index-row">
        <div v-for="idx in indices" :key="idx.code" :class="['index-card', pctClass(idx.change_pct)]">
          <div class="idx-name">{{ idx.name }}</div>
          <div class="idx-price">{{ idx.price != null ? idx.price.toFixed(2) : '--' }}</div>
          <div class="idx-change">
            <span class="idx-pct" :class="pctClass(idx.change_pct)">
              {{ idx.change_pct != null ? (idx.change_pct > 0 ? '+' : '') + idx.change_pct.toFixed(2) + '%' : '--' }}
            </span>
            <span class="idx-abs" v-if="idx.change != null">
              {{ idx.change > 0 ? '+' : '' }}{{ idx.change.toFixed(2) }}
            </span>
          </div>
          <div class="idx-vol" v-if="idx.volume">成交 {{ fmtVol(idx.volume) }}</div>
        </div>
        <div v-if="!indices.length && !loadingIndices" class="index-card idx-empty">暂无数据</div>
        <div v-if="loadingIndices" class="index-card idx-empty">
          <span class="spinner spinner-sm"></span>
        </div>
      </div>

      <!-- Breadth + Movers -->
      <div class="two-col">

        <!-- 涨跌分布直方图 -->
        <div class="panel">
          <div class="panel-title">
            涨跌分布
            <span class="panel-hint" v-if="distribution">全市场 {{ distribution.total }} 只</span>
          </div>
          <div v-if="loadingDistribution" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else-if="distribution" class="dist-body">
            <div class="dist-chart">
              <div v-for="b in distribution.buckets" :key="b.key" class="dist-col" :title="b.label + '：' + b.count + ' 只'">
                <span class="dist-cnt" v-if="b.count">{{ b.count }}</span>
                <div class="dist-bar" :class="b.side" :style="{ height: distBarHeight(b.count) + '%' }"></div>
                <span class="dist-lbl">{{ b.label }}</span>
              </div>
            </div>
            <div class="breadth-stats">
              <div class="bstat"><div class="bstat-val up">{{ distribution.up_count }}</div><div class="bstat-lbl">上涨</div></div>
              <div class="bstat"><div class="bstat-val down">{{ distribution.down_count }}</div><div class="bstat-lbl">下跌</div></div>
              <div class="bstat"><div class="bstat-val">{{ distribution.flat_count }}</div><div class="bstat-lbl">平盘</div></div>
              <div class="bstat">
                <div class="bstat-val" :class="(distribution.advance_decline_ratio ?? 0) > 1 ? 'up' : 'down'">
                  {{ distribution.advance_decline_ratio != null ? distribution.advance_decline_ratio.toFixed(2) : '--' }}
                </div>
                <div class="bstat-lbl">涨跌比</div>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">行情快照尚未就绪</div>
        </div>

        <!-- Movers -->
        <div class="panel">
          <div class="panel-title">
            涨跌榜
            <div class="mover-tabs">
              <button :class="['mtab', moverMode === 'up' ? 'active' : '']" @click="moverMode = 'up'">涨幅</button>
              <button :class="['mtab', moverMode === 'down' ? 'active' : '']" @click="moverMode = 'down'">跌幅</button>
            </div>
          </div>
          <div v-if="loadingMovers" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else class="movers-list">
            <div v-for="s in displayMovers" :key="s.code" class="mover-row">
              <div class="mover-stock">
                <router-link :to="`/stock/${s.code}`" class="mover-name" target="_blank" rel="noopener">{{ s.name }}</router-link>
                <span class="mover-code">{{ s.code }}</span>
              </div>
              <div class="mover-price mono">{{ s.price != null ? s.price.toFixed(2) : '--' }}</div>
              <div :class="['mover-pct', s.change_pct >= 0 ? 'up' : 'down']">
                {{ s.change_pct != null ? (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%' : '--' }}
              </div>
            </div>
            <div v-if="!displayMovers.length" class="panel-empty">暂无数据</div>
          </div>
        </div>

      </div>

      <!-- 连板梯队 + 板块资金流 -->
      <div class="two-col">

        <!-- 连板梯队 -->
        <div class="panel">
          <div class="panel-title">
            连板梯队
            <span class="panel-hint" v-if="limitPool?.zt_count">{{ limitPool.zt_count }} 涨停 · 封板率 {{ limitPool.seal_rate ?? '--' }}%</span>
          </div>
          <div v-if="loadingLimitPool" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else-if="limitPool?.ladders?.length" class="ladder-body">
            <div v-for="l in limitPool.ladders" :key="l.lianban" class="ladder-row">
              <div class="ladder-tag" :class="lbClass(l.lianban)">{{ l.lianban }}板<span class="ladder-n">×{{ l.count }}</span></div>
              <div class="ladder-stocks">
                <router-link v-for="s in l.stocks" :key="s.code" :to="`/stock/${s.code}`" class="ladder-chip" :title="s.industry" target="_blank" rel="noopener">
                  {{ s.name }}
                </router-link>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">当前无涨停数据（休市/盘前）</div>
        </div>

        <!-- 板块资金流 TOP -->
        <div class="panel">
          <div class="panel-title">
            行业资金流
            <div class="mover-tabs">
              <button :class="['mtab', flowMode === 'in' ? 'active' : '']" @click="flowMode = 'in'">流入</button>
              <button :class="['mtab', flowMode === 'out' ? 'active' : '']" @click="flowMode = 'out'">流出</button>
            </div>
          </div>
          <div v-if="loadingFlow" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else-if="displayFlow.length" class="flow-list">
            <div v-for="b in displayFlow" :key="b.name" class="flow-row" @click="goSector(b.name)">
              <span class="flow-name">{{ b.name }}</span>
              <div class="flow-meta">
                <span :class="['flow-chg', (b.change_pct ?? 0) >= 0 ? 'up' : 'down']">{{ fmtPct(b.change_pct) }}</span>
                <span :class="['flow-amt', (b.net_flow ?? 0) >= 0 ? 'up' : 'down']">{{ fmtFlow(b.net_flow) }}</span>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">暂无资金流数据（非交易时段）</div>
        </div>

      </div>

      <!-- 两市两融 + 增量快讯 -->
      <div class="two-col">

        <!-- 两市两融 -->
        <div class="panel">
          <div class="panel-title">
            两市两融
            <span class="panel-hint" v-if="marginTotal?.date">{{ marginTotal.date }}</span>
          </div>
          <div v-if="loadingMargin" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <template v-else-if="marginTotal">
            <div class="margin-hero">
              <span class="mh-label">两市融资融券余额</span>
              <span class="mh-value mono">{{ fmtYi(marginTotal.total) }}</span>
              <span class="mh-sub">融资 {{ fmtYi(marginTotal.rz) }} · 融券 {{ fmtYi(marginTotal.rq) }}</span>
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
          </template>
          <div v-else class="panel-empty">暂无两融数据</div>
        </div>

        <!-- 增量快讯 -->
        <div class="panel">
          <div class="panel-title">
            增量快讯
            <button class="mtab" @click="openPage('/cls')">财联社电报 →</button>
          </div>
          <div v-if="loadingFlash" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else-if="flash.length" class="flash-list">
            <a v-for="(n, i) in flash.slice(0, 8)" :key="i" :href="n.url || undefined"
               :target="n.url ? '_blank' : undefined" class="flash-row">
              <span class="flash-time mono">{{ shortTime(n.time) }}</span>
              <span class="flash-title">{{ n.title }}</span>
            </a>
          </div>
          <div v-else class="panel-empty">暂无快讯</div>
        </div>

      </div>

    </template>

    <!-- ════════════ TAB: 行业板块 ════════════ -->
    <template v-if="tab === 'sector'">
      <SectorBoardPanel />
    </template>

    <!-- ════════════ TAB: 板块拥挤度 ════════════ -->
    <template v-if="tab === 'crowding'">
      <SectorCrowdingPanel />
    </template>

  </div>
</template>

<script setup>
import VChart from '../charts'
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import SectorBoardPanel from '../components/SectorBoardPanel.vue'
import SectorCrowdingPanel from '../components/SectorCrowdingPanel.vue'

const route  = useRoute()
const router = useRouter()
// 跳转统一在新标签页打开
function openPage(to) { window.open(router.resolve(to).href, '_blank') }

// ── Active tab ────────────────────────────────────────────────
const tab = ref('overview')

// ── Tab 1: 大盘行情 ───────────────────────────────────────────
const indices        = ref([])
const breadth        = ref(null)
const distribution   = ref(null)
const topMovers      = ref([])
const turnover       = ref(null)
const limitPool      = ref(null)
const sectorFlow     = ref([])
const hsgt           = ref(null)
const moverMode      = ref('up')
const flowMode       = ref('in')
const loadingIndices = ref(false)
const loadingBreadth = ref(false)
const loadingDistribution = ref(false)
const loadingMovers  = ref(false)
const loadingLimitPool = ref(false)
const loadingFlow    = ref(false)

// 两市两融 + 增量快讯（原首页「市场资讯」并入此处）
const margin       = ref([])
const marginSeries = ref([])
const flash        = ref([])
const loadingMargin = ref(false)
const loadingFlash  = ref(false)

const marginTotal   = computed(() => margin.value.find(m => m.market === '两市合计') || null)
function fmtYi(v) {
  if (v == null) return '—'
  const yi = v / 1e8
  if (yi >= 10000) return (yi / 10000).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) + ' 万亿'
  return yi.toLocaleString('zh-CN', { maximumFractionDigits: 1 }) + ' 亿'
}
function shortTime(t) {
  if (!t) return ''
  const m = String(t).match(/(\d{1,2}:\d{2})/)
  return m ? m[1] : String(t).slice(-8, -3)
}
const MC_W = 280, MC_H = 56, MC_PAD = 3
const marginChart = computed(() => {
  const s = (marginSeries.value || []).slice(-132)   // 近半年
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

const displayMovers = computed(() =>
  moverMode.value === 'up'
    ? [...topMovers.value].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)).slice(0, 12)
    : [...topMovers.value].sort((a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0)).slice(0, 12)
)

const displayFlow = computed(() => {
  const arr = [...sectorFlow.value]
  return flowMode.value === 'in'
    ? arr.sort((a, b) => (b.net_flow ?? 0) - (a.net_flow ?? 0)).slice(0, 12)
    : arr.sort((a, b) => (a.net_flow ?? 0) - (b.net_flow ?? 0)).slice(0, 12)
})

// 南向资金合计(北向已停披露，只取 available 的南向通道)
const southbound = computed(() => {
  if (!hsgt.value?.channels) return null
  const south = hsgt.value.channels.filter(c => c.direction === '南向' && c.net_buy != null)
  if (!south.length) return null
  return south.reduce((s, c) => s + c.net_buy, 0)
})

// 情绪温度: 综合涨跌比、涨停数、封板率、连板高度 → 0~100°
const moodScore = computed(() => {
  let score = 50
  const ratio = distribution.value?.advance_decline_ratio
  if (ratio != null) score += Math.min(Math.max((ratio - 1) * 18, -25), 25)
  const lu = breadth.value?.limit_up ?? 0, ld = breadth.value?.limit_down ?? 0
  score += Math.min((lu - ld * 2) * 0.4, 18)
  if (limitPool.value?.seal_rate != null) score += (limitPool.value.seal_rate - 50) * 0.2
  if (limitPool.value?.top_height) score += Math.min(limitPool.value.top_height * 1.5, 12)
  return Math.round(Math.min(Math.max(score, 0), 100))
})
const moodLabel = computed(() => {
  const s = moodScore.value
  return s >= 70 ? '亢奋' : s >= 58 ? '偏暖' : s >= 42 ? '中性' : s >= 30 ? '偏冷' : '冰点'
})
const moodClass = computed(() => {
  const s = moodScore.value
  return s >= 58 ? 'up' : s <= 42 ? 'down' : 'muted'
})

function distBarHeight(count) {
  const max = Math.max(1, ...(distribution.value?.buckets || []).map(b => b.count))
  return Math.max(count ? 4 : 0, (count / max) * 100)
}
function lbClass(lb) {
  return lb >= 4 ? 'lb-hot' : lb >= 2 ? 'lb-warm' : 'lb-base'
}
function fmtFlow(v) {
  if (v == null) return '—'
  const a = Math.abs(v)
  const s = a >= 1 ? a.toFixed(1) + '亿' : (a * 1e4).toFixed(0) + '万'
  return (v >= 0 ? '+' : '-') + s
}

// ── Global loading indicator ───────────────────────────────────
const isLoading = computed(() =>
  loadingIndices.value || loadingDistribution.value || loadingMovers.value ||
  loadingLimitPool.value
)

// ── Data loaders ──────────────────────────────────────────────

async function loadIndices() {
  loadingIndices.value = true
  try {
    const res = await axios.get('/api/market/indices')
    indices.value = res.data.indices || []
  } catch { indices.value = [] } finally { loadingIndices.value = false }
}

async function loadBreadth() {
  loadingBreadth.value = true
  try {
    const res = await axios.get('/api/market/breadth')
    breadth.value = res.data
  } catch { breadth.value = null } finally { loadingBreadth.value = false }
}

async function loadMovers() {
  loadingMovers.value = true
  try {
    const res = await axios.get('/api/market/movers')
    topMovers.value = res.data.stocks || []
  } catch { topMovers.value = [] } finally { loadingMovers.value = false }
}

async function loadDistribution() {
  loadingDistribution.value = true
  try {
    const res = await axios.get('/api/market/distribution')
    distribution.value = res.data
    // distribution 已含全部宽度字段，复用驱动顶部脉冲条，省一次 /breadth 请求
    breadth.value = {
      up_count: res.data.up_count, down_count: res.data.down_count,
      flat_count: res.data.flat_count, limit_up: res.data.limit_up,
      limit_down: res.data.limit_down, total: res.data.total,
      advance_decline_ratio: res.data.advance_decline_ratio,
    }
  } catch { distribution.value = null } finally { loadingDistribution.value = false }
}

async function loadTurnover() {
  try { const res = await axios.get('/api/market/turnover'); turnover.value = res.data } catch { turnover.value = null }
}

async function loadLimitPool() {
  loadingLimitPool.value = true
  try {
    const res = await axios.get('/api/market/limit-pool')
    limitPool.value = res.data
  } catch { limitPool.value = null } finally { loadingLimitPool.value = false }
}

async function loadSectorFlow() {
  loadingFlow.value = true
  try {
    const res = await axios.get('/api/sector/fund-flow', { params: { indicator: '今日' } })
    sectorFlow.value = res.data.boards || []
  } catch { sectorFlow.value = [] } finally { loadingFlow.value = false }
}

async function loadHsgt() {
  try { const res = await axios.get('/api/market/hsgt'); hsgt.value = res.data } catch { hsgt.value = null }
}

async function loadMargin() {
  loadingMargin.value = true
  try {
    const res = await axios.get('/api/home/margin')
    margin.value = res.data?.items || []
    marginSeries.value = res.data?.series || []
  } catch { margin.value = []; marginSeries.value = [] } finally { loadingMargin.value = false }
}

async function loadFlash() {
  loadingFlash.value = true
  try {
    const res = await axios.get('/api/news/flash', { params: { count: 12 } })
    flash.value = res.data?.items || []
  } catch { flash.value = [] } finally { loadingFlash.value = false }
}

// 大盘行情 Tab 的全部数据(并发拉取)。板块明细已独立到「行业板块」Tab。
function loadOverviewAll() {
  return Promise.allSettled([
    loadIndices(), loadDistribution(), loadMovers(),
    loadTurnover(), loadLimitPool(), loadSectorFlow(), loadHsgt(),
    loadMargin(), loadFlash(),
  ])
}

// ── Tab switching ─────────────────────────────────────────────

async function switchTab(t) {
  tab.value = t
  if (t === 'overview' && !indices.value.length) {
    await loadOverviewAll()
  }
}

function refreshCurrent() {
  if (tab.value === 'overview') {
    indices.value = []; breadth.value = null; distribution.value = null
    topMovers.value = []; turnover.value = null
    limitPool.value = null; sectorFlow.value = []; hsgt.value = null
    loadOverviewAll()
  }
}

// 行业资金流点击板块 → 切到「行业板块」Tab(详尽热力图/汇总表/成分股下钻在那里)
function goSector() {
  tab.value = 'sector'
}

// ── Helpers ───────────────────────────────────────────────────

function pctClass(pct) {
  if (pct == null) return ''
  return pct > 0 ? 'up' : pct < 0 ? 'down' : ''
}

function fmtPct(v) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

function fmtVol(v) {
  if (!v) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toString()
}

// ── Init ──────────────────────────────────────────────────────

onMounted(async () => {
  // 深链:?tab=sector 或 ?sector=* → 行业板块;否则大盘行情
  const initTab = route.query.tab
  if (initTab === 'crowding') {
    tab.value = 'crowding'
  } else if (initTab === 'sector' || route.query.sector) {
    tab.value = 'sector'
  } else {
    await loadOverviewAll()
  }
})
</script>

<style scoped>
.market-hub { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; min-height: 100%; }

/* ── Tab bar ── */
.hub-tabs { display: flex; align-items: center; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; align-self: flex-start; width: 100%; }
.hub-tab { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.hub-tab:hover { color: var(--text-1); }
.hub-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(15,23,42,0.12); }
.tab-spacer { flex: 1; }
.btn-refresh { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border); background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }
.btn-refresh:hover { border-color: var(--accent); color: var(--accent); }
.btn-refresh:disabled { opacity: 0.5; cursor: default; }
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

/* ── Panel base ── */
.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; }
.panel-title { font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.panel-hint { font-size: 11px; color: var(--text-3); font-weight: 400; }
.panel-loading { font-size: 12px; color: var(--text-3); padding: 16px 0; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px; }
.panel-empty { font-size: 12px; color: var(--text-3); padding: 20px 0; text-align: center; }
.chart-panel { padding: 14px; }
.error-box { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #dc2626; border-radius: var(--radius-md); padding: 10px 14px; font-size: 13px; }

/* ── Index row ── */
.index-row { display: flex; gap: 12px; flex-wrap: wrap; }
.index-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px 20px; min-width: 150px; flex: 1; }
.index-card.up   { border-color: rgba(239,68,68,0.3); }
.index-card.down { border-color: rgba(34,197,94,0.3); }
.idx-name  { font-size: 12px; color: var(--text-3); margin-bottom: 6px; }
.idx-price { font-size: 22px; font-weight: 700; color: var(--text-1); }
.idx-change { display: flex; align-items: baseline; gap: 6px; margin-top: 4px; }
.idx-pct { font-size: 14px; font-weight: 700; }
.idx-pct.up   { color: #dc2626; }
.idx-pct.down { color: #16a34a; }
.idx-abs { font-size: 12px; color: var(--text-3); }
.idx-vol { font-size: 11px; color: var(--text-3); margin-top: 6px; }
.idx-empty { display: flex; align-items: center; justify-content: center; font-size: 12px; color: var(--text-3); }

/* ── Two-col ── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 860px) { .two-col { grid-template-columns: 1fr; } }

/* ── Pulse bar (顶部量能/情绪条) ── */
.pulse-bar { display: flex; align-items: stretch; gap: 0; padding: 12px 4px; flex-wrap: wrap; }
.pulse-item { display: flex; flex-direction: column; gap: 3px; padding: 0 18px; justify-content: center; min-width: 96px; }
.pulse-hsgt { align-items: flex-end; }
.pulse-lbl { font-size: 11px; color: var(--text-3); }
.pulse-val { font-size: 19px; font-weight: 700; color: var(--text-1); line-height: 1.1; }
.pulse-val small { font-size: 11px; font-weight: 500; color: var(--text-3); margin-left: 2px; }
.pulse-val.muted { color: var(--text-3); }
.pulse-val.accent-num { color: var(--accent); }
.pulse-sub { font-size: 11px; color: var(--text-3); }
.pulse-sep { width: 1px; background: var(--border); margin: 4px 0; }
.pulse-grow { flex: 1; }

/* ── Distribution histogram ── */
.dist-body { display: flex; flex-direction: column; gap: 14px; }
.dist-chart { display: flex; align-items: flex-end; gap: 3px; height: 132px; padding-top: 14px; }
.dist-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; gap: 3px; height: 100%; position: relative; }
.dist-cnt { font-size: 9px; color: var(--text-3); line-height: 1; }
.dist-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; transition: height 0.3s; }
.dist-bar.up   { background: #dc2626; }
.dist-bar.down { background: #16a34a; }
.dist-bar.flat { background: var(--text-3); }
.dist-lbl { font-size: 8.5px; color: var(--text-3); white-space: nowrap; transform: scale(0.92); }

/* ── 连板梯队 ── */
.ladder-body { display: flex; flex-direction: column; gap: 10px; }
.ladder-row { display: flex; gap: 10px; align-items: flex-start; }
.ladder-tag { flex-shrink: 0; min-width: 52px; text-align: center; font-size: 12px; font-weight: 700; padding: 4px 8px; border-radius: var(--radius-sm); }
.ladder-tag.lb-hot  { background: #dc2626; color: #fff; }
.ladder-tag.lb-warm { background: rgba(239,68,68,0.18); color: #dc2626; }
.ladder-tag.lb-base { background: var(--bg-hover); color: var(--text-2); }
.ladder-n { font-size: 10px; font-weight: 500; margin-left: 3px; opacity: 0.85; }
.ladder-stocks { display: flex; flex-wrap: wrap; gap: 5px; flex: 1; }
.ladder-chip { font-size: 12px; padding: 3px 9px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; color: var(--text-1); text-decoration: none; transition: all 0.12s; }
.ladder-chip:hover { border-color: var(--accent); color: var(--accent); }

/* ── 行业资金流 ── */
.flow-list { display: flex; flex-direction: column; gap: 1px; }
.flow-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 8px; border-radius: var(--radius-sm); cursor: pointer; }
.flow-row:hover { background: var(--bg-hover); }
.flow-name { font-size: 13px; color: var(--text-1); font-weight: 500; }
.flow-meta { display: flex; align-items: center; gap: 14px; }
.flow-chg { font-size: 12px; font-weight: 600; min-width: 56px; text-align: right; }
.flow-amt { font-size: 13px; font-weight: 700; font-family: var(--font-mono); min-width: 66px; text-align: right; }
.flow-chg.up, .flow-amt.up { color: #dc2626; }
.flow-chg.down, .flow-amt.down { color: #16a34a; }
.muted { color: var(--text-3); }

/* ── Breadth ── */
.breadth-body { display: flex; flex-direction: column; gap: 14px; }
.breadth-bar-wrap { display: flex; flex-direction: column; gap: 8px; }
.breadth-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; gap: 2px; }
.seg { min-width: 4px; }
.seg-up   { background: #dc2626; }
.seg-flat { background: var(--border); }
.seg-down { background: #16a34a; }
.breadth-leg { display: flex; gap: 12px; font-size: 11px; }
.leg-up   { color: #dc2626; }
.leg-flat { color: var(--text-3); }
.leg-down { color: #16a34a; }
.breadth-stats { display: flex; gap: 20px; }
.bstat { text-align: center; }
.bstat-val { font-size: 20px; font-weight: 700; color: var(--text-1); }
.bstat-val.up   { color: #dc2626; }
.bstat-val.down { color: #16a34a; }
.bstat-lbl { font-size: 11px; color: var(--text-3); margin-top: 2px; }

/* ── Movers ── */
.mover-tabs { display: flex; gap: 4px; background: var(--bg-hover); border-radius: 6px; padding: 2px; }
.mtab { padding: 3px 10px; border-radius: 4px; border: none; background: transparent; color: var(--text-2); font-size: 11px; cursor: pointer; }
.mtab.active { background: var(--bg-surface); color: var(--accent); }
.movers-list { display: flex; flex-direction: column; gap: 2px; }
.mover-row { display: flex; align-items: center; gap: 8px; padding: 6px 6px; border-radius: var(--radius-sm); }
.mover-row:hover { background: var(--bg-hover); }
.mover-stock { flex: 1; }
.mover-name { font-size: 13px; font-weight: 500; color: var(--text-1); text-decoration: none; cursor: pointer; }
.mover-name:hover { color: var(--accent); }
.mover-code { font-size: 10px; color: var(--text-3); margin-left: 4px; }
.mover-price { font-size: 13px; color: var(--text-2); font-family: var(--font-mono); min-width: 54px; text-align: right; }
.mover-pct { font-size: 13px; font-weight: 700; min-width: 58px; text-align: right; }
.mover-pct.up   { color: #dc2626; }
.mover-pct.down { color: #16a34a; }

/* ── Sector mini tiles ── */
/* ── 板块区头部(标题 + 行业/概念切换)── */
.sect-header { display: flex; align-items: center; gap: 14px; margin-top: 4px; }
.sect-h-title { font-size: 15px; font-weight: 700; color: var(--text-1); }
.sect-title-l { display: flex; align-items: center; gap: 12px; }
.inline-sub { padding: 2px; }
.inline-sub .sub-tab { padding: 3px 11px; font-size: 11px; }

/* ── Sub-tabs ── */
.sub-tabs { display: flex; gap: 4px; background: var(--bg-hover); border-radius: 8px; padding: 3px; align-self: flex-start; }
.sub-tab { padding: 5px 14px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.sub-tab.active { background: var(--bg-surface); color: var(--accent); box-shadow: 0 1px 3px rgba(15,23,42,0.12); }

/* ── Board layout ── */
.board-controls { display: flex; align-items: center; gap: 12px; padding: 10px 14px; flex-wrap: wrap; }
.board-search-wrap { display: flex; align-items: center; gap: 6px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 5px 10px; }
.board-search { background: transparent; border: none; color: var(--text-1); font-size: 13px; outline: none; width: 180px; }
.sort-chips { display: flex; gap: 4px; }
.sort-chip { font-size: 11px; padding: 3px 9px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 4px; color: var(--text-3); cursor: pointer; transition: all 0.12s; white-space: nowrap; }
.sort-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.count-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }

.board-layout { display: grid; grid-template-columns: 320px 1fr; gap: 14px; align-items: start; }
.board-list { overflow: hidden; padding: 0; }
.board-list-inner { max-height: 540px; overflow-y: auto; }
.board-row { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.board-row:last-child { border-bottom: none; }
.board-row:hover { background: var(--bg-hover); }
.board-row.selected { background: var(--accent-dim); }
.board-row.selected .board-name { color: var(--accent); }
.board-row-main { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; }
.board-name { font-size: 13px; font-weight: 600; color: var(--text-1); }
.board-chg { font-size: 13px; font-weight: 700; font-family: var(--font-mono); }
.board-row-meta { display: flex; gap: 10px; flex-wrap: wrap; }
.leader-tag { font-size: 10px; color: var(--text-3); }

.stocks-panel { display: flex; flex-direction: column; gap: 10px; }
.empty-stocks { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 48px; text-align: center; }
.stocks-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; }
.stocks-table-wrap { overflow-x: auto; max-height: 460px; overflow-y: auto; padding: 0; }
.action-link { font-size: 11px; padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); text-decoration: none; white-space: nowrap; cursor: pointer; }
.action-link:hover { border-color: var(--accent); color: var(--accent); }

/* ── Shared ── */
.up   { color: #dc2626; }
.down { color: #16a34a; }
.pos  { color: var(--success); }
.neg  { color: var(--danger); }
.fw-600 { font-weight: 600; }
.mono { font-family: var(--font-mono); }
.accent { color: var(--accent); }
.text-3 { color: var(--text-3); }
.text-2 { color: var(--text-2); }
.btn-ghost { background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-2); cursor: pointer; }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
.btn-primary { background: var(--accent); border: none; border-radius: var(--radius-sm); color: #fff; cursor: pointer; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

/* ── Data table (shared) ── */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { background: var(--bg-hover); color: var(--text-2); font-weight: 600; padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
.data-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }

/* 两市两融 + 增量快讯（首页「市场资讯」并入） */
.margin-hero { display: flex; flex-direction: column; gap: 3px; padding: 12px 14px 10px; }
.mh-label { font-size: 11px; color: var(--text-2); }
.mh-value { font-size: 23px; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }
.mh-sub { font-size: 11px; color: var(--text-3); }
.margin-trend { padding: 0 14px 12px; }
.mt-svg { width: 100%; height: 56px; display: block; }
.mt-line { fill: none; stroke: var(--up); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.mt-line.down { stroke: var(--down); }
.mt-area { fill: var(--up); opacity: 0.10; stroke: none; }
.mt-area.down { fill: var(--down); }
.mt-foot { display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: var(--text-3); margin-top: 2px; }
.mt-chg { font-weight: 600; font-variant-numeric: tabular-nums; }
.flash-list { display: flex; flex-direction: column; }
.flash-row { display: flex; gap: 10px; padding: 9px 14px; text-decoration: none; color: var(--text-1); border-bottom: 1px solid var(--border); transition: background 0.12s; }
.flash-row:last-child { border-bottom: none; }
.flash-row:hover { background: var(--bg-hover); }
.flash-time { font-size: 11px; color: var(--text-3); flex-shrink: 0; padding-top: 1px; width: 38px; }
.flash-title { font-size: 12.5px; line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }

@media (max-width: 768px) {
  .market-hub { padding: 10px 12px; }
  .hub-tabs { overflow-x: auto; flex-wrap: nowrap; }
  .hub-tab { white-space: nowrap; flex-shrink: 0; padding: 7px 12px; }
  .two-col { grid-template-columns: 1fr; }
  .board-layout { grid-template-columns: 1fr; }
  .board-controls { padding: 8px 10px; gap: 8px; }
  .board-search-wrap { flex: 1; }
  .index-row { gap: 8px; }
  .data-table { min-width: 520px; }
  /* pulse-bar：窄屏横向滚动，避免多行堆叠 */
  .pulse-bar { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; padding: 10px 12px; gap: 0; }
  .pulse-item { flex-shrink: 0; padding: 0 14px; }
  .pulse-sep { flex-shrink: 0; }
  .pulse-grow { display: none; }
  /* 指数卡窄屏横向滚动 */
  .index-row { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .index-card { min-width: 130px; flex-shrink: 0; }
}
</style>
