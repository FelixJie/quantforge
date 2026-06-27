<template>
  <div class="cls-page">
    <div class="page-head">
      <h2 class="page-title">📡 财联社电报</h2>
      <div class="cls-filters" v-if="!searchMode">
        <button :class="['mtab', clsCategory === '' ? 'active' : '']" @click="switchClsCategory('')">全部</button>
        <button :class="['mtab', clsCategory === 'red' ? 'active' : '']" @click="switchClsCategory('red')">重点</button>
      </div>
      <div class="cls-search">
        <span class="search-ico">🔍</span>
        <input v-model="searchKw" class="search-input" type="search" placeholder="搜索电报关键词/个股…"
               @keyup.enter="doSearch" />
        <button v-if="searchMode" class="search-clear" @click="clearSearch" title="返回">✕</button>
      </div>
      <div class="tab-spacer"></div>
      <button class="btn-ghost btn-sm" @click="toggleSummary" :class="{ active: showSummary }">📊 汇总分析</button>
      <button v-if="!searchMode" class="btn-ghost btn-sm" @click="loadCls(true)" :disabled="loadingCls">
        <span v-if="loadingCls" class="spinner spinner-sm"></span>
        <span v-else>刷新</span>
      </button>
    </div>

    <!-- ── 汇总分析面板 ── -->
    <div v-if="showSummary" class="panel summary-panel">
      <div v-if="loadingSummary" class="panel-loading">
        <span class="spinner"></span><span class="text-2">AI 正在汇总盘面…</span>
      </div>
      <template v-else-if="summary">
        <div class="summary-head">
          <span class="summary-title">📊 盘面汇总分析</span>
          <span v-if="summary.sentiment" :class="['sent-pill', sentClass(summary.sentiment.level)]">
            情绪 {{ summary.sentiment.label }} · {{ summary.sentiment.score }}
          </span>
          <span class="tab-spacer"></span>
          <button class="btn-ghost btn-xs" @click="loadSummary(true)" :disabled="loadingSummary">重新分析</button>
        </div>
        <div v-if="summary.summary" class="summary-text">{{ summary.summary }}</div>
        <div v-else class="summary-text text-3">AI 暂未给出综述，可点「重新分析」重试。</div>
        <div v-if="summary.themes?.length" class="summary-block">
          <span class="summary-label">热点主题</span>
          <span class="cls-chip subj" v-for="t in summary.themes" :key="t.name">{{ t.name }}<i v-if="t.count > 1">×{{ t.count }}</i></span>
        </div>
        <div v-if="summary.hot_stocks?.length" class="summary-block">
          <span class="summary-label">高频个股</span>
          <span class="cls-chip stock" v-for="s in summary.hot_stocks" :key="s.name">{{ s.name }}<i>×{{ s.count }}</i></span>
        </div>
        <div class="summary-foot text-3">基于最近 {{ summary.count }} 条电报 · {{ fmtUpdated(summary.updated_at) }}</div>
      </template>
      <div v-else class="empty-card"><span class="text-3">暂无汇总，点「重新分析」生成</span></div>
    </div>

    <div class="panel cls-board">
      <div v-if="searchMode" class="search-hint">
        <span class="text-2">“{{ activeKw }}” 搜索结果</span>
        <span class="text-3" v-if="!loadingCls">共 {{ clsItems.length }} 条{{ clsMore || hasMore ? '+' : '' }}</span>
      </div>
      <div v-if="loadingCls && !clsItems.length" class="panel-loading">
        <span class="spinner"></span><span class="text-2">加载中...</span>
      </div>
      <template v-else-if="clsItems.length">
        <div class="cls-timeline">
          <div v-for="item in clsItems" :key="item.id"
               :class="['cls-item', { 'is-red': item.is_red, 'is-new': item._isNew }]"
               @click="item._expanded = !item._expanded">
            <div class="cls-time">{{ item.time }}</div>
            <div class="cls-body">
              <div class="cls-text">
                <span v-if="item._isNew" class="new-badge">NEW</span>
                <span :class="['sdot', item.sentiment]"></span>
                <span class="cls-title" v-html="highlight(item.title)"></span>
              </div>
              <div v-if="item._expanded && item.content && item.content !== item.title" class="cls-content" v-html="highlight(item.content)"></div>
              <div class="cls-tags" v-if="item.stocks?.length || item.subjects?.length">
                <span class="cls-chip stock" v-for="s in item.stocks" :key="s.code || s.name">{{ s.name || s.code }}</span>
                <span class="cls-chip subj" v-for="t in item.subjects" :key="t">{{ t }}</span>
              </div>
              <div class="cls-stats" v-if="item.reading_num || item.share_num">
                <span v-if="item.reading_num">👁 {{ item.reading_num }}</span>
                <span v-if="item.share_num">↗ {{ item.share_num }}</span>
                <span v-if="item.comment_num">💬 {{ item.comment_num }}</span>
              </div>
            </div>
          </div>
        </div>
        <button class="cls-more" @click="loadMore" :disabled="clsMore || !canLoadMore">
          <span v-if="clsMore" class="spinner spinner-sm"></span>
          <span v-else>{{ canLoadMore ? '加载更多' : '没有更多了' }}</span>
        </button>
      </template>
      <div v-else class="empty-card">
        <span class="text-3">{{ searchMode ? '没有匹配的电报，换个关键词试试' : '暂无电报，点击刷新重试' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const clsItems    = ref([])
const loadingCls  = ref(false)
const clsCategory = ref('')        // '' 全部 / 'red' 重点
const clsCursor   = ref('')
const clsMore     = ref(false)     // 加载更多中
let clsTimer = null

// ── 搜索 ──────────────────────────────────────────────────────
const searchKw   = ref('')         // 输入框
const activeKw   = ref('')         // 当前生效的搜索词
const searchMode = computed(() => !!activeKw.value)
const searchPage = ref(0)
const hasMore    = ref(false)

// ── 汇总分析 ──────────────────────────────────────────────────
const showSummary    = ref(false)
const loadingSummary = ref(false)
const summary        = ref(null)

const canLoadMore = computed(() =>
  searchMode.value ? hasMore.value : !!clsCursor.value)

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}
function highlight(text) {
  const safe = escapeHtml(text)
  if (!activeKw.value) return safe
  const kw = activeKw.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return safe.replace(new RegExp(kw, 'gi'), m => `<mark>${m}</mark>`)
}
function fmtUpdated(iso) {
  if (!iso) return ''
  return iso.replace('T', ' ').slice(5, 16)
}
function sentClass(level) {
  if (level && level.includes('bull')) return 'pos'
  if (level && level.includes('bear')) return 'neg'
  return 'neu'
}

// ── 新增信息标记 ──────────────────────────────────────────────
const SEEN_KEY = 'cls_seen_news'
const SEEN_MAX = 800
function loadSeen() {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || '[]')) }
  catch { return new Set() }
}
function saveSeen(set) {
  try { localStorage.setItem(SEEN_KEY, JSON.stringify([...set].slice(-SEEN_MAX))) } catch {}
}
function markNew(items) {
  const seen = loadSeen()
  const firstRun = seen.size === 0
  for (const it of items) {
    const key = it.title + '|' + (it.date || '')
    it._isNew = !firstRun && !seen.has(key)
    seen.add(key)
  }
  saveSeen(seen)
  return items
}

async function loadCls(reset = true) {
  if (reset) { loadingCls.value = true; clsCursor.value = '' }
  else { clsMore.value = true }
  try {
    const res = await axios.get('/api/news/cls', {
      params: { count: 40, category: clsCategory.value, last_time: reset ? '' : clsCursor.value },
    })
    const items = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
    clsCursor.value = res.data.next_cursor || ''
    if (reset) clsItems.value = markNew(items)
    else {
      const seen = new Set(clsItems.value.map(i => i.id))
      clsItems.value = [...clsItems.value, ...items.filter(i => !seen.has(i.id))]
    }
  } catch {} finally { loadingCls.value = false; clsMore.value = false }
}

function switchClsCategory(cat) {
  if (clsCategory.value === cat) return
  clsCategory.value = cat
  loadCls(true)
}

// ── 搜索逻辑 ──────────────────────────────────────────────────
async function loadSearch(reset = true) {
  if (reset) { loadingCls.value = true; searchPage.value = 0 }
  else { clsMore.value = true; searchPage.value += 1 }
  try {
    const res = await axios.get('/api/news/cls/search', {
      params: { keyword: activeKw.value, page: searchPage.value, rn: 30 },
    })
    const items = (res.data.items || []).map(i => ({ ...i, _expanded: true }))
    hasMore.value = !!res.data.has_more
    if (reset) clsItems.value = items
    else {
      const seen = new Set(clsItems.value.map(i => i.id))
      clsItems.value = [...clsItems.value, ...items.filter(i => !seen.has(i.id))]
    }
  } catch {} finally { loadingCls.value = false; clsMore.value = false }
}

function doSearch() {
  const kw = searchKw.value.trim()
  if (!kw) { clearSearch(); return }
  activeKw.value = kw
  loadSearch(true)
}
function clearSearch() {
  searchKw.value = ''
  activeKw.value = ''
  clsItems.value = []
  loadCls(true)
}
function loadMore() {
  searchMode.value ? loadSearch(false) : loadCls(false)
}

// ── 汇总分析逻辑 ──────────────────────────────────────────────
async function loadSummary(force = false) {
  if (loadingSummary.value) return
  if (summary.value && !force) return
  loadingSummary.value = true
  try {
    const res = await axios.get('/api/news/cls/summary', { params: { count: 50 } })
    summary.value = res.data
  } catch {} finally { loadingSummary.value = false }
}
function toggleSummary() {
  showSummary.value = !showSummary.value
  if (showSummary.value) loadSummary(false)
}

onMounted(() => {
  loadCls(true)
  clsTimer = setInterval(() => { if (!searchMode.value) loadCls(true) }, 120000)
})
onUnmounted(() => { if (clsTimer) clearInterval(clsTimer) })
</script>

<style scoped>
.cls-page { padding: 20px 24px; display: flex; flex-direction: column; gap: 14px; min-height: 100%; }
.page-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.page-title { font-size: 17px; font-weight: 700; color: var(--text-1); margin: 0; }
.tab-spacer { flex: 1; }
.cls-filters { display: flex; gap: 4px; background: var(--bg-hover); border-radius: 6px; padding: 2px; }
.mtab { padding: 3px 10px; border-radius: 4px; border: none; background: transparent; color: var(--text-2); font-size: 11px; cursor: pointer; }
.mtab.active { background: var(--bg-surface); color: var(--accent); }

/* 搜索框 */
.cls-search { display: flex; align-items: center; gap: 5px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: 8px; padding: 3px 9px; min-width: 200px; }
.cls-search:focus-within { border-color: var(--accent); }
.search-ico { font-size: 12px; opacity: 0.6; }
.search-input { flex: 1; min-width: 0; border: none; background: transparent; color: var(--text-1); font-size: 12px; outline: none; }
.search-input::placeholder { color: var(--text-3); }
.search-clear { border: none; background: transparent; color: var(--text-3); cursor: pointer; font-size: 13px; padding: 0 2px; }
.search-clear:hover { color: var(--danger); }

.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.panel-loading { font-size: 12px; color: var(--text-3); padding: 24px 0; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px; }

/* ── 汇总分析面板 ── */
.summary-panel { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }
.summary-head { display: flex; align-items: center; gap: 10px; }
.summary-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.sent-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.sent-pill.pos { color: #dc2626; background: #dc262615; }
.sent-pill.neg { color: var(--success); background: color-mix(in srgb, var(--success) 14%, transparent); }
.sent-pill.neu { color: var(--text-2); background: var(--bg-elevated); }
.summary-text { font-size: 13px; line-height: 1.75; color: var(--text-1); white-space: pre-wrap; }
.summary-block { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.summary-label { font-size: 11px; color: var(--text-3); margin-right: 2px; }
.summary-block .cls-chip i { font-style: normal; opacity: 0.6; margin-left: 2px; }
.summary-foot { font-size: 11px; }

/* ── 财联社电报 ── */
.cls-board { padding: 0; overflow: hidden; }
.search-hint { display: flex; align-items: center; justify-content: space-between; padding: 9px 16px; border-bottom: 1px solid var(--border); font-size: 12px; }
.cls-timeline { max-height: calc(100vh - 200px); overflow-y: auto; }
.cls-item { display: flex; gap: 12px; padding: 11px 16px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.cls-item:last-child { border-bottom: none; }
.cls-item:hover { background: var(--bg-hover); }
.cls-item.is-new { background: color-mix(in srgb, var(--accent) 7%, transparent); }
.cls-time { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); flex-shrink: 0; padding-top: 1px; white-space: nowrap; }
.cls-body { flex: 1; min-width: 0; }
.cls-text { display: flex; align-items: flex-start; gap: 8px; }
.cls-title { font-size: 14px; color: var(--text-1); line-height: 1.6; }
.cls-item.is-red .cls-title { color: #dc2626; font-weight: 600; }
.cls-content { font-size: 13px; color: var(--text-2); line-height: 1.7; margin-top: 6px; padding-left: 15px; border-left: 2px solid var(--border); }
.cls-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.cls-chip { font-size: 11px; padding: 1px 7px; border-radius: 4px; white-space: nowrap; }
.cls-chip.stock { color: #dc2626; background: #dc262615; }
.cls-chip.subj { color: var(--text-2); background: var(--bg-elevated); }
.cls-stats { display: flex; gap: 12px; margin-top: 6px; font-size: 11px; color: var(--text-3); }
.cls-more { width: 100%; padding: 10px; border: none; border-top: 1px solid var(--border); background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }
.cls-more:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-1); }
.cls-more:disabled { color: var(--text-3); cursor: default; }

.new-badge { display: inline-block; font-size: 10px; font-weight: 800; line-height: 1; color: #fff; background: var(--accent, #f59e0b); padding: 2px 5px; border-radius: 4px; vertical-align: 1px; letter-spacing: 0.5px; }
.sdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 6px; }
.sdot.positive { background: var(--success); }
.sdot.negative { background: var(--danger); }
.sdot.neutral  { background: var(--text-3); }
:deep(mark) { background: var(--accent, #f59e0b); color: #fff; border-radius: 2px; padding: 0 2px; }

.empty-card { padding: 24px; text-align: center; }
.text-2 { color: var(--text-2); }
.text-3 { color: var(--text-3); }
.btn-ghost { background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-2); cursor: pointer; padding: 5px 12px; font-size: 12px; }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
.btn-ghost.active { border-color: var(--accent); color: var(--accent); background: color-mix(in srgb, var(--accent) 8%, transparent); }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-xs { padding: 2px 8px; font-size: 11px; }

@media (max-width: 768px) {
  .cls-page { padding: 10px 12px; }
  .page-head { gap: 8px; }
  .page-title { width: 100%; }
  .cls-search { flex: 1; min-width: 0; order: 5; }
  .cls-timeline { max-height: calc(100vh - 240px); }
}
</style>
