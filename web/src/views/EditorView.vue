<template>
  <div class="editor-view">
    <div class="page-header">
      <h1>策略编辑器</h1>
      <div class="header-actions">
        <button class="btn-secondary" @click="showGeneratePanel = !showGeneratePanel">
          ✨ AI 生成
        </button>
        <button class="btn-secondary" @click="loadTemplate('dual_ma')">双均线模板</button>
        <button class="btn-secondary" @click="loadTemplate('mean_reversion')">均值回归模板</button>
        <button class="btn-secondary" @click="loadTemplate('empty')">空白模板</button>
      </div>
    </div>

    <!-- AI Generate Panel -->
    <div class="generate-panel" v-if="showGeneratePanel">
      <textarea
        v-model="nlDescription"
        class="nl-input"
        placeholder="用自然语言描述你的策略，例如：当RSI低于30时买入，高于70时卖出，持仓超过30天强制止盈..."
        rows="3"
      ></textarea>
      <div class="generate-actions">
        <select v-model="baseTemplate">
          <option value="empty">空白基础</option>
          <option value="dual_ma">双均线基础</option>
          <option value="mean_reversion">均值回归基础</option>
        </select>
        <button class="btn-primary" @click="generateStrategy" :disabled="generating">
          {{ generating ? '生成中...' : '▶ 生成策略代码' }}
        </button>
        <span class="generate-note">{{ generateNote }}</span>
      </div>
    </div>

    <div class="editor-layout">
      <!-- Left: file list -->
      <div class="file-panel">
        <div class="file-panel-header">
          <span>自定义策略</span>
          <button class="btn-new" @click="newFile">+ 新建</button>
        </div>
        <div
          v-for="s in savedStrategies"
          :key="s.filename"
          :class="['file-item', { active: currentFilename === s.filename }]"
          @click="openFile(s.filename)"
        >
          <div class="file-name">{{ s.filename }}.py</div>
          <button class="file-delete" @click.stop="deleteFile(s.filename)">×</button>
        </div>
        <div v-if="savedStrategies.length === 0" class="file-empty">
          点击"新建"创建策略
        </div>
      </div>

      <!-- Center: code editor -->
      <div class="code-panel">
        <div class="code-toolbar">
          <input
            v-model="currentFilename"
            class="filename-input"
            placeholder="策略文件名 (如 my_strategy)"
          />
          <div class="toolbar-right">
            <span v-if="saveStatus" :class="['save-status', saveStatus]">
              {{ saveStatus === 'saved' ? '✓ 已保存' : saveStatus === 'error' ? '✗ 保存失败' : '保存中...' }}
            </span>
            <button class="btn-save" @click="saveStrategy" :disabled="!currentCode.trim()">
              💾 保存
            </button>
            <button class="btn-run" @click="runBacktest" :disabled="!savedModulePath">
              ▶ 回测
            </button>
          </div>
        </div>

        <textarea
          v-model="currentCode"
          class="code-editor"
          spellcheck="false"
          @keydown.tab.prevent="insertTab"
          @input="onCodeChange"
        ></textarea>

        <div v-if="syntaxError" class="syntax-error">{{ syntaxError }}</div>
      </div>

      <!-- Right: backtest quick-run -->
      <div class="run-panel">
        <div class="run-panel-title">快速回测</div>

        <div class="form-group">
          <label>标的代码</label>
          <input v-model="runForm.symbol" placeholder="000001" />
        </div>
        <div class="form-group">
          <label>区间</label>
          <div class="date-presets">
            <button v-for="p in presets" :key="p.label"
              :class="['preset-btn', activePreset === p.label ? 'active' : '']"
              @click="applyPreset(p)">{{ p.label }}</button>
          </div>
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>开始</label>
            <input type="date" v-model="runForm.start" />
          </div>
          <div class="form-group">
            <label>结束</label>
            <input type="date" v-model="runForm.end" />
          </div>
        </div>
        <div class="form-group">
          <label>初始资金</label>
          <input type="number" v-model.number="runForm.capital" />
        </div>

        <button class="btn-primary full-width" @click="runBacktest" :disabled="!savedModulePath || runningBt">
          {{ runningBt ? '运行中...' : '▶ 运行回测' }}
        </button>

        <!-- Results -->
        <template v-if="btResult">
          <div class="metrics-mini" v-if="btResult.summary">
            <div class="metric-item">
              <div class="metric-label">总收益</div>
              <div class="metric-val" :class="btResult.summary.total_return >= 0 ? 'pos' : 'neg'">
                {{ (btResult.summary.total_return * 100).toFixed(2) }}%
              </div>
            </div>
            <div class="metric-item">
              <div class="metric-label">夏普</div>
              <div class="metric-val">{{ btResult.summary.sharpe_ratio?.toFixed(3) }}</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">最大回撤</div>
              <div class="metric-val neg">{{ (btResult.summary.max_drawdown * 100).toFixed(2) }}%</div>
            </div>
            <div class="metric-item">
              <div class="metric-label">胜率</div>
              <div class="metric-val">{{ (btResult.summary.win_rate * 100).toFixed(1) }}%</div>
            </div>
          </div>
          <div class="report-link" v-if="btResult.job_id">
            <a :href="`/api/optimizer/report/${btResult.job_id}`" target="_blank">
              📄 查看 HTML 报告
            </a>
          </div>
          <div v-if="btResult.status === 'error'" class="error-msg">{{ btResult.error }}</div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const showGeneratePanel = ref(false)
const nlDescription = ref('')
const baseTemplate = ref('empty')
const generating = ref(false)
const generateNote = ref('')

const savedStrategies = ref([])
const currentFilename = ref('my_strategy')
const currentCode = ref('')
const savedModulePath = ref('')
const saveStatus = ref('')
const syntaxError = ref('')
let saveTimer = null

const runForm = ref({
  symbol: '000001',
  start: '',
  end: new Date().toISOString().slice(0, 10),
  capital: 1000000,
})
const presets = [
  { label: '1M', months: 1 },
  { label: '3M', months: 3 },
  { label: '6M', months: 6 },
  { label: '1Y', months: 12 },
  { label: '2Y', months: 24 },
]
const activePreset = ref('1Y')

const runningBt = ref(false)
const btResult = ref(null)

function applyPreset(p) {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - p.months)
  runForm.value.start = start.toISOString().slice(0, 10)
  runForm.value.end = end.toISOString().slice(0, 10)
  activePreset.value = p.label
}

function insertTab(e) {
  const el = e.target
  const start = el.selectionStart
  const end = el.selectionEnd
  currentCode.value = currentCode.value.substring(0, start) + '    ' + currentCode.value.substring(end)
  setTimeout(() => { el.selectionStart = el.selectionEnd = start + 4 }, 0)
}

function onCodeChange() {
  syntaxError.value = ''
  saveStatus.value = ''
  clearTimeout(saveTimer)
}

function newFile() {
  currentFilename.value = 'my_strategy_' + Date.now().toString().slice(-4)
  currentCode.value = _EMPTY_TEMPLATE
  savedModulePath.value = ''
  saveStatus.value = ''
  btResult.value = null
}

async function loadTemplate(templateId) {
  try {
    const res = await axios.get(`/api/editor/templates/${templateId}`)
    currentCode.value = res.data.code
    saveStatus.value = ''
    syntaxError.value = ''
  } catch {}
}

async function loadSavedList() {
  try {
    const res = await axios.get('/api/editor/strategies')
    savedStrategies.value = res.data
  } catch {}
}

async function openFile(filename) {
  try {
    const res = await axios.get(`/api/editor/strategies/${filename}`)
    currentFilename.value = res.data.filename
    currentCode.value = res.data.code
    saveStatus.value = ''
    btResult.value = null
  } catch {}
}

async function saveStrategy() {
  if (!currentFilename.value || !currentCode.value.trim()) return
  saveStatus.value = 'saving'
  try {
    const res = await axios.post('/api/editor/strategies', {
      filename: currentFilename.value,
      code: currentCode.value,
    })
    savedModulePath.value = res.data.module_path
    saveStatus.value = 'saved'
    syntaxError.value = ''
    await loadSavedList()
  } catch (e) {
    saveStatus.value = 'error'
    syntaxError.value = e.response?.data?.detail || '保存失败'
  }
}

async function deleteFile(filename) {
  if (!confirm(`删除 ${filename}.py ?`)) return
  try {
    await axios.delete(`/api/editor/strategies/${filename}`)
    if (currentFilename.value === filename) {
      currentCode.value = ''
      savedModulePath.value = ''
    }
    await loadSavedList()
  } catch {}
}

async function generateStrategy() {
  if (!nlDescription.value.trim()) return
  generating.value = true
  generateNote.value = ''
  try {
    const res = await axios.post('/api/editor/generate', {
      description: nlDescription.value,
      template: baseTemplate.value,
    })
    currentCode.value = res.data.code
    generateNote.value = res.data.source === 'claude' ? '✓ 由 Claude AI 生成' : '⚠ 已插入描述（未配置 API Key）'
    showGeneratePanel.value = false
  } catch (e) {
    generateNote.value = '生成失败: ' + (e.response?.data?.detail || e.message)
  }
  generating.value = false
}

async function runBacktest() {
  if (!savedModulePath.value) {
    await saveStrategy()
    if (!savedModulePath.value) return
  }
  runningBt.value = true
  btResult.value = null

  try {
    const res = await axios.post('/api/backtest/run', {
      strategy: savedModulePath.value,
      symbols: [runForm.value.symbol],
      start: runForm.value.start,
      end: runForm.value.end,
      initial_capital: runForm.value.capital,
      enable_risk: false,
    })

    // Poll for result
    const jobId = res.data.job_id
    let job = res.data
    while (['queued', 'running'].includes(job.status)) {
      await new Promise(r => setTimeout(r, 1500))
      const poll = await axios.get(`/api/backtest/${jobId}`)
      job = poll.data
    }
    btResult.value = job
  } catch (e) {
    btResult.value = { status: 'error', error: e.response?.data?.detail || e.message }
  }
  runningBt.value = false
}

const _EMPTY_TEMPLATE = `"""自定义策略"""
from quantforge.strategy.base import Strategy
from quantforge.strategy.context import StrategyContext
from quantforge.core.datatypes import BarData
from quantforge.core.constants import Exchange


class CustomStrategy(Strategy):
    name = "custom"
    description = "自定义策略"

    def __init__(self, symbol: str = "000001", exchange: str = "SZSE", **kwargs):
        self.symbol = symbol
        self.exchange = exchange

    async def on_init(self, ctx: StrategyContext) -> None:
        ctx.log("策略初始化")

    async def on_bar(self, bar: BarData) -> None:
        ctx = self._ctx
        pass
`

onMounted(async () => {
  applyPreset({ label: '1Y', months: 12 })
  await loadSavedList()
  await loadTemplate('dual_ma')
})
</script>

<style scoped>
.editor-view { padding: 20px 28px; display: flex; flex-direction: column; height: 100%; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.page-header h1 { font-size: 22px; font-weight: 700; }
.header-actions { display: flex; gap: 8px; flex-wrap: wrap; }

.btn-secondary {
  background: #1a2035; border: 1px solid #2d3748; color: #a0aec0;
  border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer;
}
.btn-secondary:hover { background: #2d3748; color: #e2e8f0; }

/* AI Panel */
.generate-panel {
  background: #161b27; border: 1px solid #4a5568; border-radius: 8px;
  padding: 14px; margin-bottom: 14px;
}
.nl-input {
  width: 100%; background: #0f1117; border: 1px solid #2d3748;
  border-radius: 6px; padding: 10px; color: #e2e8f0; font-size: 13px;
  resize: vertical; font-family: inherit;
}
.generate-actions { display: flex; align-items: center; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
.generate-actions select {
  background: #0f1117; border: 1px solid #2d3748; border-radius: 6px;
  padding: 6px 10px; color: #e2e8f0; font-size: 12px;
}
.generate-note { font-size: 12px; color: #718096; }
.btn-primary {
  background: #2b6cb0; color: white; border: none;
  border-radius: 6px; padding: 7px 14px; font-size: 13px; cursor: pointer;
}
.btn-primary:hover:not(:disabled) { background: #3182ce; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

/* Layout */
.editor-layout { display: grid; grid-template-columns: 180px 1fr 220px; gap: 12px; flex: 1; min-height: 0; }

/* File panel */
.file-panel { background: #161b27; border: 1px solid #2d3748; border-radius: 8px; overflow: hidden; }
.file-panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px; border-bottom: 1px solid #2d3748;
  font-size: 12px; color: #a0aec0; font-weight: 600;
}
.btn-new { background: none; border: none; color: #63b3ed; cursor: pointer; font-size: 12px; }
.file-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; cursor: pointer; font-size: 12px;
  border-bottom: 1px solid #1a2035;
}
.file-item:hover { background: #1a2035; }
.file-item.active { background: #1a2f4a; color: #63b3ed; }
.file-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.file-delete { background: none; border: none; color: #4a5568; cursor: pointer; font-size: 14px; padding: 0 2px; }
.file-delete:hover { color: #fc8181; }
.file-empty { padding: 16px 12px; font-size: 12px; color: #4a5568; text-align: center; }

/* Code panel */
.code-panel { display: flex; flex-direction: column; background: #161b27; border: 1px solid #2d3748; border-radius: 8px; overflow: hidden; }
.code-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid #2d3748; gap: 8px;
}
.filename-input {
  background: #0f1117; border: 1px solid #2d3748; border-radius: 4px;
  padding: 4px 8px; color: #e2e8f0; font-size: 12px; width: 200px;
}
.toolbar-right { display: flex; align-items: center; gap: 8px; }
.save-status { font-size: 11px; }
.save-status.saved { color: #48bb78; }
.save-status.error { color: #fc8181; }
.save-status.saving { color: #f6ad55; }
.btn-save, .btn-run {
  padding: 5px 12px; border-radius: 5px; font-size: 12px; cursor: pointer; border: none;
}
.btn-save { background: #2d3748; color: #e2e8f0; }
.btn-save:hover { background: #4a5568; }
.btn-run { background: #276749; color: #9ae6b4; }
.btn-run:hover:not(:disabled) { background: #2f855a; }
.btn-run:disabled { opacity: 0.4; cursor: not-allowed; }

.code-editor {
  flex: 1; background: #0d1117; color: #e2e8f0; border: none;
  padding: 14px; font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
  font-size: 13px; line-height: 1.7; resize: none; outline: none;
  min-height: 400px; tab-size: 4;
}
.syntax-error { padding: 8px 12px; background: #2d1a1a; color: #fc8181; font-size: 12px; border-top: 1px solid #fc8181; }

/* Run panel */
.run-panel { background: #161b27; border: 1px solid #2d3748; border-radius: 8px; padding: 16px; overflow-y: auto; }
.run-panel-title { font-size: 13px; font-weight: 600; color: #a0aec0; margin-bottom: 12px; }

.form-group { margin-bottom: 10px; }
.form-group label { display: block; font-size: 11px; color: #718096; margin-bottom: 4px; }
.form-group input { width: 100%; background: #0f1117; border: 1px solid #2d3748; border-radius: 5px; padding: 6px 8px; color: #e2e8f0; font-size: 12px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }

.date-presets { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
.preset-btn { background: #1a2035; border: 1px solid #2d3748; color: #718096; border-radius: 4px; padding: 3px 7px; font-size: 11px; cursor: pointer; }
.preset-btn.active { background: #1a2f4a; border-color: #63b3ed; color: #63b3ed; }
.preset-btn:hover { background: #2d3748; }

.full-width { width: 100%; margin-top: 4px; }

.metrics-mini { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }
.metric-item { background: #0f1117; border-radius: 5px; padding: 8px; }
.metric-label { font-size: 10px; color: #718096; margin-bottom: 3px; }
.metric-val { font-size: 14px; font-weight: 700; }
.pos { color: #48bb78; }
.neg { color: #f56565; }

.report-link { margin-top: 10px; text-align: center; }
.report-link a { color: #63b3ed; font-size: 12px; text-decoration: none; }
.report-link a:hover { text-decoration: underline; }

.error-msg { margin-top: 10px; background: #2d1a1a; border: 1px solid #fc8181; border-radius: 5px; padding: 8px; color: #fc8181; font-size: 11px; }

@media (max-width: 768px) {
  .editor-layout { grid-template-columns: 1fr; grid-template-rows: auto 1fr auto; }
  .file-panel { max-height: 160px; overflow-y: auto; }
  .code-editor { min-height: 260px; }
}
</style>
