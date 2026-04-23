<template>
  <div class="vfy-wrap">

    <!-- ── Header ─────────────────────────────────────────────────────── -->
    <div class="vfy-header card">
      <!-- Row 1: title + verify -->
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
      <!-- Row 2: filters -->
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

    <!-- ── Stats bar ──────────────────────────────────────────────────── -->
    <div class="stats-section" v-if="predTotal > 0">
      <!-- Line 1: 总数 = 待验证 + 正收益 + 负收益 -->
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
      <!-- Line 2: 正收益 = 达目标 + 其他正  |  负收益 = 触止损 + 其他负 -->
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
      <!-- Line 3: 准确率 + 平均涨跌 -->
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

    <!-- ── Prediction table ──────────────────────────────────────────── -->
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
            <!-- AI建议价 -->
            <td class="td-mono td-dim">{{ p.buy_price ?? '-' }}</td>
            <!-- 当日实际开盘价（成本基准） -->
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
            <!-- 现价 -->
            <td class="td-mono">
              <template v-if="p.actual_close">
                <span :class="(changePct(p) ?? 0) >= 0 ? 'td-up' : 'td-dn'">{{ p.actual_close }}</span>
              </template>
              <span v-else class="td-dim">-</span>
            </td>
            <!-- 涨跌幅 -->
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
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()

// ── State ─────────────────────────────────────────────────────────────────────
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
const trackFrom = ref(thirtyAgo.toISOString().slice(0, 10))
const trackTo   = ref(today.toISOString().slice(0, 10))

// ── Sorting ──────────────────────────────────────────────────────────────────
const sortKey = ref('date')
const sortDir = ref('desc')  // 'asc' | 'desc'

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

// ── Load predictions ──────────────────────────────────────────────────────────
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

// ── Filtering ──────────────────────────────────────────────────────────────────

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

// Numeric sort keys — compare as numbers, not strings
const numericKeys = new Set(['buy_price', 'entry_price', 'actual_close', 'confidence', 'change_pct'])

// Sorted predictions (after filtering)
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

// ── Stats (computed from filteredPredictions) ────────────────────────────────
// 待验证 = 未验证
const fPendingCount = computed(() => filteredPredictions.value.filter(p => !p.verified).length)
// 进行中 = 已验证，但未达目标也未触止损（outcome: positive/negative/neutral）
const fOpenCount = computed(() => filteredPredictions.value.filter(p => p.verified && !['hit_target', 'hit_stop'].includes(p.outcome)).length)
// 已完结 = 达目标 + 触止损
const fDoneCount   = computed(() => filteredPredictions.value.filter(p => p.outcome === 'hit_target' || p.outcome === 'hit_stop').length)
// 正收益 = hit_target + positive + neutral(持平归入正)
const fProfitCount = computed(() => filteredPredictions.value.filter(p => ['hit_target', 'positive', 'neutral'].includes(p.outcome)).length)
// 负收益 = hit_stop + negative
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

// ── Navigate to detail page ───────────────────────────────────────────────────
function openDetail(p) {
  sessionStorage.setItem('verifyPred', JSON.stringify(p))
  router.push('/verify-detail')
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function outLabel(o) {
  return { hit_target:'达目标', hit_stop:'触止损', positive:'正收益', negative:'负收益', neutral:'持平', open:'待验证' }[o] || '待验证'
}

function changePct(p) {
  const basis = p.entry_price || p.buy_price
  if (!p.actual_close || !basis || basis <= 0) return null
  return ((p.actual_close - basis) / basis * 100).toFixed(1)
}

onMounted(() => { load() })
</script>

<style scoped>
.vfy-wrap { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }

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

/* Sortable headers */
.sortable { cursor: pointer; user-select: none; transition: color 0.12s; }
.sortable:hover { color: var(--accent); }
.sort-icon { font-size: 10px; opacity: 0.6; margin-left: 2px; }

.td-date { font-size: 11px; color: var(--text-3); white-space: nowrap; font-family: var(--font-mono); }
.td-stock b { font-weight: 700; }
.td-code { font-size: 11px; color: var(--text-3); margin-left: 5px; font-family: var(--font-mono); }
.td-mono { font-family: var(--font-mono); }
/* A-share: red=涨, green=跌 */
.td-stop { color: #22c55e; font-family: var(--font-mono); white-space: nowrap; }
.td-tgt  { color: #ef4444; font-family: var(--font-mono); white-space: nowrap; }
.td-up { color: #ef4444; font-weight: 600; font-family: var(--font-mono); }
.td-dn { color: #22c55e; font-weight: 600; font-family: var(--font-mono); }
.td-dim { color: var(--text-3); font-family: var(--font-mono); }
.pct-sub { font-size: 10px; opacity: 0.75; font-family: var(--font-mono); margin-left: 2px; }
.pct-profit { color: #ef4444; }
.pct-loss   { color: #22c55e; }

.entry-price { color: var(--cyan); font-family: var(--font-mono); font-weight: 600; }

/* Search bar */
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

@media (max-width: 600px) {
  .vfy-wrap { padding: 12px; }
  .stats-row .sc { min-width: 65px; padding: 8px 10px; }
  .sc-val { font-size: 16px; }
}
</style>
