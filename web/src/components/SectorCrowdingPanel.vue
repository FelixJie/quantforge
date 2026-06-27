<template>
  <div class="crowd-view">
    <!-- 行业 / 概念 切换 -->
    <div class="view-tabs">
      <button :class="['view-tab', kind === 'industry' ? 'active' : '']" @click="switchKind('industry')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        行业拥挤度
      </button>
      <button :class="['view-tab', kind === 'concept' ? 'active' : '']" @click="switchKind('concept')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        概念拥挤度
      </button>
      <div class="tab-spacer"></div>
      <button class="btn-ghost btn-sm" @click="load(true)" :disabled="loading">刷新</button>
    </div>

    <div v-if="loading" class="card loading-card">
      <span class="spinner"></span>
      <span class="text-2">计算{{ kindLabel }}拥挤度（多因子合成）...</span>
    </div>

    <div v-if="!loading && errorMsg" class="error-box">{{ errorMsg }}</div>

    <template v-if="!loading && data && boards.length">
      <!-- 方法说明 -->
      <div class="method-note">
        拥挤度 = 成交占比·换手·动量·估值·赚钱效应·放量 六因子横截面分位合成（0–100，越高越拥挤）。
        <span v-if="data.has_history">已积累 {{ data.history_days }} 日历史，含放量倍数 / 20日动量 / 成交占比时序分位。</span>
        <span v-else class="muted">历史不足（{{ data.history_days }} 日），动量暂用当日涨跌、放量待数据积累后启用。</span>
      </div>

      <!-- 概览条 -->
      <div class="overview-bar card">
        <div class="ov-item">
          <span class="ov-lbl">市场拥挤温度</span>
          <span class="ov-val" :class="tempClass">{{ data.summary.temp }}<small>°</small></span>
          <span class="ov-sub">中位拥挤度</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item">
          <span class="ov-lbl">拥挤格局</span>
          <span class="ov-val" :class="regimeClass">{{ data.summary.regime }}</span>
          <span class="ov-sub">{{ data.summary.hot_count }} 个板块 ≥70</span>
        </div>
        <div class="ov-sep"></div>
        <div class="ov-item ov-flex">
          <span class="ov-lbl">最拥挤</span>
          <div class="ov-chips">
            <span v-for="(nm, i) in data.summary.most_crowded" :key="nm" class="ov-chip hot"
                  @click="selectBoard(nm)">{{ i + 1 }}. {{ nm }}</span>
          </div>
        </div>
        <div class="ov-sep" v-if="data.summary.rising.length"></div>
        <div class="ov-item ov-flex" v-if="data.summary.rising.length">
          <span class="ov-lbl">拥挤抬升最快</span>
          <div class="ov-chips">
            <span v-for="r in data.summary.rising" :key="r.name" class="ov-chip rising"
                  @click="selectBoard(r.name)" :title="'成交占比较自身均值 +' + (r.delta != null ? r.delta.toFixed(2) : '—') + 'pp'">
              {{ r.name }} ▲
            </span>
          </div>
        </div>
      </div>

      <!-- 分档分布 -->
      <div class="card band-card">
        <div class="band-head">
          <span class="text-1 fw-600">拥挤度分档分布</span>
          <span class="text-3" style="font-size:11px">共 {{ boards.length }} 个板块 · 点击分档筛选</span>
        </div>
        <div class="band-dist">
          <button v-for="b in data.summary.bands" :key="b.band"
                  :class="['band-seg', 'bg-' + b.band, bandFilter === b.band ? 'sel' : '', !b.count ? 'empty' : '']"
                  :style="{ flex: Math.max(b.count, 0.15) }"
                  @click="toggleBandFilter(b.band)"
                  :title="b.label + '：' + b.count + ' 个'">
            <span class="band-seg-cnt">{{ b.count }}</span>
            <span class="band-seg-lbl">{{ b.label }}</span>
          </button>
        </div>
      </div>

      <!-- 气泡图：动量 × 拥挤度 -->
      <div class="card chart-card">
        <div class="chart-header">
          <span class="text-1 fw-600">拥挤度 × 动量象限</span>
          <span class="text-3" style="font-size:11px">横轴=近期动量，纵轴=拥挤度，气泡大小=成交额，颜色=分档；右上=高位拥挤(注意风险)</span>
        </div>
        <v-chart class="bubble-chart" :option="bubbleOption" autoresize @click="onBubbleClick" />
      </div>

      <!-- 排行榜 + 明细 -->
      <div class="crowd-split">
        <!-- 左：排行榜 -->
        <div class="card table-wrap split-left">
          <div class="tbl-controls">
            <div class="board-search-wrap">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input class="board-search" v-model="query" placeholder="搜索板块..." />
            </div>
            <span v-if="bandFilter" class="filter-tag" @click="bandFilter = ''">{{ bandLabelOf(bandFilter) }} ✕</span>
            <span class="count-hint">{{ shown.length }} 个</span>
          </div>
          <table class="data-table crowd-table">
            <thead>
              <tr>
                <th>#</th>
                <th>板块</th>
                <th class="th-sort" @click="setSort('crowding')">拥挤度<span v-if="sortKey==='crowding'" class="sa">{{ sortAsc?'↑':'↓' }}</span></th>
                <th class="th-sort" @click="setSort('amount_share')">成交占比<span v-if="sortKey==='amount_share'" class="sa">{{ sortAsc?'↑':'↓' }}</span></th>
                <th class="th-sort" @click="setSort('turnover_rate')">换手<span v-if="sortKey==='turnover_rate'" class="sa">{{ sortAsc?'↑':'↓' }}</span></th>
                <th class="th-sort" @click="setSort('momentum_nd')">动量<span v-if="sortKey==='momentum_nd'" class="sa">{{ sortAsc?'↑':'↓' }}</span></th>
                <th class="th-sort" @click="setSort('volume_surge')">放量<span v-if="sortKey==='volume_surge'" class="sa">{{ sortAsc?'↑':'↓' }}</span></th>
                <th>趋势</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(b, i) in shown" :key="b.name"
                  :class="['stock-row', selected === b.name ? 'row-selected' : '']" @click="selectBoard(b.name)">
                <td class="text-3 mono">{{ i + 1 }}</td>
                <td class="fw-600 board-cell">{{ b.name }}</td>
                <td>
                  <div class="crowd-cell">
                    <div class="crowd-bar-bg"><div :class="['crowd-bar', 'bg-' + b.band]" :style="{ width: b.crowding + '%' }"></div></div>
                    <span class="crowd-num" :class="'tx-' + b.band">{{ b.crowding }}</span>
                  </div>
                </td>
                <td class="mono text-2">{{ b.amount_share != null ? b.amount_share.toFixed(2) + '%' : '—' }}</td>
                <td class="mono text-3">{{ b.turnover_rate != null ? b.turnover_rate.toFixed(2) + '%' : '—' }}</td>
                <td :class="['mono', (b.momentum_nd ?? 0) >= 0 ? 'pos' : 'neg']">
                  {{ b.momentum_nd != null ? ((b.momentum_nd >= 0 ? '+' : '') + b.momentum_nd.toFixed(1) + '%') : '—' }}
                </td>
                <td class="mono" :class="surgeClass(b.volume_surge)">{{ b.volume_surge != null ? b.volume_surge.toFixed(2) + '×' : '—' }}</td>
                <td><span :class="['trend-ar', 'tr-' + b.trend]">{{ trendIcon(b.trend) }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 右：选中板块因子明细 -->
        <div class="split-right">
          <template v-if="selectedBoard">
            <div class="card detail-card">
              <div class="detail-head">
                <div>
                  <span class="text-1 fw-700" style="font-size:15px">{{ selectedBoard.name }}</span>
                  <span :class="['band-tag', 'bg-' + selectedBoard.band]">{{ selectedBoard.band_label }}</span>
                </div>
                <div class="detail-score" :class="'tx-' + selectedBoard.band">{{ selectedBoard.crowding }}<small>/100</small></div>
              </div>

              <div class="factor-list">
                <div v-for="f in factorRows(selectedBoard)" :key="f.key" class="factor-row">
                  <span class="factor-lbl">{{ f.label }}</span>
                  <div class="factor-bar-bg">
                    <div class="factor-bar" :style="{ width: (f.pct ?? 0) + '%', background: factorColor(f.pct) }"></div>
                  </div>
                  <span class="factor-pct">{{ f.pct != null ? f.pct.toFixed(0) : '—' }}</span>
                  <span class="factor-raw text-3">{{ f.raw }}</span>
                </div>
              </div>

              <div class="detail-extra">
                <div class="ex-tile"><span class="ex-lbl">涨跌</span><span :class="(selectedBoard.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">{{ fmtPct(selectedBoard.change_pct) }}</span></div>
                <div class="ex-tile"><span class="ex-lbl">上涨/下跌</span><span><span class="pos">{{ selectedBoard.up_count ?? '—' }}</span>/<span class="neg">{{ selectedBoard.down_count ?? '—' }}</span></span></div>
                <div class="ex-tile" v-if="selectedBoard.avg_pb != null"><span class="ex-lbl">平均PB</span><span>{{ selectedBoard.avg_pb.toFixed(2) }}</span></div>
                <div class="ex-tile" v-if="selectedBoard.net_flow != null"><span class="ex-lbl">资金净流</span><span :class="selectedBoard.net_flow >= 0 ? 'pos' : 'neg'">{{ (selectedBoard.net_flow >= 0 ? '+' : '') + selectedBoard.net_flow.toFixed(2) }}亿</span></div>
                <div class="ex-tile" v-if="selectedBoard.share_ts_pct != null"><span class="ex-lbl">成交占比时序分位</span><span :class="selectedBoard.share_ts_pct >= 70 ? 'neg-warn' : ''">{{ selectedBoard.share_ts_pct.toFixed(0) }}%</span></div>
                <div class="ex-tile"><span class="ex-lbl">成交额</span><span>{{ fmtAmount(selectedBoard.amount) }}</span></div>
              </div>

              <div class="detail-tip" :class="tipTone(selectedBoard)">{{ crowdTip(selectedBoard) }}</div>

              <a class="action-link" :href="'/?tab=sector'" target="_blank" rel="noopener" @click.prevent="goConstituents(selectedBoard.name)">查看成分股 →</a>
            </div>
          </template>
          <div v-else class="card split-placeholder">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 3v18h18"/><path d="M18 9l-5 5-3-3-4 4"/></svg>
            <span class="text-3">点击板块查看拥挤度因子拆解</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
// 模块级缓存：切页返回 / F5 不重算（5 分钟有效）。
const _CROWD_TTL = 5 * 60 * 1000
const _crowdCache = { industry: null, concept: null, ts: { industry: 0, concept: 0 } }
</script>

<script setup>
import VChart from '../charts'
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router  = useRouter()
const kind    = ref('industry')
const data    = ref(null)
const loading = ref(false)
const errorMsg = ref('')
const query   = ref('')
const bandFilter = ref('')
const sortKey = ref('crowding')
const sortAsc = ref(false)
const selected = ref('')

const kindLabel = computed(() => (kind.value === 'concept' ? '概念' : '行业'))
const boards = computed(() => data.value?.boards || [])

const BAND_LABELS = { extreme: '极度拥挤', high: '拥挤', warm: '偏热', neutral: '中性', cool: '偏冷', cold: '冷清' }
const BAND_COLORS = { extreme: '#b91c1c', high: '#ef4444', warm: '#f59e0b', neutral: '#64748b', cool: '#0ea5e9', cold: '#3b82f6' }
function bandLabelOf(k) { return BAND_LABELS[k] || k }

const tempClass = computed(() => {
  const t = data.value?.summary?.temp ?? 50
  return t >= 65 ? 'hot' : t >= 45 ? 'warm-tx' : 'cool-tx'
})
const regimeClass = computed(() => {
  const r = data.value?.summary?.regime
  return r === '过热' ? 'hot' : r === '升温' ? 'warm-tx' : r === '清淡' ? 'cool-tx' : ''
})

const shown = computed(() => {
  let arr = boards.value
  if (bandFilter.value) arr = arr.filter(b => b.band === bandFilter.value)
  if (query.value.trim()) arr = arr.filter(b => b.name?.includes(query.value.trim()))
  arr = [...arr].sort((a, b) => {
    const av = a[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    const bv = b[sortKey.value] ?? (sortAsc.value ? Infinity : -Infinity)
    return sortAsc.value ? av - bv : bv - av
  })
  return arr
})

const selectedBoard = computed(() => boards.value.find(b => b.name === selected.value) || null)

const FACTOR_DEFS = [
  { key: 'amount_share', label: '成交占比', raw: b => b.amount_share != null ? b.amount_share.toFixed(2) + '%' : '—' },
  { key: 'turnover',     label: '换手强度', raw: b => b.turnover_rate != null ? b.turnover_rate.toFixed(2) + '%' : '—' },
  { key: 'momentum',     label: '近期动量', raw: b => b.momentum_nd != null ? ((b.momentum_nd >= 0 ? '+' : '') + b.momentum_nd.toFixed(1) + '%') : '—' },
  { key: 'valuation',    label: '估值水平', raw: b => b.avg_pb != null ? 'PB ' + b.avg_pb.toFixed(2) : '—' },
  { key: 'breadth',      label: '赚钱效应', raw: b => (b.up_count != null && b.down_count != null) ? `${b.up_count}涨/${b.down_count}跌` : '—' },
  { key: 'volume',       label: '放量倍数', raw: b => b.volume_surge != null ? b.volume_surge.toFixed(2) + '×' : '—' },
]
function factorRows(b) {
  return FACTOR_DEFS.map(f => ({ key: f.key, label: f.label, pct: b.factors?.[f.key], raw: f.raw(b) }))
}
function factorColor(pct) {
  if (pct == null) return 'var(--border)'
  if (pct >= 80) return '#b91c1c'
  if (pct >= 60) return '#f59e0b'
  if (pct >= 40) return '#64748b'
  return '#3b82f6'
}

function setSort(k) {
  if (sortKey.value === k) sortAsc.value = !sortAsc.value
  else { sortKey.value = k; sortAsc.value = false }
}
function toggleBandFilter(k) { bandFilter.value = bandFilter.value === k ? '' : k }
function selectBoard(nm) { selected.value = selected.value === nm ? '' : nm }
function trendIcon(t) { return t === 'up' ? '▲' : t === 'down' ? '▼' : '—' }
function surgeClass(v) { return v == null ? 'text-3' : v >= 2 ? 'neg-warn' : v >= 1.3 ? 'warm-tx' : 'text-3' }

function fmtPct(v) { return v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + '%' }
function fmtAmount(v) {
  if (!v) return '—'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

function tipTone(b) {
  if (b.crowding >= 70 && (b.momentum_nd ?? 0) > 0) return 'tone-risk'
  if (b.crowding <= 35 && (b.momentum_nd ?? 0) >= 0) return 'tone-watch'
  return ''
}
function crowdTip(b) {
  const hot = b.crowding >= 70, rising = b.trend === 'up'
  if (hot && (b.momentum_nd ?? 0) > 0) return '高位拥挤 + 上涨动量：交易过度集中，警惕踩踏/退潮风险。'
  if (hot) return '资金高度集中但动量转弱，留意拥挤退潮。'
  if (b.crowding <= 35 && rising) return '低拥挤且占比抬升：关注度回升，可能处于左侧蓄势。'
  if (b.crowding <= 25) return '交易清淡、关注度低，分歧不大。'
  return '拥挤度中性，无明显过度集中。'
}

function goConstituents(name) {
  window.open(router.resolve({ path: '/', query: { tab: 'sector', sector: name } }).href, '_blank')
}

// ── 气泡图 ────────────────────────────────────────────────────
const bubbleOption = computed(() => {
  const arr = boards.value
  if (!arr.length) return null
  const maxAmt = Math.max(...arr.map(b => b.amount || 0), 1)
  const points = arr.map(b => ({
    name: b.name,
    value: [b.momentum_nd ?? 0, b.crowding],
    symbolSize: 8 + 26 * Math.sqrt((b.amount || 0) / maxAmt),
    itemStyle: { color: BAND_COLORS[b.band] || '#64748b', opacity: 0.82, borderColor: '#fff', borderWidth: 0.6 },
    _b: b,
  }))
  return {
    backgroundColor: 'transparent',
    grid: { left: 48, right: 18, top: 16, bottom: 40 },
    tooltip: {
      formatter: p => {
        const b = p.data._b
        return `<b>${b.name}</b><br/>拥挤度：<b>${b.crowding}</b> (${b.band_label})<br/>`
          + `动量：${b.momentum_nd != null ? b.momentum_nd.toFixed(1) + '%' : '—'}<br/>`
          + `成交占比：${b.amount_share != null ? b.amount_share.toFixed(2) + '%' : '—'}`
          + (b.volume_surge != null ? `<br/>放量：${b.volume_surge.toFixed(2)}×` : '')
      }
    },
    xAxis: {
      type: 'value', name: '近期动量%', nameLocation: 'middle', nameGap: 24,
      nameTextStyle: { fontSize: 10, color: '#94a3b8' },
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.12)' } },
    },
    yAxis: {
      type: 'value', name: '拥挤度', min: 0, max: 100,
      nameTextStyle: { fontSize: 10, color: '#94a3b8' },
      axisLabel: { fontSize: 10, color: '#94a3b8' },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.12)' } },
    },
    series: [{
      type: 'scatter', data: points,
      markLine: {
        silent: true, symbol: 'none',
        lineStyle: { color: 'rgba(239,68,68,0.45)', type: 'dashed' },
        label: { show: true, formatter: '拥挤线 70', fontSize: 9, color: '#ef4444', position: 'insideEndTop' },
        data: [{ yAxis: 70 }],
      },
    }],
  }
})
function onBubbleClick(p) { if (p.data?._b?.name) selectBoard(p.data._b.name) }

// ── 数据加载 ──────────────────────────────────────────────────
async function load(force = false) {
  const k = kind.value
  if (!force && _crowdCache[k] && Date.now() - _crowdCache.ts[k] < _CROWD_TTL) {
    data.value = _crowdCache[k]
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await axios.get('/api/sector/crowding', { params: { kind: k } })
    data.value = res.data
    _crowdCache[k] = res.data
    _crowdCache.ts[k] = Date.now()
  } catch (e) {
    errorMsg.value = e.response?.data?.detail || '拥挤度数据获取失败'
    data.value = null
  }
  loading.value = false
}

function switchKind(k) {
  if (kind.value === k) return
  kind.value = k
  selected.value = ''
  bandFilter.value = ''
  load()
}

onMounted(() => load())
</script>

<style scoped>
.crowd-view { display: flex; flex-direction: column; gap: 14px; }

.view-tabs { display: flex; align-items: center; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; }
.view-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.view-tab:hover { color: var(--text-1); }
.view-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(15,23,42,0.12); }
.tab-spacer { flex: 1; }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn-ghost { background: transparent; border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-2); cursor: pointer; }
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }

.loading-card { display: flex; align-items: center; gap: 10px; padding: 30px; }
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.error-box { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #dc2626; border-radius: var(--radius-md); padding: 10px 14px; font-size: 13px; }
.method-note { font-size: 11.5px; color: var(--text-3); line-height: 1.6; padding: 0 2px; }
.muted { color: var(--text-3); }

/* 概览条 */
.overview-bar { display: flex; align-items: stretch; padding: 14px 6px; flex-wrap: wrap; gap: 4px; }
.ov-item { display: flex; flex-direction: column; gap: 3px; padding: 0 18px; justify-content: center; min-width: 110px; }
.ov-flex { flex: 1; min-width: 200px; }
.ov-lbl { font-size: 11px; color: var(--text-3); }
.ov-val { font-size: 24px; font-weight: 800; color: var(--text-1); line-height: 1.1; }
.ov-val small { font-size: 13px; font-weight: 600; }
.ov-val.hot { color: #dc2626; }
.ov-val.warm-tx { color: #f59e0b; }
.ov-val.cool-tx { color: #3b82f6; }
.ov-sub { font-size: 11px; color: var(--text-3); }
.ov-sep { width: 1px; background: var(--border); margin: 4px 0; }
.ov-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }
.ov-chip { font-size: 11.5px; padding: 3px 9px; border-radius: 12px; cursor: pointer; transition: all 0.12s; white-space: nowrap; }
.ov-chip.hot { background: rgba(239,68,68,0.12); color: #dc2626; }
.ov-chip.rising { background: rgba(245,158,11,0.14); color: #d97706; }
.ov-chip:hover { filter: brightness(0.95); transform: translateY(-1px); }

/* 分档分布 */
.band-card { padding: 14px 16px; }
.band-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.fw-600 { font-weight: 600; }
.band-dist { display: flex; gap: 4px; height: 56px; }
.band-seg { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; border: none; border-radius: var(--radius-sm); color: #fff; cursor: pointer; min-width: 40px; transition: all 0.15s; opacity: 0.92; }
.band-seg:hover { opacity: 1; }
.band-seg.sel { outline: 2px solid var(--text-1); outline-offset: 1px; }
.band-seg.empty { opacity: 0.4; }
.band-seg-cnt { font-size: 16px; font-weight: 800; }
.band-seg-lbl { font-size: 10px; opacity: 0.92; white-space: nowrap; }

/* 分档颜色 */
.bg-extreme { background: #b91c1c; }
.bg-high    { background: #ef4444; }
.bg-warm    { background: #f59e0b; }
.bg-neutral { background: #64748b; }
.bg-cool    { background: #0ea5e9; }
.bg-cold    { background: #3b82f6; }
.tx-extreme { color: #b91c1c; }
.tx-high    { color: #ef4444; }
.tx-warm    { color: #d97706; }
.tx-neutral { color: #64748b; }
.tx-cool    { color: #0ea5e9; }
.tx-cold    { color: #3b82f6; }

/* 图表 */
.chart-card { padding: 14px; overflow: hidden; }
.chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 8px; }
.bubble-chart { height: 320px; }

/* 排行 + 明细 左右分布 */
.crowd-split { display: flex; gap: 14px; align-items: flex-start; }
.split-left { flex: 1 1 60%; min-width: 0; }
.split-right { flex: 1 1 40%; min-width: 0; }
.tbl-controls { display: flex; align-items: center; gap: 10px; padding: 10px 14px; flex-wrap: wrap; }
.board-search-wrap { display: flex; align-items: center; gap: 6px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 5px 10px; }
.board-search { background: transparent; border: none; color: var(--text-1); font-size: 13px; outline: none; width: 150px; }
.filter-tag { font-size: 11px; padding: 3px 9px; background: var(--accent-dim); border: 1px solid var(--accent); border-radius: 4px; color: var(--accent); cursor: pointer; }
.count-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }

.table-wrap { overflow-x: auto; max-height: 620px; overflow-y: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.crowd-table th { background: var(--bg-hover); color: var(--text-2); font-weight: 600; padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
.crowd-table td { padding: 7px 10px; border-bottom: 1px solid var(--border); color: var(--text-1); white-space: nowrap; }
.crowd-table tr:last-child td { border-bottom: none; }
.th-sort { cursor: pointer; user-select: none; }
.th-sort:hover { color: var(--accent); }
.sa { color: var(--accent); margin-left: 2px; }
.stock-row { cursor: pointer; }
.stock-row:hover { background: var(--bg-hover); }
.stock-row.row-selected { background: var(--accent-dim); }
.board-cell { color: var(--text-1); }

.crowd-cell { display: flex; align-items: center; gap: 8px; }
.crowd-bar-bg { width: 64px; height: 7px; background: var(--bg-hover); border-radius: 4px; overflow: hidden; flex-shrink: 0; }
.crowd-bar { height: 100%; border-radius: 4px; transition: width 0.3s; }
.crowd-num { font-size: 13px; font-weight: 700; font-family: var(--font-mono); min-width: 30px; }

.trend-ar { font-size: 12px; font-weight: 700; }
.tr-up { color: #dc2626; }
.tr-down { color: #16a34a; }
.tr-flat { color: var(--text-3); }

/* 明细卡 */
.detail-card { padding: 16px; display: flex; flex-direction: column; gap: 14px; }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.band-tag { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; color: #fff; margin-left: 8px; }
.detail-score { font-size: 30px; font-weight: 800; line-height: 1; }
.detail-score small { font-size: 13px; font-weight: 600; color: var(--text-3); }
.factor-list { display: flex; flex-direction: column; gap: 9px; }
.factor-row { display: grid; grid-template-columns: 60px 1fr 30px auto; align-items: center; gap: 9px; }
.factor-lbl { font-size: 12px; color: var(--text-2); }
.factor-bar-bg { height: 8px; background: var(--bg-hover); border-radius: 4px; overflow: hidden; }
.factor-bar { height: 100%; border-radius: 4px; transition: width 0.3s; }
.factor-pct { font-size: 12px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); text-align: right; }
.factor-raw { font-size: 11px; min-width: 64px; text-align: right; }

.detail-extra { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.ex-tile { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 7px 10px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 12px; }
.ex-lbl { color: var(--text-3); }
.ex-tile span:last-child { font-weight: 700; font-family: var(--font-mono); }

.detail-tip { font-size: 12px; line-height: 1.6; padding: 9px 12px; border-radius: var(--radius-md); background: var(--bg-base); border: 1px solid var(--border); color: var(--text-2); }
.tone-risk { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.3); color: #b91c1c; }
.tone-watch { background: rgba(59,130,246,0.08); border-color: rgba(59,130,246,0.3); color: #2563eb; }
.neg-warn { color: #dc2626; font-weight: 700; }

.action-link { font-size: 12px; padding: 6px 12px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-2); text-decoration: none; text-align: center; }
.action-link:hover { border-color: var(--accent); color: var(--accent); }
.split-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px 20px; color: var(--text-3); min-height: 240px; }

.pos { color: #dc2626; }
.neg { color: #16a34a; }
.mono { font-family: var(--font-mono); }
.text-1 { color: var(--text-1); }
.text-2 { color: var(--text-2); }
.text-3 { color: var(--text-3); }
.warm-tx { color: #d97706; }
.cool-tx { color: #3b82f6; }
.hot { color: #dc2626; }

/* 移动端 */
@media (max-width: 768px) {
  .view-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .view-tab { white-space: nowrap; flex-shrink: 0; }
  .overview-bar { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; }
  .ov-item { flex-shrink: 0; }
  .ov-flex { min-width: 220px; }
  .ov-sep { flex-shrink: 0; }
  .chart-header { flex-wrap: wrap; gap: 4px; }
  .bubble-chart { height: 280px; }
  .band-seg-lbl { transform: scale(0.9); }
  /* 左右分布改上下堆叠 */
  .crowd-split { flex-direction: column; }
  .split-left, .split-right { width: 100%; flex: 1 1 auto; }
  .crowd-table { min-width: 540px; }
  .detail-extra { grid-template-columns: 1fr; }
}
</style>
