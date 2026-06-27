<template>
  <div class="sector-view">
    <!-- Tab bar -->
    <div class="view-tabs">
      <button :class="['view-tab', tab === 'industry' ? 'active' : '']" @click="switchTab('industry')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        行业板块
      </button>
      <button :class="['view-tab', tab === 'concept' ? 'active' : '']" @click="switchTab('concept')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        概念板块
      </button>
    </div>

    <!-- ══ INDUSTRY / CONCEPT — sortable summary table ══ -->
    <template v-if="tab === 'industry' || tab === 'concept'">
      <div v-if="loadingBoards" class="card loading-card">
        <span class="spinner"></span>
        <span class="text-2">加载{{ boardLabel }}汇总（含成分股估值，首次较慢）...</span>
      </div>

      <div v-if="!loadingBoards && summaryError" class="error-box">{{ summaryError }}</div>

      <template v-if="!loadingBoards && currentBoards.length">
        <!-- Treemap heatmap -->
        <div class="card chart-card">
          <div class="chart-header">
            <span class="text-1 fw-600">{{ boardLabel }}热力图</span>
            <span class="text-3" style="font-size:11px">面积=市值，颜色=涨跌幅，点击板块查看成分股</span>
          </div>
          <v-chart class="treemap-chart" :option="treemapOption" autoresize @click="onTreemapClick" />
        </div>

        <!-- Controls -->
        <div class="board-controls card">
          <div class="board-search-wrap">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="board-search" v-model="boardQuery" placeholder="搜索板块名称..." />
          </div>
          <button class="btn-ghost btn-sm" @click="loadSummary(true)" :disabled="loadingBoards">刷新</button>
          <span class="text-3" style="font-size:11px">共 {{ filteredSortedBoards.length }} 个板块 · 点击表头排序</span>
        </div>

        <!-- 板块 ｜ 成分股 左右分布 -->
        <div class="board-split">
          <!-- 左：板块汇总表 -->
          <div class="card summary-table-wrap split-left">
            <table class="data-table summary-table">
              <thead>
                <tr>
                  <th>板块</th>
                  <th v-for="c in displayCols" :key="c.key" class="th-sort" @click="toggleSort(c.key)">
                    {{ c.label }}<span v-if="sortKey === c.key" class="sort-arrow">{{ sortAsc ? ' ↑' : ' ↓' }}</span>
                  </th>
                  <th v-if="tab !== 'concept'">领涨股</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="b in filteredSortedBoards" :key="b.name"
                  :class="['stock-row', selectedBoard === b.name ? 'row-selected' : '']"
                  @click="selectBoard(b.name)">
                  <td class="fw-600 board-cell">{{ b.name }}</td>
                  <template v-for="c in displayCols" :key="c.key">
                    <td v-if="c.kind === 'updown'" class="mono">
                      <span class="pos">{{ b.up_count }}</span><span class="text-3">/</span><span class="neg">{{ b.down_count }}</span>
                    </td>
                    <td v-else :class="cellCls(b, c)">{{ cellText(b, c) }}</td>
                  </template>
                  <td v-if="tab !== 'concept'" class="leader-cell text-3">
                    <span v-if="b.leader">{{ b.leader }}
                      <span :class="(b.leader_change ?? 0) >= 0 ? 'pos' : 'neg'">
                        {{ b.leader_change != null ? ((b.leader_change >= 0 ? '+' : '') + b.leader_change.toFixed(1) + '%') : '' }}
                      </span>
                    </span>
                    <span v-else>—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 右：选中板块成分股 -->
          <div class="split-right">
            <template v-if="selectedBoard">
              <div class="card stocks-header">
                <span class="text-1 fw-600">{{ selectedBoard }} · 成分股</span>
                <span class="text-3" style="font-size:11px">{{ boardStocks.length }} 只</span>
              </div>

              <div v-if="loadingStocks" class="card loading-card">
                <span class="spinner spinner-sm"></span>
                <span class="text-2" style="font-size:13px">加载 {{ selectedBoard }} 成分股...</span>
              </div>

              <div v-if="!loadingStocks && boardSummary" class="card board-summary">
                <div class="summary-grid">
                  <div class="summary-tile"><span class="summary-label">平均涨跌</span><span :class="['summary-value', (boardSummary.avgChange ?? 0) >= 0 ? 'pos' : 'neg']">{{ boardSummary.avgChange != null ? ((boardSummary.avgChange >= 0 ? '+' : '') + boardSummary.avgChange.toFixed(2) + '%') : '—' }}</span></div>
                  <div class="summary-tile"><span class="summary-label">平均PE</span><span class="summary-value">{{ boardSummary.avgPe != null ? boardSummary.avgPe.toFixed(1) : '—' }}</span></div>
                  <div class="summary-tile"><span class="summary-label">PE中位数</span><span class="summary-value">{{ boardSummary.medianPe != null ? boardSummary.medianPe.toFixed(1) : '—' }}</span></div>
                  <div class="summary-tile"><span class="summary-label">平均PB</span><span class="summary-value">{{ boardSummary.avgPb != null ? boardSummary.avgPb.toFixed(2) : '—' }}</span></div>
                  <div class="summary-tile"><span class="summary-label">平均换手</span><span class="summary-value">{{ boardSummary.avgTurnover != null ? boardSummary.avgTurnover.toFixed(2) + '%' : '—' }}</span></div>
                  <div class="summary-tile"><span class="summary-label">成交额</span><span class="summary-value">{{ fmtAmount(boardSummary.amount) }}</span></div>
                  <div class="summary-tile"><span class="summary-label">涨停</span><span class="summary-value pos">{{ boardSummary.limitUp }}</span></div>
                </div>
              </div>

              <div v-if="!loadingStocks && boardStocks.length" class="card stocks-table-wrap">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>代码</th><th>名称</th><th>现价</th><th>涨跌%</th><th>换手率</th><th>PE</th><th>PB</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="s in boardStocks" :key="s.code" class="stock-row">
                      <td><span class="mono accent">{{ s.code }}</span></td>
                      <td class="stock-name">{{ s.name }}</td>
                      <td class="mono">{{ s.price?.toFixed(2) ?? '—' }}</td>
                      <td :class="(s.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                        {{ s.change_pct != null ? ((s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(2) + '%') : '—' }}
                      </td>
                      <td class="mono text-3">{{ s.turnover_rate?.toFixed(2) ?? '—' }}%</td>
                      <td class="mono text-3">{{ s.pe?.toFixed(1) ?? '—' }}</td>
                      <td class="mono text-3">{{ s.pb?.toFixed(2) ?? '—' }}</td>
                      <td><router-link :to="{ path: '/backtest', query: { symbol: s.code } }" class="action-link" target="_blank" rel="noopener">回测</router-link></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <div v-else class="card split-placeholder">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
              <span class="text-3">点击左侧板块查看成分股</span>
            </div>
          </div>
        </div>
      </template>
    </template>

  </div>
</template>

<script>
// 模块级缓存：在组件卸载/重新挂载（切换页面再回来）后仍然存活，
// 实现「板块/成分股加载一次后，第二次点击直接出来」。
// 同时落 sessionStorage，使整页刷新(F5)/重开标签后也能秒出（10 分钟有效期）。
const _SECTOR_TTL = 10 * 60 * 1000
const _SECTOR_KEY = 'qf_sector_cache_v1'

function _emptyCache() {
  return {
    tab: 'industry',
    industry: { summary: [], stocks: {}, selected: '' },
    concept:  { summary: [], stocks: {}, selected: '' },
  }
}

function _loadCache() {
  try {
    const raw = sessionStorage.getItem(_SECTOR_KEY)
    if (!raw) return _emptyCache()
    const obj = JSON.parse(raw)
    if (!obj || Date.now() - (obj.ts || 0) > _SECTOR_TTL) return _emptyCache()
    return { tab: obj.tab || 'industry', industry: obj.industry, concept: obj.concept }
  } catch { return _emptyCache() }
}

const _sectorCache = _loadCache()

function _persistCache() {
  try {
    sessionStorage.setItem(_SECTOR_KEY, JSON.stringify({
      ts: Date.now(),
      tab: _sectorCache.tab,
      industry: _sectorCache.industry,
      concept: _sectorCache.concept,
    }))
  } catch { /* 配额满/隐私模式：忽略，退回内存缓存 */ }
}
</script>

<script setup>
import VChart from '../charts'
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const tab             = ref(_sectorCache.tab)
const industrySummary = ref(_sectorCache.industry.summary)
const conceptSummary  = ref(_sectorCache.concept.summary)
const selectedBoard   = ref('')
const boardStocks     = ref([])
const loadingBoards   = ref(false)
const loadingStocks   = ref(false)
const boardQuery      = ref('')
const sortKey         = ref('change_pct')
const sortAsc         = ref(false)
const summaryError    = ref('')

// Sortable summary table columns (click header to sort). Per-tab：
// 行业=新浪(含成分股估值)，概念=同花顺指数(指数/资金净流，无板块PE)。
const industryCols = [
  { key: 'change_pct',    label: '涨跌%',  kind: 'pct' },
  { key: 'up_count',      label: '涨/跌',  kind: 'updown' },
  { key: 'avg_pe',        label: '平均PE', kind: 'pe' },
  { key: 'median_pe',     label: 'PE中位', kind: 'pe' },
  { key: 'avg_pb',        label: '平均PB', kind: 'num2' },
  { key: 'turnover_rate', label: '换手%',  kind: 'pctplain' },
  { key: 'market_cap',    label: '总市值', kind: 'amount' },
  { key: 'amount',        label: '成交额', kind: 'amount' },
]
const conceptCols = [
  { key: 'change_pct',  label: '涨跌%',       kind: 'pct' },
  { key: 'up_count',    label: '涨/跌',       kind: 'updown' },
  { key: 'index_value', label: '指数',        kind: 'num2' },
  { key: 'net_flow',    label: '资金净流(亿)', kind: 'netflow' },
  { key: 'amount',      label: '成交额',      kind: 'amount' },
]
const displayCols = computed(() => (tab.value === 'concept' ? conceptCols : industryCols))

function cellText(b, c) {
  const v = b[c.key]
  if (v == null) return '—'
  switch (c.kind) {
    case 'pct':      return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
    case 'pctplain': return v.toFixed(2) + '%'
    case 'pe':       return v.toFixed(1)
    case 'num2':     return v.toFixed(2)
    case 'netflow':  return (v >= 0 ? '+' : '') + v.toFixed(2)
    case 'amount':   return fmtAmount(v)
    default:         return String(v)
  }
}

function cellCls(b, c) {
  if (c.kind === 'pct' || c.kind === 'netflow') return (b[c.key] ?? 0) >= 0 ? 'pos' : 'neg'
  if (c.kind === 'pe') return peValueClass(b[c.key])
  return 'mono text-3'
}

// ── Data ────────────────────────────────────────────────────────────────────

const boardLabel = computed(() => (tab.value === 'concept' ? '概念板块' : '行业板块'))

const currentBoards = computed(() =>
  tab.value === 'concept' ? conceptSummary.value : industrySummary.value
)

const filteredSortedBoards = computed(() => {
  let arr = currentBoards.value
  if (boardQuery.value.trim()) {
    const q = boardQuery.value.trim()
    arr = arr.filter(b => b.name?.includes(q))
  }
  arr = [...arr].sort((a, b) => {
    const av = a[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    const bv = b[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    return sortAsc.value ? av - bv : bv - av
  })
  return arr
})

// ── Board summary (aggregate stats of constituent stocks) ────────────────────

function _median(arr) {
  if (!arr.length) return null
  const s = [...arr].sort((a, b) => a - b)
  const n = s.length
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2
}

const boardSummary = computed(() => {
  const stocks = boardStocks.value
  if (!stocks.length) return null
  const peVals  = stocks.map(s => s.pe).filter(v => v != null && v > 0 && v < 1000)
  const pbVals  = stocks.map(s => s.pb).filter(v => v != null && v > 0)
  const chgVals = stocks.map(s => s.change_pct).filter(v => v != null)
  const turVals = stocks.map(s => s.turnover_rate).filter(v => v != null)
  const amtSum  = stocks.reduce((acc, s) => acc + (s.turnover || 0), 0)
  const mean = arr => (arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null)
  return {
    total:       stocks.length,
    limitUp:     stocks.filter(s => (s.change_pct ?? 0) >= 9.8).length,
    avgChange:   mean(chgVals),
    avgPe:       mean(peVals),
    medianPe:    _median(peVals),
    avgPb:       mean(pbVals),
    avgTurnover: mean(turVals),
    amount:      amtSum,
  }
})

function fmtAmount(v) {
  if (!v) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

// ── Actions ──────────────────────────────────────────────────────────────────

function toggleSort(key) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = false }
}

async function switchTab(t) {
  tab.value = t
  _sectorCache.tab = t
  _persistCache()
  sortKey.value = 'change_pct'
  sortAsc.value = false
  // 恢复该 tab 上次选中的板块与已缓存成分股（无需重新请求）
  const c = _sectorCache[t]
  selectedBoard.value = c.selected || ''
  boardStocks.value = c.selected && c.stocks[c.selected] ? c.stocks[c.selected] : []
  const cached = t === 'concept' ? conceptSummary.value : industrySummary.value
  if (!cached.length) await loadSummary()
}

async function loadSummary(force = false) {
  const kind = tab.value === 'concept' ? 'concept' : 'industry'
  loadingBoards.value = true
  summaryError.value = ''
  if (force) {
    selectedBoard.value = ''
    boardStocks.value = []
    _sectorCache[kind].selected = ''
    _sectorCache[kind].stocks = {}
  }
  try {
    const res = await axios.get(`/api/sector/${kind}-summary`)
    const boards = res.data.boards || []
    _sectorCache[kind].summary = boards
    _persistCache()
    if (kind === 'concept') conceptSummary.value = boards
    else                    industrySummary.value = boards
  } catch (e) {
    summaryError.value = e.response?.data?.detail || `${boardLabel.value}汇总数据获取失败`
  }
  loadingBoards.value = false
}

async function selectBoard(name) {
  const kind = tab.value === 'concept' ? 'concept' : 'industry'
  if (selectedBoard.value === name) {
    selectedBoard.value = ''
    boardStocks.value = []
    _sectorCache[kind].selected = ''
    _persistCache()
    return
  }
  selectedBoard.value = name
  _sectorCache[kind].selected = name
  // 命中缓存：第二次点击直接出来
  const hit = _sectorCache[kind].stocks[name]
  if (hit) { boardStocks.value = hit; loadingStocks.value = false; _persistCache(); return }
  loadingStocks.value = true
  boardStocks.value = []
  try {
    const res = await axios.get(`/api/sector/${kind}/${encodeURIComponent(name)}`)
    const stocks = res.data.stocks || []
    boardStocks.value = stocks
    _sectorCache[kind].stocks[name] = stocks
    _persistCache()
  } catch (e) {
    console.error('Load stocks failed:', e.response?.data?.detail || e.message)
  }
  loadingStocks.value = false
}

function onTreemapClick(params) {
  if (params.data?.name) selectBoard(params.data.name)
}

function peValueClass(pe) {
  if (pe == null) return 'mono text-3'
  if (pe <= 15) return 'mono pe-low'
  if (pe <= 30) return 'mono pe-mid'
  if (pe <= 60) return 'mono pe-high'
  return 'mono pe-very-high'
}

// ── Color helper (A-share: up=red, down=green) ────────────────────────────────

function changeToColor(pct) {
  if (pct == null) return '#e2e8f0'
  if (pct >= 5)  return '#b91c1c'
  if (pct >= 3)  return '#dc2626'
  if (pct >= 1)  return '#dc2626'
  if (pct >= 0)  return '#dc2626'
  if (pct >= -1) return '#16a34a'
  if (pct >= -3) return '#16a34a'
  if (pct >= -5) return '#16a34a'
  return '#166534'
}

// ── ECharts options ───────────────────────────────────────────────────────────

const treemapOption = computed(() => {
  const boards = currentBoards.value
  if (!boards.length) return null
  return {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: p => {
        const d = p.data
        const chg = d.change_pct != null ? ((d.change_pct >= 0 ? '+' : '') + d.change_pct.toFixed(2) + '%') : '—'
        return `<b>${d.name}</b><br/>涨跌：${chg}<br/>上涨：${d.up_count} 下跌：${d.down_count}<br/>换手：${d.turnover_rate?.toFixed(2) ?? '—'}%`
      }
    },
    series: [{
      type: 'treemap',
      width: '100%',
      height: '100%',
      roam: false,
      nodeClick: 'link',
      breadcrumb: { show: false },
      label: {
        show: true,
        fontSize: 11,
        color: '#fff',
        formatter: p => {
          const chg = p.data.change_pct != null
            ? (p.data.change_pct >= 0 ? '+' : '') + p.data.change_pct.toFixed(2) + '%'
            : ''
          return `{name|${p.data.name}}\n{chg|${chg}}`
        },
        rich: {
          name: { fontSize: 11, fontWeight: 700, color: '#fff' },
          chg:  { fontSize: 10, color: 'rgba(255,255,255,0.85)' },
        },
      },
      itemStyle: { borderColor: '#f5f7fa', borderWidth: 2 },
      emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 } },
      data: boards
        .filter(b => b.market_cap != null && b.market_cap > 0)
        .map(b => ({
          name:          b.name,
          value:         b.market_cap,
          change_pct:    b.change_pct,
          up_count:      b.up_count,
          down_count:    b.down_count,
          turnover_rate: b.turnover_rate,
          itemStyle:     { color: changeToColor(b.change_pct) },
        })),
    }],
  }
})

onMounted(() => {
  const c = _sectorCache[tab.value]
  // 恢复上次选中的板块及其成分股
  if (c.selected) {
    selectedBoard.value = c.selected
    if (c.stocks[c.selected]) boardStocks.value = c.stocks[c.selected]
  }
  // 汇总已缓存则直接展示，否则才请求
  if (!c.summary.length) loadSummary()
})
</script>

<style scoped>
.sector-view { display: flex; flex-direction: column; gap: 14px; }

/* Tabs */
.view-tabs { display: flex; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; align-self: flex-start; }
.view-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.view-tab:hover { color: var(--text-1); }
.view-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(15,23,42,0.12); }

/* Loading */
.loading-card { display: flex; align-items: center; gap: 10px; padding: 30px; }

/* Chart */
.chart-card { padding: 14px; overflow: hidden; }
.chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.fw-600 { font-weight: 600; }

/* Controls */
.board-controls { display: flex; align-items: center; gap: 12px; padding: 10px 14px; flex-wrap: wrap; }
.board-search-wrap { display: flex; align-items: center; gap: 6px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 5px 10px; }
.board-search { background: transparent; border: none; color: var(--text-1); font-size: 13px; outline: none; width: 180px; }
.btn-sm { padding: 5px 12px; font-size: 12px; }

/* 左右分布：左=板块表，右=成分股 */
.board-split { display: flex; gap: 14px; align-items: flex-start; }
.split-left { flex: 0 0 46%; min-width: 0; }
.split-right { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.split-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px 20px; color: var(--text-3); min-height: 240px; }

/* Summary table */
.summary-table-wrap { overflow-x: auto; max-height: 620px; overflow-y: auto; }
.summary-table { width: 100%; }
.summary-table th.th-sort { cursor: pointer; user-select: none; white-space: nowrap; }
.summary-table th.th-sort:hover { color: var(--accent); }
.sort-arrow { color: var(--accent); }
.summary-table .stock-row { cursor: pointer; }
.summary-table .stock-row.row-selected { background: var(--accent-dim); }
.summary-table .board-cell { color: var(--text-1); white-space: nowrap; }
.summary-table .leader-cell { font-size: 11px; white-space: nowrap; }
.pe-low { color: #16a34a; font-weight: 600; }
.pe-mid { color: #2563eb; font-weight: 600; }
.pe-high { color: #d97706; font-weight: 600; }
.pe-very-high { color: #dc2626; font-weight: 600; }

/* Stocks panel */
.stocks-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; }
.stocks-table-wrap { overflow-x: auto; max-height: 500px; overflow-y: auto; }
.stock-name { font-size: 13px; color: var(--text-1); }
.action-link { font-size: 11px; padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); text-decoration: none; white-space: nowrap; transition: all 0.12s; }
.action-link:hover { border-color: var(--accent); color: var(--accent); }

/* Board summary tiles */
.board-summary { padding: 14px 16px; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }
.summary-tile { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); }
.summary-label { font-size: 11px; color: var(--text-3); }
.summary-value { font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.summary-value.pos { color: #dc2626; }
.summary-value.neg { color: #16a34a; }
.pos { color: #dc2626; }
.neg { color: #16a34a; }

.treemap-chart { height: 340px; }

/* ── 移动端适配 ─────────────────────────────────────────── */
@media (max-width: 768px) {
  .sector-view { gap: 10px; }
  .view-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .view-tab { white-space: nowrap; flex-shrink: 0; }
  .chart-card { padding: 12px; }
  /* 热力图说明换行 */
  .chart-header { flex-wrap: wrap; gap: 4px; }
  .treemap-chart { height: 280px; }
  /* 窄屏左右分布改回上下堆叠 */
  .board-split { flex-direction: column; }
  .split-left { flex: 1 1 auto; width: 100%; }
  .split-placeholder { display: none; }
  /* 表格已是横向滚动容器，确保有最小宽度 */
  .summary-table, .stocks-table-wrap .data-table { min-width: 520px; }
  .board-summary { padding: 12px; }
  .summary-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
}
</style>
