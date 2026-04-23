<template>
  <div class="ai-picks-wrap">

    <!-- ── Header ─────────────────────────────────────────────── -->
    <div class="picks-header">
      <div class="header-left">
        <div class="ai-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          AI 每日精选
        </div>
      </div>
      <div class="header-right">
        <button class="btn-history" :class="{ active: showHistory }" @click="showHistory = !showHistory">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          历史记录
        </button>
        <button class="btn-refresh" @click="refresh(true)" :disabled="refreshing || status?.running">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" :class="{ spin: refreshing || status?.running }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          {{ refreshing || status?.running ? '分析中...' : '重新分析' }}
        </button>
      </div>
    </div>

    <!-- History panel -->
    <div v-if="showHistory" class="history-panel">
      <div class="history-title">历史推荐记录</div>
      <div v-if="!history.length" class="history-empty">暂无历史记录</div>
      <div v-else class="history-list">
        <div
          v-for="h in history" :key="h.date"
          class="history-item"
          :class="{ active: h.date === data?.date }"
          @click="loadDate(h.date)"
        >
          <span class="h-date">{{ formatDate(h.date) }}</span>
          <span class="h-count">{{ h.pick_count }} 只</span>
          <span class="h-summary">{{ h.market_summary?.slice(0, 30) }}...</span>
        </div>
      </div>
    </div>

    <!-- Loading / Error -->
    <div v-if="loading" class="state-card">
      <div class="loading-ring"></div>
      <div class="state-text">AI 正在深度分析候选股票，请稍候...</div>
      <div class="state-sub">首次生成约需 30-60 秒</div>
    </div>
    <div v-else-if="error" class="state-card error">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <div class="state-text">{{ error }}</div>
      <button class="btn-refresh" @click="load()">重试</button>
    </div>

    <!-- Refresh banner -->
    <div v-if="bgRefreshMsg" class="refresh-banner">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      {{ bgRefreshMsg }}
      <button class="banner-close" @click="bgRefreshMsg = ''">×</button>
    </div>

    <template v-if="!loading && !error && data">
      <div class="header-meta">
        <span class="meta-date">{{ formatDate(data.date) }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-time">生成于 {{ formatTime(data.generated_at) }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-count">从 {{ data.candidate_count }} 只候选中精选</span>
      </div>

      <!-- Market summary -->
      <div class="market-summary">
        <div class="summary-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        </div>
        <div class="summary-text">{{ data.market_summary }}</div>
      </div>

      <div class="op-strategy" v-if="data.operation_strategy">
        <span class="op-label">操作策略</span>
        <span class="op-text">{{ data.operation_strategy }}</span>
      </div>

      <!-- Picks grid -->
      <div class="picks-grid">
        <div
          v-for="pick in data.picks" :key="pick.code"
          class="pick-card"
          :class="'risk-' + (pick.risk_level || '中')"
        >
          <div class="card-head">
            <div class="card-rank">#{{ pick.rank }}</div>
            <div class="card-stock">
              <div class="stock-name">{{ pick.name }}</div>
              <div class="stock-code">{{ pick.code }}</div>
            </div>
            <div class="card-tags">
              <span class="tag-sector" v-if="pick.sector">{{ pick.sector }}</span>
              <span :class="['tag-risk', 'risk-' + (pick.risk_level || '中')]">{{ pick.risk_level || '中' }}险</span>
            </div>
          </div>

          <div class="card-price" v-if="pick.price || pick.change_pct !== undefined">
            <span class="price-val" v-if="pick.price">¥{{ pick.price?.toFixed(2) }}</span>
            <span v-if="pick.change_pct !== undefined && pick.change_pct !== null" :class="['price-change', pick.change_pct >= 0 ? 'up' : 'down']">
              {{ pick.change_pct >= 0 ? '+' : '' }}{{ pick.change_pct?.toFixed(2) }}%
            </span>
            <div class="price-meta">
              <span v-if="pick.pe">PE {{ pick.pe?.toFixed(1) }}</span>
              <span v-if="pick.pb">PB {{ pick.pb?.toFixed(2) }}</span>
            </div>
          </div>

          <div class="card-reason">{{ pick.reason }}</div>

          <div class="card-signals" v-if="pick.signals?.length">
            <span v-for="sig in pick.signals" :key="sig" class="signal-tag">{{ sig }}</span>
          </div>

          <div class="card-strats" v-if="pick.hit_strategies?.length">
            <span v-for="s in pick.hit_strategies.slice(0,3)" :key="s.key" class="strat-chip"
              :style="{ borderColor: s.color + '66', color: s.color }">{{ s.name }}</span>
          </div>

          <div class="card-price-levels" v-if="pick.buy_price || pick.stop_price || pick.target_price">
            <div class="pl-item pl-buy" v-if="pick.buy_price"><div class="pl-lbl">买入价</div><div class="pl-val">{{ pick.buy_price }}</div></div>
            <div class="pl-item pl-stop" v-if="pick.stop_price"><div class="pl-lbl">止损价</div><div class="pl-val">{{ pick.stop_price }}</div></div>
            <div class="pl-item pl-target" v-if="pick.target_price"><div class="pl-lbl">目标价</div><div class="pl-val">{{ pick.target_price }}</div></div>
          </div>

          <div class="card-checklist" v-if="pick.checklist?.length">
            <div class="checklist-title">操作前置条件</div>
            <div v-for="item in pick.checklist" :key="item" class="checklist-item">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              {{ item }}
            </div>
          </div>

          <div class="card-targets">
            <div class="target-item target-up">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
              目标 +{{ pick.target_pct }}%
            </div>
            <div class="target-sep"></div>
            <div class="target-item target-down">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
              止损 -{{ pick.stop_pct }}%
            </div>
            <div class="target-sep"></div>
            <div class="target-item target-period">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/></svg>
              {{ pick.holding_period || '1-2周' }}
            </div>
          </div>

          <div class="card-confidence">
            <div class="conf-label"><span>AI 置信度</span><span class="conf-val">{{ pick.confidence }}%</span></div>
            <div class="conf-bar"><div class="conf-fill" :style="{ width: pick.confidence + '%', background: confidenceColor(pick.confidence) }"></div></div>
          </div>

          <div class="card-actions">
            <router-link :to="'/market?symbol=' + pick.code" class="act-btn act-chart">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
              K线
            </router-link>
            <router-link :to="'/backtest?symbols=' + pick.code" class="act-btn act-backtest">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6l1 9H8L9 3z"/><path d="M6.1 15a3 3 0 0 0 2.19 5h7.42a3 3 0 0 0 2.19-5L15 12H9L6.1 15z"/></svg>
              回测
            </router-link>
            <router-link :to="'/live?symbol=' + pick.code" class="act-btn act-live">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
              模拟
            </router-link>
          </div>
        </div>
      </div>

      <div class="disclaimer">⚠️ 以上内容由 AI 模型基于量化因子数据分析生成，仅供参考，不构成投资建议。</div>
    </template>

  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const data = ref(null)
const loading = ref(false)
const error = ref('')
const refreshing = ref(false)
const bgRefreshMsg = ref('')
const showHistory = ref(false)
const history = ref([])
const status = ref(null)
let pollTimer = null

async function load(dateKey) {
  loading.value = true; error.value = ''
  try {
    const url = dateKey ? `/api/ai-picks/history-date/${dateKey}` : '/api/ai-picks/daily'
    const res = await axios.get(url)
    data.value = res.data
  } catch (e) {
    error.value = e.response?.data?.detail || '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function loadDate(dateKey) {
  await load(dateKey)
  showHistory.value = false
}

async function loadHistory() {
  try {
    const res = await axios.get('/api/ai-picks/history')
    history.value = res.data.history || []
  } catch {}
}

async function loadStatus() {
  try {
    const res = await axios.get('/api/ai-picks/status')
    status.value = res.data
    return res.data
  } catch {}
}

async function refresh(force = false) {
  refreshing.value = true; bgRefreshMsg.value = ''
  try {
    const res = await axios.post(`/api/ai-picks/refresh?force=${force}`)
    const s = res.data.status
    if (s === 'fresh') { bgRefreshMsg.value = '今日推荐已是最新，无需重新生成'; refreshing.value = false; return }
    if (s === 'started') {
      bgRefreshMsg.value = 'AI 正在后台分析中，约 30-60 秒后自动刷新'
      pollTimer = setInterval(async () => {
        const st = await loadStatus()
        if (st && !st.running && st.has_today) {
          clearInterval(pollTimer); pollTimer = null; refreshing.value = false
          bgRefreshMsg.value = '✅ AI 分析完成！'
          await load(); await loadHistory()
        }
      }, 5000)
    }
  } catch (e) {
    bgRefreshMsg.value = e.response?.data?.detail || '启动分析失败'
    refreshing.value = false
  }
}

function confidenceColor(v) {
  if (v >= 80) return '#22c55e'
  if (v >= 60) return '#3b82f6'
  if (v >= 40) return '#f59e0b'
  return '#ef4444'
}

function formatDate(s) {
  if (!s) return ''
  const [y, m, d] = s.split('-')
  return `${y}年${parseInt(m)}月${parseInt(d)}日`
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

onMounted(async () => {
  await Promise.all([load(), loadHistory(), loadStatus()])
})

onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.ai-picks-wrap { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; min-height: 100%; }

/* Header */
.picks-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.header-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ai-badge { display: flex; align-items: center; gap: 6px; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; font-size: 13px; font-weight: 600; padding: 5px 12px; border-radius: 20px; }
.header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.header-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); }
.meta-sep { color: var(--border); }

/* Buttons */
.btn-history { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-2); font-size: 12px; cursor: pointer; }
.btn-history:hover, .btn-history.active { border-color: var(--accent); color: var(--accent); }
.btn-refresh { display: flex; align-items: center; gap: 5px; padding: 6px 14px; border-radius: var(--radius-md); border: none; background: var(--accent); color: #fff; font-size: 12px; font-weight: 500; cursor: pointer; }
.btn-refresh:disabled { opacity: 0.5; cursor: default; }

@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

/* History panel */
.history-panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; }
.history-title { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 10px; }
.history-empty { font-size: 12px; color: var(--text-3); }
.history-list { display: flex; flex-direction: column; gap: 4px; }
.history-item { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: var(--radius-md); cursor: pointer; font-size: 12px; }
.history-item:hover { background: var(--bg-hover); }
.history-item.active { background: var(--accent-dim); }
.h-date { color: var(--text-1); font-weight: 500; white-space: nowrap; }
.h-count { color: var(--accent); font-weight: 600; white-space: nowrap; }
.h-summary { color: var(--text-3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* States */
.state-card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px 24px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.state-text { font-size: 14px; color: var(--text-1); font-weight: 500; }
.state-sub { font-size: 12px; color: var(--text-3); }
@keyframes ring { to { transform: rotate(360deg); } }
.loading-ring { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: #6366f1; border-radius: 50%; animation: ring 0.8s linear infinite; }
.refresh-banner { display: flex; align-items: center; gap: 8px; background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3); color: #818cf8; border-radius: var(--radius-md); padding: 8px 14px; font-size: 12px; }
.banner-close { margin-left: auto; background: none; border: none; color: inherit; cursor: pointer; font-size: 16px; line-height: 1; }

/* Market summary */
.market-summary { display: flex; align-items: flex-start; gap: 10px; background: linear-gradient(135deg, rgba(99,102,241,0.08), rgba(139,92,246,0.08)); border: 1px solid rgba(99,102,241,0.2); border-radius: var(--radius-lg); padding: 14px 16px; color: #a5b4fc; }
.summary-icon { margin-top: 1px; flex-shrink: 0; }
.summary-text { font-size: 13px; line-height: 1.6; }

.op-strategy { display: flex; align-items: center; gap: 8px; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); border-radius: var(--radius-md); padding: 8px 14px; }
.op-label { font-size: 11px; font-weight: 700; color: #f59e0b; white-space: nowrap; }
.op-text { font-size: 12px; color: var(--text-1); }

/* Picks grid */
.picks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }

.pick-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.15s; }
.pick-card:hover { border-color: var(--accent); }

.card-head { display: flex; align-items: flex-start; gap: 10px; }
.card-rank { font-size: 11px; font-weight: 700; color: var(--text-3); background: var(--bg-hover); padding: 2px 7px; border-radius: 10px; white-space: nowrap; }
.card-stock { flex: 1; }
.stock-name { font-size: 14px; font-weight: 700; color: var(--text-1); }
.stock-code { font-size: 11px; color: var(--text-3); margin-top: 2px; font-family: var(--font-mono); }
.card-tags { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.tag-sector { font-size: 10px; color: var(--text-3); background: var(--bg-hover); padding: 2px 6px; border-radius: 6px; }
.tag-risk { font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 600; }
.risk-低 .tag-risk.risk-低, .tag-risk.risk-低 { background: rgba(34,197,94,0.15); color: #4ade80; }
.risk-中 .tag-risk.risk-中, .tag-risk.risk-中 { background: rgba(245,158,11,0.15); color: #fbbf24; }
.risk-高 .tag-risk.risk-高, .tag-risk.risk-高 { background: rgba(239,68,68,0.15); color: #f87171; }

.card-price { display: flex; align-items: center; gap: 8px; }
.price-val { font-size: 18px; font-weight: 700; color: var(--text-1); }
.price-change { font-size: 13px; font-weight: 600; }
.price-change.up { color: #ef4444; }
.price-change.down { color: #22c55e; }
.price-meta { margin-left: auto; display: flex; gap: 6px; font-size: 11px; color: var(--text-3); }

.card-reason { font-size: 12px; color: var(--text-2); line-height: 1.6; }

.card-signals { display: flex; flex-wrap: wrap; gap: 5px; }
.signal-tag { font-size: 10px; padding: 2px 7px; background: rgba(99,102,241,0.12); color: #818cf8; border-radius: 10px; }

.card-strats { display: flex; flex-wrap: wrap; gap: 5px; }
.strat-chip { font-size: 10px; padding: 2px 7px; border: 1px solid; border-radius: 10px; }

.card-price-levels { display: flex; gap: 8px; }
.pl-item { flex: 1; background: var(--bg-hover); border-radius: var(--radius-sm); padding: 6px 8px; text-align: center; }
.pl-lbl { font-size: 10px; color: var(--text-3); margin-bottom: 2px; }
.pl-val { font-size: 13px; font-weight: 700; }
.pl-buy .pl-val { color: var(--accent); }
.pl-stop .pl-val { color: #ef4444; }
.pl-target .pl-val { color: #22c55e; }

.card-checklist { background: var(--bg-hover); border-radius: var(--radius-sm); padding: 8px 10px; }
.checklist-title { font-size: 10px; color: var(--text-3); font-weight: 600; margin-bottom: 5px; }
.checklist-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-2); margin-top: 3px; }

.card-targets { display: flex; align-items: center; gap: 6px; }
.target-item { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.target-up { color: #ef4444; }
.target-down { color: #22c55e; }
.target-period { color: var(--text-3); }
.target-sep { width: 1px; height: 12px; background: var(--border); }

.card-confidence { display: flex; flex-direction: column; gap: 4px; }
.conf-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); }
.conf-val { font-weight: 600; color: var(--text-1); }
.conf-bar { height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.conf-fill { height: 100%; border-radius: 2px; transition: width 0.4s; }

.card-actions { display: flex; gap: 6px; margin-top: 2px; }
.act-btn { flex: 1; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 5px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 500; text-decoration: none; border: 1px solid var(--border); color: var(--text-2); background: var(--bg-hover); transition: all 0.12s; }
.act-btn:hover { border-color: var(--accent); color: var(--accent); }

.disclaimer { font-size: 11px; color: var(--text-3); text-align: center; padding: 4px; }
</style>
