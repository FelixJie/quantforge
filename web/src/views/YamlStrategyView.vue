<template>
  <div class="yaml-hub">

    <!-- ── Sidebar list ──────────────────────────────────────── -->
    <div class="yaml-sidebar">
      <div class="sidebar-head">
        <span class="sidebar-title">YAML 策略</span>
        <button class="btn-new" @click="newStrategy">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新建
        </button>
      </div>

      <div class="strategy-list">
        <div
          v-for="s in strategies" :key="s.name"
          :class="['strategy-item', selectedName === s.name ? 'active' : '']"
          @click="selectStrategy(s.name)"
        >
          <div class="item-name">{{ s.display_name || s.name }}</div>
          <div class="item-caps">
            <span v-if="s.has_screener" class="cap-dot cap-screener" title="选股筛选">选</span>
            <span v-if="s.has_yaml_signal" class="cap-dot cap-signal" title="AI信号">AI</span>
            <span v-if="s.has_backtest" class="cap-dot cap-backtest" title="可回测">测</span>
          </div>
        </div>
        <div v-if="!strategies.length" class="list-empty">暂无策略，点击「新建」创建</div>
      </div>
    </div>

    <!-- ── Main panel ────────────────────────────────────────── -->
    <div class="yaml-main">

      <div v-if="!selectedName && !isCreating" class="no-select">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
        <p>从左侧选择策略，或点击「新建」</p>
      </div>

      <template v-else>
        <!-- Toolbar -->
        <div class="main-toolbar">
          <div class="toolbar-left">
            <span class="toolbar-title">{{ isCreating ? '新建策略' : selectedMeta?.display_name || selectedName }}</span>
            <span class="cap-badges" v-if="!isCreating">
              <span v-if="selectedMeta?.has_screener" class="cap-badge screener">选股筛选</span>
              <span v-if="selectedMeta?.has_yaml_signal" class="cap-badge signal">AI信号</span>
              <span v-if="selectedMeta?.has_backtest" class="cap-badge backtest">可回测</span>
            </span>
          </div>
          <div class="toolbar-right">
            <div class="tab-pills" v-if="!isCreating">
              <button :class="['tab-pill', mainTab==='edit'?'active':'']" @click="mainTab='edit'">编辑</button>
              <button :class="['tab-pill', mainTab==='analyze'?'active':'']" @click="mainTab='analyze'">AI问股</button>
              <button :class="['tab-pill', mainTab==='links'?'active':'']" @click="mainTab='links'">三通道</button>
            </div>
            <button v-if="mainTab==='edit' || isCreating" class="btn-save" @click="saveStrategy" :disabled="saving">{{ saving ? '保存中...' : '保存' }}</button>
            <button v-if="!isCreating" class="btn-del" @click="showDelConfirm=true">删除</button>
          </div>
        </div>

        <div v-if="saveMsg" :class="['save-msg', saveMsg.type]">{{ saveMsg.text }}</div>

        <!-- Edit tab -->
        <div v-if="mainTab==='edit' || isCreating" class="edit-area">
          <div class="edit-toolbar">
            <div class="edit-hint">YAML 文件驱动选股、AI信号、回测三个通道，保存后立即生效</div>
            <div class="ai-gen-row">
              <input
                v-model="genDescription"
                class="gen-input"
                placeholder="用一句话描述策略，AI自动生成YAML..."
                @keyup.enter="generateYaml"
              />
              <button class="btn-gen-ai" @click="generateYaml" :disabled="generating">
                <svg v-if="!generating" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                <span v-if="generating" class="mini-spinner"></span>
                {{ generating ? 'AI生成中...' : 'AI生成' }}
              </button>
            </div>
          </div>
          <div class="name-row" v-if="isCreating">
            <label>文件名（英文/下划线）</label>
            <input v-model="newName" class="name-input" placeholder="my_strategy" />
          </div>
          <textarea class="yaml-editor" v-model="editorContent" spellcheck="false"></textarea>
        </div>

        <!-- Analyze tab -->
        <div v-if="mainTab==='analyze' && !isCreating" class="analyze-area">
          <div class="analyze-form">
            <input v-model="analyzeSymbol" class="sym-input" placeholder="输入股票代码，如 000001" @keyup.enter="runAnalyze" />
            <button class="btn-analyze" @click="runAnalyze" :disabled="analyzing">{{ analyzing ? '分析中...' : '开始分析' }}</button>
          </div>
          <div v-if="analyzing" class="analyze-loading">
            <div class="loading-ring"></div><span>AI 正在分析，请稍候...</span>
          </div>
          <div v-if="analyzeResult" class="analyze-result">
            <div :class="['signal-banner', 'signal-' + analyzeResult.signal]">
              {{ { BUY: '🟢 买入', SELL: '🔴 卖出', HOLD: '🟡 持有' }[analyzeResult.signal] || analyzeResult.signal }}
              <span class="signal-score">置信度 {{ analyzeResult.confidence }}%</span>
            </div>
            <div class="result-section">
              <div class="result-label">分析原因</div>
              <div class="result-text">{{ analyzeResult.reason }}</div>
            </div>
            <div class="result-section" v-if="analyzeResult.key_factors?.length">
              <div class="result-label">关键因子</div>
              <div class="factor-list">
                <span v-for="f in analyzeResult.key_factors" :key="f" class="factor-tag">{{ f }}</span>
              </div>
            </div>
            <div class="result-section" v-if="analyzeResult.risks?.length">
              <div class="result-label">风险提示</div>
              <ul class="risk-list"><li v-for="r in analyzeResult.risks" :key="r">{{ r }}</li></ul>
            </div>
          </div>
        </div>

        <!-- Links tab -->
        <div v-if="mainTab==='links' && !isCreating" class="links-area">
          <div class="link-card">
            <div class="link-icon screener-icon">选</div>
            <div class="link-body">
              <div class="link-title">选股筛选</div>
              <div class="link-desc">基于策略 screener 配置，批量筛选满足条件的A股标的</div>
            </div>
            <router-link :to="'/screener?strategy=yaml_' + selectedName" class="link-btn">前往筛选</router-link>
          </div>
          <div class="link-card">
            <div class="link-icon signal-icon">AI</div>
            <div class="link-body">
              <div class="link-title">AI 信号问股</div>
              <div class="link-desc">将策略规则交给 LLM 解读，对指定股票给出 买入/卖出/持有 建议</div>
            </div>
            <button class="link-btn" @click="mainTab='analyze'">切换至问股</button>
          </div>
          <div class="link-card">
            <div class="link-icon backtest-icon">测</div>
            <div class="link-body">
              <div class="link-title">回测 / 实盘</div>
              <div class="link-desc">
                执行类：<code>{{ selectedMeta?.execution_class || '-' }}</code>
                <span v-if="selectedMeta?.execution_display">（{{ selectedMeta.execution_display }}）</span>
              </div>
            </div>
            <router-link :to="'/backtest?strategy=' + (selectedMeta?.execution_path || '')" class="link-btn">前往回测</router-link>
          </div>
        </div>
      </template>
    </div>

    <!-- Delete confirm modal -->
    <div v-if="showDelConfirm" class="modal-overlay" @click.self="showDelConfirm=false">
      <div class="modal-box">
        <div class="modal-title">确认删除？</div>
        <div class="modal-body">将删除 <strong>{{ selectedMeta?.display_name || selectedName }}</strong>，不可恢复。</div>
        <div class="modal-actions">
          <button class="btn-cancel" @click="showDelConfirm=false">取消</button>
          <button class="btn-del-confirm" @click="doDelete">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const strategies = ref([])
const selectedName = ref(null)
const isCreating = ref(false)
const mainTab = ref('edit')
const editorContent = ref('')
const newName = ref('')
const saving = ref(false)
const saveMsg = ref(null)
const analyzeSymbol = ref('')
const analyzing = ref(false)
const analyzeResult = ref(null)
const showDelConfirm = ref(false)
const genDescription = ref('')
const generating = ref(false)

const selectedMeta = computed(() => strategies.value.find(s => s.name === selectedName.value))

async function loadList() {
  try {
    const res = await axios.get('/api/yaml-strategy/list')
    strategies.value = res.data.strategies || []
  } catch {}
}

async function selectStrategy(name) {
  isCreating.value = false
  mainTab.value = 'edit'
  analyzeResult.value = null
  saveMsg.value = null
  try {
    const res = await axios.get(`/api/yaml-strategy/${name}`)
    selectedName.value = name
    editorContent.value = res.data.content
  } catch (e) {
    alert('加载失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function newStrategy() {
  try {
    const res = await axios.get('/api/yaml-strategy/template')
    editorContent.value = res.data.template
  } catch {
    editorContent.value = 'name: 我的策略\ndescription: 策略描述\n'
  }
  selectedName.value = null
  isCreating.value = true
  newName.value = ''
  saveMsg.value = null
}

async function saveStrategy() {
  saving.value = true; saveMsg.value = null
  try {
    const stem = (newName.value || 'new_strategy').replace(/\s+/g, '_').toLowerCase()
    if (isCreating.value) {
      await axios.post('/api/yaml-strategy/', { name: stem, content: editorContent.value })
      saveMsg.value = { type: 'ok', text: '创建成功' }
      isCreating.value = false
      await loadList()
      await selectStrategy(stem)
    } else {
      await axios.put(`/api/yaml-strategy/${selectedName.value}`, { name: selectedName.value, content: editorContent.value })
      saveMsg.value = { type: 'ok', text: '已保存' }
      await loadList()
    }
    setTimeout(() => { saveMsg.value = null }, 3000)
  } catch (e) {
    saveMsg.value = { type: 'err', text: e.response?.data?.detail || '保存失败' }
  } finally {
    saving.value = false
  }
}

async function doDelete() {
  showDelConfirm.value = false
  try {
    await axios.delete(`/api/yaml-strategy/${selectedName.value}`)
    selectedName.value = null
    await loadList()
  } catch (e) {
    alert('删除失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function generateYaml() {
  if (!genDescription.value.trim()) return
  generating.value = true
  try {
    const res = await axios.post('/api/yaml-strategy/generate', {
      description: genDescription.value.trim(),
      name: newName.value || null,
    })
    editorContent.value = res.data.yaml
    genDescription.value = ''
  } catch (e) {
    saveMsg.value = { type: 'err', text: 'AI生成失败: ' + (e.response?.data?.detail || e.message) }
  } finally {
    generating.value = false
  }
}

async function runAnalyze() {
  if (!analyzeSymbol.value.trim()) return
  analyzing.value = true; analyzeResult.value = null
  try {
    const res = await axios.post('/api/yaml-strategy/analyze', {
      symbol: analyzeSymbol.value.trim(),
      strategy_name: selectedName.value,
    })
    analyzeResult.value = res.data
  } catch (e) {
    alert('分析失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    analyzing.value = false
  }
}

onMounted(loadList)
</script>

<style scoped>
.yaml-hub { display: flex; height: 100%; overflow: hidden; }

.yaml-sidebar { width: 220px; min-width: 220px; border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; background: var(--bg-surface); }
.sidebar-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid var(--border); }
.sidebar-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.btn-new { display: flex; align-items: center; gap: 4px; font-size: 11px; padding: 4px 9px; border-radius: var(--radius-sm); border: 1px solid var(--accent); color: var(--accent); background: transparent; cursor: pointer; }
.btn-new:hover { background: var(--accent-dim); }
.strategy-list { flex: 1; overflow-y: auto; padding: 8px; }
.strategy-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: var(--radius-md); cursor: pointer; margin-bottom: 2px; }
.strategy-item:hover { background: var(--bg-hover); }
.strategy-item.active { background: var(--accent-dim); }
.item-name { font-size: 13px; font-weight: 500; color: var(--text-1); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-caps { display: flex; gap: 3px; flex-shrink: 0; }
.cap-dot { font-size: 9px; font-weight: 700; padding: 1px 4px; border-radius: 4px; }
.cap-dot.cap-screener { background: rgba(59,130,246,0.2); color: #60a5fa; }
.cap-dot.cap-signal   { background: rgba(139,92,246,0.2); color: #a78bfa; }
.cap-dot.cap-backtest { background: rgba(34,197,94,0.2); color: #4ade80; }
.list-empty { padding: 20px 10px; font-size: 12px; color: var(--text-3); text-align: center; }

.yaml-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.no-select { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: var(--text-3); font-size: 13px; }

.main-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid var(--border); gap: 10px; flex-wrap: wrap; flex-shrink: 0; }
.toolbar-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.toolbar-title { font-size: 14px; font-weight: 600; color: var(--text-1); white-space: nowrap; }
.toolbar-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.tab-pills { display: flex; gap: 3px; background: var(--bg-hover); border-radius: 8px; padding: 3px; }
.tab-pill { padding: 4px 10px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: 12px; cursor: pointer; white-space: nowrap; }
.tab-pill.active { background: var(--bg-surface); color: var(--accent); box-shadow: 0 1px 3px rgba(0,0,0,0.2); }
.btn-save { padding: 5px 14px; border-radius: var(--radius-sm); border: none; background: var(--accent); color: #fff; font-size: 12px; cursor: pointer; white-space: nowrap; }
.btn-save:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-del { padding: 5px 12px; border-radius: var(--radius-sm); border: 1px solid #ef4444; color: #ef4444; background: transparent; font-size: 12px; cursor: pointer; }
.save-msg { padding: 6px 16px; font-size: 12px; flex-shrink: 0; }
.save-msg.ok { color: #22c55e; }
.save-msg.err { color: #ef4444; }
.cap-badges { display: flex; gap: 5px; }
.cap-badge { font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 600; }
.cap-badge.screener { background: rgba(59,130,246,0.15); color: #60a5fa; }
.cap-badge.signal   { background: rgba(139,92,246,0.15); color: #a78bfa; }
.cap-badge.backtest { background: rgba(34,197,94,0.15); color: #4ade80; }

.edit-area { flex: 1; display: flex; flex-direction: column; padding: 12px 16px; gap: 8px; overflow: hidden; min-height: 0; }
.edit-toolbar { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
.edit-hint { font-size: 11px; color: var(--text-3); }
.ai-gen-row { display: flex; gap: 6px; }
.gen-input { flex: 1; background: var(--bg-hover); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 6px 10px; font-size: 12px; }
.gen-input:focus { outline: none; border-color: #8b5cf6; }
.btn-gen-ai { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: var(--radius-sm); border: none; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; font-size: 12px; cursor: pointer; white-space: nowrap; flex-shrink: 0; }
.btn-gen-ai:disabled { opacity: 0.6; cursor: not-allowed; }
@keyframes spin-mini { to { transform: rotate(360deg); } }
.mini-spinner { width: 11px; height: 11px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin-mini 0.7s linear infinite; display: inline-block; }
.name-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); flex-shrink: 0; }
.name-input { max-width: 200px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 5px 9px; font-size: 12px; }
.yaml-editor { flex: 1; background: var(--bg-hover); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-1); padding: 12px; font-family: var(--font-mono); font-size: 12px; line-height: 1.6; resize: none; outline: none; overflow-y: auto; min-height: 0; }
.yaml-editor:focus { border-color: var(--accent); }

.analyze-area { flex: 1; padding: 16px; display: flex; flex-direction: column; gap: 14px; overflow-y: auto; }
.analyze-form { display: flex; gap: 8px; flex-shrink: 0; }
.sym-input { flex: 1; max-width: 220px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 7px 10px; font-size: 13px; }
.btn-analyze { padding: 7px 16px; border-radius: var(--radius-sm); border: none; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; font-size: 13px; cursor: pointer; }
.btn-analyze:disabled { opacity: 0.6; cursor: not-allowed; }
.analyze-loading { display: flex; align-items: center; gap: 10px; color: var(--text-3); font-size: 13px; }
@keyframes ring { to { transform: rotate(360deg); } }
.loading-ring { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: #6366f1; border-radius: 50%; animation: ring 0.8s linear infinite; }
.analyze-result { display: flex; flex-direction: column; gap: 12px; }
.signal-banner { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-radius: var(--radius-md); font-size: 15px; font-weight: 700; }
.signal-BUY  { background: rgba(34,197,94,0.12); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); }
.signal-SELL { background: rgba(239,68,68,0.12); color: #ef4444; border: 1px solid rgba(239,68,68,0.3); }
.signal-HOLD { background: rgba(245,158,11,0.12); color: #f59e0b; border: 1px solid rgba(245,158,11,0.3); }
.signal-score { margin-left: auto; font-size: 12px; font-weight: 500; opacity: 0.8; }
.result-section { background: var(--bg-hover); border-radius: var(--radius-md); padding: 12px 14px; }
.result-label { font-size: 11px; font-weight: 600; color: var(--text-3); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; }
.result-text { font-size: 13px; color: var(--text-1); line-height: 1.6; }
.factor-list { display: flex; flex-wrap: wrap; gap: 6px; }
.factor-tag { font-size: 11px; padding: 2px 8px; background: rgba(99,102,241,0.12); color: #818cf8; border-radius: 10px; }
.risk-list { padding-left: 16px; font-size: 12px; color: var(--text-2); line-height: 1.8; margin: 0; }

.links-area { flex: 1; padding: 16px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }
.link-card { display: flex; align-items: center; gap: 14px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; }
.link-icon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; }
.screener-icon { background: rgba(59,130,246,0.15); color: #60a5fa; }
.signal-icon   { background: rgba(139,92,246,0.15); color: #a78bfa; }
.backtest-icon { background: rgba(34,197,94,0.15); color: #4ade80; }
.link-body { flex: 1; min-width: 0; }
.link-title { font-size: 14px; font-weight: 600; color: var(--text-1); margin-bottom: 4px; }
.link-desc { font-size: 12px; color: var(--text-3); line-height: 1.5; }
.link-desc code { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; font-size: 11px; font-family: var(--font-mono); }
.link-btn { padding: 6px 14px; border-radius: var(--radius-sm); border: 1px solid var(--accent); color: var(--accent); background: transparent; font-size: 12px; cursor: pointer; text-decoration: none; white-space: nowrap; display: inline-block; }
.link-btn:hover { background: var(--accent-dim); }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal-box { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 24px; width: 360px; }
.modal-title { font-size: 15px; font-weight: 700; color: var(--text-1); margin-bottom: 10px; }
.modal-body { font-size: 13px; color: var(--text-2); margin-bottom: 20px; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }
.btn-cancel { padding: 6px 14px; border-radius: var(--radius-sm); border: 1px solid var(--border); color: var(--text-2); background: transparent; font-size: 13px; cursor: pointer; }
.btn-del-confirm { padding: 6px 14px; border-radius: var(--radius-sm); border: none; background: #ef4444; color: #fff; font-size: 13px; cursor: pointer; }
</style>
