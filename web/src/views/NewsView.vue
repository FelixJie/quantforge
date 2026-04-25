<template>
  <div class="news-view">

    <!-- ══ 顶栏 ══════════════════════════════════════════════ -->
    <div class="news-header">
      <div class="header-left">
        <!-- Tab 切换 -->
        <div class="tab-bar">
          <button
            v-for="tab in tabs" :key="tab.key"
            :class="['tab-btn', { active: activeTab === tab.key }]"
            @click="switchTab(tab.key)"
          >
            <span class="tab-icon">{{ tab.icon }}</span>
            {{ tab.label }}
            <span v-if="tab.count" class="tab-count">{{ tab.count }}</span>
          </button>
        </div>
      </div>
      <div class="header-right">
        <!-- 情绪过滤 -->
        <div class="sentiment-filter">
          <button
            v-for="f in sentimentFilters" :key="f.value"
            :class="['sf-btn', f.value, { active: sentFilter === f.value }]"
            @click="sentFilter = sentFilter === f.value ? 'all' : f.value"
          >{{ f.label }}</button>
        </div>
        <!-- 刷新 -->
        <button class="refresh-btn" @click="refresh" :disabled="loading" :title="`${refreshCountdown}s 后自动刷新`">
          <svg :class="['refresh-icon', { spinning: loading }]" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.5 2v6h-6"/><path d="M2.5 22v-6h6"/>
            <path d="M22 11.5A10 10 0 0 0 3.2 7.2M2 12.5a10 10 0 0 0 18.8 4.2"/>
          </svg>
          <span class="countdown-dot" :style="{ opacity: refreshCountdown < 30 ? 1 : 0.4 }"></span>
        </button>
      </div>
    </div>

    <!-- ══ 情绪仪表盘 ════════════════════════════════════════ -->
    <div class="sentiment-dash" v-if="sentiment">
      <div class="sent-gauge">
        <div class="sent-score-wrap">
          <span :class="['sent-score', sentiment.level]">{{ sentiment.label }}</span>
          <span class="sent-score-num" :class="sentiment.level">
            {{ sentiment.score > 0 ? '+' : '' }}{{ sentiment.score }}
          </span>
        </div>
        <div class="sent-bar-wrap">
          <div class="sent-bar">
            <div class="sb-neg" :style="{ width: negPct + '%' }"></div>
            <div class="sb-neu" :style="{ width: neuPct + '%' }"></div>
            <div class="sb-pos" :style="{ width: posPct + '%' }"></div>
          </div>
          <div class="sent-bar-labels">
            <span class="neg">利空 {{ sentiment.negative }}</span>
            <span class="text-3">中性 {{ sentiment.neutral }}</span>
            <span class="pos">利多 {{ sentiment.positive }}</span>
          </div>
        </div>
      </div>
      <div class="sent-headlines">
        <span class="sent-head-label">最新快讯</span>
        <div class="headline-chips">
          <span
            v-for="h in sentiment.recent_headlines" :key="h"
            class="headline-chip"
            :title="h"
          >{{ h }}</span>
        </div>
      </div>
      <div class="sent-time text-3">{{ sentiment.updated_at?.slice(11,16) }} 更新</div>
    </div>

    <!-- ══ 主体 ═════════════════════════════════════════════ -->
    <div class="news-body">

      <!-- ── 新闻列表 ─────────────────────────────────────── -->
      <div class="news-feed">

        <!-- 加载骨架 -->
        <div v-if="loading && !displayItems.length" class="skeletons">
          <div v-for="i in 8" :key="i" class="skeleton-card">
            <div class="sk-line sk-title"></div>
            <div class="sk-line sk-sub"></div>
          </div>
        </div>

        <!-- 空态 -->
        <div v-else-if="!displayItems.length" class="empty-state">
          <div class="empty-icon">📭</div>
          <p>{{ sentFilter !== 'all' ? '该情绪分类暂无内容' : '暂无数据，点击刷新重试' }}</p>
        </div>

        <!-- 新闻卡片 -->
        <template v-else>
          <!-- 时间分组 -->
          <template v-for="group in groupedItems" :key="group.date">
            <div class="date-divider">
              <span>{{ group.label }}</span>
            </div>
            <div
              v-for="item in group.items" :key="item.id || item.title"
              class="news-card"
              :class="{ expanded: item._expanded }"
              @click="openItem(item)"
            >
              <!-- 左侧情绪条 -->
              <div class="nc-stripe" :class="item.sentiment"></div>

              <div class="nc-body">
                <!-- 标签行 -->
                <div class="nc-tags">
                  <span class="nc-type" :class="item.type">{{ typeLabel(item.type) }}</span>
                  <span class="nc-category">{{ item.category }}</span>
                  <span v-for="s in item.stocks?.slice(0,2)" :key="s.code" class="nc-stock">
                    {{ s.code }}{{ s.name ? ' ' + s.name : '' }}
                  </span>
                </div>

                <!-- 标题 -->
                <div class="nc-title">{{ item.title }}</div>

                <!-- 内容预览 -->
                <div v-if="item.content" class="nc-preview">{{ item.content }}</div>

                <!-- 底部元信息 -->
                <div class="nc-meta">
                  <span class="nc-source">{{ item.source }}</span>
                  <span class="nc-time mono">{{ item.time || item.date?.slice(5) }}</span>
                  <span v-if="item.url" class="nc-link" @click.stop="openUrl(item.url)">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                    原文
                  </span>
                </div>
              </div>
            </div>
          </template>

          <!-- 加载更多 -->
          <div v-if="displayItems.length >= pageSize" class="load-more">
            <button class="btn-ghost" @click="pageSize += 20">加载更多</button>
          </div>
        </template>
      </div>

      <!-- ── 右侧面板 ────────────────────────────────────── -->
      <div class="side-panel">

        <!-- 个股查询 -->
        <div class="panel-card">
          <div class="panel-title">个股资讯</div>
          <div class="stock-search-row">
            <input
              v-model="searchSym"
              class="input"
              placeholder="股票代码 如 000001"
              maxlength="6"
              @keyup.enter="loadStock"
            />
            <button class="btn-primary" @click="loadStock" :disabled="loadingStock || !searchSym">
              <span v-if="loadingStock" class="spinner spinner-sm"></span>
              <span v-else>查询</span>
            </button>
          </div>

          <!-- 个股结果 -->
          <div v-if="loadingStock" class="side-loading">
            <span class="spinner spinner-sm"></span> 查询中...
          </div>
          <div v-else-if="stockItems.length">
            <!-- 个股情绪 -->
            <div v-if="stockSentiment" class="stock-sent-row">
              <span :class="['sent-mini', stockSentiment.level]">{{ stockSentiment.label }}</span>
              <span class="text-3" style="font-size:11px">共 {{ stockItems.length }} 条</span>
            </div>
            <div class="stock-news-list">
              <div
                v-for="item in stockItems.slice(0, stockShowAll ? 999 : 6)"
                :key="item.id || item.title"
                class="sn-item"
                @click="openItem(item)"
              >
                <span :class="['sdot', item.sentiment]"></span>
                <div class="sn-content">
                  <div class="sn-title">{{ item.title }}</div>
                  <div class="sn-meta mono">{{ item.time || item.date?.slice(5) }} · {{ item.source }}</div>
                </div>
              </div>
              <button v-if="stockItems.length > 6 && !stockShowAll" class="show-more-btn" @click="stockShowAll = true">
                查看全部 {{ stockItems.length }} 条
              </button>
            </div>
          </div>
          <div v-else-if="stockQueried && !loadingStock" class="side-empty">
            未找到 {{ searchSym }} 的相关资讯
          </div>
        </div>

        <!-- AI 市场速评 -->
        <div class="panel-card ai-card">
          <div class="panel-title">
            <span>✨ AI 市场速评</span>
            <button
              class="ai-gen-btn"
              @click="loadAISummary(null)"
              :disabled="aiLoading"
            >
              <span v-if="aiLoading && !aiSymbol" class="spinner spinner-sm"></span>
              <span v-else>生成</span>
            </button>
          </div>
          <div v-if="aiLoading && !aiSymbol" class="side-loading">
            <span class="spinner spinner-sm"></span> AI 分析中...
          </div>
          <div v-else-if="aiSummary && !aiSymbol" class="ai-result">
            <p class="ai-text">{{ aiSummary.summary }}</p>
            <div class="ai-meta text-3">{{ aiSummary.generated_at?.slice(11,19) }} 生成 · {{ aiSummary.item_count }} 条素材</div>
          </div>
          <div v-else class="side-empty">点击「生成」获取AI市场分析</div>
        </div>

      </div>
    </div>

    <!-- ══ 阅读器 Modal ═══════════════════════════════════════ -->
    <div v-if="readingItem" class="reader-overlay" @click.self="readingItem = null">
      <div class="reader">
        <div class="reader-head">
          <div class="reader-tags">
            <span class="nc-type" :class="readingItem.type">{{ typeLabel(readingItem.type) }}</span>
            <span class="nc-category">{{ readingItem.category }}</span>
            <span :class="['sdot', readingItem.sentiment]" style="margin:0 2px"></span>
          </div>
          <button class="modal-close" @click="readingItem = null">×</button>
        </div>
        <div class="reader-body">
          <h2 class="reader-title">{{ readingItem.title }}</h2>
          <div class="reader-meta">
            <span>{{ readingItem.source }}</span>
            <span class="mono">{{ readingItem.date }} {{ readingItem.time }}</span>
            <span v-for="s in readingItem.stocks" :key="s.code" class="nc-stock">{{ s.code }} {{ s.name }}</span>
          </div>
          <div class="reader-content">
            {{ readingItem.content || '（完整内容请点击下方链接查看原文）' }}
          </div>
          <!-- AI 个股速评 -->
          <div v-if="readingItem.stocks?.length" class="reader-ai">
            <div class="reader-ai-head">
              <span class="ai-tag">✨ AI 速评 · {{ readingItem.stocks[0]?.code }}</span>
              <button class="ai-gen-btn" @click="loadAISummary(readingItem.stocks[0]?.code)" :disabled="aiLoading">
                <span v-if="aiLoading && aiSymbol === readingItem.stocks[0]?.code" class="spinner spinner-sm"></span>
                <span v-else>生成</span>
              </button>
            </div>
            <div v-if="aiLoading && aiSymbol === readingItem.stocks[0]?.code" class="side-loading">
              <span class="spinner spinner-sm"></span> 分析中...
            </div>
            <p v-else-if="aiSummary && aiSymbol === readingItem.stocks[0]?.code" class="ai-text">
              {{ aiSummary.summary }}
            </p>
          </div>
        </div>
        <div class="reader-foot" v-if="readingItem.url">
          <a :href="readingItem.url" target="_blank" rel="noopener" class="btn-primary reader-link">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
            查看原文
          </a>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()

// ── State ─────────────────────────────────────────────────────────────
const activeTab   = ref('flash')
const sentFilter  = ref('all')
const pageSize    = ref(30)
const loading     = ref(false)

const flashItems  = ref([])
const annItems    = ref([])
const sentiment   = ref(null)

const searchSym   = ref('')
const stockItems  = ref([])
const stockSentiment = ref(null)
const loadingStock = ref(false)
const stockQueried = ref(false)
const stockShowAll = ref(false)

const aiSummary   = ref(null)
const aiLoading   = ref(false)
const aiSymbol    = ref(null)

const readingItem = ref(null)

let refreshTimer   = null
let countdownTimer = null
const refreshCountdown = ref(120)
const REFRESH_SEC  = 120

const sentimentFilters = [
  { value: 'positive', label: '利多' },
  { value: 'negative', label: '利空' },
  { value: 'neutral',  label: '中性' },
]

const tabs = computed(() => [
  { key: 'flash',        icon: '⚡', label: '快讯',  count: flashItems.value.length || '' },
  { key: 'announcement', icon: '📋', label: '公告',  count: annItems.value.length || '' },
])

// ── Derived ───────────────────────────────────────────────────────────
const rawItems = computed(() =>
  activeTab.value === 'flash' ? flashItems.value : annItems.value
)

const filteredItems = computed(() => {
  let items = rawItems.value
  if (sentFilter.value !== 'all') items = items.filter(i => i.sentiment === sentFilter.value)
  return items
})

const displayItems = computed(() => filteredItems.value.slice(0, pageSize.value))

const groupedItems = computed(() => {
  const groups = {}
  const today = new Date().toISOString().slice(0, 10)
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10)

  for (const item of displayItems.value) {
    const d = item.date || '未知'
    if (!groups[d]) groups[d] = []
    groups[d].push(item)
  }

  return Object.entries(groups).map(([date, items]) => ({
    date,
    label: date === today ? '今天' : date === yesterday ? '昨天' : date,
    items,
  }))
})

// Sentiment pct bars
const posPct = computed(() => sentiment.value
  ? Math.round(sentiment.value.positive / Math.max(sentiment.value.total, 1) * 100) : 0)
const negPct = computed(() => sentiment.value
  ? Math.round(sentiment.value.negative / Math.max(sentiment.value.total, 1) * 100) : 0)
const neuPct = computed(() => 100 - posPct.value - negPct.value)

// ── Fetch ─────────────────────────────────────────────────────────────
async function loadFlash() {
  try {
    const res = await axios.get('/api/news/flash', { params: { count: 50 } })
    flashItems.value = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
  } catch (e) { console.warn('Flash news:', e.message) }
}

async function loadAnnouncements() {
  try {
    const res = await axios.get('/api/news/market', { params: { count: 50 } })
    annItems.value = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
  } catch (e) { console.warn('Announcements:', e.message) }
}

async function loadSentiment() {
  try {
    const res = await axios.get('/api/news/sentiment')
    sentiment.value = res.data
  } catch (e) { console.warn('Sentiment:', e.message) }
}

async function refresh() {
  loading.value = true
  refreshCountdown.value = REFRESH_SEC
  await Promise.all([loadSentiment(), loadFlash(), loadAnnouncements()])
  loading.value = false
}

async function switchTab(tab) {
  activeTab.value = tab
  sentFilter.value = 'all'
  pageSize.value = 30
}

async function loadStock() {
  if (!searchSym.value.trim()) return
  loadingStock.value = true
  stockQueried.value = true
  stockShowAll.value = false
  stockItems.value = []
  stockSentiment.value = null
  try {
    const res = await axios.get(`/api/news/stock/${searchSym.value.trim()}`)
    stockItems.value = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
    stockSentiment.value = res.data.sentiment || null
  } catch (e) { console.warn('Stock news:', e.message) }
  loadingStock.value = false
}

async function loadAISummary(sym) {
  aiLoading.value = true
  aiSymbol.value = sym
  aiSummary.value = null
  try {
    const params = sym ? { symbol: sym } : {}
    const res = await axios.post('/api/news/ai-summary', null, { params })
    aiSummary.value = res.data
  } catch (e) {
    aiSummary.value = { summary: 'AI分析暂时不可用', generated_at: new Date().toISOString() }
  }
  aiLoading.value = false
}

// ── Interaction ───────────────────────────────────────────────────────
function openItem(item) {
  readingItem.value = item
  aiSummary.value = null
  aiSymbol.value = null
}

function openUrl(url) {
  window.open(url, '_blank', 'noopener')
}

function typeLabel(type) {
  return { flash: '快讯', announcement: '公告', news: '新闻' }[type] || type
}

// ── Timers ────────────────────────────────────────────────────────────
function startTimers() {
  refreshTimer = setInterval(refresh, REFRESH_SEC * 1000)
  countdownTimer = setInterval(() => {
    refreshCountdown.value = Math.max(0, refreshCountdown.value - 1)
    if (refreshCountdown.value === 0) refreshCountdown.value = REFRESH_SEC
  }, 1000)
}

// ── Lifecycle ─────────────────────────────────────────────────────────
onMounted(async () => {
  if (route.query.symbol) searchSym.value = route.query.symbol
  loading.value = true
  await Promise.all([loadSentiment(), loadFlash(), loadAnnouncements()])
  loading.value = false
  if (searchSym.value) loadStock()
  startTimers()
})

onUnmounted(() => {
  clearInterval(refreshTimer)
  clearInterval(countdownTimer)
})

watch(activeTab, () => { pageSize.value = 30 })
</script>

<style scoped>
.news-view {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  min-height: 0;
}

/* ── Header ──────────────────────────────────── */
.news-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.header-left { display: flex; align-items: center; }
.header-right { display: flex; align-items: center; gap: 10px; }

/* Tab bar */
.tab-bar {
  display: flex;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 3px;
  gap: 2px;
}
.tab-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 6px 14px;
  background: transparent; border: none;
  border-radius: calc(var(--radius-md) - 2px);
  color: var(--text-3); font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.12s; white-space: nowrap;
}
.tab-btn:hover { color: var(--text-1); background: var(--bg-hover); }
.tab-btn.active { background: var(--accent); color: #fff; }
.tab-icon { font-size: 13px; }
.tab-count {
  font-size: 10px; padding: 1px 5px; border-radius: 8px;
  background: rgba(255,255,255,0.15); color: inherit;
}
.tab-btn.active .tab-count { background: rgba(255,255,255,0.25); }

/* Sentiment filter */
.sentiment-filter { display: flex; gap: 4px; }
.sf-btn {
  padding: 4px 10px; font-size: 11px; font-weight: 600;
  border-radius: var(--radius-md); border: 1px solid var(--border);
  background: transparent; cursor: pointer; transition: all 0.12s; color: var(--text-3);
}
.sf-btn.positive { color: var(--profit); border-color: rgba(245,101,101,0.3); }
.sf-btn.negative { color: var(--loss); border-color: rgba(72,187,120,0.3); }
.sf-btn.neutral  { color: var(--text-2); }
.sf-btn.active.positive { background: rgba(245,101,101,0.12); }
.sf-btn.active.negative { background: rgba(72,187,120,0.12); }
.sf-btn.active.neutral  { background: var(--bg-hover); color: var(--text-1); border-color: var(--border-light); }

/* Refresh button */
.refresh-btn {
  display: flex; align-items: center; gap: 5px;
  background: transparent; border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 6px 10px;
  color: var(--text-3); cursor: pointer; transition: all 0.12s;
}
.refresh-btn:hover { color: var(--text-1); border-color: var(--border-light); }
.refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.refresh-icon { transition: transform 0.3s; }
.refresh-icon.spinning { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.countdown-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent); transition: opacity 0.5s;
}

/* ── Sentiment dashboard ─────────────────────── */
.sentiment-dash {
  display: flex;
  align-items: center;
  gap: 20px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 12px 16px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.sent-gauge { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
.sent-score-wrap { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-width: 60px; }
.sent-score {
  font-size: 13px; font-weight: 700;
  padding: 2px 8px; border-radius: var(--radius-sm);
}
.sent-score.bullish, .sent-score.mild_bullish   { background: rgba(245,101,101,0.12); color: var(--profit); }
.sent-score.bearish, .sent-score.mild_bearish   { background: rgba(72,187,120,0.12);  color: var(--loss); }
.sent-score.neutral { background: var(--bg-elevated); color: var(--text-2); }
.sent-score-num { font-size: 11px; font-weight: 600; padding: 0 4px; }
.sent-score-num.bullish, .sent-score-num.mild_bullish { color: var(--profit); }
.sent-score-num.bearish, .sent-score-num.mild_bearish { color: var(--loss); }
.sent-score-num.neutral { color: var(--text-3); }

.sent-bar-wrap { display: flex; flex-direction: column; gap: 4px; min-width: 140px; }
.sent-bar {
  height: 6px; border-radius: 3px; overflow: hidden;
  display: flex; background: var(--bg-elevated);
}
.sb-neg { background: var(--loss);   height: 100%; transition: width 0.5s; }
.sb-neu { background: var(--text-3); height: 100%; opacity: 0.4; transition: width 0.5s; }
.sb-pos { background: var(--profit); height: 100%; transition: width 0.5s; }
.sent-bar-labels {
  display: flex; justify-content: space-between; font-size: 10px; font-weight: 500;
}

.sent-headlines { flex: 1; min-width: 0; display: flex; align-items: center; gap: 8px; }
.sent-head-label { font-size: 10px; color: var(--text-3); font-weight: 600; flex-shrink: 0; white-space: nowrap; }
.headline-chips { display: flex; gap: 5px; flex-wrap: nowrap; overflow: hidden; }
.headline-chip {
  font-size: 11px; color: var(--text-2); background: var(--bg-elevated);
  padding: 2px 8px; border-radius: 10px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  max-width: 220px; flex-shrink: 1;
}
.sent-time { font-size: 11px; flex-shrink: 0; white-space: nowrap; }

/* ── Main body ───────────────────────────────── */
.news-body {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 14px;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── Feed ────────────────────────────────────── */
.news-feed {
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
  border-radius: var(--radius-xl);
  background: var(--bg-surface);
  border: 1px solid var(--border);
}

/* Date divider */
.date-divider {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 16px 4px;
  font-size: 11px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.05em;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0; z-index: 1;
}

/* News card */
.news-card {
  display: flex;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}
.news-card:last-child { border-bottom: none; }
.news-card:hover { background: var(--bg-hover); }

.nc-stripe {
  width: 3px;
  flex-shrink: 0;
  border-radius: 0;
}
.nc-stripe.positive { background: var(--profit); }
.nc-stripe.negative { background: var(--loss); }
.nc-stripe.neutral  { background: var(--text-3); opacity: 0.3; }

.nc-body {
  flex: 1;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}

.nc-tags { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.nc-type {
  font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 4px;
}
.nc-type.flash        { background: rgba(59,130,246,0.15); color: #60a5fa; }
.nc-type.announcement { background: rgba(245,158,11,0.15); color: #fbbf24; }
.nc-type.news         { background: rgba(168,85,247,0.15); color: #c084fc; }

.nc-category {
  font-size: 10px; color: var(--text-3); background: var(--bg-elevated);
  padding: 1px 6px; border-radius: 4px;
}
.nc-stock {
  font-size: 10px; color: var(--accent); background: var(--accent-dim);
  padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono);
}

.nc-title {
  font-size: 13px; color: var(--text-1); line-height: 1.5;
  font-weight: 500;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.news-card:hover .nc-title { color: var(--accent); }

.nc-preview {
  font-size: 12px; color: var(--text-3); line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.nc-meta {
  display: flex; align-items: center; gap: 10px;
  font-size: 11px; color: var(--text-3);
}
.nc-source { font-weight: 500; }
.nc-time { }
.nc-link {
  display: flex; align-items: center; gap: 3px;
  color: var(--accent); cursor: pointer; margin-left: auto;
  opacity: 0;
  transition: opacity 0.12s;
}
.news-card:hover .nc-link { opacity: 1; }

/* Skeleton */
.skeletons { display: flex; flex-direction: column; }
.skeleton-card { padding: 12px 16px; border-bottom: 1px solid var(--border); }
.sk-line {
  background: var(--bg-elevated);
  border-radius: 4px;
  animation: shimmer 1.5s infinite;
}
.sk-title { height: 14px; width: 85%; margin-bottom: 8px; }
.sk-sub   { height: 11px; width: 40%; }
@keyframes shimmer {
  0%, 100% { opacity: 0.5; }
  50%       { opacity: 1; }
}

.load-more { padding: 14px; text-align: center; border-top: 1px solid var(--border); }

/* ── Side panel ──────────────────────────────── */
.side-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.panel-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.panel-title {
  font-size: 13px; font-weight: 600; color: var(--text-1);
  display: flex; align-items: center; justify-content: space-between;
}

.stock-search-row { display: flex; gap: 6px; }
.stock-search-row .input { flex: 1; }
.stock-search-row .btn-primary { padding: 7px 12px; font-size: 12px; white-space: nowrap; }

.stock-sent-row { display: flex; align-items: center; justify-content: space-between; }
.sent-mini {
  font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
}
.sent-mini.bullish, .sent-mini.mild_bullish { background: rgba(245,101,101,0.12); color: var(--profit); }
.sent-mini.bearish, .sent-mini.mild_bearish { background: rgba(72,187,120,0.12);  color: var(--loss); }
.sent-mini.neutral { background: var(--bg-elevated); color: var(--text-2); }

.stock-news-list { display: flex; flex-direction: column; gap: 0; }
.sn-item {
  display: flex; align-items: flex-start; gap: 8px;
  padding: 8px 0; border-bottom: 1px solid var(--border);
  cursor: pointer; transition: background 0.1s;
}
.sn-item:last-child { border-bottom: none; }
.sn-item:hover { background: var(--bg-hover); margin: 0 -14px; padding: 8px 14px; }
.sn-content { flex: 1; min-width: 0; }
.sn-title { font-size: 12px; color: var(--text-1); line-height: 1.4; margin-bottom: 2px; }
.sn-item:hover .sn-title { color: var(--accent); }
.sn-meta { font-size: 10px; color: var(--text-3); }
.sdot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.sdot.positive { background: var(--profit); }
.sdot.negative { background: var(--loss); }
.sdot.neutral  { background: var(--text-3); opacity: 0.5; }

.show-more-btn {
  width: 100%; padding: 6px; margin-top: 4px;
  background: transparent; border: 1px dashed var(--border);
  border-radius: var(--radius-md); color: var(--text-3);
  font-size: 11px; cursor: pointer; transition: all 0.12s;
}
.show-more-btn:hover { color: var(--accent); border-color: var(--accent); }

.side-loading { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-3); }
.side-empty { font-size: 12px; color: var(--text-3); text-align: center; padding: 12px 0; }

/* AI card */
.ai-card { background: linear-gradient(135deg, var(--bg-surface), rgba(139,92,246,0.05)); border-color: rgba(139,92,246,0.2); }
.ai-gen-btn {
  font-size: 11px; padding: 3px 10px;
  background: rgba(139,92,246,0.15); border: 1px solid rgba(139,92,246,0.3);
  border-radius: var(--radius-md); color: #a78bfa; cursor: pointer; transition: all 0.12s;
}
.ai-gen-btn:hover { background: rgba(139,92,246,0.25); }
.ai-gen-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ai-result { display: flex; flex-direction: column; gap: 6px; }
.ai-text { font-size: 12px; color: var(--text-1); line-height: 1.7; white-space: pre-wrap; margin: 0; }
.ai-meta { font-size: 10px; }

/* ── Reader modal ────────────────────────────── */
.reader-overlay {
  position: fixed; inset: 0; z-index: 300;
  background: rgba(0,0,0,0.65); backdrop-filter: blur(4px);
  display: flex; justify-content: flex-end;
}
.reader {
  width: 520px; max-width: 95vw;
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }

.reader-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px; border-bottom: 1px solid var(--border);
}
.reader-tags { display: flex; align-items: center; gap: 6px; }
.modal-close {
  background: none; border: none; color: var(--text-3);
  font-size: 22px; cursor: pointer; line-height: 1; padding: 0;
  width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
}
.modal-close:hover { color: var(--text-1); background: var(--bg-hover); }

.reader-body { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.reader-title { font-size: 17px; font-weight: 700; color: var(--text-1); line-height: 1.5; margin: 0; }
.reader-meta {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  font-size: 12px; color: var(--text-3);
}
.reader-content {
  font-size: 14px; color: var(--text-2); line-height: 1.8;
  padding: 14px; background: var(--bg-base);
  border-radius: var(--radius-lg); border: 1px solid var(--border);
}

.reader-ai {
  background: rgba(139,92,246,0.06);
  border: 1px solid rgba(139,92,246,0.2);
  border-radius: var(--radius-lg);
  padding: 14px;
  display: flex; flex-direction: column; gap: 10px;
}
.reader-ai-head {
  display: flex; align-items: center; justify-content: space-between;
}
.ai-tag { font-size: 11px; font-weight: 700; color: #a78bfa; background: #8b5cf618; padding: 2px 7px; border-radius: 4px; }

.reader-foot { padding: 14px 20px; border-top: 1px solid var(--border); background: var(--bg-base); }
.reader-link {
  display: inline-flex; align-items: center; gap: 6px;
  text-decoration: none; font-size: 13px; padding: 8px 16px;
}

/* ── Responsive ──────────────────────────────── */
@media (max-width: 900px) {
  .news-body { grid-template-columns: 1fr; }
  .side-panel { order: -1; overflow-y: visible; }
}
@media (max-width: 768px) {
  .news-view { padding: 10px 12px; gap: 8px; }
  .sentiment-dash { padding: 10px 12px; gap: 12px; }
  .sent-headlines { display: none; }
  .headline-chips { display: none; }
  .header-right { gap: 6px; }
  .sentiment-filter { gap: 3px; }
  .sf-btn { padding: 3px 8px; font-size: 10px; }
  .tab-btn { padding: 5px 10px; font-size: 12px; }
  .reader { width: 100%; max-width: 100%; position: fixed; inset: auto 0 0 0; height: 88vh; border-left: none; border-top: 1px solid var(--border); border-radius: var(--radius-xl) var(--radius-xl) 0 0; }
  .reader-overlay { align-items: flex-end; }
}
</style>
