<template>
  <div class="ps-root">
    <!-- 顶部标题栏 -->
    <div class="ps-header">
      <div class="ps-header-left">
        <h1 class="ps-title">涨价逻辑</h1>
        <span class="ps-subtitle">以事件驱动（涨价函 / 产品涨价）· 每主题一年时间线</span>
      </div>
      <div class="ps-header-right">
        <span v-if="updatedAt && mode === 'today'" class="ps-updated">{{ updatedAt }}</span>
        <button v-if="mode === 'today'" class="ps-btn-refresh" :class="{ loading: refreshing }" @click="refresh" :disabled="refreshing">
          <svg v-if="!refreshing" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
          </svg>
          <svg v-else class="spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 12a9 9 0 1 1-6.2-8.6"/>
          </svg>
          {{ refreshing ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 模式切换：今日 / 时间脉络 / 历史存档 -->
    <div class="ps-mode-tabs">
      <button class="ps-mode-tab" :class="{ active: mode === 'today' }" @click="switchMode('today')">今日分析</button>
      <button class="ps-mode-tab" :class="{ active: mode === 'timeline' }" @click="switchMode('timeline')">时间脉络</button>
      <button class="ps-mode-tab" :class="{ active: mode === 'history' }" @click="switchMode('history')">历史存档</button>
    </div>

    <!-- 来源统计栏 -->
    <div class="ps-stats" v-if="mode === 'today' && signalData.total">
      <div class="ps-stat-total">
        <span class="ps-stat-num">{{ signalData.total }}</span>
        <span class="ps-stat-label">条提价线索</span>
      </div>
      <div class="ps-stat-sources">
        <span
          v-for="(cnt, src) in signalData.by_source" :key="src"
          class="ps-src-chip"
        >{{ src }} <em>{{ cnt }}</em></span>
      </div>
    </div>

    <!-- 历史存档：日期选择条 -->
    <div class="ps-date-bar" v-if="mode === 'history'">
      <div class="ps-date-bar-loading" v-if="datesLoading">加载历史…</div>
      <div class="ps-date-bar-empty" v-else-if="!archiveDates.length">暂无历史存档，每日生成后将自动归档</div>
      <button
        v-for="d in archiveDates" :key="d.date"
        class="ps-date-chip" :class="{ active: selectedDate === d.date }"
        @click="selectDate(d.date)"
      >
        <span class="ps-date-chip-d">{{ fmtDate(d.date) }}</span>
        <span class="ps-date-chip-n" v-if="d.theme_count">{{ d.theme_count }}主题</span>
        <span class="ps-date-chip-t" v-if="d.generated_at" title="产出时间">{{ fmtDateTime(d.generated_at).slice(-5) }}</span>
      </button>
    </div>

    <!-- 时间脉络 -->
    <div class="ps-timeline" v-if="mode === 'timeline'">
      <div class="ps-loading" v-if="timelineLoading">
        <div class="ps-spinner"></div>
        <span>梳理涨价主题脉络…</span>
      </div>
      <div v-else-if="threads.length" class="ps-thread-list">
        <div class="ps-thread-hint">把近 {{ timelineSpan }} 天存档里同一涨价主题串起来，看确定性与龙头股的演进（持续越久越靠前）</div>
        <div v-for="(t, ti) in threads" :key="ti" class="ps-thread-card">
          <div class="ps-thread-head">
            <div class="ps-thread-left">
              <span class="ps-thread-name">{{ t.theme }}</span>
              <span class="ps-theme-cat" v-if="t.category">{{ t.category }}</span>
            </div>
            <span class="ps-thread-span">{{ fmtDate(t.first_seen) }} → {{ fmtDate(t.last_seen) }} · {{ t.days_count }}天</span>
          </div>
          <!-- 确定性脉络轨迹 -->
          <div class="ps-thread-track">
            <div v-for="(p, pi) in t.points" :key="pi" class="ps-track-point" :title="p.date + ' · ' + p.confidence">
              <span class="ps-track-dot" :class="'conf-' + p.confidence"></span>
              <span class="ps-track-date">{{ fmtDate(p.date).slice(-5) }}</span>
              <span class="ps-track-conf" :class="'conf-' + p.confidence">{{ p.confidence }}</span>
            </div>
          </div>
          <div class="ps-thread-aliases" v-if="t.aliases?.length">
            <span class="ps-section-label">各日叫法</span>
            <span class="ps-alias-text">{{ t.aliases.join(' · ') }}</span>
          </div>
          <div class="ps-thread-logic" v-if="t.latest_logic">{{ t.latest_logic }}</div>
          <div class="ps-theme-stocks" v-if="t.latest_stocks?.length">
            <span class="ps-section-label">最新龙头</span>
            <div class="ps-stock-chips">
              <span v-for="nm in t.latest_stocks" :key="nm" class="ps-stock-chip flat" @click="goStockByName(nm)">
                <span class="ps-chip-name">{{ nm }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="ps-empty">
        <p>暂无可串联的历史主题，多积累几天存档后再来看脉络</p>
      </div>
    </div>

    <!-- 主体：上方线索墙 + 下方 AI 主题卡（今日 / 历史存档复用） -->
    <div class="ps-body" v-if="mode !== 'timeline'">

      <!-- AI 主题分析（主列） -->
      <section class="ps-panel ps-analysis">
        <div class="ps-panel-head">
          <span class="ps-panel-title">{{ mode === 'history' ? (selectedDate ? fmtDate(selectedDate) + ' 涨价主题' : '历史涨价主题') : 'AI 涨价主题分析' }}</span>
          <span v-if="mode === 'today' && va._pending" class="ps-badge pending">生成中</span>
          <span v-else-if="va.themes?.length" class="ps-badge ok">{{ va.themes.length }} 个主题</span>
          <span v-if="va.signal_count" class="ps-badge info">基于 {{ va.signal_count }} 条线索</span>
          <span v-if="va.generated_at" class="ps-gen-time" title="本篇分析产出时间">产出 {{ fmtDateTime(va.generated_at) }}</span>
          <span v-if="va.partial" class="ps-badge warn" title="历史回填：库内研报/机构荐股/韭研可追溯，财经快讯不可回溯故缺失">近似·缺快讯</span>
          <button v-if="mode === 'today'" class="ps-btn-regen" @click="regenAnalysis" :disabled="regenLoading" title="重新生成">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
            </svg>
          </button>
        </div>

        <!-- 加载中 -->
        <div class="ps-loading" v-if="vaLoading">
          <div class="ps-spinner"></div>
          <span>{{ mode === 'history' ? '读取存档…' : '正在采集涨价线索并分析…' }}</span>
        </div>

        <!-- pending 提示（仅今日） -->
        <div v-else-if="mode === 'today' && va._pending && !va.themes?.length" class="ps-pending-box">
          <div class="ps-spinner"></div>
          <div class="ps-pending-text">
            <div class="ps-pending-title">AI 分析生成中</div>
            <div class="ps-pending-sub">正在综合多源线索，约 30–60 秒，请稍候</div>
          </div>
          <button class="ps-btn-poll" @click="pollAnalysis">刷新结果</button>
        </div>

        <!-- 有结果 -->
        <div v-else-if="va.themes?.length" class="ps-themes">
          <!-- 总体判断 -->
          <div class="ps-summary" v-if="va.summary">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
            {{ va.summary }}
          </div>

          <!-- 主题卡片 -->
          <div
            v-for="(th, idx) in va.themes"
            :key="idx"
            class="ps-theme-card"
            :class="'conf-' + th.confidence"
          >
            <!-- 卡片头 -->
            <div class="ps-theme-head">
              <div class="ps-theme-left">
                <span class="ps-theme-name">{{ th.theme }}</span>
                <span class="ps-theme-cat" v-if="th.category">{{ th.category }}</span>
              </div>
              <div class="ps-theme-badges">
                <span class="ps-conf-badge" :class="'conf-' + th.confidence">{{ th.confidence }}</span>
                <span class="ps-catalyst-badge" v-if="th.catalyst">{{ th.catalyst }}</span>
                <span
                  v-if="th.generated_at || va.generated_at"
                  class="ps-card-stamp"
                  title="本篇产出日期与具体时间"
                >🕒 {{ fmtDateTime(th.generated_at || va.generated_at) }}</span>
              </div>
            </div>

            <!-- 驱动事件（事件驱动核心：涨价函 / 产品涨价 / 供需驱动） -->
            <div class="ps-trigger" v-if="th.trigger && (th.trigger.event || th.trigger.date)">
              <span class="ps-trigger-type" :class="'et-' + (th.trigger.type || '')">{{ th.trigger.type || '驱动事件' }}</span>
              <span class="ps-trigger-event">{{ th.trigger.event || '—' }}</span>
              <span class="ps-trigger-date" v-if="th.trigger.date">{{ th.trigger.date }}</span>
            </div>

            <!-- 传导逻辑 -->
            <div class="ps-theme-logic">{{ th.logic }}</div>

            <!-- 证据线索 -->
            <div class="ps-evidence" v-if="th.evidence?.length">
              <span class="ps-section-label">线索依据</span>
              <div class="ps-evidence-list">
                <span v-for="(ev, ei) in th.evidence" :key="ei" class="ps-ev-item">{{ ev }}</span>
              </div>
            </div>

            <!-- 龙头个股 -->
            <div class="ps-theme-stocks" v-if="th.stocks?.length">
              <span class="ps-section-label">龙头个股</span>
              <div class="ps-stock-chips">
                <div
                  v-for="s in th.stocks"
                  :key="s.code || s.name"
                  class="ps-stock-chip"
                  :class="pctClass(s.change_pct)"
                  @click="s.code && goStock(s.code)"
                >
                  <span class="ps-chip-name">{{ s.name }}</span>
                  <span class="ps-chip-code" v-if="s.code">{{ s.code }}</span>
                  <span class="ps-chip-pct" v-if="s.change_pct != null">
                    {{ s.change_pct > 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) }}%
                  </span>
                  <span class="ps-chip-mcap" v-if="s.market_cap">{{ mcapFmt(s.market_cap) }}</span>
                </div>
              </div>
            </div>

            <!-- 一年涨价时间线（按需展开，库内研报/机构荐股回溯） -->
            <div class="ps-year-line">
              <button class="ps-yl-toggle" @click="toggleTimeline(th.theme)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 8v4l3 3"/><circle cx="12" cy="12" r="9"/>
                </svg>
                {{ openTimelines[th.theme] ? '收起涨价时间线' : '查看一年涨价时间线' }}
              </button>
              <div v-if="openTimelines[th.theme]" class="ps-yl-body">
                <div v-if="timelineCache[th.theme]?.loading" class="ps-yl-loading">
                  <div class="ps-spinner"></div><span>回溯近一年涨价事件…</span>
                </div>
                <template v-else>
                  <div class="ps-yl-meta" v-if="timelineCache[th.theme]?.total">
                    近一年 <em>{{ timelineCache[th.theme].total }}</em> 个涨价事件 · 始于 {{ timelineCache[th.theme].first_date }}
                  </div>
                  <div class="ps-yl-events" v-if="(timelineCache[th.theme]?.events || []).length">
                    <div v-for="(e, ei) in timelineCache[th.theme].events" :key="ei" class="ps-yl-event">
                      <span class="ps-yl-dot" :class="'et-' + e.event_type"></span>
                      <span class="ps-yl-date">{{ e.date }}</span>
                      <span class="ps-yl-et" :class="'et-' + e.event_type">{{ e.event_type }}</span>
                      <span class="ps-yl-title">{{ e.title }}</span>
                      <span class="ps-yl-src">{{ e.source }}</span>
                    </div>
                  </div>
                  <div v-else class="ps-yl-empty">近一年库内暂无该主题的涨价事件记录</div>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div v-else class="ps-empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:.3"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
          <p v-if="mode === 'history'">{{ selectedDate ? '该日期暂无存档' : '选择上方日期查看当日涨价主题' }}</p>
          <p v-else>近期暂未捕捉到明显涨价线索，或点击刷新重新分析</p>
          <button v-if="mode === 'today'" class="ps-btn-gen" @click="regenAnalysis">立即生成</button>
        </div>
      </section>

      <!-- 右侧：原始线索流（仅今日） -->
      <section class="ps-panel ps-signals" v-if="mode === 'today'">
        <div class="ps-panel-head">
          <span class="ps-panel-title">原始线索</span>
          <span class="ps-badge info" v-if="signalData.signals?.length">{{ signalData.signals.length }}</span>
          <div class="ps-filter-tabs">
            <button
              v-for="src in ['全部', ...srcList]" :key="src"
              class="ps-filter-tab"
              :class="{ active: activeFilter === src }"
              @click="activeFilter = src"
            >{{ src }}</button>
          </div>
        </div>

        <div class="ps-loading" v-if="signalsLoading">
          <div class="ps-spinner"></div>
          <span>采集中…</span>
        </div>

        <div v-else-if="filteredSignals.length" class="ps-signal-list">
          <div v-for="(sig, i) in filteredSignals" :key="i" class="ps-signal-row">
            <div class="ps-sig-top">
              <span class="ps-sig-src" :class="'src-' + sig.source_kind">{{ sig.source }}</span>
              <span class="ps-sig-et" :class="'et-' + sig.event_type" v-if="sig.event_type">{{ sig.event_type }}</span>
              <span class="ps-sig-date">{{ sig.date }}</span>
            </div>
            <div class="ps-sig-title">{{ sig.title }}</div>
            <div class="ps-sig-snippet" v-if="sig.snippet">{{ sig.snippet }}</div>
            <div class="ps-sig-kws">
              <span v-for="kw in (sig.keywords || []).slice(0, 4)" :key="kw" class="ps-kw-tag">{{ kw }}</span>
              <span v-if="sig.stocks?.length" class="ps-sig-stocks">
                → {{ sig.stocks.slice(0, 3).join('、') }}
              </span>
            </div>
          </div>
        </div>

        <div v-else class="ps-empty">
          <p>暂无含提价关键词的线索</p>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()

const mode = ref('today')   // today | timeline | history

const signalData = ref({ signals: [], by_source: {}, total: 0 })
const analysis = ref({ themes: [], summary: '', _pending: false })
const signalsLoading = ref(true)
const analysisLoading = ref(true)
const refreshing = ref(false)
const regenLoading = ref(false)
const updatedAt = ref('')
const activeFilter = ref('全部')

// 时间脉络
const threads = ref([])
const timelineLoading = ref(false)
const timelineSpan = ref(45)
const timelineLoaded = ref(false)

// 历史存档
const archiveDates = ref([])
const datesLoading = ref(false)
const datesLoaded = ref(false)
const selectedDate = ref('')
const historyData = ref({ themes: [], summary: '' })
const historyLoading = ref(false)

const srcList = computed(() => Object.keys(signalData.value.by_source || {}))

// 单主题一年涨价时间线（按需展开 + 缓存，键=主题名）
const openTimelines = reactive({})
const timelineCache = reactive({})

async function toggleTimeline(theme) {
  if (!theme) return
  openTimelines[theme] = !openTimelines[theme]
  if (openTimelines[theme] && !timelineCache[theme]) {
    timelineCache[theme] = { loading: true, events: [], total: 0 }
    try {
      const { data } = await axios.get('/api/price-surge/theme-timeline', { params: { theme } })
      timelineCache[theme] = { ...data, loading: false }
    } catch (e) {
      timelineCache[theme] = { loading: false, events: [], total: 0 }
    }
  }
}

// 主题视图数据源：今日走实时分析，历史走存档
const va = computed(() => (mode.value === 'history' ? historyData.value : analysis.value))
const vaLoading = computed(() => (mode.value === 'history' ? historyLoading.value : analysisLoading.value))

function fmtDate(d) {
  if (!d) return ''
  const t = String(d).slice(0, 10)
  return t.replace(/^\d{4}-/, '').replace('-', '/')  // 06-24 → 06/24（保留紧凑）
}

// 完整产出时间戳 → 「06/24 16:30」（日期 + 具体产出时间）
function fmtDateTime(iso) {
  if (!iso) return ''
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return ''
  const p = n => String(n).padStart(2, '0')
  return `${p(dt.getMonth() + 1)}/${p(dt.getDate())} ${p(dt.getHours())}:${p(dt.getMinutes())}`
}

const filteredSignals = computed(() => {
  const sigs = signalData.value.signals || []
  if (activeFilter.value === '全部') return sigs
  return sigs.filter(s => s.source === activeFilter.value)
})

function pctClass(pct) {
  if (pct == null) return ''
  return pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
}

function mcapFmt(v) {
  if (!v) return ''
  const yi = v > 1e6 ? v / 1e8 : v
  return yi >= 1000 ? (yi / 1000).toFixed(1) + '千亿' : yi.toFixed(0) + '亿'
}

function goStock(code) {
  router.push(`/stock/${code}`)
}

async function goStockByName(name) {
  if (!name) return
  try {
    const { data } = await axios.get('/api/market/search-global', { params: { q: name, limit: 1 } })
    const hit = (data?.items || [])[0]
    if (hit?.code && /^\d{6}$/.test(hit.code)) router.push(`/stock/${hit.code}`)
  } catch (_) {}
}

function switchMode(m) {
  mode.value = m
  if (m === 'timeline' && !timelineLoaded.value) loadTimeline()
  if (m === 'history' && !datesLoaded.value) loadDates()
}

async function loadTimeline() {
  timelineLoading.value = true
  try {
    const { data } = await axios.get('/api/price-surge/timeline')
    threads.value = data.threads || []
    timelineSpan.value = data.span_days || 45
    timelineLoaded.value = true
  } catch (e) {
    console.error('timeline error', e)
  } finally {
    timelineLoading.value = false
  }
}

async function loadDates() {
  datesLoading.value = true
  try {
    const { data } = await axios.get('/api/price-surge/dates')
    archiveDates.value = data.dates || []
    datesLoaded.value = true
    if (archiveDates.value.length) selectDate(archiveDates.value[0].date)
  } catch (e) {
    console.error('dates error', e)
  } finally {
    datesLoading.value = false
  }
}

async function selectDate(d) {
  selectedDate.value = d
  historyLoading.value = true
  try {
    const { data } = await axios.get('/api/price-surge/history', { params: { d } })
    historyData.value = data
  } catch (e) {
    console.error('history error', e)
    historyData.value = { themes: [], summary: '' }
  } finally {
    historyLoading.value = false
  }
}

async function loadSignals() {
  signalsLoading.value = true
  try {
    const { data } = await axios.get('/api/price-surge/signals')
    signalData.value = data
    if (data.updated_at) {
      updatedAt.value = new Date(data.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }
  } catch (e) {
    console.error('signals error', e)
  } finally {
    signalsLoading.value = false
  }
}

async function loadAnalysis() {
  analysisLoading.value = true
  try {
    const { data } = await axios.get('/api/price-surge/analysis')
    analysis.value = data
  } catch (e) {
    console.error('analysis error', e)
  } finally {
    analysisLoading.value = false
  }
}

async function pollAnalysis() {
  try {
    const { data } = await axios.get('/api/price-surge/analysis')
    analysis.value = data
  } catch (_) {}
}

async function refresh() {
  refreshing.value = true
  try {
    const { data } = await axios.get('/api/price-surge/signals?force=true')
    signalData.value = data
    if (data.updated_at) {
      updatedAt.value = new Date(data.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }
  } catch (_) {}
  finally { refreshing.value = false }
}

async function regenAnalysis() {
  regenLoading.value = true
  try {
    await axios.get('/api/price-surge/refresh')
    analysis.value = { ...analysis.value, _pending: true }
    setTimeout(pollAnalysis, 5000)
    setTimeout(pollAnalysis, 15000)
    setTimeout(pollAnalysis, 35000)
  } catch (_) {}
  finally { regenLoading.value = false }
}

onMounted(async () => {
  await Promise.all([loadSignals(), loadAnalysis()])
  if (analysis.value._pending) {
    let n = 0
    const t = setInterval(async () => {
      n++
      await pollAnalysis()
      if (!analysis.value._pending || n >= 8) clearInterval(t)
    }, 10000)
  }
})
</script>

<style scoped>
/* ── Root ───────────────────────────────────────────────── */
.ps-root {
  padding: 16px;
  max-width: 1440px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── Header ─────────────────────────────────────────────── */
.ps-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.ps-header-left { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ps-title { font-size: 18px; font-weight: 700; color: var(--text-primary); margin: 0; }
.ps-subtitle { font-size: 12px; color: var(--text-muted); }
.ps-header-right { display: flex; align-items: center; gap: 10px; }
.ps-updated { font-size: 11px; color: var(--text-muted); }

.ps-btn-refresh {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: 6px;
  border: 1px solid var(--border-subtle); background: var(--bg-card);
  color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all .15s;
}
.ps-btn-refresh:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.ps-btn-refresh:disabled { opacity: .5; cursor: default; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Stats bar ──────────────────────────────────────────── */
.ps-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
}
.ps-stat-total { display: flex; align-items: baseline; gap: 5px; flex-shrink: 0; }
.ps-stat-num { font-size: 22px; font-weight: 700; color: var(--color-up, #e11d2a); }
.ps-stat-label { font-size: 12px; color: var(--text-muted); }
.ps-stat-sources { display: flex; gap: 6px; flex-wrap: wrap; }
.ps-src-chip {
  padding: 2px 8px; border-radius: 5px;
  background: var(--bg-hover); border: 1px solid var(--border-subtle);
  font-size: 11px; color: var(--text-secondary);
}
.ps-src-chip em { font-style: normal; font-weight: 700; color: var(--accent, #e11d2a); margin-left: 3px; }

/* ── Body grid ──────────────────────────────────────────── */
.ps-body {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 12px;
  align-items: start;
}

/* ── Panel ──────────────────────────────────────────────── */
.ps-panel {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  overflow: hidden;
}
.ps-panel-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px 10px;
  border-bottom: 1px solid var(--border-subtle);
  flex-wrap: wrap;
}
.ps-panel-title { font-size: 13px; font-weight: 600; color: var(--text-primary); flex: 1; min-width: 80px; }

/* ── Badges ─────────────────────────────────────────────── */
.ps-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500;
  flex-shrink: 0;
}
.ps-badge.pending { background: rgba(234,179,8,.15); color: #ca8a04; }
.ps-badge.ok      { background: rgba(34,197,94,.15);  color: #16a34a; }
.ps-badge.info    { background: var(--bg-hover); color: var(--text-muted); }
.ps-badge.warn    { background: rgba(234,179,8,.15); color: #ca8a04; }

/* 产出时间标记（面板头 / 主题卡） */
.ps-gen-time {
  margin-left: auto; flex-shrink: 0;
  font-size: 11px; color: var(--text-muted);
  font-variant-numeric: tabular-nums; letter-spacing: .2px;
}
.ps-card-stamp {
  padding: 2px 7px; border-radius: 4px; font-size: 10px;
  background: var(--bg-hover); color: var(--text-muted);
  font-variant-numeric: tabular-nums; white-space: nowrap;
}

/* ── Loading / Empty ────────────────────────────────────── */
.ps-loading, .ps-empty {
  padding: 40px; display: flex; flex-direction: column;
  align-items: center; gap: 10px; color: var(--text-muted); font-size: 13px;
}
.ps-spinner {
  width: 20px; height: 20px;
  border: 2px solid var(--border-subtle); border-top-color: var(--accent, #e11d2a);
  border-radius: 50%; animation: spin 1s linear infinite;
}

/* ── Pending box ────────────────────────────────────────── */
.ps-pending-box {
  display: flex; align-items: center; gap: 14px;
  padding: 24px 16px; margin: 12px 14px;
  background: var(--bg-hover); border-radius: 10px;
  border: 1px dashed var(--border-subtle);
}
.ps-pending-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.ps-pending-sub   { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
.ps-btn-poll {
  margin-left: auto; padding: 5px 12px; border-radius: 6px;
  border: 1px solid var(--border-subtle); background: var(--bg-card);
  color: var(--text-secondary); font-size: 12px; cursor: pointer;
}
.ps-btn-poll:hover { border-color: var(--accent); color: var(--accent); }

/* ── Summary ────────────────────────────────────────────── */
.ps-summary {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 12px 14px;
  font-size: 13px; color: var(--text-secondary); line-height: 1.6;
  border-bottom: 1px solid var(--border-subtle);
}
.ps-summary svg { flex-shrink: 0; margin-top: 2px; opacity: .6; }

/* ── Theme card ─────────────────────────────────────────── */
.ps-themes { display: flex; flex-direction: column; }
.ps-theme-card {
  padding: 14px;
  border-bottom: 1px solid var(--border-subtle);
  transition: background .1s;
}
.ps-theme-card:last-child { border-bottom: none; }
.ps-theme-card.conf-高 { border-left: 3px solid var(--color-up, #e11d2a); }
.ps-theme-card.conf-中 { border-left: 3px solid #ca8a04; }
.ps-theme-card.conf-低 { border-left: 3px solid var(--border-subtle); }

.ps-theme-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 8px; margin-bottom: 8px; flex-wrap: wrap;
}
.ps-theme-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ps-theme-name { font-size: 15px; font-weight: 700; color: var(--text-primary); }
.ps-theme-cat {
  padding: 2px 7px; border-radius: 4px; font-size: 11px;
  background: var(--bg-hover); color: var(--text-muted); border: 1px solid var(--border-subtle);
}
.ps-theme-badges { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }

.ps-conf-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600;
}
.ps-conf-badge.conf-高 { background: rgba(225,29,42,.15); color: #e11d2a; }
.ps-conf-badge.conf-中 { background: rgba(234,179,8,.15); color: #ca8a04; }
.ps-conf-badge.conf-低 { background: rgba(100,116,139,.15); color: #64748b; }

.ps-catalyst-badge {
  padding: 2px 8px; border-radius: 4px; font-size: 11px;
  background: rgba(99,102,241,.1); color: #6366f1; border: 1px solid rgba(99,102,241,.2);
}

.ps-theme-logic {
  font-size: 13px; color: var(--text-secondary); line-height: 1.65;
  margin-bottom: 10px;
}

/* ── Evidence & section labels ──────────────────────────── */
.ps-section-label {
  font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 5px;
}
.ps-evidence { margin-bottom: 10px; }
.ps-evidence-list { display: flex; flex-direction: column; gap: 4px; }
.ps-ev-item {
  font-size: 12px; color: var(--text-muted);
  padding: 4px 8px; background: var(--bg-hover); border-radius: 5px;
  border-left: 2px solid var(--border-subtle);
  line-height: 1.5;
}

/* ── Stock chips ────────────────────────────────────────── */
.ps-theme-stocks { }
.ps-stock-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.ps-stock-chip {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 10px; border-radius: 8px;
  background: var(--bg-hover); border: 1px solid var(--border-subtle);
  cursor: pointer; transition: all .12s;
}
.ps-stock-chip:hover { border-color: var(--accent); }
.ps-stock-chip.up   { border-color: rgba(225,29,42,.3); }
.ps-stock-chip.down { border-color: rgba(38,166,154,.3); }
.ps-chip-name { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.ps-chip-code { font-size: 10px; color: var(--text-muted); }
.ps-chip-pct  { font-size: 12px; font-weight: 600; }
.ps-chip-mcap { font-size: 10px; color: var(--text-muted); }
.up   { color: var(--color-up, #e11d2a) !important; }
.down { color: var(--color-down, #26a69a) !important; }
.flat { color: var(--text-muted); }

/* ── Action buttons ─────────────────────────────────────── */
.ps-btn-regen {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 6px;
  border: 1px solid var(--border-subtle); background: transparent;
  color: var(--text-muted); cursor: pointer; transition: all .12s;
}
.ps-btn-regen:hover { border-color: var(--accent); color: var(--accent); }
.ps-btn-gen {
  padding: 8px 18px; border-radius: 8px; background: var(--accent, #e11d2a);
  color: #fff; border: none; font-size: 13px; cursor: pointer; transition: opacity .15s;
}
.ps-btn-gen:hover { opacity: .85; }

/* ── Signal list (right column) ─────────────────────────── */
.ps-filter-tabs { display: flex; gap: 3px; flex-wrap: wrap; }
.ps-filter-tab {
  padding: 2px 7px; border-radius: 4px; font-size: 11px;
  border: 1px solid var(--border-subtle); background: transparent;
  color: var(--text-muted); cursor: pointer; transition: all .12s;
}
.ps-filter-tab:hover { border-color: var(--accent); color: var(--accent); }
.ps-filter-tab.active { background: var(--accent, #e11d2a); border-color: var(--accent); color: #fff; }

.ps-signal-list { max-height: 78vh; overflow-y: auto; }
.ps-signal-row {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-subtle);
  transition: background .1s;
}
.ps-signal-row:last-child { border-bottom: none; }
.ps-signal-row:hover { background: var(--bg-hover); }

.ps-sig-top {
  display: flex; align-items: center; justify-content: space-between;
  gap: 6px; margin-bottom: 4px;
}
.ps-sig-src {
  font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600;
}
.src-news            { background: rgba(99,102,241,.12); color: #6366f1; }
.src-industry_report { background: rgba(14,165,233,.12); color: #0ea5e9; }
.src-stock_report    { background: rgba(234,179,8,.12);  color: #ca8a04; }
.src-blog            { background: rgba(34,197,94,.12);  color: #16a34a; }
.src-fenchuan        { background: rgba(239,68,68,.12);  color: #ef4444; }

.ps-sig-date { font-size: 10px; color: var(--text-muted); }
.ps-sig-title {
  font-size: 12px; font-weight: 600; color: var(--text-primary);
  line-height: 1.5; margin-bottom: 3px;
}
.ps-sig-snippet {
  font-size: 11px; color: var(--text-muted); line-height: 1.5;
  margin-bottom: 5px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.ps-sig-kws { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.ps-kw-tag {
  padding: 1px 5px; border-radius: 3px; font-size: 10px;
  background: rgba(225,29,42,.08); color: var(--color-up, #e11d2a);
  border: 1px solid rgba(225,29,42,.15);
}
.ps-sig-stocks { font-size: 10px; color: var(--text-muted); margin-left: 2px; }

/* ── Mode tabs ──────────────────────────────────────────── */
.ps-mode-tabs {
  display: flex; gap: 4px;
  padding: 4px; border-radius: 10px;
  background: var(--bg-card); border: 1px solid var(--border-subtle);
  align-self: flex-start;
}
.ps-mode-tab {
  padding: 6px 16px; border-radius: 7px; font-size: 13px;
  border: none; background: transparent; color: var(--text-secondary);
  cursor: pointer; transition: all .15s; font-weight: 500;
}
.ps-mode-tab:hover { color: var(--text-primary); }
.ps-mode-tab.active { background: var(--accent, #e11d2a); color: #fff; }

/* ── History date bar ───────────────────────────────────── */
.ps-date-bar {
  display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto;
  padding: 8px 10px;
  background: var(--bg-card); border: 1px solid var(--border-subtle); border-radius: 10px;
  -webkit-overflow-scrolling: touch;
}
.ps-date-bar-loading, .ps-date-bar-empty { font-size: 12px; color: var(--text-muted); padding: 4px 6px; }
.ps-date-chip {
  display: flex; flex-direction: column; align-items: center; gap: 1px;
  padding: 5px 12px; border-radius: 7px; flex-shrink: 0;
  border: 1px solid var(--border-subtle); background: var(--bg-hover);
  color: var(--text-secondary); cursor: pointer; transition: all .12s;
}
.ps-date-chip:hover { border-color: var(--accent); }
.ps-date-chip.active { background: var(--accent, #e11d2a); border-color: var(--accent); color: #fff; }
.ps-date-chip-d { font-size: 13px; font-weight: 600; }
.ps-date-chip-n { font-size: 10px; opacity: .8; }
.ps-date-chip-t { font-size: 10px; opacity: .6; font-variant-numeric: tabular-nums; }

/* ── Timeline threads ───────────────────────────────────── */
.ps-timeline { display: flex; flex-direction: column; }
.ps-thread-hint { font-size: 12px; color: var(--text-muted); padding: 2px 2px 10px; line-height: 1.5; }
.ps-thread-list { display: flex; flex-direction: column; gap: 10px; }
.ps-thread-card {
  background: var(--bg-card); border: 1px solid var(--border-subtle);
  border-radius: 12px; padding: 14px;
}
.ps-thread-head {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; margin-bottom: 12px; flex-wrap: wrap;
}
.ps-thread-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ps-thread-name { font-size: 16px; font-weight: 700; color: var(--text-primary); }
.ps-thread-span { font-size: 11px; color: var(--text-muted); }

.ps-thread-track {
  display: flex; gap: 0; overflow-x: auto; padding: 4px 0 10px;
  -webkit-overflow-scrolling: touch;
}
.ps-track-point {
  display: flex; flex-direction: column; align-items: center; gap: 3px;
  position: relative; flex-shrink: 0; min-width: 58px; padding: 0 2px;
}
/* 连线 */
.ps-track-point::before {
  content: ''; position: absolute; top: 6px; left: -50%; width: 100%; height: 2px;
  background: var(--border-subtle);
}
.ps-track-point:first-child::before { display: none; }
.ps-track-dot {
  width: 13px; height: 13px; border-radius: 50%; z-index: 1;
  border: 2px solid var(--bg-card); background: #64748b;
}
.ps-track-dot.conf-高 { background: #e11d2a; }
.ps-track-dot.conf-中 { background: #ca8a04; }
.ps-track-dot.conf-低 { background: #94a3b8; }
.ps-track-date { font-size: 10px; color: var(--text-muted); }
.ps-track-conf { font-size: 11px; font-weight: 600; }
.ps-track-conf.conf-高 { color: #e11d2a; }
.ps-track-conf.conf-中 { color: #ca8a04; }
.ps-track-conf.conf-低 { color: #94a3b8; }

.ps-thread-logic {
  font-size: 13px; color: var(--text-secondary); line-height: 1.6;
  margin: 4px 0 10px;
}
.ps-thread-aliases { margin: 2px 0 8px; }
.ps-alias-text { font-size: 11px; color: var(--text-muted); line-height: 1.5; }

/* ── Trigger event (事件驱动) ───────────────────────────── */
.ps-trigger {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; margin-bottom: 10px; border-radius: 8px;
  background: var(--bg-hover); border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent, #e11d2a);
}
.ps-trigger-type {
  padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; flex-shrink: 0;
}
.ps-trigger-event { font-size: 13px; color: var(--text-primary); line-height: 1.5; font-weight: 500; flex: 1; min-width: 120px; }
.ps-trigger-date { font-size: 11px; color: var(--text-muted); flex-shrink: 0; }

/* 事件类型配色（涨价函最硬→红、价格上涨→橙、供需驱动→蓝、提价预期→灰） */
.et-涨价函   { background: rgba(225,29,42,.14);  color: #e11d2a; }
.et-价格上涨 { background: rgba(234,88,12,.14);  color: #ea580c; }
.et-供需驱动 { background: rgba(14,165,233,.14); color: #0ea5e9; }
.et-提价预期 { background: rgba(100,116,139,.14); color: #64748b; }

/* 原始线索上的事件类型小标 */
.ps-sig-et { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; margin-right: auto; }

/* ── 一年涨价时间线 ─────────────────────────────────────── */
.ps-year-line { margin-top: 10px; }
.ps-yl-toggle {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 11px; border-radius: 6px;
  border: 1px solid var(--border-subtle); background: var(--bg-hover);
  color: var(--text-secondary); font-size: 12px; cursor: pointer; transition: all .12s;
}
.ps-yl-toggle:hover { border-color: var(--accent); color: var(--accent); }
.ps-yl-body { margin-top: 10px; }
.ps-yl-loading { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-muted); padding: 6px 0; }
.ps-yl-meta { font-size: 12px; color: var(--text-muted); margin-bottom: 8px; }
.ps-yl-meta em { font-style: normal; font-weight: 700; color: var(--accent, #e11d2a); }
.ps-yl-empty { font-size: 12px; color: var(--text-muted); padding: 6px 0; }

.ps-yl-events {
  display: flex; flex-direction: column; gap: 0;
  border-left: 2px solid var(--border-subtle);
  margin-left: 4px; padding-left: 0;
  max-height: 320px; overflow-y: auto;
}
.ps-yl-event {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  position: relative; padding: 6px 4px 6px 14px;
}
.ps-yl-dot {
  position: absolute; left: -6px; top: 11px;
  width: 9px; height: 9px; border-radius: 50%;
  border: 2px solid var(--bg-card); background: #64748b;
}
.ps-yl-dot.et-涨价函   { background: #e11d2a; }
.ps-yl-dot.et-价格上涨 { background: #ea580c; }
.ps-yl-dot.et-供需驱动 { background: #0ea5e9; }
.ps-yl-dot.et-提价预期 { background: #94a3b8; }
.ps-yl-date { font-size: 11px; color: var(--text-muted); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.ps-yl-et { font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; flex-shrink: 0; }
.ps-yl-title { font-size: 12px; color: var(--text-secondary); line-height: 1.5; flex: 1; min-width: 140px; }
.ps-yl-src { font-size: 10px; color: var(--text-muted); flex-shrink: 0; }

/* ── Mobile ─────────────────────────────────────────────── */
@media (max-width: 768px) {
  .ps-mode-tabs { align-self: stretch; }
  .ps-mode-tab { flex: 1; text-align: center; padding: 7px 6px; }
  .ps-thread-name { font-size: 15px; }
  .ps-root { padding: 10px 8px; }
  .ps-body {
    grid-template-columns: 1fr;
  }
  .ps-signals { order: -1; }
  .ps-signal-list { max-height: 50vh; }
  .ps-theme-head { flex-direction: column; }
  .ps-pending-box { flex-wrap: wrap; }
  .ps-btn-poll { margin-left: 0; }
  .ps-stat-sources { gap: 4px; }
}
</style>
