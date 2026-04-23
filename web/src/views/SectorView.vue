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
      <button :class="['view-tab', tab === 'flow' ? 'active' : '']" @click="switchTab('flow')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
        资金流向
      </button>
    </div>

    <!-- ══ INDUSTRY & CONCEPT shared layout ══ -->
    <template v-if="tab === 'industry' || tab === 'concept'">
      <div v-if="loadingBoards" class="card loading-card">
        <span class="spinner"></span>
        <span class="text-2">加载{{ tab === 'industry' ? '行业' : '概念' }}板块数据...</span>
      </div>

      <template v-if="!loadingBoards && currentBoards.length">
        <!-- Treemap heatmap -->
        <div class="card chart-card">
          <div class="chart-header">
            <span class="text-1 fw-600">{{ tab === 'industry' ? '行业' : '概念' }}板块热力图</span>
            <span class="text-3" style="font-size:11px">面积=市值，颜色=涨跌幅，点击板块查看成分股</span>
          </div>
          <v-chart :option="treemapOption" autoresize style="height:340px" @click="onTreemapClick" />
        </div>

        <!-- Search + sort controls -->
        <div class="board-controls card">
          <div class="board-search-wrap">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="board-search" v-model="boardQuery" placeholder="搜索板块名称..." />
          </div>
          <div class="sort-chips">
            <button v-for="s in sortOptions" :key="s.key"
              :class="['sort-chip', sortKey === s.key ? 'active' : '']"
              @click="toggleSort(s.key)">
              {{ s.label }}{{ sortKey === s.key ? (sortAsc ? ' ↑' : ' ↓') : '' }}
            </button>
          </div>
          <span class="text-3" style="font-size:11px">共 {{ currentBoards.length }} 个板块</span>
        </div>

        <!-- Board list + constituent stocks layout -->
        <div class="board-layout">
          <!-- Left: board ranking table -->
          <div class="board-list card">
            <div class="board-list-inner">
              <div
                v-for="b in filteredSortedBoards" :key="b.name"
                :class="['board-row', selectedBoard === b.name ? 'selected' : '']"
                @click="selectBoard(b.name)"
              >
                <div class="board-row-main">
                  <span class="board-name">{{ b.name }}</span>
                  <span :class="['board-chg', (b.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                    {{ b.change_pct != null ? ((b.change_pct >= 0 ? '+' : '') + b.change_pct.toFixed(2) + '%') : '—' }}
                  </span>
                </div>
                <div class="board-row-meta">
                  <span class="text-3">↑{{ b.up_count }} ↓{{ b.down_count }}</span>
                  <span class="text-3">换手 {{ b.turnover_rate?.toFixed(2) ?? '—' }}%</span>
                  <span v-if="b.leader" class="leader-tag">
                    {{ b.leader }}
                    <span :class="(b.leader_change ?? 0) >= 0 ? 'up' : 'down'">
                      {{ b.leader_change != null ? ((b.leader_change >= 0 ? '+' : '') + b.leader_change.toFixed(2) + '%') : '' }}
                    </span>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- Right: constituent stocks -->
          <div class="stocks-panel">
            <div v-if="!selectedBoard" class="card empty-stocks">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <p class="text-3">点击左侧板块查看成分股</p>
            </div>

            <div v-if="selectedBoard && loadingStocks" class="card loading-card">
              <span class="spinner spinner-sm"></span>
              <span class="text-2" style="font-size:13px">加载 {{ selectedBoard }} 成分股...</span>
            </div>

            <template v-if="selectedBoard && !loadingStocks && boardStocks.length">
              <div class="card stocks-header">
                <span class="text-1 fw-600">{{ selectedBoard }}</span>
                <span class="text-3" style="font-size:11px">{{ boardStocks.length }} 只成分股</span>
              </div>
              <div class="card stocks-table-wrap">
                <table class="data-table">
                  <thead>
                    <tr>
                      <th>代码</th>
                      <th>名称</th>
                      <th>现价</th>
                      <th>涨跌%</th>
                      <th>换手率</th>
                      <th>PE</th>
                      <th>PB</th>
                      <th></th>
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
                      <td>
                        <router-link :to="{ path: '/backtest', query: { symbol: s.code } }" class="action-link">回测</router-link>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>

            <div v-if="selectedBoard && !loadingStocks && !boardStocks.length" class="card empty-stocks">
              <p class="text-3">暂无成分股数据</p>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ══ FUND FLOW tab ══ -->
    <template v-if="tab === 'flow'">
      <div class="flow-header card">
        <span class="text-1 fw-600">行业资金流向</span>
        <div class="indicator-chips">
          <button v-for="ind in ['今日', '5日', '10日']" :key="ind"
            :class="['ind-chip', flowIndicator === ind ? 'active' : '']"
            @click="switchIndicator(ind)">{{ ind }}</button>
        </div>
        <button class="btn-ghost btn-sm" @click="loadFlow" :disabled="loadingFlow">
          <span v-if="loadingFlow" class="spinner spinner-sm"></span>
          <span v-else>刷新</span>
        </button>
      </div>

      <div v-if="loadingFlow" class="card loading-card">
        <span class="spinner"></span><span class="text-2">加载资金流向...</span>
      </div>

      <div v-if="!loadingFlow && flowError" class="error-box">{{ flowError }}</div>

      <template v-if="!loadingFlow && flowData.length">
        <!-- Top inflow / outflow charts -->
        <div class="flow-charts">
          <div class="card chart-card">
            <div class="chart-header">
              <span class="text-2" style="font-size:12px">净流入 Top 10</span>
            </div>
            <v-chart :option="inflowOption" autoresize style="height:280px" />
          </div>
          <div class="card chart-card">
            <div class="chart-header">
              <span class="text-2" style="font-size:12px">净流出 Top 10</span>
            </div>
            <v-chart :option="outflowOption" autoresize style="height:280px" />
          </div>
        </div>

        <!-- Full table -->
        <div class="card">
          <div class="modal-table-wrap" style="max-height:500px">
            <table class="data-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>板块</th>
                  <th>净流入(万)</th>
                  <th>净流入%</th>
                  <th>主力净流入</th>
                  <th>涨跌%</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="b in flowData" :key="b.name"
                  :class="['stock-row', (b.net_flow ?? 0) >= 0 ? 'row-inflow' : 'row-outflow']">
                  <td class="text-3">{{ b.rank }}</td>
                  <td class="fw-600">{{ b.name }}</td>
                  <td :class="(b.net_flow ?? 0) >= 0 ? 'pos' : 'neg'">
                    {{ b.net_flow != null ? ((b.net_flow >= 0 ? '+' : '') + (b.net_flow / 10000).toFixed(0) + '万') : '—' }}
                  </td>
                  <td :class="(b.net_flow_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                    {{ b.net_flow_pct != null ? ((b.net_flow_pct >= 0 ? '+' : '') + b.net_flow_pct.toFixed(2) + '%') : '—' }}
                  </td>
                  <td :class="(b.main_flow ?? 0) >= 0 ? 'pos' : 'neg'">
                    {{ b.main_flow != null ? ((b.main_flow >= 0 ? '+' : '') + (b.main_flow / 10000).toFixed(0) + '万') : '—' }}
                  </td>
                  <td :class="(b.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                    {{ b.change_pct != null ? ((b.change_pct >= 0 ? '+' : '') + b.change_pct.toFixed(2) + '%') : '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const tab            = ref('industry')
const industryBoards = ref([])
const conceptBoards  = ref([])
const selectedBoard  = ref('')
const boardStocks    = ref([])
const flowData       = ref([])
const flowIndicator  = ref('今日')
const loadingBoards  = ref(false)
const loadingStocks  = ref(false)
const loadingFlow    = ref(false)
const boardQuery     = ref('')
const sortKey        = ref('change_pct')
const sortAsc        = ref(false)
const flowError      = ref('')

const sortOptions = [
  { key: 'change_pct',   label: '涨跌幅' },
  { key: 'turnover_rate', label: '换手率' },
  { key: 'up_count',     label: '上涨家数' },
  { key: 'market_cap',   label: '总市值' },
]

// ── Data ────────────────────────────────────────────────────────────────────

const currentBoards = computed(() =>
  tab.value === 'industry' ? industryBoards.value : conceptBoards.value
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

// ── Actions ──────────────────────────────────────────────────────────────────

function toggleSort(key) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = false }
}

async function switchTab(t) {
  tab.value = t
  selectedBoard.value = ''
  boardStocks.value = []
  if (t === 'industry' && !industryBoards.value.length) await loadBoards('industry')
  if (t === 'concept'  && !conceptBoards.value.length)  await loadBoards('concept')
  if (t === 'flow'     && !flowData.value.length)        await loadFlow()
}

async function loadBoards(type) {
  loadingBoards.value = true
  try {
    const res = await axios.get(`/api/sector/${type}`)
    if (type === 'industry') industryBoards.value = res.data.boards || []
    else                     conceptBoards.value  = res.data.boards || []
  } catch (e) {
    console.error('Load boards failed:', e.response?.data?.detail || e.message)
  }
  loadingBoards.value = false
}

async function selectBoard(name) {
  if (selectedBoard.value === name) { selectedBoard.value = ''; boardStocks.value = []; return }
  selectedBoard.value = name
  loadingStocks.value = true
  boardStocks.value = []
  try {
    const endpoint = tab.value === 'industry' ? 'industry' : 'concept'
    const res = await axios.get(`/api/sector/${endpoint}/${encodeURIComponent(name)}`)
    boardStocks.value = res.data.stocks || []
  } catch (e) {
    console.error('Load stocks failed:', e.response?.data?.detail || e.message)
  }
  loadingStocks.value = false
}

async function loadFlow() {
  loadingFlow.value = true
  flowError.value = ''
  try {
    const res = await axios.get('/api/sector/fund-flow', { params: { indicator: flowIndicator.value } })
    flowData.value = res.data.boards || []
  } catch (e) {
    flowError.value = e.response?.data?.detail || '资金流向数据获取失败（非交易时间可能无数据）'
  }
  loadingFlow.value = false
}

async function switchIndicator(ind) {
  flowIndicator.value = ind
  await loadFlow()
}

function onTreemapClick(params) {
  if (params.data?.name) selectBoard(params.data.name)
}

// ── Color helper (A-share: up=red, down=green) ────────────────────────────────

function changeToColor(pct) {
  if (pct == null) return '#334155'
  if (pct >= 5)  return '#b91c1c'
  if (pct >= 3)  return '#dc2626'
  if (pct >= 1)  return '#ef4444'
  if (pct >= 0)  return '#f87171'
  if (pct >= -1) return '#4ade80'
  if (pct >= -3) return '#22c55e'
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
      itemStyle: { borderColor: '#0f172a', borderWidth: 2 },
      emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 } },
      data: boards
        .filter(b => b.market_cap != null && b.market_cap > 0)
        .map(b => ({
          name:         b.name,
          value:        b.market_cap,
          change_pct:   b.change_pct,
          up_count:     b.up_count,
          down_count:   b.down_count,
          turnover_rate: b.turnover_rate,
          itemStyle:    { color: changeToColor(b.change_pct) },
        })),
    }],
  }
})

const inflowOption = computed(() => {
  if (!flowData.value.length) return null
  const top10 = [...flowData.value]
    .filter(b => (b.net_flow ?? 0) > 0)
    .slice(0, 10)
    .reverse()
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>净流入: ${(p[0].value / 10000).toFixed(0)}万` },
    grid: { left: 80, right: 20, top: 8, bottom: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (v/10000).toFixed(0)+'w' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    yAxis: { type: 'category', data: top10.map(b => b.name), axisLabel: { color: '#a0aec0', fontSize: 11 } },
    series: [{ type: 'bar', data: top10.map(b => ({ value: b.net_flow, itemStyle: { color: '#ef4444' } })), barMaxWidth: 20 }],
  }
})

const outflowOption = computed(() => {
  if (!flowData.value.length) return null
  const bottom10 = [...flowData.value]
    .filter(b => (b.net_flow ?? 0) < 0)
    .slice(-10)
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>净流出: ${(Math.abs(p[0].value) / 10000).toFixed(0)}万` },
    grid: { left: 80, right: 20, top: 8, bottom: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (Math.abs(v)/10000).toFixed(0)+'w' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    yAxis: { type: 'category', data: bottom10.map(b => b.name), axisLabel: { color: '#a0aec0', fontSize: 11 } },
    series: [{ type: 'bar', data: bottom10.map(b => ({ value: b.net_flow, itemStyle: { color: '#22c55e' } })), barMaxWidth: 20 }],
  }
})

onMounted(() => {
  loadBoards('industry')
})
</script>

<style scoped>
.sector-view { padding: 24px; display: flex; flex-direction: column; gap: 14px; }

/* Tabs */
.view-tabs { display: flex; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; align-self: flex-start; }
.view-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.view-tab:hover { color: var(--text-1); }
.view-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(0,0,0,0.3); }

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
.sort-chips { display: flex; gap: 4px; }
.sort-chip { font-size: 11px; padding: 3px 9px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 4px; color: var(--text-3); cursor: pointer; transition: all 0.12s; white-space: nowrap; }
.sort-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }

/* Board layout */
.board-layout { display: grid; grid-template-columns: 320px 1fr; gap: 14px; align-items: start; }

.board-list { overflow: hidden; }
.board-list-inner { max-height: 560px; overflow-y: auto; }

.board-row { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.board-row:last-child { border-bottom: none; }
.board-row:hover { background: var(--bg-hover); }
.board-row.selected { background: var(--accent-dim); border-left: 3px solid var(--accent); padding-left: 11px; }
.board-row-main { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.board-name { font-size: 13px; font-weight: 600; color: var(--text-1); }
.board-chg { font-size: 13px; font-weight: 700; font-family: var(--font-mono); }
.board-chg.up { color: #f87171; }
.board-chg.down { color: #4ade80; }
.board-row-meta { display: flex; gap: 10px; flex-wrap: wrap; }
.leader-tag { font-size: 10px; color: var(--text-3); }
.up { color: #f87171; }
.down { color: #4ade80; }

/* Stocks panel */
.stocks-panel { display: flex; flex-direction: column; gap: 10px; }
.empty-stocks { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 60px; text-align: center; }
.stocks-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; }
.stocks-table-wrap { overflow-x: auto; max-height: 500px; overflow-y: auto; }
.stock-name { font-size: 13px; color: var(--text-1); }
.action-link { font-size: 11px; padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); text-decoration: none; white-space: nowrap; transition: all 0.12s; }
.action-link:hover { border-color: var(--accent); color: var(--accent); }

/* Fund flow */
.flow-header { display: flex; align-items: center; gap: 14px; padding: 12px 16px; flex-wrap: wrap; }
.indicator-chips { display: flex; gap: 4px; }
.ind-chip { font-size: 12px; padding: 4px 12px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 20px; color: var(--text-2); cursor: pointer; transition: all 0.12s; }
.ind-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); font-weight: 600; }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.flow-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.row-inflow { background: rgba(239, 68, 68, 0.03); }
.row-outflow { background: rgba(34, 197, 94, 0.03); }

@media (max-width: 768px) {
  .board-layout { grid-template-columns: 1fr; }
  .flow-charts { grid-template-columns: 1fr; }
}
</style>
