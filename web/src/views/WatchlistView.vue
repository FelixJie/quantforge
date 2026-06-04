<template>
  <div class="watchlist-page">

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="hub-tabs">
      <button :class="['hub-tab', tab === 'watchlist' ? 'active' : '']" @click="switchTab('watchlist')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        自选股
      </button>
      <button :class="['hub-tab', tab === 'all' ? 'active' : '']" @click="switchTab('all')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
        全部股票
      </button>
      <div class="tab-spacer"></div>
      <button class="btn-refresh" @click="refreshData" :disabled="isLoading">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: isLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <!-- ════════════ TAB: 自选股 ════════════ -->
    <template v-if="tab === 'watchlist'">
      <div v-if="watchlistLoading" class="panel"><div class="panel-loading"><span class="spinner spinner-sm"></span> 加载自选股...</div></div>
      
      <div v-else-if="watchlist.length === 0" class="panel">
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
          <p>还没有自选股</p>
          <p class="text-3">点击上方"全部股票"添加</p>
        </div>
      </div>

      <div v-else class="panel">
        <div class="watchlist-header">
          <div class="watchlist-title">我的自选 ({{ sortedWatchlist.length }})</div>
          <div class="sort-chips">
            <button v-for="s in sortOpts" :key="s.key"
              :class="['sort-chip', sortKey === s.key ? 'active' : '']"
              @click="toggleSort(s.key)">
              {{ s.label }}{{ sortKey === s.key ? (sortAsc ? ' ↑' : ' ↓') : '' }}
            </button>
          </div>
        </div>

        <!-- 标签筛选 -->
        <div v-if="watchlistStore.tags.length" class="tag-filter">
          <button :class="['tagf-chip', tagFilter === '' ? 'active' : '']" @click="tagFilter = ''">全部</button>
          <button v-for="t in watchlistStore.tags" :key="t.tag"
            :class="['tagf-chip', tagFilter === t.tag ? 'active' : '']"
            @click="tagFilter = tagFilter === t.tag ? '' : t.tag">
            {{ t.tag }} <span class="tagf-count">{{ t.count }}</span>
          </button>
        </div>

        <div class="card-grid">
          <div v-for="stock in sortedWatchlist" :key="stock.code" class="wl-card" @click="goToDetail(stock.code)">
            <button class="card-x" @click.stop="removeFromWatchlist(stock.code)" title="移除自选">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
            <div class="wl-top">
              <span class="wl-name">{{ stock.name }}</span>
              <span class="wl-code">{{ stock.code }}</span>
            </div>
            <div class="wl-price-row">
              <span :class="['wl-price', getPriceClass(stock.code)]">{{ getCurrentPrice(stock.code) }}</span>
              <span :class="['wl-badge', getPriceClass(stock.code)]">{{ getChangePercent(stock.code) }}</span>
            </div>
            <div class="wl-spark" v-if="getChartData(stock.code).length > 0">
              <StockMiniChart :data="getChartData(stock.code)" :width="240" :height="40" :color="getStockColor(stock.code)" />
            </div>
            <div class="wl-meta">
              <span>PE {{ fmtNum(realtimeData[stock.code]?.pe) }}</span>
              <span>换手 {{ fmtPct(realtimeData[stock.code]?.turnover_rate) }}</span>
              <span>额 {{ fmtAmt(realtimeData[stock.code]?.turnover) }}</span>
            </div>
            <div class="wl-tags" @click.stop>
              <span v-for="t in (stock.tags || [])" :key="t" class="wl-tag">
                {{ t }}<i class="tag-x" @click="removeTag(stock, t)">×</i>
              </span>
              <input v-if="tagEditCode === stock.code" class="tag-input"
                v-model="tagInput" @keyup.enter="addTag(stock)" @blur="addTag(stock)" placeholder="标签名" />
              <button v-else class="tag-add" @click="startTagEdit(stock.code)">＋标签</button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ════════════ TAB: 全部股票 ════════════ -->
    <template v-if="tab === 'all'">
      <!-- 搜索和筛选 -->
      <div class="panel">
        <div class="search-row">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="searchQuery" @input="handleSearch" class="search-input" placeholder="搜索股票代码或名称..." />
        </div>
        <div class="filter-chips">
          <button :class="['filter-chip', filterType === 'all' ? 'active' : '']" @click="setFilter('all')">全部</button>
          <button :class="['filter-chip', filterType === 'gainers' ? 'active' : '']" @click="setFilter('gainers')">涨幅榜</button>
          <button :class="['filter-chip', filterType === 'losers' ? 'active' : '']" @click="setFilter('losers')">跌幅榜</button>
        </div>
      </div>

      <!-- 股票列表 -->
      <div v-if="allStocksLoading" class="panel"><div class="panel-loading"><span class="spinner spinner-sm"></span> 加载全部股票...</div></div>
      
      <div v-else-if="filteredAllStocks.length === 0 && !allStocksLoading" class="panel">
        <div class="panel-empty">未找到匹配的股票</div>
      </div>

      <div v-else class="panel">
        <div class="panel-title">
          股票列表 ({{ filteredAllStocks.length }})
        </div>
        <div class="card-grid">
          <div v-for="stock in paginatedStocks" :key="stock.code" class="wl-card" @click="goToDetail(stock.code)">
            <div class="wl-top">
              <span class="wl-name">{{ stock.name }}</span>
              <span class="wl-code">{{ stock.code }}</span>
            </div>
            <div class="wl-price-row">
              <span :class="['wl-price', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.price != null ? stock.price.toFixed(2) : '--' }}
              </span>
              <span :class="['wl-badge', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.change_pct != null ? ((stock.change_pct > 0 ? '+' : '') + stock.change_pct.toFixed(2) + '%') : '--' }}
              </span>
            </div>
            <div class="wl-card-foot">
              <span v-if="stock.exchange" class="exchange-tag">{{ stock.exchange }}</span>
              <span v-else class="text-3" style="font-size:11px">—</span>
              <button v-if="!isInWatchlist(stock.code)" class="wl-add" @click.stop="addToWatchlist(stock)">＋ 自选</button>
              <span v-else class="wl-added">✓ 已自选</span>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="pagination">
          <button class="page-btn" @click="currentPage--" :disabled="currentPage === 1">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
          <button class="page-btn" @click="currentPage++" :disabled="currentPage === totalPages">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
        </div>
      </div>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'
import StockMiniChart from '../components/StockMiniChart.vue'

const router = useRouter()
const watchlistStore = useWatchlistStore()

const tab = ref('all')
const filterType = ref('all')
const searchQuery = ref('')
const sortKey = ref('change_pct')
const sortAsc = ref(false)
const currentPage = ref(1)
const pageSize = 50
const tagFilter = ref('')
const tagEditCode = ref('')
const tagInput = ref('')

const watchlistLoading = ref(false)
const allStocksLoading = ref(false)
const allStocks = ref([])
const isLoading = computed(() => watchlistLoading.value || allStocksLoading.value)

const sortOpts = [
  { key: 'change_pct', label: '涨跌幅' },
  { key: 'price', label: '价格' },
  { key: 'name', label: '名称' },
]

const watchlist = computed(() => watchlistStore.watchlist)
const realtimeData = computed(() => watchlistStore.realtimeData)
const miniChartData = computed(() => watchlistStore.miniChartData)

const filteredAllStocks = computed(() => {
  let stocks = [...allStocks.value]
  
  // 应用筛选
  if (filterType.value === 'gainers') {
    stocks = stocks.filter(s => (s.change_pct ?? 0) > 0).sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0)).slice(0, 100)
  } else if (filterType.value === 'losers') {
    stocks = stocks.filter(s => (s.change_pct ?? 0) < 0).sort((a, b) => (a.change_pct || 0) - (b.change_pct || 0)).slice(0, 100)
  }
  
  // 应用搜索
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase()
    stocks = stocks.filter(s => 
      s.name.toLowerCase().includes(q) || 
      s.code.toLowerCase().includes(q)
    )
  }
  
  return stocks
})

const totalPages = computed(() => Math.ceil(filteredAllStocks.value.length / pageSize))

const paginatedStocks = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredAllStocks.value.slice(start, start + pageSize)
})

const sortedWatchlist = computed(() => {
  let list = [...watchlist.value]
  if (tagFilter.value) {
    list = list.filter(s => (s.tags || []).includes(tagFilter.value))
  }

  if (sortKey.value === 'change_pct') {
    list.sort((a, b) => {
      const aPct = realtimeData.value[a.code]?.change_pct ?? 0
      const bPct = realtimeData.value[b.code]?.change_pct ?? 0
      return sortAsc.value ? aPct - bPct : bPct - aPct
    })
  } else if (sortKey.value === 'price') {
    list.sort((a, b) => {
      const aPrice = realtimeData.value[a.code]?.price ?? 0
      const bPrice = realtimeData.value[b.code]?.price ?? 0
      return sortAsc.value ? aPrice - bPrice : bPrice - aPrice
    })
  } else if (sortKey.value === 'name') {
    list.sort((a, b) => sortAsc.value ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name))
  }
  
  return list
})

function switchTab(t) {
  tab.value = t
  currentPage.value = 1
  if (t === 'all' && allStocks.value.length === 0) {
    loadAllStocks()
  }
}

function setFilter(f) {
  filterType.value = f
  currentPage.value = 1
}

function toggleSort(key) {
  if (sortKey.value === key) {
    sortAsc.value = !sortAsc.value
  } else {
    sortKey.value = key
    sortAsc.value = false
  }
}

function handleSearch() {
  currentPage.value = 1
}

async function loadAllStocks() {
  allStocksLoading.value = true
  try {
    const response = await axios.get('/api/market/all-stocks', {
      params: { page_size: 8000 }
    })
    allStocks.value = response.data.stocks || []
  } catch (error) {
    console.error('Failed to load all stocks:', error)
    allStocks.value = []
  } finally {
    allStocksLoading.value = false
  }
}

async function refreshData() {
  await loadAllStocks()
  await loadWatchlistData()
}

async function loadWatchlistData() {
  if (watchlist.value.length === 0) return
  
  watchlistLoading.value = true
  try {
    await watchlistStore.refreshAll()
    // 走势图按需后台加载（数据源可用时卡片自动出现 sparkline）
    watchlistStore.fetchAllMiniChartData()
  } finally {
    watchlistLoading.value = false
  }
}

function isInWatchlist(code) {
  return watchlistStore.isInWatchlist(code)
}

function addToWatchlist(stock) {
  watchlistStore.addToWatchlist({
    code: stock.code,
    name: stock.name,
  })
}

function removeFromWatchlist(code) {
  if (confirm('确定要移除这只股票吗？')) {
    watchlistStore.removeFromWatchlist(code)
  }
}

function goToDetail(code) {
  router.push(`/stock-detail?symbol=${code}`)
}

// Watchlist functions
function getCurrentPrice(code) {
  const data = realtimeData.value[code]
  if (data && data.price != null) {
    return data.price.toFixed(2)
  }
  return '--'
}

function getChangePercent(code) {
  const data = realtimeData.value[code]
  if (data && data.change_pct != null) {
    const pct = parseFloat(data.change_pct)
    const sign = pct >= 0 ? '+' : ''
    return sign + pct.toFixed(2) + '%'
  }
  return '--'
}

function getPriceClass(code) {
  const data = realtimeData.value[code]
  if (!data || data.change_pct == null) return ''
  return data.change_pct >= 0 ? 'up' : 'down'
}

function getStockColor(code) {
  const data = realtimeData.value[code]
  if (!data || data.change_pct == null) return null
  return data.change_pct >= 0 ? 'red' : 'green'
}

function getChartData(code) {
  return miniChartData.value[code] || []
}

// ── 格式化 ──────────────────────────────────────────────────────────────────
function fmtNum(v) { return v != null ? Number(v).toFixed(1) : '--' }
function fmtPct(v) { return v != null ? Number(v).toFixed(2) + '%' : '--' }
function fmtAmt(v) {
  if (!v) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return String(Math.round(v))
}

// ── 标签编辑 ────────────────────────────────────────────────────────────────
function startTagEdit(code) {
  tagEditCode.value = code
  tagInput.value = ''
}

async function addTag(stock) {
  const t = tagInput.value.trim()
  tagInput.value = ''
  tagEditCode.value = ''
  if (!t) return
  const cur = stock.tags || []
  if (cur.includes(t)) return
  await watchlistStore.setTags(stock.code, [...cur, t])
}

async function removeTag(stock, t) {
  await watchlistStore.setTags(stock.code, (stock.tags || []).filter(x => x !== t))
}

onMounted(async () => {
  // 进入只加载自选股（快）；全部股票切到该 tab 时再懒加载
  await loadWatchlistData()
  watchlistStore.startAutoRefresh(15000)
})

onBeforeUnmount(() => {
  watchlistStore.stopAutoRefresh()
})

watch(tab, (newTab) => {
  if (newTab === 'watchlist') {
    loadWatchlistData()
  }
})
</script>

<style scoped>
.watchlist-page {
  padding: 20px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ── Tab bar ─────────────────────────────────────────────── */
.hub-tabs {
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 3px;
}
.hub-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  border-radius: calc(var(--radius-md) - 2px);
  cursor: pointer;
  transition: all 0.15s;
}
.hub-tab:hover { color: var(--text-1); }
.hub-tab.active {
  background: var(--bg-elevated);
  color: var(--text-1);
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.tab-spacer { flex: 1; }
.btn-refresh {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-2);
  font-size: 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-refresh:hover:not(:disabled) { color: var(--text-1); border-color: var(--border-light); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-refresh .spin { animation: wl-spin 0.9s linear infinite; }
@keyframes wl-spin { to { transform: rotate(360deg); } }

/* ── Panel (card container) ──────────────────────────────── */
.panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 16px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 12px;
}
.panel-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: var(--text-2);
  font-size: 13px;
}
.panel-empty {
  text-align: center;
  padding: 48px 20px;
  color: var(--text-3);
  font-size: 14px;
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
}

.empty-state svg {
  margin-bottom: 16px;
}

.empty-state p {
  margin: 0;
  color: var(--text-2);
}

.watchlist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}

.watchlist-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-1);
  border-radius: 6px;
  margin-bottom: 8px;
}

.search-row svg {
  color: var(--text-3);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  background: none;
  border: none;
  color: var(--text-1);
  font-size: 13px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-3);
}

.filter-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.filter-chip,
.sort-chip {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-chip:hover,
.sort-chip:hover {
  border-color: var(--text-3);
  color: var(--text-2);
}

.filter-chip.active,
.sort-chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}

.sort-chips {
  display: flex;
  gap: 4px;
}

.stock-list {
  display: flex;
  flex-direction: column;
}

.stock-row {
  display: flex;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.2s;
}

.stock-row:last-child {
  border-bottom: none;
}

.stock-row:hover {
  background: var(--bg-1);
  margin: 0 -12px;
  padding-left: 12px;
  padding-right: 12px;
}

.stock-main {
  flex: 1;
  min-width: 0;
}

.stock-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
}

.stock-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-code {
  font-size: 11px;
  color: var(--text-3);
  font-family: 'JetBrains Mono', monospace;
}

.exchange-tag {
  font-size: 10px;
  color: var(--accent);
  background: rgba(230, 57, 70, 0.15);
  padding: 1px 4px;
  border-radius: 3px;
}

.stock-chart {
  margin-top: 4px;
}

.stock-data {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  margin-left: 12px;
}

.stock-price {
  font-size: 14px;
  font-weight: 700;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-1);
}

.stock-price.up {
  color: var(--up);
}

.stock-price.down {
  color: var(--down);
}

.stock-pct {
  font-size: 12px;
  font-weight: 600;
  font-family: 'JetBrains Mono', monospace;
  padding: 2px 6px;
  border-radius: 4px;
}

.stock-pct.up {
  color: var(--up);
  background: rgba(239, 68, 68, 0.15);
}

.stock-pct.down {
  color: var(--down);
  background: rgba(34, 197, 94, 0.15);
}

.remove-btn,
.add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  margin-left: 8px;
  transition: all 0.2s;
}

.remove-btn {
  background: transparent;
  color: var(--text-3);
}

.remove-btn:hover {
  background: rgba(239, 68, 68, 0.15);
  color: var(--down);
}

.add-btn {
  background: var(--accent);
  color: white;
}

.add-btn:hover {
  opacity: 0.8;
}

.added-indicator {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: 8px;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px 0 8px;
}

.page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.page-info {
  font-size: 13px;
  color: var(--text-3);
  font-family: 'JetBrains Mono', monospace;
}

/* ── 卡片网格 ───────────────────────────────────────────────────────────── */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.wl-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: transform 0.16s, border-color 0.16s, box-shadow 0.16s;
}
.wl-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-glow);
  box-shadow: var(--accent-glow);
}

.card-x {
  position: absolute;
  top: 8px; right: 8px;
  width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent;
  color: var(--text-3); border-radius: 5px;
  cursor: pointer; opacity: 0;
  transition: all 0.15s;
}
.wl-card:hover .card-x { opacity: 1; }
.card-x:hover { background: rgba(239,68,68,0.15); color: var(--down); }

.wl-top { display: flex; align-items: baseline; gap: 8px; padding-right: 22px; }
.wl-name {
  font-size: 15px; font-weight: 700; color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.wl-code { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); flex-shrink: 0; }

.wl-price-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wl-price { font-size: 22px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1; }
.wl-price.up { color: var(--up); }
.wl-price.down { color: var(--down); }
.wl-badge { font-size: 13px; font-weight: 700; font-family: var(--font-mono); padding: 3px 8px; border-radius: 6px; flex-shrink: 0; }
.wl-badge.up { color: var(--up); background: rgba(239,68,68,0.14); }
.wl-badge.down { color: var(--down); background: rgba(34,197,94,0.14); }

.wl-spark { height: 40px; overflow: hidden; margin: 0 -2px; }

.wl-meta { display: flex; gap: 12px; font-size: 11px; color: var(--text-2); font-family: var(--font-mono); }

.wl-tags { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.wl-tag {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 11px; color: var(--accent);
  background: var(--accent-dim); border: 1px solid var(--border-light);
  border-radius: 10px; padding: 1px 8px;
}
.tag-x { font-style: normal; cursor: pointer; opacity: 0.55; }
.tag-x:hover { opacity: 1; color: var(--down); }
.tag-add {
  font-size: 11px; color: var(--text-3);
  background: transparent; border: 1px dashed var(--border-light);
  border-radius: 10px; padding: 1px 8px; cursor: pointer; transition: all 0.15s;
}
.tag-add:hover { color: var(--accent); border-color: var(--accent); }
.tag-input {
  width: 72px; font-size: 11px; color: var(--text-1);
  background: var(--bg-base); border: 1px solid var(--accent);
  border-radius: 10px; padding: 1px 8px; outline: none;
}

.wl-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.wl-add { font-size: 12px; color: #fff; background: var(--accent); border: none; border-radius: 6px; padding: 4px 12px; cursor: pointer; transition: background 0.15s; }
.wl-add:hover { background: var(--accent-hover); }
.wl-added { font-size: 11px; color: var(--accent); }

/* ── 标签筛选条 ─────────────────────────────────────────────────────────── */
.tag-filter { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tagf-chip {
  font-size: 12px; color: var(--text-2);
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: 14px; padding: 3px 11px; cursor: pointer; transition: all 0.15s;
}
.tagf-chip:hover { border-color: var(--text-3); color: var(--text-1); }
.tagf-chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.tagf-count { opacity: 0.7; font-size: 10px; }
</style>