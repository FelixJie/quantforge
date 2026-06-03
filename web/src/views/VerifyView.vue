<template>
  <div class="vfy-wrap">

    <!-- ── Tabs ─────────────────────────────────────────────────────── -->
    <div class="tabs-container">
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'ai' }"
        @click="activeTab = 'ai'"
      >
        AI 推荐验证
      </button>
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'watchlist' }"
        @click="activeTab = 'watchlist'"
      >
        自选股验证
      </button>
    </div>

    <!-- ── AI Recommendations Tab ─────────────────────────────────────── -->
    <div v-if="activeTab === 'ai'" class="tab-content">
      <!-- Header -->
      <div class="vfy-header card">
        <div class="hd-row hd-row-top">
          <div class="hd-title">推荐验证</div>
          <div class="hd-right">
            <span v-if="verifyMsg" :class="['vmsg', verifyMsg.type]">{{ verifyMsg.text }}</span>
            <label class="force-label">
              <input type="checkbox" v-model="forceVerify" class="force-cb" />
              <span>强制重验</span>
            </label>
            <button class="btn-verify" @click="triggerVerify" :disabled="verifying">
              {{ verifying ? '验证中…' : '验证选定区间' }}
            </button>
          </div>
        </div>
        <div class="hd-row hd-row-filters">
          <div class="date-range">
            <input type="date" v-model="trackFrom" @change="load" class="date-in" />
            <span class="date-sep">至</span>
            <input type="date" v-model="trackTo"   @change="load" class="date-in" />
          </div>
          <select v-model="filterVerified" @change="load" class="filter-sel">
            <option :value="null">全部状态</option>
            <option :value="false">待验证</option>
            <option :value="true">已验证</option>
          </select>
          <select v-model="filterOutcome" class="filter-sel">
            <option value="">全部结果</option>
            <option value="hit_target">达目标</option>
            <option value="hit_stop">触止损</option>
            <option value="positive">正收益</option>
            <option value="negative">负收益</option>
            <option value="open">进行中</option>
          </select>
          <div class="search-wrap">
            <svg class="search-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input v-model="searchQuery" class="search-in" placeholder="股票名 / 代码" />
            <button v-if="searchQuery" class="search-clear" @click="searchQuery = ''">×</button>
          </div>
        </div>
      </div>

      <div class="stats-section" v-if="predTotal > 0">
        <div class="formula-row">
          <div class="fm-item">
            <span class="fm-val">{{ filteredPredictions.length }}</span>
            <span class="fm-lbl">全部</span>
          </div>
          <span class="fm-eq">=</span>
          <div class="fm-item fm-pending">
            <span class="fm-val">{{ fPendingCount }}</span>
            <span class="fm-lbl">待验证</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item fm-profit">
            <span class="fm-val">{{ fProfitCount }}</span>
            <span class="fm-lbl">正收益</span>
            <span class="fm-sub" v-if="fAvgPosPct != null">均+{{ fAvgPosPct }}%</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item fm-loss">
            <span class="fm-val">{{ fNegCount }}</span>
            <span class="fm-lbl">负收益</span>
            <span class="fm-sub" v-if="fAvgNegPct != null">均{{ fAvgNegPct }}%</span>
          </div>
        </div>
        <div class="formula-row">
          <div class="fm-item fm-profit">
            <span class="fm-val">{{ fProfitCount }}</span>
            <span class="fm-lbl">正收益</span>
          </div>
          <span class="fm-eq">=</span>
          <div class="fm-item fm-hit">
            <span class="fm-val">{{ fHitTarget }}</span>
            <span class="fm-lbl">达目标</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item">
            <span class="fm-val">{{ fProfitCount - fHitTarget }}</span>
            <span class="fm-lbl">未达目标</span>
          </div>
          <div class="fm-divider"></div>
          <div class="fm-item fm-loss">
            <span class="fm-val">{{ fNegCount }}</span>
            <span class="fm-lbl">负收益</span>
          </div>
          <span class="fm-eq">=</span>
          <div class="fm-item fm-stp">
            <span class="fm-val">{{ fHitStop }}</span>
            <span class="fm-lbl">触止损</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item">
            <span class="fm-val">{{ fNegCount - fHitStop }}</span>
            <span class="fm-lbl">未触止损</span>
          </div>
        </div>
        <div class="formula-row">
          <div class="fm-item fm-accent">
            <span class="fm-val">{{ fAccuracy != null ? fAccuracy + '%' : '-' }}</span>
            <span class="fm-lbl">方向准确率</span>
          </div>
          <div class="fm-item" :class="(fAvgChange||0) >= 0 ? 'fm-profit' : 'fm-loss'">
            <span class="fm-val">{{ fAvgChange != null ? (fAvgChange > 0 ? '+' : '') + fAvgChange + '%' : '-' }}</span>
            <span class="fm-lbl">平均涨跌</span>
          </div>
        </div>
      </div>

      <div class="table-card card">
        <div v-if="loading" class="tbl-loading">加载中…</div>
        <table v-else-if="sortedPredictions.length" class="pred-tbl">
          <thead>
            <tr>
              <th class="sortable" @click="toggleSort('date')">
                日期 <span class="sort-icon">{{ sortIcon('date') }}</span>
              </th>
              <th>股票</th>
              <th class="sortable" @click="toggleSort('buy_price')">
                建议价 <span class="sort-icon">{{ sortIcon('buy_price') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('entry_price')">
                开盘价 <span class="sort-icon">{{ sortIcon('entry_price') }}</span>
              </th>
              <th>止损</th>
              <th>目标</th>
              <th class="sortable" @click="toggleSort('actual_close')">
                现价 <span class="sort-icon">{{ sortIcon('actual_close') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('change_pct')">
                涨跌 <span class="sort-icon">{{ sortIcon('change_pct') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('confidence')">
                置信度 <span class="sort-icon">{{ sortIcon('confidence') }}</span>
              </th>
              <th>风险</th>
              <th>结果</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in sortedPredictions" :key="p.id" class="pred-row" @click="openDetail(p)">
              <td class="td-date">{{ p.date }}</td>
              <td class="td-stock">
                <b>{{ p.name }}</b>
                <span class="td-code">{{ p.code }}</span>
              </td>
              <td class="td-mono td-dim">{{ p.buy_price ?? '-' }}</td>
              <td class="td-mono">
                <span v-if="p.entry_price" class="entry-price">{{ p.entry_price }}</span>
                <span v-else class="td-dim">-</span>
              </td>
              <td class="td-stop">
                {{ p.stop_price ?? '-' }}
                <span v-if="p.stop_pct" class="pct-sub pct-loss">(-{{ p.stop_pct.toFixed(1) }}%)</span>
              </td>
              <td class="td-tgt">
                {{ p.target_price ?? '-' }}
                <span v-if="p.target_pct" class="pct-sub pct-profit">(+{{ p.target_pct.toFixed(1) }}%)</span>
              </td>
              <td class="td-mono">
                <template v-if="p.actual_close">
                  <span :class="(changePct(p) ?? 0) >= 0 ? 'td-up' : 'td-dn'">{{ p.actual_close }}</span>
                </template>
                <span v-else class="td-dim">-</span>
              </td>
              <td class="td-mono">
                <template v-if="changePct(p) !== null">
                  <span :class="['pct-chip', (changePct(p) ?? 0) >= 0 ? 'chip-up' : 'chip-dn']">
                    {{ (changePct(p) ?? 0) >= 0 ? '+' : '' }}{{ changePct(p) }}%
                  </span>
                </template>
                <span v-else class="td-dim">-</span>
              </td>
              <td>
                <div class="conf-row">
                  <div class="conf-bar"><div class="conf-fill" :style="{ width: (p.confidence||0)+'%' }"></div></div>
                  <span class="conf-num">{{ p.confidence ?? '-' }}</span>
                </div>
              </td>
              <td><span :class="['risk-badge', 'r-' + (p.risk_level||'中')]">{{ p.risk_level ?? '-' }}</span></td>
              <td>
                <span :class="['out-badge', 'o-' + (p.outcome||'open')]">{{ outLabel(p.outcome) }}</span>
              </td>
              <td class="td-action">
                <span class="detail-link">详情 →</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="predictions.length && !sortedPredictions.length" class="tbl-empty">
          <p>没有匹配的记录</p>
          <p class="sub">调整搜索条件或清除筛选</p>
        </div>
        <div v-else class="tbl-empty">
          <p>暂无预测记录</p>
          <p class="sub">AI 每日精选后自动生成预测记录</p>
        </div>
      </div>
    </div>

    <!-- ── Watchlist Tab ─────────────────────────────────────────────── -->
    <div v-if="activeTab === 'watchlist'" class="tab-content">
      <div class="vfy-header card">
        <div class="hd-row hd-row-top">
          <div class="hd-title">自选股验证</div>
          <div class="hd-right">
            <select v-model="watchlistPeriod" class="filter-sel">
              <option :value="7">7 天</option>
              <option :value="30">30 天</option>
              <option :value="90">90 天</option>
              <option :value="180">180 天</option>
              <option :value="365">365 天</option>
            </select>
            <button class="btn-verify" @click="verifyWatchlist" :disabled="watchlistVerifying || watchlistStore.watchlist.length === 0">
              {{ watchlistVerifying ? '验证中…' : '运行验证' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="watchlistStore.watchlist.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path>
          </svg>
        </div>
        <h3>还没有自选股</h3>
        <p>先去添加一些股票到自选股</p>
        <button class="btn-verify" @click="goToWatchlist">去添加</button>
      </div>

      <div v-else class="results-section">
        <div v-if="watchlistStore.watchlistVerifications.length > 0" class="result-card">
          <div class="result-header">
            <div>
              <h3>最近验证</h3>
              <p class="result-meta">{{ formatDate(watchlistStore.watchlistVerifications[0].createdAt) }}</p>
            </div>
            <div class="total-return">
              <span class="return-label">平均收益</span>
              <span class="return-value" :class="getReturnClass(watchlistStore.watchlistVerifications[0].totalReturn)">
                {{ watchlistStore.watchlistVerifications[0].totalReturn }}%
              </span>
            </div>
          </div>
          <div class="result-table">
            <table>
              <thead>
                <tr>
                  <th>股票</th>
                  <th>期初价</th>
                  <th>期末价</th>
                  <th>涨跌</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in watchlistStore.watchlistVerifications[0].results" :key="item.code">
                  <td>
                    <span class="stock-code">{{ item.code }}</span>
                    <span class="stock-name">{{ item.name }}</span>
                  </td>
                  <td>{{ item.startPrice.toFixed(2) }}</td>
                  <td>{{ item.endPrice.toFixed(2) }}</td>
                  <td>
                    <span class="change-value" :class="getReturnClass(item.changePercent)">
                      {{ item.changePercent > 0 ? '+' : '' }}{{ item.changePercent }}%
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-if="watchlistStore.watchlistVerifications.length > 1" class="history-section">
          <h3 class="section-title">历史验证</h3>
          <div class="history-list">
            <div 
              v-for="verification in watchlistStore.watchlistVerifications.slice(1)" 
              :key="verification.id" 
              class="history-item"
            >
              <div class="history-info">
                <span class="history-date">{{ formatDate(verification.createdAt) }}</span>
                <span class="history-period">{{ verification.periodDays }} 天</span>
              </div>
              <div class="history-return">
                <span class="return-label">平均收益</span>
                <span class="return-value" :class="getReturnClass(verification.totalReturn)">
                  {{ verification.totalReturn }}%
                </span>
              </div>
              <button class="btn-remove" @click="removeVerification(verification.id)" title="删除">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'

const router = useRouter()
const watchlistStore = useWatchlistStore()

// Tab state
const activeTab = ref('ai')

// ── AI Picks State ─────────────────────────────────────────────────────────────
const predictions    = ref([])
const stats          = ref({})
const predTotal      = ref(0)
const loading        = ref(false)
const verifying      = ref(false)
const verifyMsg      = ref(null)
const forceVerify    = ref(false)
const filterVerified = ref(null)
const filterOutcome  = ref('')
const searchQuery    = ref('')

const today     = new Date()
const thirtyAgo = new Date(today); thirtyAgo.setDate(thirtyAgo.getDate() - 30)
const future    = new Date(today); future.setDate(future.getDate() + 30)
const trackFrom = ref(thirtyAgo.toISOString().slice(0, 10))
const trackTo   = ref(future.toISOString().slice(0, 10))

const sortKey = ref('date')
const sortDir = ref('desc')

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'date' ? 'desc' : 'desc'
  }
}

function sortIcon(key) {
  if (sortKey.value !== key) return '⇅'
  return sortDir.value === 'asc' ? '↑' : '↓'
}

async function load() {
  loading.value = true
  try {
    const params = { limit: 300, date_from: trackFrom.value, date_to: trackTo.value }
    if (filterVerified.value !== null) params.verified = filterVerified.value
    const [pr, sr] = await Promise.all([
      axios.get('/api/predictions/', { params }),
      axios.get('/api/predictions/stats', { params: { date_from: trackFrom.value, date_to: trackTo.value } }),
    ])
    predictions.value = pr.data.predictions
    predTotal.value   = pr.data.total
    stats.value       = sr.data
  } finally {
    loading.value = false
  }
}

async function triggerVerify() {
  verifying.value = true; verifyMsg.value = null
  try {
    const res = await axios.post('/api/predictions/verify', {
      date_from: trackFrom.value,
      date_to: trackTo.value,
      force: forceVerify.value,
    })
    verifyMsg.value = { type: 'ok', text: res.data.message }
    setTimeout(() => { load(); setTimeout(() => { verifyMsg.value = null }, 2000) }, 3000)
  } catch (e) {
    verifyMsg.value = { type: 'err', text: e.response?.data?.detail || '验证失败' }
  } finally {
    verifying.value = false
  }
}

const filteredPredictions = computed(() => {
  let list = predictions.value
  if (filterOutcome.value) {
    if (filterOutcome.value === 'open') {
      list = list.filter(p => !['hit_target', 'hit_stop', 'positive', 'negative'].includes(p.outcome))
    } else {
      list = list.filter(p => p.outcome === filterOutcome.value)
    }
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(p =>
      (p.name || '').toLowerCase().includes(q) ||
      (p.code || '').includes(q)
    )
  }
  return list
})

const numericKeys = new Set(['buy_price', 'entry_price', 'actual_close', 'confidence', 'change_pct'])

const sortedPredictions = computed(() => {
  const list = [...filteredPredictions.value]
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  const isNumeric = numericKeys.has(key)

  list.sort((a, b) => {
    let va, vb
    if (key === 'change_pct') {
      va = parseFloat(changePct(a)) || -9999
      vb = parseFloat(changePct(b)) || -9999
    } else if (isNumeric) {
      va = parseFloat(a[key]) || -9999
      vb = parseFloat(b[key]) || -9999
    } else {
      va = a[key] ?? ''
      vb = b[key] ?? ''
    }
    if (va < vb) return -1 * dir
    if (va > vb) return 1 * dir
    return 0
  })
  return list
})

const fPendingCount = computed(() => filteredPredictions.value.filter(p => !p.verified).length)
const fOpenCount = computed(() => filteredPredictions.value.filter(p => p.verified && !['hit_target', 'hit_stop'].includes(p.outcome)).length)
const fProfitCount = computed(() => filteredPredictions.value.filter(p => ['hit_target', 'positive', 'neutral'].includes(p.outcome)).length)
const fNegCount    = computed(() => filteredPredictions.value.filter(p => ['hit_stop', 'negative'].includes(p.outcome)).length)
const fHitTarget   = computed(() => filteredPredictions.value.filter(p => p.outcome === 'hit_target').length)
const fHitStop     = computed(() => filteredPredictions.value.filter(p => p.outcome === 'hit_stop').length)

const fAccuracy = computed(() => {
  const verified = filteredPredictions.value.filter(p => p.verified)
  if (!verified.length) return null
  const pos = verified.filter(p => ['hit_target', 'positive', 'neutral'].includes(p.outcome)).length
  return (pos / verified.length * 100).toFixed(1)
})

const fAvgChange = computed(() => {
  const changes = filteredPredictions.value
    .filter(p => p.actual_change_pct != null)
    .map(p => p.actual_change_pct)
  if (!changes.length) return null
  return (changes.reduce((a, b) => a + b, 0) / changes.length).toFixed(2)
})

const fAvgPosPct = computed(() => {
  const vals = filteredPredictions.value
    .filter(p => p.actual_change_pct != null && p.actual_change_pct > 0)
    .map(p => p.actual_change_pct)
  if (!vals.length) return null
  return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2)
})

const fAvgNegPct = computed(() => {
  const vals = filteredPredictions.value
    .filter(p => p.actual_change_pct != null && p.actual_change_pct < 0)
    .map(p => p.actual_change_pct)
  if (!vals.length) return null
  return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2)
})

function openDetail(p) {
  sessionStorage.setItem('verifyPred', JSON.stringify(p))
  router.push('/verify-detail')
}

function outLabel(o) {
  return { hit_target:'达目标', hit_stop:'触止损', positive:'正收益', negative:'负收益', neutral:'持平', open:'待验证' }[o] || '待验证'
}

function changePct(p) {
  const basis = p.entry_price || p.buy_price
  if (!p.actual_close || !basis || basis <= 0) return null
  return ((p.actual_close - basis) / basis * 100).toFixed(1)
}

// ── Watchlist Verification State ──────────────────────────────────────────────
const watchlistPeriod = ref(30)
const watchlistVerifying = ref(false)

async function verifyWatchlist() {
  if (watchlistVerifying.value || watchlistStore.watchlist.length === 0) return
  watchlistVerifying.value = true
  try {
    await watchlistStore.verifyWatchlist(watchlistPeriod.value)
  } catch (e) {
    console.error('Watchlist verification failed:', e)
    alert('验证失败，请稍后重试')
  } finally {
    watchlistVerifying.value = false
  }
}

function removeVerification(id) {
  if (confirm('确定要删除这条验证记录吗？')) {
    watchlistStore.removeVerification(id)
  }
}

function goToWatchlist() {
  router.push('/watchlist')
}

function formatDate(dateStr) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getReturnClass(value) {
  const num = parseFloat(value)
  if (num > 0) return 'positive'
  if (num < 0) return 'negative'
  return 'neutral'
}

onMounted(() => { load() })
</script>

<style scoped>
.vfy-wrap { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }

/* Tabs */
.tabs-container {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  background: var(--bg-surface);
  padding: 4px;
  border-radius: 8px;
  width: fit-content;
}

.tab-btn {
  padding: 10px 20px;
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.tab-btn:hover {
  background: var(--bg-hover);
}

.tab-btn.active {
  background: var(--accent);
  color: white;
}

.tab-content {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Header */
.vfy-header { padding: 10px 14px 8px; display: flex; flex-direction: column; gap: 8px; }
.hd-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hd-row-top { justify-content: space-between; }
.hd-row-filters { flex-wrap: wrap; }
.hd-right { display: flex; align-items: center; gap: 8px; }
.hd-title { font-size: 13px; font-weight: 700; color: var(--text-1); letter-spacing: 0.03em; }

.date-in  { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 4px 7px; font-size: 11px; }
.date-sep { font-size: 11px; color: var(--text-3); }
.filter-sel { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 4px 7px; font-size: 11px; }

.force-label { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-3); cursor: pointer; user-select: none; }
.force-cb { width: 12px; height: 12px; accent-color: var(--accent); cursor: pointer; }

.vmsg { font-size: 12px; padding: 4px 10px; border-radius: 6px; }
.vmsg.ok  { background: #14532d33; color: #4ade80; }
.vmsg.err { background: #7f1d1d33; color: #fca5a5; }

.btn-verify { background: var(--accent); color: #fff; border: none; border-radius: var(--radius-sm); padding: 5px 13px; font-size: 11px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; letter-spacing: 0.02em; }
.btn-verify:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-verify:hover:not(:disabled) { opacity: 0.85; }

/* Stats — formula rows */
.stats-section { display: flex; flex-direction: column; gap: 4px; }
.formula-row {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  background: var(--bg-glass); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 6px 12px;
}
.fm-item { display: flex; flex-direction: column; align-items: center; min-width: 48px; padding: 2px 6px; }
.fm-val { font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1.2; }
.fm-lbl { font-size: 9px; color: var(--text-3); letter-spacing: 0.04em; margin-top: 1px; }
.fm-sub { font-size: 9px; font-family: var(--font-mono); color: var(--text-3); }
.fm-eq, .fm-op { font-size: 14px; font-weight: 600; color: var(--text-3); font-family: var(--font-mono); }
.fm-divider { width: 1px; height: 28px; background: var(--border-light); margin: 0 6px; flex-shrink: 0; }
.fm-pending .fm-val { color: #fbbf24; }
.fm-profit .fm-val  { color: #ef4444; }
.fm-loss .fm-val    { color: #22c55e; }
.fm-hit .fm-val     { color: #ef4444; }
.fm-stp .fm-val     { color: #22c55e; }
.fm-accent .fm-val  { color: var(--accent); }

/* Table card */
.table-card { overflow: visible; padding: 0; }
.pred-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.pred-tbl th {
  background: var(--bg-elevated); color: var(--text-3); font-weight: 600; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.06em; padding: 7px 8px; text-align: left;
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.pred-tbl td { padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-1); overflow: visible; }
.pred-tbl tr:last-child td { border-bottom: none; }
.pred-row { cursor: pointer; transition: background 0.1s; }
.pred-row:hover { background: var(--bg-hover); }

.sortable { cursor: pointer; user-select: none; transition: color 0.12s; }
.sortable:hover { color: var(--accent); }
.sort-icon { font-size: 10px; opacity: 0.6; margin-left: 2px; }

.td-date { font-size: 11px; color: var(--text-3); white-space: nowrap; font-family: var(--font-mono); }
.td-stock b { font-weight: 700; }
.td-code { font-size: 11px; color: var(--text-3); margin-left: 5px; font-family: var(--font-mono); }
.td-mono { font-family: var(--font-mono); }
.td-stop { color: #22c55e; font-family: var(--font-mono); white-space: nowrap; }
.td-tgt  { color: #ef4444; font-family: var(--font-mono); white-space: nowrap; }
.td-up { color: #ef4444; font-weight: 600; font-family: var(--font-mono); }
.td-dn { color: #22c55e; font-weight: 600; font-family: var(--font-mono); }
.td-dim { color: var(--text-3); font-family: var(--font-mono); }
.pct-sub { font-size: 10px; opacity: 0.75; font-family: var(--font-mono); margin-left: 2px; }
.pct-profit { color: #ef4444; }
.pct-loss   { color: #22c55e; }

.entry-price { color: var(--cyan); font-family: var(--font-mono); font-weight: 600; }

.search-wrap {
  position: relative; display: flex; align-items: center;
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 0 7px; gap: 4px;
  min-width: 150px;
}
.search-icon { color: var(--text-3); flex-shrink: 0; }
.search-in {
  background: none; border: none; outline: none;
  color: var(--text-1); font-size: 11px; padding: 4px 0;
  width: 120px;
}
.search-in::placeholder { color: var(--text-3); }
.search-clear {
  background: none; border: none; color: var(--text-3); cursor: pointer;
  font-size: 13px; line-height: 1; padding: 0; flex-shrink: 0;
}
.search-clear:hover { color: var(--text-1); }

.pct-chip { display: inline-block; font-size: 10px; padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-weight: 600; }
.pct-chip.chip-up { background: #ef444422; color: #ef4444; }
.pct-chip.chip-dn { background: #22c55e22; color: #22c55e; }

.conf-row { display: flex; align-items: center; gap: 6px; }
.conf-bar { flex: 1; height: 4px; background: var(--border); border-radius: 2px; min-width: 40px; }
.conf-fill { height: 100%; background: var(--accent); border-radius: 2px; }
.conf-num { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); min-width: 20px; text-align: right; }

.risk-badge { padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.r-低 { background: #14532d33; color: #4ade80; }
.r-中 { background: #78350f33; color: #fbbf24; }
.r-高 { background: #7f1d1d33; color: #f87171; }

.out-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.o-hit_target { background: #ef444422; color: #ef4444; }
.o-positive   { background: #ef444418; color: #f87171; }
.o-hit_stop   { background: #22c55e22; color: #22c55e; }
.o-negative   { background: #22c55e18; color: #4ade80; }
.o-neutral    { background: var(--bg-elevated); color: var(--text-2); }
.o-open       { background: var(--bg-elevated); color: var(--text-3); }

.tbl-loading, .tbl-empty { padding: 40px; text-align: center; color: var(--text-3); }
.tbl-empty .sub { font-size: 12px; margin-top: 6px; }

.td-action { text-align: right; }
.detail-link {
  font-size: 11px; color: var(--accent); cursor: pointer;
  opacity: 0.7; white-space: nowrap; transition: opacity 0.12s;
}
.pred-row:hover .detail-link { opacity: 1; }

/* Watchlist Tab Styles */
.empty-state {
  text-align: center;
  padding: 60px 24px;
  background: var(--bg-surface);
  border: 1px dashed var(--border);
  border-radius: 12px;
}

.empty-icon {
  color: var(--text-4);
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0 0 8px;
}

.empty-state p {
  font-size: 13px;
  color: var(--text-3);
  margin: 0 0 16px;
}

.results-section {
  margin-top: 16px;
}

.result-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 20px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(61,142,248,0.04), transparent);
}

.result-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 4px;
}

.result-meta {
  font-size: 12px;
  color: var(--text-3);
  margin: 0;
}

.total-return {
  text-align: right;
}

.return-label {
  display: block;
  font-size: 10px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.return-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.return-value.positive {
  color: var(--success);
}

.return-value.negative {
  color: var(--danger);
}

.return-value.neutral {
  color: var(--text-2);
}

.result-table {
  padding: 0 20px 20px;
}

.result-table table {
  width: 100%;
  border-collapse: collapse;
}

.result-table thead {
  background: var(--bg-base);
}

.result-table th {
  padding: 12px 14px;
  text-align: left;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border);
}

.result-table td {
  padding: 12px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}

.result-table tbody tr:last-child td {
  border-bottom: none;
}

.stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-1);
  margin-right: 8px;
}

.stock-name {
  color: var(--text-3);
  font-size: 12px;
}

.change-value {
  font-family: var(--font-mono);
  font-weight: 600;
}

.change-value.positive {
  color: var(--success);
}

.change-value.negative {
  color: var(--danger);
}

.history-section {
  margin-top: 24px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0 0 12px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.history-info {
  display: flex;
  gap: 12px;
  align-items: center;
}

.history-date {
  font-size: 13px;
  color: var(--text-2);
  font-weight: 500;
}

.history-period {
  font-size: 12px;
  color: var(--text-3);
  background: var(--bg-base);
  padding: 2px 8px;
  border-radius: 4px;
}

.history-return {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-remove {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.15s;
}

.btn-remove:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}

@media (max-width: 600px) {
  .vfy-wrap { padding: 12px; }
  .stats-row .sc { min-width: 65px; padding: 8px 10px; }
  .sc-val { font-size: 16px; }
}
</style>
