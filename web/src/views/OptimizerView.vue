<template>
  <div class="optimizer-view">
    <div class="page-header">
      <h1>参数优化</h1>
    </div>

    <div class="layout">
      <!-- Left: config -->
      <div class="form-panel">
        <h2>优化配置</h2>

        <!-- Mode -->
        <div class="form-group">
          <label>优化模式</label>
          <div class="radio-group">
            <label class="radio-label">
              <input type="radio" v-model="mode" value="grid" /> 网格搜索
            </label>
            <label class="radio-label">
              <input type="radio" v-model="mode" value="wf" /> Walk-Forward
            </label>
          </div>
        </div>

        <!-- Strategy -->
        <div class="form-group">
          <label>策略</label>
          <select v-model="form.strategy">
            <option v-for="s in strategies" :key="s.module_path" :value="s.module_path">
              {{ s.name }} — {{ s.class_name }}
            </option>
          </select>
        </div>

        <!-- Symbol / Exchange -->
        <div class="form-row">
          <div class="form-group">
            <label>标的</label>
            <input v-model="form.symbol" placeholder="000001" />
          </div>
          <div class="form-group">
            <label>交易所</label>
            <select v-model="form.exchange">
              <option value="SZSE">深交所</option>
              <option value="SSE">上交所</option>
            </select>
          </div>
        </div>

        <!-- Dates -->
        <div class="form-row">
          <div class="form-group">
            <label>开始</label>
            <input type="date" v-model="form.start" />
          </div>
          <div class="form-group">
            <label>结束</label>
            <input type="date" v-model="form.end" />
          </div>
        </div>

        <!-- Walk-forward extra config -->
        <template v-if="mode === 'wf'">
          <div class="form-row">
            <div class="form-group">
              <label>训练窗口 (天)</label>
              <input type="number" v-model.number="wfForm.inSampleDays" />
            </div>
            <div class="form-group">
              <label>测试窗口 (天)</label>
              <input type="number" v-model.number="wfForm.outSampleDays" />
            </div>
          </div>
          <div class="form-group">
            <label>步长 (天)</label>
            <input type="number" v-model.number="wfForm.stepDays" />
          </div>
        </template>

        <!-- Optimize metric -->
        <div class="form-group">
          <label>优化目标</label>
          <select v-model="form.metric">
            <option value="sharpe">夏普比率</option>
            <option value="total_return">总收益率</option>
          </select>
        </div>

        <!-- Parameter grid -->
        <div class="params-section">
          <div class="params-header">
            <span class="params-title">参数网格</span>
            <button class="btn-add" @click="addParam">+ 添加参数</button>
          </div>
          <div class="param-row" v-for="(p, i) in paramRows" :key="i">
            <input v-model="p.name" placeholder="参数名" class="param-name" />
            <input v-model="p.valuesStr" placeholder="值列表 (逗号分隔)" class="param-values" />
            <button class="btn-remove" @click="removeParam(i)">×</button>
          </div>
          <div class="combo-count" v-if="comboCount > 0">
            共 {{ comboCount }} 个参数组合
          </div>
        </div>

        <button class="btn-primary" @click="runOptimize" :disabled="running">
          {{ running ? '运行中...' : '▶ 开始优化' }}
        </button>
        <div v-if="submitError" class="error-msg" style="margin-top:10px">{{ submitError }}</div>
      </div>

      <!-- Right: results -->
      <div class="result-panel">
        <div v-if="!currentJob" class="empty-state">
          <div class="empty-icon">🔍</div>
          <p>配置参数并点击"开始优化"</p>
        </div>

        <template v-else>
          <!-- Status bar -->
          <div class="result-header">
            <div>
              <span>Job: <code>{{ currentJob.job_id }}</code></span>
              <span v-if="currentJob.total > 0" class="progress-text">
                {{ currentJob.progress }} / {{ currentJob.total }}
              </span>
            </div>
            <span :class="['badge', currentJob.status]">{{ currentJob.status }}</span>
          </div>

          <!-- Progress bar -->
          <div class="progress-bar-wrap" v-if="currentJob.status === 'running' && currentJob.total > 0">
            <div class="progress-bar" :style="{ width: progressPct + '%' }"></div>
          </div>

          <!-- Grid search results table -->
          <template v-if="currentJob.type === 'grid' && currentJob.results?.length">
            <div class="section-title">网格搜索结果 (Top {{ currentJob.results.length }})</div>
            <table class="results-table">
              <thead>
                <tr>
                  <th v-for="key in paramKeys" :key="key">{{ key }}</th>
                  <th>夏普</th><th>收益率</th><th>最大回撤</th><th>胜率</th><th>交易数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in currentJob.results.slice(0, 20)" :key="JSON.stringify(r.params)"
                    :class="{ 'best-row': JSON.stringify(r.params) === JSON.stringify(currentJob.best?.params) }">
                  <td v-for="key in paramKeys" :key="key" class="mono">{{ r.params[key] }}</td>
                  <td :class="r.sharpe >= 0 ? 'pos' : 'neg'">{{ r.sharpe.toFixed(3) }}</td>
                  <td :class="r.total_return >= 0 ? 'pos' : 'neg'">{{ (r.total_return * 100).toFixed(2) }}%</td>
                  <td class="neg">{{ (r.max_drawdown * 100).toFixed(2) }}%</td>
                  <td>{{ (r.win_rate * 100).toFixed(1) }}%</td>
                  <td>{{ r.trade_count }}</td>
                </tr>
              </tbody>
            </table>
          </template>

          <!-- Walk-forward results -->
          <template v-if="currentJob.type === 'walk_forward' && currentJob.windows?.length">
            <!-- Summary cards -->
            <div class="wf-summary">
              <div class="wf-card">
                <div class="wf-label">OOS 平均夏普</div>
                <div class="wf-val" :class="currentJob.mean_oos_sharpe >= 0 ? 'pos' : 'neg'">
                  {{ currentJob.mean_oos_sharpe?.toFixed(3) }}
                </div>
              </div>
              <div class="wf-card">
                <div class="wf-label">OOS 平均收益</div>
                <div class="wf-val" :class="currentJob.mean_oos_return >= 0 ? 'pos' : 'neg'">
                  {{ currentJob.mean_oos_return != null ? (currentJob.mean_oos_return * 100).toFixed(2) + '%' : '-' }}
                </div>
              </div>
              <div class="wf-card">
                <div class="wf-label">最优参数</div>
                <div class="wf-val-small">{{ JSON.stringify(currentJob.best_params) }}</div>
              </div>
            </div>

            <!-- Windows table -->
            <div class="section-title">分窗口结果</div>
            <table class="results-table">
              <thead>
                <tr>
                  <th>训练区间</th><th>测试区间</th>
                  <th v-for="key in wfParamKeys" :key="key">{{ key }}</th>
                  <th>IS夏普</th><th>OOS夏普</th><th>OOS收益</th><th>OOS回撤</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="w in currentJob.windows" :key="w.out_start">
                  <td class="mono small">{{ w.in_start.slice(0,7) }}→{{ w.in_end.slice(0,7) }}</td>
                  <td class="mono small">{{ w.out_start.slice(0,7) }}→{{ w.out_end.slice(0,7) }}</td>
                  <td v-for="key in wfParamKeys" :key="key" class="mono">{{ w.best_params[key] }}</td>
                  <td>{{ w.in_sharpe.toFixed(3) }}</td>
                  <td :class="w.oos_sharpe >= 0 ? 'pos' : 'neg'">{{ w.oos_sharpe.toFixed(3) }}</td>
                  <td :class="w.oos_return >= 0 ? 'pos' : 'neg'">{{ (w.oos_return*100).toFixed(2) }}%</td>
                  <td class="neg">{{ (w.oos_drawdown*100).toFixed(2) }}%</td>
                </tr>
              </tbody>
            </table>
          </template>

          <!-- Error -->
          <div v-if="currentJob.status === 'error'" class="error-msg" style="margin-top:12px">
            {{ currentJob.error }}
          </div>
        </template>
      </div>
    </div>

    <!-- Plugin list -->
    <div class="plugins-section" v-if="plugins.length">
      <div class="section-title">已加载插件</div>
      <div class="plugin-cards">
        <div class="plugin-card" v-for="p in plugins" :key="p.name">
          <div class="plugin-name">{{ p.name }}</div>
          <div class="plugin-version">v{{ p.version }}</div>
          <div class="plugin-desc">{{ p.description }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const strategies = ref([])
const plugins = ref([])
const currentJob = ref(null)
const running = ref(false)
const submitError = ref('')
let pollTimer = null

const mode = ref('grid')

const form = ref({
  strategy: '',
  symbol: '000001',
  exchange: 'SZSE',
  start: '2022-01-01',
  end: '2023-11-30',
  metric: 'sharpe',
})

const wfForm = ref({
  inSampleDays: 365,
  outSampleDays: 90,
  stepDays: 90,
})

const paramRows = ref([
  { name: 'fast_period', valuesStr: '5,10,20' },
  { name: 'slow_period', valuesStr: '30,60,90' },
])

const comboCount = computed(() => {
  let total = 1
  for (const p of paramRows.value) {
    const vals = p.valuesStr.split(',').filter(v => v.trim())
    if (vals.length) total *= vals.length
  }
  return total > 1 ? total : 0
})

const progressPct = computed(() => {
  if (!currentJob.value || !currentJob.value.total) return 0
  return Math.min(100, Math.round(currentJob.value.progress / currentJob.value.total * 100))
})

const paramKeys = computed(() => {
  if (!currentJob.value?.results?.length) return []
  return Object.keys(currentJob.value.results[0]?.params || {})
})

const wfParamKeys = computed(() => {
  if (!currentJob.value?.windows?.length) return []
  return Object.keys(currentJob.value.windows[0]?.best_params || {})
})

function addParam() {
  paramRows.value.push({ name: '', valuesStr: '' })
}

function removeParam(i) {
  paramRows.value.splice(i, 1)
}

function buildParams() {
  return paramRows.value
    .filter(p => p.name && p.valuesStr)
    .map(p => ({
      name: p.name.trim(),
      values: p.valuesStr.split(',').map(v => {
        const n = Number(v.trim())
        return isNaN(n) ? v.trim() : n
      }),
    }))
}

async function runOptimize() {
  submitError.value = ''
  const params = buildParams()
  if (!params.length) {
    submitError.value = '请至少添加一个参数'
    return
  }

  running.value = true
  clearInterval(pollTimer)

  const payload = {
    strategy: form.value.strategy,
    symbols: [form.value.symbol],
    exchange: form.value.exchange,
    start: form.value.start,
    end: form.value.end,
    initial_capital: 1000000,
    params,
    optimize_metric: form.value.metric,
    ...(mode.value === 'wf' ? {
      in_sample_days: wfForm.value.inSampleDays,
      out_sample_days: wfForm.value.outSampleDays,
      step_days: wfForm.value.stepDays,
    } : {}),
  }

  const endpoint = mode.value === 'grid' ? '/api/optimizer/grid' : '/api/optimizer/walk-forward'
  try {
    const res = await axios.post(endpoint, payload)
    currentJob.value = res.data
    pollTimer = setInterval(pollJob, 2000)
  } catch (e) {
    submitError.value = e.response?.data?.detail || '提交失败'
    running.value = false
  }
}

async function pollJob() {
  if (!currentJob.value) return
  try {
    const res = await axios.get(`/api/optimizer/jobs/${currentJob.value.job_id}`)
    currentJob.value = res.data
    if (['done', 'error'].includes(res.data.status)) {
      clearInterval(pollTimer)
      running.value = false
    }
  } catch {}
}

onMounted(async () => {
  try {
    const res = await axios.get('/api/strategy/')
    strategies.value = res.data
    if (strategies.value.length) form.value.strategy = strategies.value[0].module_path
  } catch {}
  try {
    const res = await axios.get('/api/optimizer/plugins')
    plugins.value = res.data
  } catch {}
})

onUnmounted(() => clearInterval(pollTimer))
</script>

<style scoped>
.optimizer-view { padding: 28px; }
.page-header { margin-bottom: 20px; }
.page-header h1 { font-size: 22px; font-weight: 700; }

.layout { display: grid; grid-template-columns: 340px 1fr; gap: 20px; }

.form-panel, .result-panel {
  background: #161b27; border: 1px solid #2d3748;
  border-radius: 10px; padding: 20px;
}
.form-panel h2 { font-size: 15px; font-weight: 600; margin-bottom: 14px; }

.form-group { margin-bottom: 12px; }
.form-group label { display: block; font-size: 12px; color: #a0aec0; margin-bottom: 4px; }
.form-group input, .form-group select {
  width: 100%; background: #0f1117; border: 1px solid #2d3748;
  border-radius: 6px; padding: 7px 10px; color: #e2e8f0; font-size: 13px;
}
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

.radio-group { display: flex; gap: 16px; }
.radio-label { font-size: 13px; color: #e2e8f0; cursor: pointer; display: flex; align-items: center; gap: 5px; }

.params-section { margin-bottom: 14px; }
.params-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.params-title { font-size: 12px; color: #a0aec0; }
.btn-add { font-size: 11px; padding: 3px 8px; background: #1a2f4a; color: #63b3ed; border: 1px solid #63b3ed; border-radius: 4px; cursor: pointer; }
.param-row { display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; margin-bottom: 6px; }
.param-name, .param-values {
  background: #0f1117; border: 1px solid #2d3748; border-radius: 4px;
  padding: 5px 8px; color: #e2e8f0; font-size: 12px;
}
.btn-remove { background: none; border: none; color: #718096; cursor: pointer; font-size: 16px; padding: 0 4px; }
.combo-count { font-size: 11px; color: #63b3ed; text-align: right; }

.btn-primary {
  width: 100%; background: #2b6cb0; color: white; border: none;
  border-radius: 6px; padding: 9px; font-size: 13px; cursor: pointer; margin-top: 4px;
}
.btn-primary:hover:not(:disabled) { background: #3182ce; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.result-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-size: 13px; color: #a0aec0; }
.result-header code { color: #63b3ed; font-family: monospace; }
.progress-text { font-size: 12px; color: #718096; margin-left: 10px; }

.progress-bar-wrap { background: #2d3748; border-radius: 3px; height: 4px; margin-bottom: 14px; }
.progress-bar { background: #63b3ed; height: 100%; border-radius: 3px; transition: width 0.3s; }

.badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.badge.done { background: #1a4731; color: #48bb78; }
.badge.running, .badge.queued { background: #1a2f4a; color: #63b3ed; }
.badge.error { background: #3d1a1a; color: #fc8181; }

.section-title { font-size: 13px; font-weight: 600; color: #a0aec0; margin-bottom: 10px; margin-top: 16px; }

.results-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.results-table th { text-align: left; padding: 7px 8px; color: #718096; border-bottom: 1px solid #2d3748; font-weight: 500; }
.results-table td { padding: 6px 8px; border-bottom: 1px solid #1a2035; }
.results-table tr.best-row td { background: rgba(99,179,237,0.06); }
.results-table tr:hover td { background: #1a2035; }
.mono { font-family: monospace; }
.small { font-size: 11px; }
.pos { color: #48bb78; }
.neg { color: #f56565; }

.wf-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 8px; }
.wf-card { background: #0f1117; border-radius: 6px; padding: 10px; }
.wf-label { font-size: 11px; color: #718096; margin-bottom: 4px; }
.wf-val { font-size: 18px; font-weight: 700; }
.wf-val-small { font-size: 11px; color: #63b3ed; font-family: monospace; word-break: break-all; }

.empty-state { text-align: center; padding: 50px 0; color: #718096; }
.empty-icon { font-size: 40px; margin-bottom: 12px; }

.error-msg { background: #2d1a1a; border: 1px solid #fc8181; border-radius: 6px; padding: 10px 12px; color: #fc8181; font-size: 12px; }

.plugins-section { margin-top: 24px; }
.plugin-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.plugin-card { background: #161b27; border: 1px solid #2d3748; border-radius: 8px; padding: 14px; }
.plugin-name { font-size: 13px; font-weight: 600; margin-bottom: 2px; }
.plugin-version { font-size: 11px; color: #718096; margin-bottom: 4px; }
.plugin-desc { font-size: 12px; color: #a0aec0; }

@media (max-width: 768px) {
  .layout { grid-template-columns: 1fr; }
  .form-row { grid-template-columns: 1fr; }
  .wf-summary { grid-template-columns: repeat(2, 1fr); }
  .param-row { grid-template-columns: 1fr 1fr auto; }
}
</style>
