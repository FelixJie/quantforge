<template>
  <div class="live-view">
    <!-- Portfolio overview -->
    <div class="stats-row" v-if="portfolio">
      <div class="metric-card">
        <div class="metric-label">总资产</div>
        <div class="metric-value mono">¥{{ fmt(portfolio.total_balance) }}</div>
        <div class="metric-sub">{{ portfolio.running_count }} 个策略运行中</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">浮动盈亏</div>
        <div class="metric-value mono" :class="portfolio.total_unrealized_pnl >= 0 ? 'pos' : 'neg'">{{ fmtPnl(portfolio.total_unrealized_pnl) }}</div>
        <div class="metric-sub">未实现</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已实现盈亏</div>
        <div class="metric-value mono" :class="portfolio.total_realized_pnl >= 0 ? 'pos' : 'neg'">{{ fmtPnl(portfolio.total_realized_pnl) }}</div>
        <div class="metric-sub">历史累计</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">持仓数量</div>
        <div class="metric-value">{{ (portfolio.positions || []).length }}</div>
        <div class="metric-sub">跨策略合计</div>
      </div>
      <div class="metric-card ws-card">
        <div class="metric-label">实时连接</div>
        <div class="ws-status-val">
          <span :class="['ws-dot', wsStatus]"></span>
          <span class="metric-value" style="font-size:14px">{{ wsLabel }}</span>
        </div>
        <div class="metric-sub">WebSocket</div>
      </div>
    </div>

    <div class="view-layout">
      <!-- Left: start session form -->
      <div class="config-panel card">
        <div class="panel-head">启动模拟</div>

        <div class="field">
          <label class="form-label">策略</label>
          <select class="select-base" v-model="form.strategy">
            <option v-for="s in strategies" :key="s.module_path" :value="s.module_path">
              {{ s.display_name || s.name }}
            </option>
          </select>
        </div>

        <div class="field">
          <label class="form-label">标的代码（可多只）</label>
          <div class="symbol-tags-wrap" @click="$refs.symTagInput?.focus()">
            <div class="symbol-tags">
              <span v-for="sym in liveSymbols" :key="sym" class="sym-tag">
                {{ sym }}
                <button class="tag-del" @click.stop="removeLiveSym(sym)">×</button>
              </span>
              <input
                ref="symTagInput"
                class="tag-input"
                v-model="liveSymInput"
                placeholder="输入代码 Enter添加"
                @keydown.enter.prevent="addLiveSyms"
                @blur="addLiveSyms"
              />
            </div>
          </div>
        </div>

        <div class="field">
          <label class="form-label">初始资金（元）</label>
          <input type="number" class="input" v-model.number="form.capital" />
        </div>

        <button class="btn-primary run-btn" @click="startSession" :disabled="starting">
          <span v-if="starting" class="spinner spinner-sm"></span>
          {{ starting ? '启动中...' : '启动模拟' }}
        </button>

        <div v-if="startError" class="error-box" style="margin-top:12px">{{ startError }}</div>

        <!-- Real-time quotes -->
        <div v-if="Object.keys(quotes).length" class="quotes-panel">
          <div class="quotes-title">实时行情</div>
          <div v-for="(q, sym) in quotes" :key="sym" class="quote-row">
            <div class="q-sym-wrap">
              <span class="q-sym mono">{{ sym }}</span>
              <span v-if="stockNames[sym]" class="q-name">{{ stockNames[sym] }}</span>
            </div>
            <span class="q-price mono">{{ q.price?.toFixed(3) }}</span>
            <span :class="['q-chg', q.change_pct >= 0 ? 'pos' : 'neg']">
              {{ q.change_pct != null ? (q.change_pct >= 0 ? '+' : '') + q.change_pct.toFixed(2) + '%' : '' }}
            </span>
          </div>
        </div>
      </div>

      <!-- Right: sessions -->
      <div class="sessions-area">
        <div v-if="sessions.length === 0" class="empty-state card">
          <div class="empty-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
          </div>
          <p>暂无模拟交易会话</p>
          <p class="empty-hint">在左侧选择策略和标的，点击启动</p>
        </div>

        <div v-for="session in sessions" :key="session.session_id" class="session-card card">
          <!-- Session header — click to expand -->
          <div class="session-head" @click="toggleExpand(session.session_id)" style="cursor:pointer">
            <div class="session-info">
              <span class="session-name">{{ strategyName(session.strategy_name) }}</span>
              <code class="session-id mono text-3">{{ session.session_id }}</code>
              <span class="session-syms text-2">{{ (session.symbols || []).map(s => stockNames[s] ? `${stockNames[s]}(${s})` : s).join(', ') }}</span>
            </div>
            <div class="session-actions" @click.stop>
              <span :class="['badge', session.status === 'running' ? 'badge-blue' : session.status === 'stopped' ? 'badge-gray' : 'badge-red']">
                {{ session.status === 'running' ? '运行中' : session.status === 'stopped' ? '已停止' : session.status }}
              </span>
              <button
                v-if="session.status === 'running'"
                class="btn-stop" @click="stopSession(session.session_id)"
                :disabled="stoppingId === session.session_id"
              >
                {{ stoppingId === session.session_id ? '停止中...' : '停止' }}
              </button>
              <button
                v-if="session.status === 'stopped'"
                class="btn-resume" @click="resumeSession(session.session_id)"
                :disabled="resumingId === session.session_id"
              >
                {{ resumingId === session.session_id ? '恢复中...' : '▶ 继续' }}
              </button>
              <button class="btn-expand" :class="{ expanded: expandedId === session.session_id }" @click.stop="toggleExpand(session.session_id)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Account stats (always visible) -->
          <div class="account-grid">
            <div class="acc-stat">
              <div class="acc-label">总资产</div>
              <div class="acc-val mono">¥{{ fmt(session.account?.balance) }}</div>
            </div>
            <div class="acc-stat">
              <div class="acc-label">可用资金</div>
              <div class="acc-val mono">¥{{ fmt(session.account?.available) }}</div>
            </div>
            <div class="acc-stat">
              <div class="acc-label">浮动盈亏</div>
              <div class="acc-val mono" :class="(session.account?.unrealized_pnl ?? 0) >= 0 ? 'pos' : 'neg'">
                {{ fmtPnl(session.account?.unrealized_pnl) }}
              </div>
            </div>
            <div class="acc-stat">
              <div class="acc-label">已实现</div>
              <div class="acc-val mono" :class="(session.account?.realized_pnl ?? 0) >= 0 ? 'pos' : 'neg'">
                {{ fmtPnl(session.account?.realized_pnl) }}
              </div>
            </div>
          </div>

          <!-- Expandable detail panel -->
          <div v-if="expandedId === session.session_id" class="detail-panel">
            <!-- Tabs -->
            <div class="detail-tabs">
              <button
                v-for="tab in detailTabs"
                :key="tab.key"
                :class="['detail-tab', activeTab[session.session_id] === tab.key ? 'active' : '']"
                @click="setTab(session.session_id, tab.key)"
              >
                {{ tab.label }}
                <span v-if="tab.key === 'trades'" class="tab-count">{{ (detail[session.session_id]?.trades || []).length }}</span>
                <span v-if="tab.key === 'orders'" class="tab-count">{{ (detail[session.session_id]?.orders || []).length }}</span>
                <span v-if="tab.key === 'logs'" class="tab-count">{{ (detail[session.session_id]?.logs || []).length }}</span>
              </button>
              <div class="tab-spacer"></div>
              <span v-if="detailLoading[session.session_id]" class="spinner spinner-sm" style="margin-right:8px"></span>
            </div>

            <!-- Tab: 持仓 -->
            <div v-if="activeTab[session.session_id] === 'positions'" class="tab-body">
              <div v-if="!session.positions?.length" class="tab-empty">暂无持仓</div>
              <table v-else class="data-table">
                <thead>
                  <tr><th>代码</th><th>持仓量</th><th>成本价</th><th>现价</th><th>浮盈</th></tr>
                </thead>
                <tbody>
                  <tr v-for="pos in session.positions" :key="pos.symbol">
                    <td class="mono accent">{{ pos.symbol }}</td>
                    <td class="mono">{{ pos.volume }}</td>
                    <td class="mono">{{ pos.avg_price?.toFixed(3) }}</td>
                    <td class="mono">{{ latestPrice(pos.symbol) }}</td>
                    <td class="mono" :class="(pos.unrealized_pnl ?? 0) >= 0 ? 'pos' : 'neg'">{{ fmtPnl(pos.unrealized_pnl) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Tab: 交易记录 -->
            <div v-if="activeTab[session.session_id] === 'trades'" class="tab-body">
              <div v-if="!(detail[session.session_id]?.trades?.length)" class="tab-empty">暂无成交记录</div>
              <table v-else class="data-table">
                <thead>
                  <tr><th>时间</th><th>代码</th><th>方向</th><th>成交价</th><th>数量</th><th>手续费</th></tr>
                </thead>
                <tbody>
                  <tr v-for="t in [...(detail[session.session_id]?.trades || [])].reverse()" :key="t.trade_id">
                    <td class="mono text-3" style="font-size:11px">{{ fmtTime(t.datetime) }}</td>
                    <td class="mono accent">{{ t.symbol }}</td>
                    <td><span :class="['dir-badge', t.direction === 'long' ? 'buy' : 'sell']">{{ t.direction === 'long' ? '买入' : '卖出' }}</span></td>
                    <td class="mono">{{ t.price?.toFixed(3) }}</td>
                    <td class="mono">{{ t.volume }}</td>
                    <td class="mono text-3">{{ t.commission?.toFixed(2) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Tab: 订单 -->
            <div v-if="activeTab[session.session_id] === 'orders'" class="tab-body">
              <div v-if="!(detail[session.session_id]?.orders?.length)" class="tab-empty">暂无订单</div>
              <table v-else class="data-table">
                <thead>
                  <tr><th>订单ID</th><th>代码</th><th>方向</th><th>委托价</th><th>数量</th><th>已成</th><th>状态</th></tr>
                </thead>
                <tbody>
                  <tr v-for="o in [...(detail[session.session_id]?.orders || [])].reverse()" :key="o.order_id">
                    <td class="mono text-3" style="font-size:11px">{{ o.order_id }}</td>
                    <td class="mono accent">{{ o.symbol }}</td>
                    <td><span :class="['dir-badge', o.direction === 'long' ? 'buy' : 'sell']">{{ o.direction === 'long' ? '买入' : '卖出' }}</span></td>
                    <td class="mono">{{ o.price?.toFixed(3) }}</td>
                    <td class="mono">{{ o.volume }}</td>
                    <td class="mono">{{ o.filled }}</td>
                    <td><span :class="['status-badge', o.status]">{{ statusLabel(o.status) }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Tab: 日志 -->
            <div v-if="activeTab[session.session_id] === 'logs'" class="tab-body log-body" ref="logContainer">
              <div v-if="!(detail[session.session_id]?.logs?.length)" class="tab-empty">暂无日志</div>
              <div v-else class="log-list">
                <div
                  v-for="(entry, i) in [...(detail[session.session_id]?.logs || [])].reverse()"
                  :key="i"
                  :class="['log-entry', entry.level]"
                >
                  <span class="log-time mono">{{ entry.time }}</span>
                  <span :class="['log-level', entry.level]">{{ entry.level.toUpperCase() }}</span>
                  <span class="log-msg">{{ entry.msg }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="session-meta text-3">
            启动时间：{{ session.started_at ? new Date(session.started_at).toLocaleString('zh-CN') : '-' }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const stockNames = ref({})   // {code: name}

const strategies  = ref([])
const sessions    = ref([])
const portfolio   = ref(null)
const quotes      = ref({})
const wsStatus    = ref('offline')
const starting    = ref(false)
const stoppingId  = ref('')
const resumingId  = ref('')
const startError  = ref('')

// Detail panel state
const expandedId      = ref('')       // which session is expanded
const activeTab       = ref({})       // session_id -> tab key
const detail          = ref({})       // session_id -> detail payload
const detailLoading   = ref({})       // session_id -> bool

let ws = null, refreshTimer = null, detailTimer = null

const detailTabs = [
  { key: 'positions', label: '持仓' },
  { key: 'trades',    label: '交易记录' },
  { key: 'orders',    label: '订单' },
  { key: 'logs',      label: '日志' },
]

const form = ref({ strategy: '', capital: 1000000 })
const liveSymbols = ref(['000001'])
const liveSymInput = ref('')

function addLiveSyms() {
  const raw = liveSymInput.value.trim()
  if (!raw) return
  const parts = raw.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean)
  for (const s of parts) {
    if (s && !liveSymbols.value.includes(s)) liveSymbols.value.push(s)
  }
  liveSymInput.value = ''
}
function removeLiveSym(sym) {
  liveSymbols.value = liveSymbols.value.filter(s => s !== sym)
}

const detectedExchange = computed(() => {
  const s = (liveSymbols.value[0] || '').trim()
  if (s.startsWith('6')) return 'SSE'
  if (s.startsWith('0') || s.startsWith('3')) return 'SZSE'
  if (s.startsWith('8') || s.startsWith('4')) return 'BSE'
  return ''
})

const wsLabel = computed(() => ({ connected: '已连接', connecting: '连接中', offline: '断线' }[wsStatus.value] || '未知'))

const strategyMap = computed(() => {
  const m = {}
  for (const s of strategies.value) {
    m[s.module_path] = s.display_name || s.name
    m[s.name] = s.display_name || s.name
    const last = s.module_path.split('.').pop()
    if (last) m[last] = s.display_name || s.name
  }
  return m
})

function strategyName(nameOrPath) {
  if (!nameOrPath) return '-'
  return strategyMap.value[nameOrPath] || nameOrPath
}

function fmt(v) { return v != null ? v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '-' }
function fmtPnl(v) {
  if (v == null) return '-'
  return (v >= 0 ? '+' : '') + v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
function latestPrice(symbol) {
  const q = quotes.value[symbol]
  return q ? q.price?.toFixed(3) : '-'
}
function fmtTime(iso) {
  if (!iso) return '-'
  return iso.replace('T', ' ').slice(0, 19)
}
function statusLabel(s) {
  return { pending: '待报', submitted: '已报', filled: '全成', cancelled: '撤单', rejected: '拒单' }[s] || s
}

// ── Detail panel ──────────────────────────────────────────────────────────────

async function toggleExpand(sessionId) {
  if (expandedId.value === sessionId) {
    expandedId.value = ''
    clearInterval(detailTimer)
    detailTimer = null
    return
  }
  expandedId.value = sessionId
  if (!activeTab.value[sessionId]) activeTab.value[sessionId] = 'positions'
  await fetchDetail(sessionId)
  // Auto-refresh detail every 3 s while expanded
  clearInterval(detailTimer)
  detailTimer = setInterval(() => { if (expandedId.value) fetchDetail(expandedId.value) }, 3000)
}

function setTab(sessionId, key) {
  activeTab.value = { ...activeTab.value, [sessionId]: key }
}

async function fetchDetail(sessionId) {
  detailLoading.value = { ...detailLoading.value, [sessionId]: true }
  try {
    const r = await axios.get(`/api/portfolio/sessions/${sessionId}/detail`)
    detail.value = { ...detail.value, [sessionId]: r.data }
    // Also sync session summary
    const idx = sessions.value.findIndex(s => s.session_id === sessionId)
    if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...r.data }
  } catch {}
  detailLoading.value = { ...detailLoading.value, [sessionId]: false }
}

// ── Session management ────────────────────────────────────────────────────────

async function loadStrategies() {
  try { const r = await axios.get('/api/strategy/'); strategies.value = r.data; if (r.data.length) form.value.strategy = r.data[0].module_path } catch {}
}
async function loadSessions() {
  try { const r = await axios.get('/api/portfolio/sessions'); sessions.value = r.data } catch {}
}
async function loadPortfolio() {
  try {
    const r = await axios.get('/api/portfolio/')
    portfolio.value = r.data
    if (r.data.latest_quotes) quotes.value = { ...quotes.value, ...r.data.latest_quotes }
  } catch {}
}

async function startSession() {
  if (!liveSymbols.value.length) { startError.value = '请至少添加一个标的'; return }
  starting.value = true; startError.value = ''
  const syms = liveSymbols.value
  const exchange = detectedExchange.value || 'SZSE'
  try {
    const res = await axios.post('/api/portfolio/sessions', {
      strategy: form.value.strategy,
      symbols: syms,
      exchange,
      initial_capital: form.value.capital,
      params: { symbol: syms[0], exchange },
    })
    sessions.value = [res.data, ...sessions.value]
    if (ws?.readyState === WebSocket.OPEN)
      ws.send(JSON.stringify({ action: 'subscribe', symbols: syms }))
  } catch (e) { startError.value = e.response?.data?.detail || '启动失败' }
  starting.value = false
}

async function stopSession(sessionId) {
  stoppingId.value = sessionId
  try {
    await axios.delete(`/api/portfolio/sessions/${sessionId}`)
    const idx = sessions.value.findIndex(s => s.session_id === sessionId)
    if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], status: 'stopped' }
  } catch (e) {
    console.error('Stop failed:', e.response?.data?.detail || e.message)
  }
  stoppingId.value = ''
}

async function resumeSession(sessionId) {
  resumingId.value = sessionId
  try {
    const res = await axios.post(`/api/portfolio/sessions/${sessionId}/resume`)
    const idx = sessions.value.findIndex(s => s.session_id === sessionId)
    if (idx >= 0) sessions.value[idx] = { ...sessions.value[idx], ...res.data }
  } catch (e) {
    console.error('Resume failed:', e.response?.data?.detail || e.message)
  }
  resumingId.value = ''
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const port = import.meta.env.VITE_API_PORT || '8000'
  wsStatus.value = 'connecting'
  ws = new WebSocket(`${proto}//${location.hostname}:${port}/api/market/ws`)
  ws.onopen = () => {
    wsStatus.value = 'connected'
    const syms = [...new Set(sessions.value.flatMap(s => s.symbols || []))]
    if (syms.length) ws.send(JSON.stringify({ action: 'subscribe', symbols: syms }))
  }
  ws.onmessage = e => {
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'quotes') quotes.value = { ...quotes.value, ...msg.data }
      else if (msg.type === 'portfolio') { portfolio.value = msg.data; if (msg.data.latest_quotes) quotes.value = { ...quotes.value, ...msg.data.latest_quotes } }
    } catch {}
  }
  ws.onclose = () => { wsStatus.value = 'offline'; setTimeout(connectWS, 5000) }
  ws.onerror = () => { wsStatus.value = 'offline' }
}

onMounted(async () => {
  if (route.query.symbol) liveSymbols.value = [route.query.symbol]
  // Load stock names for display alongside codes
  try {
    const r = await axios.get('/api/market/meta/names')
    stockNames.value = r.data.names || {}
  } catch {}
  await Promise.all([loadStrategies(), loadSessions(), loadPortfolio()])
  connectWS()
  refreshTimer = setInterval(() => Promise.all([loadSessions(), loadPortfolio()]), 10000)
})
onUnmounted(() => {
  clearInterval(refreshTimer)
  clearInterval(detailTimer)
  ws?.close()
})
</script>

<style scoped>
.live-view { padding: 24px; display: flex; flex-direction: column; gap: 16px; }

.stats-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.ws-card .metric-value { line-height: 1; }
.ws-status-val { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ws-dot.connected { background: var(--success); box-shadow: 0 0 6px var(--success); }
.ws-dot.connecting { background: var(--warning); animation: pulse 1.5s infinite; }
.ws-dot.offline { background: var(--text-3); }
@keyframes pulse { 0%,100%{opacity:1}50%{opacity:0.4} }

.view-layout { display: grid; grid-template-columns: 280px 1fr; gap: 16px; align-items: start; }

.config-panel { padding: 20px; }
.panel-head { font-size: 13px; font-weight: 600; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }

.field { margin-bottom: 14px; }
.symbol-row { position: relative; display: flex; align-items: center; }
.symbol-row .input { padding-right: 52px; }
.exch-badge { font-family: var(--font-mono); font-size: 10px; background: var(--accent-dim); color: var(--accent); padding: 2px 6px; border-radius: 3px; }
.symbol-tags-wrap { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-elevated); padding: 5px 8px; min-height: 36px; cursor: text; }
.symbol-tags { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.sym-tag { display: flex; align-items: center; gap: 3px; background: var(--accent-dim); color: var(--accent); border-radius: 4px; padding: 2px 7px; font-size: 12px; font-family: var(--font-mono); font-weight: 500; }
.tag-del { background: none; border: none; color: inherit; cursor: pointer; padding: 0; line-height: 1; font-size: 14px; opacity: 0.7; }
.tag-del:hover { opacity: 1; }
.tag-input { border: none; outline: none; background: transparent; color: var(--text-1); font-size: 12px; min-width: 80px; flex: 1; padding: 2px; }
.run-btn { width: 100%; justify-content: center; padding: 10px; font-size: 14px; }

.quotes-panel { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.quotes-title { font-size: 11px; font-weight: 600; color: var(--text-2); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }
.quote-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); }
.quote-row:last-child { border-bottom: none; }
.q-sym-wrap { flex: 1; display: flex; flex-direction: column; gap: 1px; }
.q-sym { font-size: 12px; color: var(--text-2); }
.q-name { font-size: 10px; color: var(--text-3); }
.q-price { font-size: 13px; font-weight: 600; color: var(--text-1); }
.q-chg { font-size: 11px; min-width: 52px; text-align: right; }

/* Sessions */
.sessions-area { display: flex; flex-direction: column; gap: 14px; }
.session-card { overflow: hidden; }

.session-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px; border-bottom: 1px solid var(--border);
  user-select: none;
  transition: background 0.1s;
}
.session-head:hover { background: rgba(255,255,255,0.02); }

.session-info { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.session-name { font-size: 14px; font-weight: 600; color: var(--text-1); }
.session-id { font-size: 11px; }
.session-syms { font-size: 12px; }
.session-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }

.btn-stop {
  background: rgba(239,68,68,0.1);
  border: 1px solid rgba(239,68,68,0.3);
  color: #f87171;
  border-radius: var(--radius-sm);
  padding: 4px 10px; font-size: 11px; cursor: pointer;
  transition: background 0.12s;
}
.btn-stop:hover:not(:disabled) { background: rgba(239,68,68,0.2); }
.btn-stop:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-resume {
  background: rgba(34,197,94,0.1);
  border: 1px solid rgba(34,197,94,0.3);
  color: #4ade80;
  border-radius: var(--radius-sm);
  padding: 4px 10px; font-size: 11px; cursor: pointer;
  transition: background 0.12s;
}
.btn-resume:hover:not(:disabled) { background: rgba(34,197,94,0.2); }
.btn-resume:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-expand {
  display: flex; align-items: center; justify-content: center;
  width: 26px; height: 26px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-expand:hover { border-color: var(--accent); color: var(--accent); }
.btn-expand.expanded svg { transform: rotate(180deg); }
.btn-expand svg { transition: transform 0.2s; }

.account-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; background: var(--border); }
.acc-stat { background: var(--bg-surface); padding: 12px 14px; }
.acc-label { font-size: 10px; font-weight: 500; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
.acc-val { font-size: 16px; font-weight: 700; }

/* Detail panel */
.detail-panel { border-top: 1px solid var(--border); }

.detail-tabs {
  display: flex; align-items: center;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  padding: 0 4px;
}
.detail-tab {
  display: flex; align-items: center; gap: 5px;
  padding: 9px 14px;
  font-size: 12px; font-weight: 500;
  color: var(--text-3);
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color 0.12s, border-color 0.12s;
  margin-bottom: -1px;
}
.detail-tab:hover { color: var(--text-1); }
.detail-tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-count {
  background: var(--bg-surface);
  color: var(--text-3);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 10px;
  min-width: 18px;
  text-align: center;
}
.detail-tab.active .tab-count { background: var(--accent-dim); color: var(--accent); }
.tab-spacer { flex: 1; }

.tab-body { max-height: 300px; overflow-y: auto; }
.tab-empty { padding: 24px; text-align: center; font-size: 12px; color: var(--text-3); }

/* Direction badge */
.dir-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 600;
}
.dir-badge.buy { background: rgba(34,197,94,0.12); color: #4ade80; }
.dir-badge.sell { background: rgba(239,68,68,0.12); color: #f87171; }

/* Order status badge */
.status-badge {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 500;
}
.status-badge.filled { background: rgba(34,197,94,0.12); color: #4ade80; }
.status-badge.pending, .status-badge.submitted { background: rgba(59,130,246,0.12); color: #60a5fa; }
.status-badge.cancelled { background: rgba(255,255,255,0.06); color: var(--text-3); }
.status-badge.rejected { background: rgba(239,68,68,0.12); color: #f87171; }

/* Log panel */
.log-body { max-height: 300px; overflow-y: auto; }
.log-list { padding: 8px 0; }
.log-entry {
  display: flex; align-items: baseline; gap: 10px;
  padding: 4px 16px;
  font-size: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.log-entry:hover { background: rgba(255,255,255,0.02); }
.log-time { color: var(--text-3); font-size: 11px; flex-shrink: 0; }
.log-level {
  font-size: 10px; font-weight: 700;
  flex-shrink: 0; min-width: 38px;
  text-align: center;
  padding: 1px 5px;
  border-radius: 3px;
}
.log-level.info { background: rgba(59,130,246,0.12); color: #60a5fa; }
.log-level.warning { background: rgba(245,158,11,0.12); color: #fbbf24; }
.log-level.error { background: rgba(239,68,68,0.12); color: #f87171; }
.log-level.debug { background: rgba(255,255,255,0.05); color: var(--text-3); }
.log-msg { color: var(--text-1); line-height: 1.4; word-break: break-all; }

.session-meta { padding: 8px 16px; font-size: 11px; border-top: 1px solid var(--border); }

@media (max-width: 768px) {
  .view-layout { grid-template-columns: 1fr; }
  .stats-row { grid-template-columns: repeat(3, 1fr); }
  .account-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
