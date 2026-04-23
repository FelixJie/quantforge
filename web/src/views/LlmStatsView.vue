<template>
  <div class="llm-wrap">
    <!-- Header -->
    <div class="llm-header">
      <div class="page-badge">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
        LLM 配置
      </div>
      <button class="btn-reset" @click="resetStats" v-if="stats.total_calls > 0">清空记录</button>
    </div>

    <!-- API 配置 -->
    <div class="section-card config-section">
      <div class="section-title">API 配置</div>
      <div class="config-form">
        <div class="cfg-row">
          <label class="cfg-label">Base URL</label>
          <input class="input cfg-input" v-model="cfgForm.base_url" placeholder="https://ark.cn-beijing.volces.com/api/coding/v3" />
        </div>
        <div class="cfg-row">
          <label class="cfg-label">API Key</label>
          <input class="input cfg-input" v-model="cfgForm.api_key" type="password" placeholder="输入新的 API Key（留空保持不变）" autocomplete="new-password" />
        </div>
        <div class="cfg-row">
          <label class="cfg-label">Model</label>
          <input class="input cfg-input" v-model="cfgForm.model" placeholder="Doubao-Seed-2.0-Code" />
        </div>
        <div class="cfg-actions">
          <span class="cfg-hint text-3" v-if="cfgStatus">{{ cfgStatus }}</span>
          <span class="cfg-current text-3" v-if="cfgCurrent.model">
            当前: {{ cfgCurrent.model }} · {{ cfgCurrent.api_key }}
          </span>
          <button class="btn-primary btn-sm" @click="saveConfig" :disabled="cfgSaving">
            <span v-if="cfgSaving" class="spinner spinner-sm"></span>
            <span v-else>保存配置</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 用量统计 -->
    <div v-if="stats.total_calls >= 0" class="llm-body">
      <div class="summary-row">
        <div class="sum-card">
          <div class="sum-val">{{ stats.total_calls }}</div>
          <div class="sum-lbl">总调用次数</div>
        </div>
        <div class="sum-card">
          <div class="sum-val">{{ fmtNum(stats.total_input_tokens) }}</div>
          <div class="sum-lbl">输入 Token</div>
        </div>
        <div class="sum-card">
          <div class="sum-val">{{ fmtNum(stats.total_output_tokens) }}</div>
          <div class="sum-lbl">输出 Token</div>
        </div>
        <div class="sum-card accent">
          <div class="sum-val">$ {{ stats.total_cost_usd?.toFixed(4) }}</div>
          <div class="sum-lbl">预估费用 (USD)</div>
        </div>
      </div>

      <!-- Per-caller breakdown -->
      <div class="section-card" v-if="Object.keys(stats.by_caller || {}).length">
        <div class="section-title">按调用方统计</div>
        <table class="data-table">
          <thead>
            <tr><th>调用方</th><th>次数</th><th>输入 Token</th><th>输出 Token</th><th>费用 (USD)</th></tr>
          </thead>
          <tbody>
            <tr v-for="(v, caller) in stats.by_caller" :key="caller">
              <td><span class="caller-badge">{{ caller }}</span></td>
              <td>{{ v.calls }}</td>
              <td>{{ fmtNum(v.input_tokens) }}</td>
              <td>{{ fmtNum(v.output_tokens) }}</td>
              <td class="cost-cell">$ {{ v.cost_usd?.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Recent calls -->
      <div class="section-card" v-if="stats.recent_calls?.length">
        <div class="section-title">最近 {{ stats.recent_calls.length }} 次调用</div>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>调用方</th><th>模型</th><th>输入</th><th>输出</th><th>费用</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in [...stats.recent_calls].reverse()" :key="c.ts + c.caller">
              <td class="td-ts">{{ c.ts?.slice(11) }}</td>
              <td><span class="caller-badge sm">{{ c.caller }}</span></td>
              <td class="td-model">{{ c.model?.slice(0, 24) }}</td>
              <td>{{ c.input_tokens }}</td>
              <td>{{ c.output_tokens }}</td>
              <td class="cost-cell">$ {{ c.cost_usd?.toFixed(4) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="stats.total_calls === 0" class="empty-state">
        <p>暂无 LLM 调用记录</p>
        <p class="empty-sub">运行 AI 选股或 YAML 策略分析后会自动记录</p>
      </div>
    </div>
    <div v-else class="loading-msg">加载中...</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const stats = ref({})
const cfgCurrent = ref({})
const cfgForm = ref({ base_url: '', api_key: '', model: '' })
const cfgSaving = ref(false)
const cfgStatus = ref('')

async function load() {
  const res = await axios.get('/api/llm-stats/')
  stats.value = res.data
}

async function loadConfig() {
  try {
    const res = await axios.get('/api/llm-stats/config')
    cfgCurrent.value = res.data
    cfgForm.value.base_url = res.data.base_url || ''
    cfgForm.value.model = res.data.model || ''
    // Don't pre-fill api_key (it's masked)
  } catch {}
}

async function saveConfig() {
  cfgSaving.value = true
  cfgStatus.value = ''
  try {
    await axios.put('/api/llm-stats/config', {
      base_url: cfgForm.value.base_url,
      api_key:  cfgForm.value.api_key,
      model:    cfgForm.value.model,
    })
    cfgStatus.value = '保存成功 ✓'
    cfgForm.value.api_key = ''
    await loadConfig()
  } catch (e) {
    cfgStatus.value = '保存失败: ' + (e.response?.data?.detail || e.message)
  }
  cfgSaving.value = false
}

async function resetStats() {
  if (!confirm('确定要清空 LLM 调用记录吗？')) return
  await axios.delete('/api/llm-stats/')
  await load()
}

function fmtNum(n) {
  if (n == null) return '-'
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

onMounted(() => Promise.all([load(), loadConfig()]))
</script>

<style scoped>
.llm-wrap { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.llm-header { display: flex; align-items: center; justify-content: space-between; }
.page-badge { display: inline-flex; align-items: center; gap: 6px; background: var(--accent-dim); color: var(--accent); padding: 5px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.btn-reset { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-2); border-radius: var(--radius-sm); padding: 5px 12px; font-size: 12px; cursor: pointer; }

/* Config section */
.config-section { padding: 16px; }
.config-form { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.cfg-row { display: flex; align-items: center; gap: 12px; }
.cfg-label { width: 80px; font-size: 12px; color: var(--text-2); font-weight: 600; flex-shrink: 0; }
.cfg-input { flex: 1; max-width: 480px; }
.cfg-actions { display: flex; align-items: center; gap: 12px; padding-left: 92px; }
.cfg-hint { font-size: 12px; }
.cfg-current { font-size: 11px; flex: 1; }
.btn-sm { padding: 5px 14px; font-size: 12px; }

.llm-body { display: flex; flex-direction: column; gap: 16px; }

.summary-row { display: flex; gap: 12px; flex-wrap: wrap; }
.sum-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px 22px; min-width: 130px; }
.sum-card.accent .sum-val { color: var(--accent); }
.sum-val { font-size: 24px; font-weight: 700; color: var(--text-1); }
.sum-lbl { font-size: 11px; color: var(--text-3); margin-top: 3px; }

.section-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; }
.section-title { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { color: var(--text-3); font-weight: 600; text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 11px; }
.data-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }
.caller-badge { background: var(--accent-dim); color: var(--accent); padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }
.caller-badge.sm { font-size: 11px; padding: 1px 6px; }
.cost-cell { font-weight: 600; color: var(--accent); }
.td-ts { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }
.td-model { font-size: 11px; color: var(--text-2); }

.empty-state { padding: 48px; text-align: center; color: var(--text-2); }
.empty-sub { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.loading-msg { padding: 40px; text-align: center; color: var(--text-3); }
</style>
