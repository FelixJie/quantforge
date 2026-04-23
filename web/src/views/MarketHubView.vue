<template>
  <div class="market-hub">

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="hub-tabs">
      <button :class="['hub-tab', tab === 'overview' ? 'active' : '']" @click="switchTab('overview')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
        大盘行情
      </button>
      <button :class="['hub-tab', tab === 'sector' ? 'active' : '']" @click="switchTab('sector')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        板块分析
      </button>
      <button :class="['hub-tab', tab === 'news' ? 'active' : '']" @click="switchTab('news')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/></svg>
        消息情绪
      </button>
      <div class="tab-spacer"></div>
      <button class="btn-refresh" @click="refreshCurrent" :disabled="isLoading">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: isLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <!-- ════════════ TAB: 大盘行情 ════════════ -->
    <template v-if="tab === 'overview'">

      <!-- Index cards -->
      <div class="index-row">
        <div v-for="idx in indices" :key="idx.code" :class="['index-card', pctClass(idx.change_pct)]">
          <div class="idx-name">{{ idx.name }}</div>
          <div class="idx-price">{{ idx.price != null ? idx.price.toFixed(2) : '--' }}</div>
          <div class="idx-change">
            <span class="idx-pct" :class="pctClass(idx.change_pct)">
              {{ idx.change_pct != null ? (idx.change_pct > 0 ? '+' : '') + idx.change_pct.toFixed(2) + '%' : '--' }}
            </span>
            <span class="idx-abs" v-if="idx.change != null">
              {{ idx.change > 0 ? '+' : '' }}{{ idx.change.toFixed(2) }}
            </span>
          </div>
          <div class="idx-vol" v-if="idx.volume">成交 {{ fmtVol(idx.volume) }}</div>
        </div>
        <div v-if="!indices.length && !loadingIndices" class="index-card idx-empty">暂无数据</div>
        <div v-if="loadingIndices" class="index-card idx-empty">
          <span class="spinner spinner-sm"></span>
        </div>
      </div>

      <!-- Breadth + Movers -->
      <div class="two-col">

        <!-- Market breadth -->
        <div class="panel">
          <div class="panel-title">市场宽度</div>
          <div v-if="loadingBreadth" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else-if="breadth" class="breadth-body">
            <div class="breadth-bar-wrap">
              <div class="breadth-bar">
                <div class="seg seg-up"   :style="{ flex: breadth.up_count }"></div>
                <div class="seg seg-flat" :style="{ flex: breadth.flat_count }"></div>
                <div class="seg seg-down" :style="{ flex: breadth.down_count }"></div>
              </div>
              <div class="breadth-leg">
                <span class="leg-up">▲ 上涨 {{ breadth.up_count }}</span>
                <span class="leg-flat">— 平 {{ breadth.flat_count }}</span>
                <span class="leg-down">▼ 下跌 {{ breadth.down_count }}</span>
              </div>
            </div>
            <div class="breadth-stats">
              <div class="bstat"><div class="bstat-val up">{{ breadth.limit_up ?? '--' }}</div><div class="bstat-lbl">涨停</div></div>
              <div class="bstat"><div class="bstat-val down">{{ breadth.limit_down ?? '--' }}</div><div class="bstat-lbl">跌停</div></div>
              <div class="bstat"><div class="bstat-val">{{ breadth.total ?? '--' }}</div><div class="bstat-lbl">全市场</div></div>
              <div class="bstat">
                <div class="bstat-val" :class="(breadth.advance_decline_ratio ?? 0) > 1 ? 'up' : 'down'">
                  {{ breadth.advance_decline_ratio != null ? breadth.advance_decline_ratio.toFixed(2) : '--' }}
                </div>
                <div class="bstat-lbl">涨跌比</div>
              </div>
            </div>
          </div>
          <div v-else class="panel-empty">暂无宽度数据</div>
        </div>

        <!-- Movers -->
        <div class="panel">
          <div class="panel-title">
            涨跌榜
            <div class="mover-tabs">
              <button :class="['mtab', moverMode === 'up' ? 'active' : '']" @click="moverMode = 'up'">涨幅</button>
              <button :class="['mtab', moverMode === 'down' ? 'active' : '']" @click="moverMode = 'down'">跌幅</button>
            </div>
          </div>
          <div v-if="loadingMovers" class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
          <div v-else class="movers-list">
            <div v-for="s in displayMovers" :key="s.code" class="mover-row">
              <div class="mover-stock">
                <router-link :to="'/stock-analysis?symbol=' + s.code" class="mover-name">{{ s.name }}</router-link>
                <span class="mover-code">{{ s.code }}</span>
              </div>
              <div class="mover-price mono">{{ s.price != null ? s.price.toFixed(2) : '--' }}</div>
              <div :class="['mover-pct', s.change_pct >= 0 ? 'up' : 'down']">
                {{ s.change_pct != null ? (s.change_pct > 0 ? '+' : '') + s.change_pct.toFixed(2) + '%' : '--' }}
              </div>
            </div>
            <div v-if="!displayMovers.length" class="panel-empty">暂无数据</div>
          </div>
        </div>

      </div>

      <!-- Sector mini-heatmap -->
      <div class="panel">
        <div class="panel-title">
          行业板块速览
          <span class="panel-hint">点击板块查看详情</span>
        </div>
        <div v-if="loadingSectorMini" class="panel-loading"><span class="spinner spinner-sm"></span></div>
        <div v-else-if="sectorMini.length" class="sector-tiles">
          <div
            v-for="s in sectorMini" :key="s.name"
            :class="['stile', (s.change_pct ?? 0) >= 0 ? 'up' : 'down']"
            :style="{ opacity: tileOpacity(s.change_pct) }"
            @click="goSector(s.name)"
            :title="s.name + ' ' + fmtPct(s.change_pct)"
          >
            <div class="stile-name">{{ s.name }}</div>
            <div class="stile-pct">{{ fmtPct(s.change_pct) }}</div>
          </div>
        </div>
        <div v-else class="panel-empty">暂无板块数据</div>
      </div>

    </template>

    <!-- ════════════ TAB: 板块分析 ════════════ -->
    <template v-if="tab === 'sector'">

      <!-- Sub-tabs -->
      <div class="sub-tabs">
        <button :class="['sub-tab', sectorTab === 'industry' ? 'active' : '']" @click="switchSectorTab('industry')">行业板块</button>
        <button :class="['sub-tab', sectorTab === 'concept' ? 'active' : '']" @click="switchSectorTab('concept')">概念板块</button>
        <button :class="['sub-tab', sectorTab === 'flow' ? 'active' : '']" @click="switchSectorTab('flow')">资金流向</button>
      </div>

      <!-- Industry / Concept shared layout -->
      <template v-if="sectorTab !== 'flow'">
        <div v-if="loadingBoards" class="panel"><div class="panel-loading"><span class="spinner spinner-sm"></span> 加载{{ sectorTab === 'industry' ? '行业' : '概念' }}板块...</div></div>

        <template v-if="!loadingBoards && currentBoards.length">
          <!-- Treemap -->
          <div class="panel chart-panel">
            <div class="panel-title">
              {{ sectorTab === 'industry' ? '行业' : '概念' }}板块热力图
              <span class="panel-hint">面积=市值，颜色=涨跌幅，点击查看成分股</span>
            </div>
            <v-chart :option="treemapOption" autoresize style="height:320px" @click="onTreemapClick" />
          </div>

          <!-- Controls + board list + stocks panel -->
          <div class="board-controls panel">
            <div class="board-search-wrap">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input class="board-search" v-model="boardQuery" placeholder="搜索板块名称..." />
            </div>
            <div class="sort-chips">
              <button v-for="s in sortOpts" :key="s.key"
                :class="['sort-chip', sortKey === s.key ? 'active' : '']"
                @click="toggleSort(s.key)">
                {{ s.label }}{{ sortKey === s.key ? (sortAsc ? ' ↑' : ' ↓') : '' }}
              </button>
            </div>
            <span class="count-hint">共 {{ currentBoards.length }} 个板块</span>
          </div>

          <div class="board-layout">
            <div class="board-list panel">
              <div class="board-list-inner">
                <div v-for="b in filteredSortedBoards" :key="b.name"
                  :class="['board-row', selectedBoard === b.name ? 'selected' : '']"
                  @click="selectBoard(b.name)">
                  <div class="board-row-main">
                    <span class="board-name">{{ b.name }}</span>
                    <span :class="['board-chg', (b.change_pct ?? 0) >= 0 ? 'up' : 'down']">{{ fmtPct(b.change_pct) }}</span>
                  </div>
                  <div class="board-row-meta">
                    <span class="text-3">↑{{ b.up_count }} ↓{{ b.down_count }}</span>
                    <span class="text-3">换手 {{ b.turnover_rate?.toFixed(2) ?? '—' }}%</span>
                    <span v-if="b.leader" class="leader-tag">{{ b.leader }}
                      <span :class="(b.leader_change ?? 0) >= 0 ? 'up' : 'down'">{{ fmtPct(b.leader_change) }}</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div class="stocks-panel">
              <div v-if="!selectedBoard" class="panel empty-stocks">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <span class="text-3">点击左侧板块查看成分股</span>
              </div>
              <div v-else-if="loadingStocks" class="panel empty-stocks">
                <span class="spinner spinner-sm"></span>
                <span class="text-2">加载 {{ selectedBoard }} 成分股...</span>
              </div>
              <template v-else-if="boardStocks.length">
                <div class="panel stocks-header">
                  <span class="fw-600">{{ selectedBoard }}</span>
                  <span class="text-3">{{ boardStocks.length }} 只</span>
                </div>
                <div class="panel stocks-table-wrap">
                  <table class="data-table">
                    <thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌%</th><th>换手率</th><th>PE</th><th>PB</th><th></th></tr></thead>
                    <tbody>
                      <tr v-for="s in boardStocks" :key="s.code">
                        <td><span class="mono accent">{{ s.code }}</span></td>
                        <td>{{ s.name }}</td>
                        <td class="mono">{{ s.price?.toFixed(2) ?? '—' }}</td>
                        <td :class="(s.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">{{ fmtPct(s.change_pct) }}</td>
                        <td class="mono text-3">{{ s.turnover_rate?.toFixed(2) ?? '—' }}%</td>
                        <td class="mono text-3">{{ s.pe?.toFixed(1) ?? '—' }}</td>
                        <td class="mono text-3">{{ s.pb?.toFixed(2) ?? '—' }}</td>
                        <td>
                          <router-link :to="'/stock-analysis?symbol=' + s.code" class="action-link">分析</router-link>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
              <div v-else class="panel empty-stocks"><span class="text-3">暂无成分股数据</span></div>
            </div>
          </div>
        </template>
      </template>

      <!-- Fund flow tab -->
      <template v-if="sectorTab === 'flow'">
        <div class="panel flow-header-row">
          <span class="fw-600">行业资金流向</span>
          <div class="ind-chips">
            <button v-for="ind in ['今日', '5日', '10日']" :key="ind"
              :class="['ind-chip', flowIndicator === ind ? 'active' : '']"
              @click="switchFlowIndicator(ind)">{{ ind }}</button>
          </div>
          <button class="btn-ghost btn-sm" @click="loadFlow" :disabled="loadingFlow">
            <span v-if="loadingFlow" class="spinner spinner-sm"></span>
            <span v-else>刷新</span>
          </button>
        </div>

        <div v-if="loadingFlow" class="panel panel-loading"><span class="spinner spinner-sm"></span> 加载资金流向...</div>
        <div v-if="!loadingFlow && flowError" class="error-box">{{ flowError }}</div>

        <template v-if="!loadingFlow && flowData.length">
          <div class="flow-charts">
            <div class="panel chart-panel">
              <div class="panel-title">净流入 Top 10</div>
              <v-chart :option="inflowOption" autoresize style="height:260px" />
            </div>
            <div class="panel chart-panel">
              <div class="panel-title">净流出 Top 10</div>
              <v-chart :option="outflowOption" autoresize style="height:260px" />
            </div>
          </div>
          <div class="panel">
            <div class="table-wrap">
              <table class="data-table">
                <thead><tr><th>排名</th><th>板块</th><th>净流入(万)</th><th>净流入%</th><th>主力净流入</th><th>涨跌%</th></tr></thead>
                <tbody>
                  <tr v-for="b in flowData" :key="b.name" :class="(b.net_flow ?? 0) >= 0 ? 'row-in' : 'row-out'">
                    <td class="text-3">{{ b.rank }}</td>
                    <td class="fw-600">{{ b.name }}</td>
                    <td :class="(b.net_flow ?? 0) >= 0 ? 'pos' : 'neg'">
                      {{ b.net_flow != null ? ((b.net_flow >= 0 ? '+' : '') + (b.net_flow/10000).toFixed(0) + '万') : '—' }}
                    </td>
                    <td :class="(b.net_flow_pct ?? 0) >= 0 ? 'pos' : 'neg'">{{ fmtPct(b.net_flow_pct) }}</td>
                    <td :class="(b.main_flow ?? 0) >= 0 ? 'pos' : 'neg'">
                      {{ b.main_flow != null ? ((b.main_flow >= 0 ? '+' : '') + (b.main_flow/10000).toFixed(0) + '万') : '—' }}
                    </td>
                    <td :class="(b.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">{{ fmtPct(b.change_pct) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </template>

    </template>

    <!-- ════════════ TAB: 消息情绪 ════════════ -->
    <template v-if="tab === 'news'">

      <!-- Sentiment banner -->
      <div class="panel sentiment-bar" v-if="sentiment">
        <div class="sent-group">
          <span class="sent-label">市场情绪</span>
          <span class="sent-score" :class="sentimentClass">{{ sentiment.label }}</span>
          <span class="sent-detail">
            <span class="pos">↑ {{ sentiment.positive }}</span>
            <span class="neg">↓ {{ sentiment.negative }}</span>
            <span class="neu">— {{ sentiment.neutral }}</span>
          </span>
        </div>
        <div class="sent-headlines" v-if="sentiment.recent_headlines?.length">
          <span class="h-chip" v-for="h in sentiment.recent_headlines" :key="h">{{ h }}</span>
        </div>
        <span class="sent-time text-3">{{ sentiment.updated_at?.slice(11,16) }} 更新</span>
      </div>

      <div class="news-layout">
        <!-- Left: market flash -->
        <div class="col-main">
          <div class="panel col-head">
            <span class="col-title">市场快讯</span>
            <div class="col-actions">
              <button class="btn-ghost btn-sm" @click="loadAISummary(null)" :disabled="aiLoading && !aiSymbol">
                <span v-if="aiLoading && !aiSymbol" class="spinner spinner-sm"></span>
                <span v-else>✨ AI总结</span>
              </button>
              <button class="btn-ghost btn-sm" @click="loadMarket" :disabled="loadingMarket">
                <span v-if="loadingMarket" class="spinner spinner-sm"></span>
                <span v-else>刷新</span>
              </button>
            </div>
          </div>

          <div v-if="aiSummary && !aiSymbol" class="panel ai-panel">
            <div class="ai-head">
              <span class="ai-tag">✨ AI 市场分析</span>
              <span class="text-3 tiny">{{ aiSummary.generated_at?.slice(11,19) }}</span>
            </div>
            <p class="ai-body">{{ aiSummary.summary }}</p>
          </div>

          <div v-if="loadingMarket && !marketItems.length" class="panel panel-loading">
            <span class="spinner"></span><span class="text-2">加载中...</span>
          </div>
          <div v-else-if="marketItems.length" class="panel news-list">
            <div v-for="item in marketItems" :key="item.title + item.date" class="news-item" @click="item._expanded = !item._expanded">
              <div class="ni-row">
                <span :class="['sdot', item.sentiment]"></span>
                <span class="ni-title">{{ item.title }}</span>
                <span class="ni-meta">
                  <span class="ni-source" v-if="item.source">{{ item.source }}</span>
                  <span class="ni-time">{{ item.date?.slice(5) }} {{ item.time }}</span>
                </span>
              </div>
              <div v-if="item._expanded && item.content" class="ni-content">{{ item.content }}</div>
            </div>
          </div>
          <div v-else-if="!loadingMarket" class="panel empty-card"><span class="text-3">暂无数据，点击刷新重试</span></div>
        </div>

        <!-- Right: stock news search -->
        <div class="col-side">
          <div class="panel col-head">
            <span class="col-title">个股资讯</span>
            <div class="stock-search">
              <input class="input input-sm" v-model="searchSym" placeholder="如 000001"
                     @keyup.enter="loadStock" maxlength="6" />
              <button class="btn-ghost btn-sm" @click="loadAISummary(searchSym)" :disabled="aiLoading || !searchSym" title="AI分析">✨</button>
              <button class="btn-primary btn-sm" @click="loadStock" :disabled="loadingStock || !searchSym">
                <span v-if="loadingStock" class="spinner spinner-sm"></span>
                <span v-else>查</span>
              </button>
            </div>
          </div>

          <div v-if="aiSummary && aiSymbol === searchSym" class="panel ai-panel">
            <div class="ai-head">
              <span class="ai-tag">✨ {{ searchSym }} AI分析</span>
              <span class="text-3 tiny">{{ aiSummary.generated_at?.slice(11,19) }}</span>
            </div>
            <p class="ai-body">{{ aiSummary.summary }}</p>
          </div>

          <div v-if="loadingStock" class="panel panel-loading">
            <span class="spinner"></span><span class="text-2">查询中...</span>
          </div>
          <div v-else-if="stockItems.length" class="panel news-list">
            <div class="list-header text-3">{{ searchSym }} · {{ stockItems.length }} 条资讯</div>
            <div v-for="item in stockItems" :key="item.title + item.date" class="news-item" @click="item._expanded = !item._expanded">
              <div class="ni-row">
                <span :class="['sdot', item.sentiment]"></span>
                <span class="ni-title">{{ item.title }}</span>
                <span class="ni-meta"><span class="ni-time">{{ item.date?.slice(5) }} {{ item.time }}</span></span>
              </div>
              <div v-if="item._expanded && item.content" class="ni-content">{{ item.content }}</div>
            </div>
          </div>
          <div v-else-if="stockQueried && !loadingStock" class="panel empty-card">
            <span class="text-3">未查到 {{ searchSym }} 的资讯</span>
          </div>
          <div v-else class="panel empty-card"><span class="text-3">输入股票代码查询资讯</span></div>
        </div>
      </div>

    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

const route  = useRoute()
const router = useRouter()

// ── Active tab ────────────────────────────────────────────────
const tab = ref('overview')

// ── Tab 1: 大盘行情 ───────────────────────────────────────────
const indices        = ref([])
const breadth        = ref(null)
const topMovers      = ref([])
const sectorMini     = ref([])
const moverMode      = ref('up')
const loadingIndices = ref(false)
const loadingBreadth = ref(false)
const loadingMovers  = ref(false)
const loadingSectorMini = ref(false)

const displayMovers = computed(() =>
  moverMode.value === 'up'
    ? [...topMovers.value].sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)).slice(0, 12)
    : [...topMovers.value].sort((a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0)).slice(0, 12)
)

// ── Tab 2: 板块分析 ───────────────────────────────────────────
const sectorTab      = ref('industry')
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

const sortOpts = [
  { key: 'change_pct',    label: '涨跌幅' },
  { key: 'turnover_rate', label: '换手率' },
  { key: 'up_count',      label: '上涨家数' },
  { key: 'market_cap',    label: '总市值' },
]

const currentBoards = computed(() =>
  sectorTab.value === 'industry' ? industryBoards.value : conceptBoards.value
)

const filteredSortedBoards = computed(() => {
  let arr = currentBoards.value
  if (boardQuery.value.trim()) arr = arr.filter(b => b.name?.includes(boardQuery.value.trim()))
  return [...arr].sort((a, b) => {
    const av = a[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    const bv = b[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    return sortAsc.value ? av - bv : bv - av
  })
})

const treemapOption = computed(() => {
  const boards = currentBoards.value
  if (!boards.length) return null
  return {
    backgroundColor: 'transparent',
    tooltip: {
      formatter: p => {
        const d = p.data
        return `<b>${d.name}</b><br/>涨跌：${fmtPct(d.change_pct)}<br/>上涨：${d.up_count} 下跌：${d.down_count}<br/>换手：${d.turnover_rate?.toFixed(2) ?? '—'}%`
      }
    },
    series: [{
      type: 'treemap', width: '100%', height: '100%', roam: false, nodeClick: false,
      breadcrumb: { show: false },
      label: {
        show: true, fontSize: 11, color: '#fff',
        formatter: p => `{n|${p.data.name}}\n{c|${fmtPct(p.data.change_pct)}}`,
        rich: { n: { fontSize: 11, fontWeight: 700, color: '#fff' }, c: { fontSize: 10, color: 'rgba(255,255,255,0.85)' } },
      },
      itemStyle: { borderColor: '#0f172a', borderWidth: 2 },
      emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 2 } },
      data: boards.filter(b => b.market_cap > 0).map(b => ({
        name: b.name, value: b.market_cap,
        change_pct: b.change_pct, up_count: b.up_count, down_count: b.down_count, turnover_rate: b.turnover_rate,
        itemStyle: { color: pctColor(b.change_pct) },
      })),
    }],
  }
})

const inflowOption = computed(() => {
  if (!flowData.value.length) return null
  const top10 = [...flowData.value].filter(b => (b.net_flow ?? 0) > 0).slice(0, 10).reverse()
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>净流入: ${(p[0].value/10000).toFixed(0)}万` },
    grid: { left: 80, right: 20, top: 8, bottom: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (v/10000).toFixed(0)+'w' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    yAxis: { type: 'category', data: top10.map(b => b.name), axisLabel: { color: '#a0aec0', fontSize: 11 } },
    series: [{ type: 'bar', data: top10.map(b => ({ value: b.net_flow, itemStyle: { color: '#ef4444' } })), barMaxWidth: 20 }],
  }
})

const outflowOption = computed(() => {
  if (!flowData.value.length) return null
  const bottom10 = [...flowData.value].filter(b => (b.net_flow ?? 0) < 0).slice(-10)
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', formatter: p => `${p[0].name}<br/>净流出: ${(Math.abs(p[0].value)/10000).toFixed(0)}万` },
    grid: { left: 80, right: 20, top: 8, bottom: 8 },
    xAxis: { type: 'value', axisLabel: { color: '#718096', fontSize: 10, formatter: v => (Math.abs(v)/10000).toFixed(0)+'w' }, splitLine: { lineStyle: { color: '#1a2035' } } },
    yAxis: { type: 'category', data: bottom10.map(b => b.name), axisLabel: { color: '#a0aec0', fontSize: 11 } },
    series: [{ type: 'bar', data: bottom10.map(b => ({ value: b.net_flow, itemStyle: { color: '#22c55e' } })), barMaxWidth: 20 }],
  }
})

// ── Tab 3: 消息情绪 ───────────────────────────────────────────
const sentiment    = ref(null)
const marketItems  = ref([])
const loadingMarket = ref(false)
const searchSym    = ref('')
const stockItems   = ref([])
const loadingStock = ref(false)
const stockQueried = ref(false)
const aiSummary    = ref(null)
const aiLoading    = ref(false)
const aiSymbol     = ref(null)
let newsTimer = null

const sentimentClass = computed(() => {
  const s = sentiment.value?.score ?? 0
  return s > 10 ? 'pos' : s < -10 ? 'neg' : 'neu'
})

// ── Global loading indicator ───────────────────────────────────
const isLoading = computed(() =>
  loadingIndices.value || loadingBreadth.value || loadingMovers.value ||
  loadingSectorMini.value || loadingBoards.value || loadingFlow.value || loadingMarket.value
)

// ── Data loaders ──────────────────────────────────────────────

async function loadIndices() {
  loadingIndices.value = true
  try {
    const res = await axios.get('/api/market/indices')
    indices.value = res.data.indices || []
  } catch { indices.value = [] } finally { loadingIndices.value = false }
}

async function loadBreadth() {
  loadingBreadth.value = true
  try {
    const res = await axios.get('/api/market/breadth')
    breadth.value = res.data
  } catch { breadth.value = null } finally { loadingBreadth.value = false }
}

async function loadMovers() {
  loadingMovers.value = true
  try {
    const res = await axios.get('/api/market/movers')
    topMovers.value = res.data.stocks || []
  } catch { topMovers.value = [] } finally { loadingMovers.value = false }
}

async function loadSectorMini() {
  loadingSectorMini.value = true
  try {
    const res = await axios.get('/api/sector/industry')
    sectorMini.value = (res.data.boards || []).slice(0, 36)
  } catch { sectorMini.value = [] } finally { loadingSectorMini.value = false }
}

async function loadBoards(type) {
  loadingBoards.value = true
  try {
    const res = await axios.get(`/api/sector/${type}`)
    if (type === 'industry') industryBoards.value = res.data.boards || []
    else                     conceptBoards.value  = res.data.boards || []
  } catch {} finally { loadingBoards.value = false }
}

async function selectBoard(name) {
  if (selectedBoard.value === name) { selectedBoard.value = ''; boardStocks.value = []; return }
  selectedBoard.value = name
  loadingStocks.value = true
  boardStocks.value = []
  try {
    const res = await axios.get(`/api/sector/${sectorTab.value}/${encodeURIComponent(name)}`)
    boardStocks.value = res.data.stocks || []
  } catch {} finally { loadingStocks.value = false }
}

function onTreemapClick(params) {
  if (params.data?.name) selectBoard(params.data.name)
}

async function loadFlow() {
  loadingFlow.value = true; flowError.value = ''
  try {
    const res = await axios.get('/api/sector/fund-flow', { params: { indicator: flowIndicator.value } })
    flowData.value = res.data.boards || []
  } catch (e) {
    flowError.value = e.response?.data?.detail || '资金流向数据获取失败（非交易时间可能无数据）'
  } finally { loadingFlow.value = false }
}

async function switchFlowIndicator(ind) {
  flowIndicator.value = ind
  await loadFlow()
}

function toggleSort(key) {
  if (sortKey.value === key) sortAsc.value = !sortAsc.value
  else { sortKey.value = key; sortAsc.value = false }
}

async function switchSectorTab(t) {
  sectorTab.value = t
  selectedBoard.value = ''
  boardStocks.value = []
  if (t === 'industry' && !industryBoards.value.length) await loadBoards('industry')
  if (t === 'concept'  && !conceptBoards.value.length)  await loadBoards('concept')
  if (t === 'flow'     && !flowData.value.length)        await loadFlow()
}

async function loadSentiment() {
  try { const res = await axios.get('/api/news/sentiment'); sentiment.value = res.data } catch {}
}

async function loadMarket() {
  loadingMarket.value = true
  try {
    const res = await axios.get('/api/news/market', { params: { count: 30 } })
    marketItems.value = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
  } catch {} finally { loadingMarket.value = false }
}

async function loadStock() {
  if (!searchSym.value) return
  loadingStock.value = true; stockQueried.value = true; stockItems.value = []
  try {
    const res = await axios.get(`/api/news/stock/${searchSym.value}`, { params: { count: 20 } })
    stockItems.value = (res.data.items || []).map(i => ({ ...i, _expanded: false }))
  } catch {} finally { loadingStock.value = false }
}

async function loadAISummary(sym) {
  aiLoading.value = true; aiSymbol.value = sym; aiSummary.value = null
  try {
    const res = await axios.post('/api/news/ai-summary', null, { params: sym ? { symbol: sym } : {} })
    aiSummary.value = res.data
  } catch (e) {
    aiSummary.value = { summary: 'AI分析失败: ' + (e.response?.data?.detail || e.message) }
  } finally { aiLoading.value = false }
}

// ── Tab switching ─────────────────────────────────────────────

async function switchTab(t) {
  tab.value = t
  if (t === 'overview' && !indices.value.length) {
    await Promise.allSettled([loadIndices(), loadBreadth(), loadMovers(), loadSectorMini()])
  }
  if (t === 'sector' && !industryBoards.value.length) {
    await loadBoards('industry')
  }
  if (t === 'news' && !marketItems.value.length) {
    await Promise.allSettled([loadSentiment(), loadMarket()])
    newsTimer = setInterval(() => { loadSentiment(); loadMarket() }, 120000)
  }
}

function refreshCurrent() {
  if (tab.value === 'overview') {
    indices.value = []; breadth.value = null; topMovers.value = []; sectorMini.value = []
    Promise.allSettled([loadIndices(), loadBreadth(), loadMovers(), loadSectorMini()])
  } else if (tab.value === 'sector') {
    if (sectorTab.value === 'flow') loadFlow()
    else {
      if (sectorTab.value === 'industry') { industryBoards.value = []; loadBoards('industry') }
      else { conceptBoards.value = []; loadBoards('concept') }
    }
  } else if (tab.value === 'news') {
    loadSentiment(); loadMarket()
  }
}

// Navigate to sector tab and select a board
function goSector(name) {
  tab.value = 'sector'
  sectorTab.value = 'industry'
  if (!industryBoards.value.length) {
    loadBoards('industry').then(() => selectBoard(name))
  } else {
    selectBoard(name)
  }
}

// ── Helpers ───────────────────────────────────────────────────

function pctClass(pct) {
  if (pct == null) return ''
  return pct > 0 ? 'up' : pct < 0 ? 'down' : ''
}

function fmtPct(v) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'
}

function fmtVol(v) {
  if (!v) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toString()
}

function tileOpacity(pct) {
  const abs = Math.min(Math.abs(pct ?? 0), 6)
  return 0.3 + (abs / 6) * 0.7
}

function pctColor(pct) {
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

// ── Init ──────────────────────────────────────────────────────

onMounted(async () => {
  // Check if we should start on a specific tab from query params
  const initTab = route.query.tab
  if (initTab === 'sector' || initTab === 'news') {
    await switchTab(initTab)
  } else {
    await Promise.allSettled([loadIndices(), loadBreadth(), loadMovers(), loadSectorMini()])
  }
})

onUnmounted(() => {
  if (newsTimer) clearInterval(newsTimer)
})
</script>

<style scoped>
.market-hub { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; min-height: 100%; }

/* ── Tab bar ── */
.hub-tabs { display: flex; align-items: center; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; align-self: flex-start; width: 100%; }
.hub-tab { display: flex; align-items: center; gap: 6px; padding: 7px 16px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.hub-tab:hover { color: var(--text-1); }
.hub-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
.tab-spacer { flex: 1; }
.btn-refresh { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border); background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; }
.btn-refresh:hover { border-color: var(--accent); color: var(--accent); }
.btn-refresh:disabled { opacity: 0.5; cursor: default; }
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin 1s linear infinite; }

/* ── Panel base ── */
.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; }
.panel-title { font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.panel-hint { font-size: 11px; color: var(--text-3); font-weight: 400; }
.panel-loading { font-size: 12px; color: var(--text-3); padding: 16px 0; text-align: center; display: flex; align-items: center; justify-content: center; gap: 6px; }
.panel-empty { font-size: 12px; color: var(--text-3); padding: 20px 0; text-align: center; }
.chart-panel { padding: 14px; }
.error-box { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #f87171; border-radius: var(--radius-md); padding: 10px 14px; font-size: 13px; }

/* ── Index row ── */
.index-row { display: flex; gap: 12px; flex-wrap: wrap; }
.index-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px 20px; min-width: 150px; flex: 1; }
.index-card.up   { border-color: rgba(239,68,68,0.3); }
.index-card.down { border-color: rgba(34,197,94,0.3); }
.idx-name  { font-size: 12px; color: var(--text-3); margin-bottom: 6px; }
.idx-price { font-size: 22px; font-weight: 700; color: var(--text-1); }
.idx-change { display: flex; align-items: baseline; gap: 6px; margin-top: 4px; }
.idx-pct { font-size: 14px; font-weight: 700; }
.idx-pct.up   { color: #ef4444; }
.idx-pct.down { color: #22c55e; }
.idx-abs { font-size: 12px; color: var(--text-3); }
.idx-vol { font-size: 11px; color: var(--text-3); margin-top: 6px; }
.idx-empty { display: flex; align-items: center; justify-content: center; font-size: 12px; color: var(--text-3); }

/* ── Two-col ── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 860px) { .two-col { grid-template-columns: 1fr; } }

/* ── Breadth ── */
.breadth-body { display: flex; flex-direction: column; gap: 14px; }
.breadth-bar-wrap { display: flex; flex-direction: column; gap: 8px; }
.breadth-bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden; gap: 2px; }
.seg { min-width: 4px; }
.seg-up   { background: #ef4444; }
.seg-flat { background: var(--border); }
.seg-down { background: #22c55e; }
.breadth-leg { display: flex; gap: 12px; font-size: 11px; }
.leg-up   { color: #ef4444; }
.leg-flat { color: var(--text-3); }
.leg-down { color: #22c55e; }
.breadth-stats { display: flex; gap: 20px; }
.bstat { text-align: center; }
.bstat-val { font-size: 20px; font-weight: 700; color: var(--text-1); }
.bstat-val.up   { color: #ef4444; }
.bstat-val.down { color: #22c55e; }
.bstat-lbl { font-size: 11px; color: var(--text-3); margin-top: 2px; }

/* ── Movers ── */
.mover-tabs { display: flex; gap: 4px; background: var(--bg-hover); border-radius: 6px; padding: 2px; }
.mtab { padding: 3px 10px; border-radius: 4px; border: none; background: transparent; color: var(--text-2); font-size: 11px; cursor: pointer; }
.mtab.active { background: var(--bg-surface); color: var(--accent); }
.movers-list { display: flex; flex-direction: column; gap: 2px; }
.mover-row { display: flex; align-items: center; gap: 8px; padding: 6px 6px; border-radius: var(--radius-sm); }
.mover-row:hover { background: var(--bg-hover); }
.mover-stock { flex: 1; }
.mover-name { font-size: 13px; font-weight: 500; color: var(--text-1); text-decoration: none; }
.mover-name:hover { color: var(--accent); }
.mover-code { font-size: 10px; color: var(--text-3); margin-left: 4px; }
.mover-price { font-size: 13px; color: var(--text-2); font-family: var(--font-mono); min-width: 54px; text-align: right; }
.mover-pct { font-size: 13px; font-weight: 700; min-width: 58px; text-align: right; }
.mover-pct.up   { color: #ef4444; }
.mover-pct.down { color: #22c55e; }

/* ── Sector mini tiles ── */
.sector-tiles { display: flex; flex-wrap: wrap; gap: 7px; }
.stile { padding: 7px 11px; border-radius: var(--radius-md); min-width: 78px; display: flex; flex-direction: column; align-items: center; gap: 3px; cursor: pointer; transition: transform 0.1s; }
.stile:hover { transform: scale(1.04); }
.stile.up   { background: rgba(239,68,68,0.15); }
.stile.down { background: rgba(34,197,94,0.15); }
.stile-name { font-size: 11px; color: var(--text-1); white-space: nowrap; }
.stile-pct  { font-size: 12px; font-weight: 700; }
.stile.up   .stile-pct { color: #ef4444; }
.stile.down .stile-pct { color: #22c55e; }

/* ── Sub-tabs ── */
.sub-tabs { display: flex; gap: 4px; background: var(--bg-hover); border-radius: 8px; padding: 3px; align-self: flex-start; }
.sub-tab { padding: 5px 14px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.15s; }
.sub-tab.active { background: var(--bg-surface); color: var(--accent); box-shadow: 0 1px 3px rgba(0,0,0,0.2); }

/* ── Board layout ── */
.board-controls { display: flex; align-items: center; gap: 12px; padding: 10px 14px; flex-wrap: wrap; }
.board-search-wrap { display: flex; align-items: center; gap: 6px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 5px 10px; }
.board-search { background: transparent; border: none; color: var(--text-1); font-size: 13px; outline: none; width: 180px; }
.sort-chips { display: flex; gap: 4px; }
.sort-chip { font-size: 11px; padding: 3px 9px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 4px; color: var(--text-3); cursor: pointer; transition: all 0.12s; white-space: nowrap; }
.sort-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.count-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }

.board-layout { display: grid; grid-template-columns: 320px 1fr; gap: 14px; align-items: start; }
.board-list { overflow: hidden; padding: 0; }
.board-list-inner { max-height: 540px; overflow-y: auto; }
.board-row { padding: 10px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.board-row:last-child { border-bottom: none; }
.board-row:hover { background: var(--bg-hover); }
.board-row.selected { background: var(--accent-dim); border-left: 3px solid var(--accent); padding-left: 11px; }
.board-row-main { display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px; }
.board-name { font-size: 13px; font-weight: 600; color: var(--text-1); }
.board-chg { font-size: 13px; font-weight: 700; font-family: var(--font-mono); }
.board-row-meta { display: flex; gap: 10px; flex-wrap: wrap; }
.leader-tag { font-size: 10px; color: var(--text-3); }

.stocks-panel { display: flex; flex-direction: column; gap: 10px; }
.empty-stocks { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 48px; text-align: center; }
.stocks-header { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; }
.stocks-table-wrap { overflow-x: auto; max-height: 460px; overflow-y: auto; padding: 0; }
.action-link { font-size: 11px; padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); text-decoration: none; white-space: nowrap; }
.action-link:hover { border-color: var(--accent); color: var(--accent); }

/* ── Fund flow ── */
.flow-header-row { display: flex; align-items: center; gap: 14px; padding: 10px 14px; flex-wrap: wrap; }
.ind-chips { display: flex; gap: 4px; }
.ind-chip { font-size: 12px; padding: 4px 12px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 20px; color: var(--text-2); cursor: pointer; transition: all 0.12s; }
.ind-chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); font-weight: 600; }
.flow-charts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.row-in  { background: rgba(239,68,68,0.03); }
.row-out { background: rgba(34,197,94,0.03); }
.table-wrap { max-height: 480px; overflow-y: auto; }

/* ── News ── */
.sentiment-bar { display: flex; align-items: center; gap: 16px; padding: 10px 16px; flex-wrap: wrap; }
.sent-group { display: flex; align-items: center; gap: 10px; }
.sent-label { font-size: 11px; color: var(--text-3); font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; }
.sent-score { font-size: 14px; font-weight: 700; }
.sent-score.pos { color: var(--success); }
.sent-score.neg { color: var(--danger); }
.sent-score.neu { color: var(--text-2); }
.sent-detail { display: flex; gap: 8px; font-size: 12px; }
.sent-detail .pos { color: var(--success); }
.sent-detail .neg { color: var(--danger); }
.sent-detail .neu { color: var(--text-3); }
.sent-headlines { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; }
.h-chip { font-size: 11px; color: var(--text-2); background: var(--bg-elevated); padding: 2px 8px; border-radius: 10px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sent-time { margin-left: auto; font-size: 11px; white-space: nowrap; }

.news-layout { display: grid; grid-template-columns: 1fr 360px; gap: 14px; align-items: start; }
@media (max-width: 900px) { .news-layout { grid-template-columns: 1fr; } }
.col-main { display: flex; flex-direction: column; gap: 10px; }
.col-side { display: flex; flex-direction: column; gap: 10px; }
.col-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; gap: 8px; }
.col-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.col-actions { display: flex; gap: 6px; }
.stock-search { display: flex; gap: 5px; align-items: center; }
.input-sm { width: 110px; padding: 4px 8px; font-size: 12px; }
.btn-sm { padding: 4px 10px; font-size: 12px; }

.news-list { overflow: hidden; padding: 0; }
.list-header { padding: 8px 14px 6px; border-bottom: 1px solid var(--border); font-size: 12px; }
.news-item { padding: 9px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.news-item:last-child { border-bottom: none; }
.news-item:hover { background: var(--bg-hover); }
.ni-row { display: flex; align-items: flex-start; gap: 7px; }
.ni-title { font-size: 13px; color: var(--text-1); line-height: 1.4; flex: 1; }
.ni-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex-shrink: 0; }
.ni-source { font-size: 10px; color: var(--text-3); }
.ni-time { font-size: 11px; color: var(--text-3); white-space: nowrap; font-family: var(--font-mono); }
.ni-content { font-size: 12px; color: var(--text-2); line-height: 1.6; margin-top: 6px; padding-left: 14px; border-left: 2px solid var(--border); }
.sdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.sdot.positive { background: var(--success); }
.sdot.negative { background: var(--danger); }
.sdot.neutral  { background: var(--text-3); }

.ai-panel { padding: 12px 14px; border-left: 3px solid #8b5cf6; }
.ai-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.ai-tag { font-size: 11px; font-weight: 700; color: #a78bfa; background: #8b5cf618; padding: 2px 7px; border-radius: 4px; }
.ai-body { font-size: 13px; color: var(--text-1); line-height: 1.7; white-space: pre-wrap; margin: 0; }
.empty-card { padding: 24px; text-align: center; }
.tiny { font-size: 11px; }

/* ── Shared ── */
.up   { color: #f87171; }
.down { color: #4ade80; }
.pos  { color: var(--success); }
.neg  { color: var(--danger); }
.fw-600 { font-weight: 600; }
.mono { font-family: var(--font-mono); }
.accent { color: var(--accent); }
.text-3 { color: var(--text-3); }
.text-2 { color: var(--text-2); }
.btn-ghost { background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-2); cursor: pointer; }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
.btn-primary { background: var(--accent); border: none; border-radius: var(--radius-sm); color: #fff; cursor: pointer; }
.btn-primary:disabled { opacity: 0.5; cursor: default; }

/* ── Data table (shared) ── */
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { background: var(--bg-hover); color: var(--text-2); font-weight: 600; padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
.data-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }

@media (max-width: 768px) {
  .market-hub { padding: 10px 12px; }
  .hub-tabs { overflow-x: auto; flex-wrap: nowrap; }
  .hub-tab { white-space: nowrap; flex-shrink: 0; padding: 7px 12px; }
  .two-col { grid-template-columns: 1fr; }
  .flow-charts { grid-template-columns: 1fr; }
  .board-layout { grid-template-columns: 1fr; }
  .board-controls { padding: 8px 10px; gap: 8px; }
  .board-search-wrap { flex: 1; }
  .index-row { gap: 8px; }
  .sector-tiles { gap: 5px; }
  .stile { min-width: 68px; padding: 5px 8px; }
  .sentiment-bar { padding: 8px 10px; gap: 10px; }
  .data-table { min-width: 520px; }
}
</style>
