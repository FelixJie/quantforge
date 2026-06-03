<template>
  <div class="research-view">

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="hub-tabs">
      <button :class="['hub-tab', tab === 'valuation' ? 'active' : '']" @click="switchTab('valuation')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
        个股估值
      </button>
      <button :class="['hub-tab', tab === 'industry' ? 'active' : '']" @click="switchTab('industry')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>
        产业链投研
      </button>
      <div class="tab-spacer"></div>
      <button class="btn-refresh" @click="refreshCurrent" :disabled="isLoading">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: isLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <!-- ════════════ TAB: 个股估值 ════════════ -->
    <template v-if="tab === 'valuation'">
      <div class="panel">
        <div class="search-row">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="stockCode" @keydown.enter="searchStock" class="search-input" placeholder="输入股票代码 (如 600519)" />
          <button class="btn-primary" @click="searchStock">搜索</button>
        </div>
      </div>

      <div v-if="valuationData" class="panel">
        <div class="panel-title">{{ valuationData.name }} ({{ valuationData.code }})</div>
        <div class="grid">
          <div class="card">
            <div class="label">现价</div>
            <div class="value">{{ valuationData.price }}</div>
          </div>
          <div class="card">
            <div class="label">PE (TTM)</div>
            <div class="value">{{ valuationData.pe_ttm }}</div>
          </div>
          <div class="card">
            <div class="label">PB</div>
            <div class="value">{{ valuationData.pb }}</div>
          </div>
          <div class="card">
            <div class="label">总市值</div>
            <div class="value">{{ valuationData.mcap_yi }}亿</div>
          </div>
          <div class="card">
            <div class="label">PEG</div>
            <div class="value">{{ valuationData.peg || '-' }}</div>
          </div>
          <div class="card">
            <div class="label">PE消化</div>
            <div class="value">{{ valuationData.pe_digest_years || '-' }}</div>
          </div>
        </div>
      </div>

      <div v-if="reportsData && reportsData.reports.length > 0" class="panel">
        <div class="panel-title">📊 机构研报 ({{ reportsData.count }}) - 近1年</div>
        <table>
          <thead>
            <tr>
              <th>日期</th>
              <th>机构</th>
              <th>标题</th>
              <th>评级</th>
              <th>预测EPS</th>
              <th>PDF</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in reportsData.reports.slice(0, 50)" :key="idx">
              <td>{{ r.publishDate?.slice(0, 10) || '-' }}</td>
              <td>{{ r.orgSName || '-' }}</td>
              <td class="title">{{ r.title || '-' }}</td>
              <td>{{ r.emRatingName || '-' }}</td>
              <td>{{ r.predictThisYearEps || '-' }}</td>
              <td>
                <a v-if="r.infoCode" :href="`https://pdf.dfcfw.com/pdf/H3_${r.infoCode}_1.pdf`" target="_blank">下载</a>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ════════════ TAB: 产业链投研 ════════════ -->
    <template v-if="tab === 'industry'">
      <!-- 主题和板块选择 -->
      <div class="panel">
        <div class="panel-title">选择产业链主题</div>
        <div class="topic-chips">
          <button v-for="topic in presetTopics" :key="topic.id"
            :class="['topic-chip', selectedTopic === topic.id ? 'active' : '']"
            @click="selectTopic(topic.id)">
            {{ topic.name }}
          </button>
        </div>

        <div class="panel-title" style="margin-top: 16px;">选择行业板块（可选）</div>
        <div class="sector-select-row">
          <select v-model="selectedSector" class="sector-select">
            <option value="">不选板块</option>
            <option v-for="sector in sectors" :key="sector.name" :value="sector.name">
              {{ sector.name }} {{ sector.change_pct != null ? (sector.change_pct > 0 ? '+' : '') + sector.change_pct.toFixed(2) + '%' : '' }}
            </option>
          </select>
          <button class="btn-primary" @click="aiSuggestStocks" :disabled="aiLoading">
            <svg v-if="aiLoading" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            <span v-else>🤖 AI智能选股</span>
          </button>
        </div>
      </div>

      <!-- AI推荐股票列表 -->
      <div v-if="aiSuggestedStocks.length > 0" class="panel">
        <div class="panel-title">
          🤖 AI推荐股票 ({{ aiSuggestedStocks.length }}只)
          <span v-if="aiSummary" class="panel-hint">{{ aiSummary }}</span>
        </div>
        <div class="stock-list">
          <div v-for="stock in aiSuggestedStocks" :key="stock.code" class="stock-row" @click="toggleSelectStock(stock)">
            <div class="stock-checkbox">
              <div :class="['checkbox', isSelected(stock.code) ? 'checked' : '']">
                <svg v-if="isSelected(stock.code)" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
            </div>
            <div class="stock-main">
              <div class="stock-name-row">
                <span class="stock-name">{{ stock.name }}</span>
                <span class="stock-code">{{ stock.code }}</span>
              </div>
              <div class="stock-meta">
                <span v-if="stock.pe != null">PE: {{ stock.pe.toFixed(1) }}</span>
                <span v-if="stock.turnover_rate != null">换手: {{ stock.turnover_rate.toFixed(2) }}%</span>
              </div>
            </div>
            <div class="stock-data">
              <div :class="['stock-price', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.price != null ? stock.price.toFixed(2) : '--' }}
              </div>
              <div :class="['stock-pct', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.change_pct != null ? ((stock.change_pct > 0 ? '+' : '') + stock.change_pct.toFixed(2) + '%') : '--' }}
              </div>
            </div>
          </div>
        </div>
        <div class="action-bar">
          <span class="selected-count">已选 {{ selectedStocks.length }} 只</span>
          <button class="btn-primary" @click="analyzeSelected" :disabled="selectedStocks.length === 0 || analyzing">
            <svg v-if="analyzing" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            <span v-else>📊 拉取研报分析</span>
          </button>
        </div>
      </div>

      <!-- 板块成分股列表（当没有选择AI推荐时显示） -->
      <div v-else-if="sectorStocks.length > 0" class="panel">
        <div class="panel-title">
          {{ selectedSector }} 成分股 ({{ sectorStocks.length }}只)
          <span class="panel-hint">点击选择要分析的股票</span>
        </div>
        <div class="stock-list">
          <div v-for="stock in sectorStocks" :key="stock.code" class="stock-row" @click="toggleSelectStock(stock)">
            <div class="stock-checkbox">
              <div :class="['checkbox', isSelected(stock.code) ? 'checked' : '']">
                <svg v-if="isSelected(stock.code)" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </div>
            </div>
            <div class="stock-main">
              <div class="stock-name-row">
                <span class="stock-name">{{ stock.name }}</span>
                <span class="stock-code">{{ stock.code }}</span>
              </div>
              <div class="stock-meta">
                <span v-if="stock.pe != null">PE: {{ stock.pe.toFixed(1) }}</span>
                <span v-if="stock.turnover_rate != null">换手: {{ stock.turnover_rate.toFixed(2) }}%</span>
              </div>
            </div>
            <div class="stock-data">
              <div :class="['stock-price', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.price != null ? stock.price.toFixed(2) : '--' }}
              </div>
              <div :class="['stock-pct', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                {{ stock.change_pct != null ? ((stock.change_pct > 0 ? '+' : '') + stock.change_pct.toFixed(2) + '%') : '--' }}
              </div>
            </div>
          </div>
        </div>
        <div class="action-bar">
          <span class="selected-count">已选 {{ selectedStocks.length }} 只</span>
          <button class="btn-primary" @click="analyzeSelected" :disabled="selectedStocks.length === 0 || analyzing">
            <svg v-if="analyzing" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
            <span v-else>📊 拉取研报分析</span>
          </button>
        </div>
      </div>

      <!-- 分析结果 -->
      <div v-if="analysisResults.length > 0" class="panel">
        <div class="panel-title">📊 研报分析结果</div>
        <div v-for="result in analysisResults" :key="result.code" class="analysis-result">
          <div class="result-header">
            <span class="result-name">{{ result.name }} ({{ result.code }})</span>
            <span class="report-count">{{ result.reports?.length || 0 }} 篇研报</span>
          </div>
          <div v-if="result.valuation" class="result-valuation">
            <span>PE: {{ result.valuation.pe_ttm || '--' }}</span>
            <span>PB: {{ result.valuation.pb || '--' }}</span>
            <span>市值: {{ result.valuation.mcap_yi || '--' }}亿</span>
            <span>PEG: {{ result.valuation.peg || '--' }}</span>
          </div>
          <div v-if="result.reports && result.reports.length > 0" class="result-reports">
            <table>
              <thead>
                <tr>
                  <th>日期</th>
                  <th>机构</th>
                  <th>标题</th>
                  <th>评级</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, idx) in result.reports.slice(0, 10)" :key="idx">
                  <td>{{ r.publishDate?.slice(0, 10) || '-' }}</td>
                  <td>{{ r.orgSName || '-' }}</td>
                  <td class="title">{{ r.title || '-' }}</td>
                  <td>{{ r.emRatingName || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </template>

    <div v-if="isLoading" class="panel">
      <div class="panel-loading"><span class="spinner spinner-sm"></span> 加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const tab = ref('industry')
const stockCode = ref('600519')
const valuationData = ref(null)
const reportsData = ref(null)
const isLoading = ref(false)

// 产业链投研相关
const presetTopics = ref([
  { id: 'humanoid_robot', name: '人形机器人' },
  { id: 'solid_state_battery', name: '固态电池' },
  { id: 'ai_chip', name: 'AI芯片' },
  { id: 'auto_intelligence', name: '智能驾驶' },
])
const selectedTopic = ref('humanoid_robot')
const selectedSector = ref('')
const sectors = ref([])
const sectorStocks = ref([])
const aiSuggestedStocks = ref([])
const aiSummary = ref('')
const selectedStocks = ref([])
const aiLoading = ref(false)
const analyzing = ref(false)
const analysisResults = ref([])

function switchTab(t) {
  tab.value = t
  if (t === 'industry' && sectors.value.length === 0) {
    loadSectors()
  }
}

function refreshCurrent() {
  if (tab.value === 'valuation') {
    searchStock()
  } else {
    loadSectors()
  }
}

async function searchStock() {
  isLoading.value = true
  valuationData.value = null
  reportsData.value = null
  
  try {
    const [valRes, repRes] = await Promise.all([
      axios.get(`/api/research/valuation/${stockCode.value}`),
      axios.get(`/api/research/reports/${stockCode.value}`)
    ])
    valuationData.value = valRes.data
    reportsData.value = repRes.data
  } catch (err) {
    console.error('Search failed', err)
  } finally {
    isLoading.value = false
  }
}

async function loadSectors() {
  try {
    const response = await axios.get('/api/research/sectors')
    sectors.value = response.data.sectors || []
  } catch (error) {
    console.error('Failed to load sectors:', error)
  }
}

async function selectTopic(topicId) {
  selectedTopic.value = topicId
  aiSuggestedStocks.value = []
  aiSummary.value = ''
  selectedStocks.value = []
  
  // 如果选择了板块，加载板块成分股
  if (selectedSector.value) {
    await loadSectorStocks(selectedSector.value)
  }
}

async function loadSectorStocks(sectorName) {
  try {
    const response = await axios.get(`/api/research/sector-stocks/${encodeURIComponent(sectorName)}`)
    sectorStocks.value = response.data.stocks || []
  } catch (error) {
    console.error('Failed to load sector stocks:', error)
    sectorStocks.value = []
  }
}

async function aiSuggestStocks() {
  aiLoading.value = true
  aiSuggestedStocks.value = []
  aiSummary.value = ''
  selectedStocks.value = []
  
  try {
    const topic = presetTopics.value.find(t => t.id === selectedTopic.value)?.name || selectedTopic.value
    const response = await axios.get('/api/research/ai-suggest-stocks', {
      params: {
        topic: topic,
        sector: selectedSector.value || undefined,
        limit: 30
      }
    })
    
    aiSuggestedStocks.value = response.data.recommended || []
    aiSummary.value = response.data.summary || ''
    
    // 默认全选AI推荐的股票
    selectedStocks.value = [...aiSuggestedStocks.value]
  } catch (error) {
    console.error('AI suggest failed:', error)
    // 如果AI失败，尝试加载板块成分股
    if (selectedSector.value) {
      await loadSectorStocks(selectedSector.value)
    }
  } finally {
    aiLoading.value = false
  }
}

function toggleSelectStock(stock) {
  const index = selectedStocks.value.findIndex(s => s.code === stock.code)
  if (index >= 0) {
    selectedStocks.value.splice(index, 1)
  } else {
    selectedStocks.value.push(stock)
  }
}

function isSelected(code) {
  return selectedStocks.value.some(s => s.code === code)
}

async function analyzeSelected() {
  if (selectedStocks.value.length === 0) return
  
  analyzing.value = true
  analysisResults.value = []
  
  try {
    // 并行获取所有选中股票的估值和研报
    const promises = selectedStocks.value.map(async (stock) => {
      try {
        const [valRes, repRes] = await Promise.all([
          axios.get(`/api/research/valuation/${stock.code}`),
          axios.get(`/api/research/reports/${stock.code}`)
        ])
        return {
          code: stock.code,
          name: stock.name || valRes.data.name,
          valuation: valRes.data,
          reports: repRes.data.reports || []
        }
      } catch (error) {
        console.error(`Failed to analyze ${stock.code}:`, error)
        return {
          code: stock.code,
          name: stock.name,
          valuation: null,
          reports: []
        }
      }
    })
    
    analysisResults.value = await Promise.all(promises)
  } catch (error) {
    console.error('Analysis failed:', error)
  } finally {
    analyzing.value = false
  }
}

onMounted(() => {
  loadSectors()
})
</script>

<style scoped>
.research-view {
  padding-bottom: 16px;
}

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-row svg {
  color: var(--text-3);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  color: var(--text-1);
  font-size: 13px;
  outline: none;
}

.search-input::placeholder {
  color: var(--text-3);
}

.btn-primary {
  background: var(--accent);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: opacity 0.2s;
}

.btn-primary:hover {
  opacity: 0.9;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.card {
  padding: 14px;
  background: var(--bg-1);
  border-radius: 8px;
  text-align: center;
  border: 1px solid var(--border);
}

.card .label {
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 6px;
}

.card .value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-1);
  font-family: 'JetBrains Mono', monospace;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

thead th {
  background: var(--bg-1);
  padding: 10px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  color: var(--text-3);
  font-weight: 500;
}

tbody td {
  padding: 8px;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
}

tbody tr:hover {
  background: var(--bg-1);
}

td a {
  color: var(--accent);
  text-decoration: none;
}

td a:hover {
  text-decoration: underline;
}

.title {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 产业链投研样式 */
.topic-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.topic-chip {
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.topic-chip:hover {
  border-color: var(--accent);
  color: var(--text-2);
}

.topic-chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: white;
}

.sector-select-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.sector-select {
  flex: 1;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  color: var(--text-1);
  font-size: 13px;
  outline: none;
  cursor: pointer;
}

.sector-select option {
  background: var(--bg-2);
  color: var(--text-1);
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

.stock-checkbox {
  margin-right: 10px;
}

.checkbox {
  width: 18px;
  height: 18px;
  border: 2px solid var(--border);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.checkbox.checked {
  background: var(--accent);
  border-color: var(--accent);
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

.stock-meta {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-3);
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

.action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0 4px;
  border-top: 1px solid var(--border);
  margin-top: 8px;
}

.selected-count {
  font-size: 13px;
  color: var(--text-3);
}

/* 分析结果样式 */
.analysis-result {
  border-bottom: 1px solid var(--border);
  padding: 16px 0;
}

.analysis-result:last-child {
  border-bottom: none;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
}

.report-count {
  font-size: 12px;
  color: var(--text-3);
  background: var(--bg-1);
  padding: 2px 8px;
  border-radius: 4px;
}

.result-valuation {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-3);
}

.result-valuation span {
  background: var(--bg-1);
  padding: 4px 10px;
  border-radius: 4px;
}

.result-reports table {
  font-size: 11px;
}

.result-reports th,
.result-reports td {
  padding: 6px 8px;
}
</style>