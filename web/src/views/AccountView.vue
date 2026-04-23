<template>
  <div class="account-view">

    <!-- ── 顶部操作栏 ───────────────────────────── -->
    <div class="view-header">
      <div class="header-left">
        <h2 class="view-title">账户管理</h2>
        <span class="view-sub">统一管理您的模拟与实盘账户</span>
      </div>
      <button class="btn-primary" @click="openCreate">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新建账户
      </button>
    </div>

    <!-- ── 汇总栏 ───────────────────────────────── -->
    <div class="summary-row" v-if="summary">
      <div class="sum-card">
        <div class="sum-label">账户总数</div>
        <div class="sum-value">{{ summary.count }}</div>
      </div>
      <div class="sum-card">
        <div class="sum-label">总资产</div>
        <div class="sum-value mono">¥{{ fmt(summary.total_assets) }}</div>
      </div>
      <div class="sum-card">
        <div class="sum-label">总盈亏</div>
        <div class="sum-value mono" :class="summary.total_pnl >= 0 ? 'pos' : 'neg'">
          {{ summary.total_pnl >= 0 ? '+' : '' }}¥{{ fmt(Math.abs(summary.total_pnl)) }}
        </div>
      </div>
      <div class="sum-card">
        <div class="sum-label">综合收益率</div>
        <div class="sum-value mono" :class="summary.total_pnl_pct >= 0 ? 'pos' : 'neg'">
          {{ summary.total_pnl_pct >= 0 ? '+' : '' }}{{ summary.total_pnl_pct.toFixed(2) }}%
        </div>
      </div>
    </div>

    <!-- ── 加载中 ────────────────────────────────── -->
    <div v-if="loading" class="loading-state">
      <span class="spinner"></span> 加载中...
    </div>

    <!-- ── 空状态 ────────────────────────────────── -->
    <div v-else-if="accounts.length === 0" class="empty-state">
      <div class="empty-icon">🏦</div>
      <p>还没有任何账户</p>
      <p class="empty-hint">点击右上角「新建账户」创建第一个账户</p>
    </div>

    <!-- ── 账户卡片网格 ──────────────────────────── -->
    <div v-else class="accounts-grid">
      <div
        v-for="acc in accounts"
        :key="acc.id"
        class="account-card"
        :style="{ '--acc-color': acc.color }"
      >
        <!-- 色条 -->
        <div class="acc-stripe"></div>

        <!-- 卡头 -->
        <div class="acc-head">
          <div class="acc-avatar" :style="{ background: acc.color + '22', color: acc.color }">
            {{ acc.name.charAt(0) }}
          </div>
          <div class="acc-meta">
            <div class="acc-name">{{ acc.name }}</div>
            <div class="acc-badges">
              <span :class="['type-badge', acc.type]">{{ acc.type === 'paper' ? '模拟' : '实盘' }}</span>
              <span v-if="acc.is_default" class="type-badge default">默认</span>
            </div>
          </div>
          <div class="acc-menu">
            <button class="icon-btn" @click="openEdit(acc)" title="编辑">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
            </button>
            <button class="icon-btn danger" @click="confirmDelete(acc)" title="删除">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
            </button>
          </div>
        </div>

        <!-- 资产数值 -->
        <div class="acc-balance">
          <div class="balance-label">账户总资产</div>
          <div class="balance-value mono">¥{{ fmt(acc.cash) }}</div>
          <div class="balance-pnl" :class="acc.pnl >= 0 ? 'pos' : 'neg'">
            {{ acc.pnl >= 0 ? '▲' : '▼' }}
            ¥{{ fmt(Math.abs(acc.pnl)) }}
            （{{ acc.pnl_pct >= 0 ? '+' : '' }}{{ acc.pnl_pct.toFixed(2) }}%）
          </div>
        </div>

        <!-- 次要信息 -->
        <div class="acc-stats">
          <div class="acc-stat">
            <span class="stat-l">初始资金</span>
            <span class="stat-r mono">¥{{ fmt(acc.initial_capital) }}</span>
          </div>
          <div class="acc-stat">
            <span class="stat-l">操作记录</span>
            <span class="stat-r">{{ acc.activity_count }} 条</span>
          </div>
          <div class="acc-stat">
            <span class="stat-l">创建时间</span>
            <span class="stat-r">{{ fmtDate(acc.created_at) }}</span>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="acc-actions">
          <button class="btn-action deposit" @click="openFund(acc, 'deposit')">入金</button>
          <button class="btn-action withdraw" @click="openFund(acc, 'withdraw')">出金</button>
          <button class="btn-action detail" @click="openDetail(acc)">明细</button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         模态框：新建账户
    ══════════════════════════════════════════════════ -->
    <div v-if="modal === 'create'" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-head">
          <span class="modal-title">新建账户</span>
          <button class="modal-close" @click="closeModal">×</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="form-label">账户名称</label>
            <input v-model="form.name" class="input" placeholder="例：主策略账户" maxlength="32" />
          </div>
          <div class="field">
            <label class="form-label">账户类型</label>
            <div class="type-selector">
              <button
                v-for="t in accountTypes" :key="t.value"
                :class="['type-opt', { active: form.type === t.value }]"
                @click="form.type = t.value"
              >
                <span class="type-icon">{{ t.icon }}</span>
                <div>
                  <div class="type-opt-label">{{ t.label }}</div>
                  <div class="type-opt-sub">{{ t.sub }}</div>
                </div>
              </button>
            </div>
          </div>
          <div class="field">
            <label class="form-label">初始资金（元）</label>
            <input v-model.number="form.initial_capital" class="input" type="number" min="0" step="10000" />
          </div>
          <div class="field">
            <label class="form-label">账户颜色</label>
            <div class="color-picker">
              <button
                v-for="c in colors" :key="c"
                :class="['color-dot', { selected: form.color === c }]"
                :style="{ background: c }"
                @click="form.color = c"
              ></button>
            </div>
          </div>
          <div class="field">
            <label class="form-label">备注（选填）</label>
            <input v-model="form.description" class="input" placeholder="账户用途说明" />
          </div>
          <div v-if="formError" class="error-box">{{ formError }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" @click="closeModal">取消</button>
          <button class="btn-primary" :disabled="submitting" @click="submitCreate">
            <span v-if="submitting" class="spinner spinner-sm"></span>
            创建账户
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         模态框：编辑账户
    ══════════════════════════════════════════════════ -->
    <div v-if="modal === 'edit'" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <div class="modal-head">
          <span class="modal-title">编辑账户</span>
          <button class="modal-close" @click="closeModal">×</button>
        </div>
        <div class="modal-body">
          <div class="field">
            <label class="form-label">账户名称</label>
            <input v-model="form.name" class="input" maxlength="32" />
          </div>
          <div class="field">
            <label class="form-label">账户颜色</label>
            <div class="color-picker">
              <button
                v-for="c in colors" :key="c"
                :class="['color-dot', { selected: form.color === c }]"
                :style="{ background: c }"
                @click="form.color = c"
              ></button>
            </div>
          </div>
          <div class="field">
            <label class="form-label">备注</label>
            <input v-model="form.description" class="input" />
          </div>
          <div v-if="formError" class="error-box">{{ formError }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" @click="closeModal">取消</button>
          <button class="btn-primary" :disabled="submitting" @click="submitEdit">
            <span v-if="submitting" class="spinner spinner-sm"></span>
            保存
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         模态框：入金 / 出金
    ══════════════════════════════════════════════════ -->
    <div v-if="modal === 'fund'" class="modal-overlay" @click.self="closeModal">
      <div class="modal modal-sm">
        <div class="modal-head">
          <span class="modal-title">{{ fundOp === 'deposit' ? '💰 入金' : '💸 出金' }}</span>
          <button class="modal-close" @click="closeModal">×</button>
        </div>
        <div class="modal-body">
          <div class="fund-acc-info" :style="{ borderColor: selectedAcc?.color }">
            <span class="fund-acc-name">{{ selectedAcc?.name }}</span>
            <span class="fund-acc-balance mono">余额 ¥{{ fmt(selectedAcc?.cash ?? 0) }}</span>
          </div>
          <div class="field">
            <label class="form-label">金额（元）</label>
            <input v-model.number="fundAmount" class="input" type="number" min="1" step="10000" placeholder="0.00" />
          </div>
          <div class="quick-amounts">
            <button v-for="q in quickAmounts" :key="q" class="quick-btn" @click="fundAmount = q">
              {{ q >= 10000 ? q / 10000 + '万' : q }}
            </button>
          </div>
          <div class="field">
            <label class="form-label">备注（选填）</label>
            <input v-model="fundNote" class="input" placeholder="操作说明" />
          </div>
          <div v-if="formError" class="error-box">{{ formError }}</div>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" @click="closeModal">取消</button>
          <button
            :class="['btn-primary', fundOp === 'withdraw' ? 'btn-danger' : '']"
            :disabled="submitting || !fundAmount"
            @click="submitFund"
          >
            <span v-if="submitting" class="spinner spinner-sm"></span>
            确认{{ fundOp === 'deposit' ? '入金' : '出金' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ══════════════════════════════════════════════
         抽屉：账户明细
    ══════════════════════════════════════════════════ -->
    <div v-if="modal === 'detail'" class="drawer-overlay" @click.self="closeModal">
      <div class="drawer" :style="{ '--acc-color': selectedAcc?.color }">
        <div class="drawer-head">
          <div class="drawer-title-row">
            <div class="drawer-dot" :style="{ background: selectedAcc?.color }"></div>
            <span class="drawer-title">{{ selectedAcc?.name }}</span>
            <span :class="['type-badge', selectedAcc?.type]">
              {{ selectedAcc?.type === 'paper' ? '模拟' : '实盘' }}
            </span>
          </div>
          <button class="modal-close" @click="closeModal">×</button>
        </div>

        <!-- 资产概览 -->
        <div class="drawer-summary">
          <div class="ds-item">
            <div class="ds-label">总资产</div>
            <div class="ds-value mono">¥{{ fmt(detailData?.cash ?? 0) }}</div>
          </div>
          <div class="ds-item">
            <div class="ds-label">盈亏</div>
            <div class="ds-value mono" :class="(detailData?.pnl ?? 0) >= 0 ? 'pos' : 'neg'">
              {{ (detailData?.pnl ?? 0) >= 0 ? '+' : '' }}¥{{ fmt(Math.abs(detailData?.pnl ?? 0)) }}
            </div>
          </div>
          <div class="ds-item">
            <div class="ds-label">收益率</div>
            <div class="ds-value mono" :class="(detailData?.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'">
              {{ (detailData?.pnl_pct ?? 0) >= 0 ? '+' : '' }}{{ (detailData?.pnl_pct ?? 0).toFixed(2) }}%
            </div>
          </div>
          <div class="ds-item">
            <div class="ds-label">初始资金</div>
            <div class="ds-value mono">¥{{ fmt(detailData?.initial_capital ?? 0) }}</div>
          </div>
        </div>

        <!-- 标签页 -->
        <div class="drawer-tabs">
          <button
            v-for="tab in detailTabs" :key="tab.key"
            :class="['dtab', { active: detailTab === tab.key }]"
            @click="detailTab = tab.key"
          >{{ tab.label }}</button>
        </div>

        <!-- 出入金记录 -->
        <div v-if="detailTab === 'fund'" class="drawer-content">
          <div v-if="!detailData?.fund_records?.length" class="empty-state" style="padding:32px">
            <p>暂无出入金记录</p>
          </div>
          <table v-else class="data-table">
            <thead>
              <tr>
                <th>类型</th><th>金额</th><th>操作后余额</th><th>备注</th><th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detailData.fund_records" :key="r.id">
                <td>
                  <span :class="['op-badge', r.op]">
                    {{ r.op === 'deposit' ? '入金' : '出金' }}
                  </span>
                </td>
                <td class="mono" :class="r.op === 'deposit' ? 'pos' : 'neg'">
                  {{ r.op === 'deposit' ? '+' : '-' }}¥{{ fmt(r.amount) }}
                </td>
                <td class="mono">¥{{ fmt(r.balance_after) }}</td>
                <td class="text-3">{{ r.note || '-' }}</td>
                <td class="mono text-3">{{ fmtDate(r.timestamp) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 操作日志 -->
        <div v-if="detailTab === 'log'" class="drawer-content">
          <div v-if="!detailData?.activity_logs?.length" class="empty-state" style="padding:32px">
            <p>暂无操作记录</p>
          </div>
          <div v-else class="log-list">
            <div v-for="lg in detailData.activity_logs" :key="lg.id" class="log-row">
              <div class="log-dot" :class="lg.action"></div>
              <div class="log-body">
                <div class="log-detail">{{ lg.detail }}</div>
                <div class="log-time mono">{{ fmtDate(lg.timestamp) }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="drawer-foot">
          <button class="btn-action deposit" @click="openFundFromDetail('deposit')">入金</button>
          <button class="btn-action withdraw" @click="openFundFromDetail('withdraw')">出金</button>
        </div>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="modal === 'delete'" class="modal-overlay" @click.self="closeModal">
      <div class="modal modal-sm">
        <div class="modal-head">
          <span class="modal-title">删除账户</span>
          <button class="modal-close" @click="closeModal">×</button>
        </div>
        <div class="modal-body">
          <p style="color:var(--text-1);font-size:14px;line-height:1.6">
            确定要删除账户 <strong style="color:var(--danger)">「{{ selectedAcc?.name }}」</strong> 吗？<br>
            此操作将同时删除所有出入金记录和操作日志，<strong>无法恢复</strong>。
          </p>
        </div>
        <div class="modal-foot">
          <button class="btn-ghost" @click="closeModal">取消</button>
          <button class="btn-primary btn-danger" :disabled="submitting" @click="submitDelete">
            <span v-if="submitting" class="spinner spinner-sm"></span>
            确认删除
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

// ── State ─────────────────────────────────────────────────────────────
const loading = ref(true)
const accounts = ref([])
const summary = ref(null)
const modal = ref('')         // 'create' | 'edit' | 'fund' | 'detail' | 'delete'
const selectedAcc = ref(null)
const detailData = ref(null)
const detailTab = ref('fund')
const submitting = ref(false)
const formError = ref('')
const fundOp = ref('deposit')
const fundAmount = ref(null)
const fundNote = ref('')

const form = ref({
  name: '',
  type: 'paper',
  initial_capital: 1000000,
  description: '',
  color: '#3b82f6',
})

const colors = [
  '#3b82f6', '#8b5cf6', '#10b981', '#f59e0b',
  '#ef4444', '#06b6d4', '#ec4899', '#84cc16',
]

const accountTypes = [
  { value: 'paper', icon: '🧪', label: '模拟账户', sub: '虚拟资金，无风险练习' },
  { value: 'live',  icon: '💼', label: '实盘账户', sub: '接入真实资金（未来支持）' },
]

const quickAmounts = [10000, 50000, 100000, 500000, 1000000]

const detailTabs = [
  { key: 'fund', label: '出入金记录' },
  { key: 'log',  label: '操作日志' },
]

// ── Fetch ─────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const res = await axios.get('/api/accounts')
    accounts.value = res.data.accounts
    summary.value = res.data.summary
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function loadDetail(id) {
  try {
    const res = await axios.get(`/api/accounts/${id}`)
    detailData.value = res.data
  } catch (e) {
    console.error(e)
  }
}

onMounted(load)

// ── Modal helpers ─────────────────────────────────────────────────────
function closeModal() {
  modal.value = ''
  formError.value = ''
  submitting.value = false
}

function openCreate() {
  form.value = { name: '', type: 'paper', initial_capital: 1000000, description: '', color: colors[0] }
  formError.value = ''
  modal.value = 'create'
}

function openEdit(acc) {
  selectedAcc.value = acc
  form.value = { name: acc.name, description: acc.description, color: acc.color }
  formError.value = ''
  modal.value = 'edit'
}

function openFund(acc, op) {
  selectedAcc.value = acc
  fundOp.value = op
  fundAmount.value = null
  fundNote.value = ''
  formError.value = ''
  modal.value = 'fund'
}

function openFundFromDetail(op) {
  modal.value = 'fund'
  fundOp.value = op
  fundAmount.value = null
  fundNote.value = ''
  formError.value = ''
}

async function openDetail(acc) {
  selectedAcc.value = acc
  detailTab.value = 'fund'
  detailData.value = null
  modal.value = 'detail'
  await loadDetail(acc.id)
}

function confirmDelete(acc) {
  selectedAcc.value = acc
  modal.value = 'delete'
}

// ── Submit ────────────────────────────────────────────────────────────
async function submitCreate() {
  if (!form.value.name.trim()) { formError.value = '请填写账户名称'; return }
  submitting.value = true
  formError.value = ''
  try {
    await axios.post('/api/accounts', form.value)
    closeModal()
    await load()
  } catch (e) {
    formError.value = e.response?.data?.detail || '创建失败'
  } finally {
    submitting.value = false
  }
}

async function submitEdit() {
  if (!form.value.name.trim()) { formError.value = '请填写账户名称'; return }
  submitting.value = true
  formError.value = ''
  try {
    await axios.put(`/api/accounts/${selectedAcc.value.id}`, {
      name: form.value.name,
      description: form.value.description,
      color: form.value.color,
    })
    closeModal()
    await load()
  } catch (e) {
    formError.value = e.response?.data?.detail || '更新失败'
  } finally {
    submitting.value = false
  }
}

async function submitFund() {
  if (!fundAmount.value || fundAmount.value <= 0) { formError.value = '请输入有效金额'; return }
  submitting.value = true
  formError.value = ''
  try {
    await axios.post(`/api/accounts/${selectedAcc.value.id}/fund`, {
      op: fundOp.value,
      amount: fundAmount.value,
      note: fundNote.value,
    })
    closeModal()
    await load()
    // refresh detail if open
    if (modal.value === 'detail' && selectedAcc.value) {
      await loadDetail(selectedAcc.value.id)
    }
  } catch (e) {
    formError.value = e.response?.data?.detail || '操作失败'
  } finally {
    submitting.value = false
  }
}

async function submitDelete() {
  submitting.value = true
  try {
    await axios.delete(`/api/accounts/${selectedAcc.value.id}`)
    closeModal()
    await load()
  } catch (e) {
    console.error(e)
  } finally {
    submitting.value = false
  }
}

// ── Formatters ────────────────────────────────────────────────────────
function fmt(v) {
  if (v == null) return '0.00'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDate(s) {
  if (!s) return '-'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.account-view {
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: 100%;
}

/* ── Header ─────────────────────────────────── */
.view-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.header-left { display: flex; flex-direction: column; gap: 2px; }
.view-title { font-size: 18px; font-weight: 700; color: var(--text-1); }
.view-sub { font-size: 12px; color: var(--text-3); }

/* ── Summary row ─────────────────────────────── */
.summary-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.sum-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 16px 20px;
}
.sum-label { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }
.sum-value { font-size: 22px; font-weight: 700; color: var(--text-1); }

/* ── Grid ────────────────────────────────────── */
.accounts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

/* ── Account card ────────────────────────────── */
.account-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.15s, border-color 0.15s;
  position: relative;
}
.account-card:hover {
  border-color: var(--acc-color, var(--accent));
  box-shadow: 0 0 0 1px var(--acc-color, var(--accent))33, var(--shadow-card);
}
.acc-stripe {
  height: 3px;
  background: var(--acc-color, var(--accent));
}

.acc-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 16px 12px;
}
.acc-avatar {
  width: 40px; height: 40px;
  border-radius: var(--radius-lg);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
  flex-shrink: 0;
}
.acc-meta { flex: 1; min-width: 0; }
.acc-name { font-size: 14px; font-weight: 600; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.acc-badges { display: flex; gap: 5px; margin-top: 4px; }
.acc-menu { display: flex; gap: 4px; flex-shrink: 0; }

.type-badge {
  font-size: 10px; font-weight: 600;
  padding: 2px 6px; border-radius: 4px;
}
.type-badge.paper { background: rgba(59,130,246,0.15); color: #60a5fa; }
.type-badge.live  { background: rgba(16,185,129,0.15); color: #34d399; }
.type-badge.default { background: rgba(245,158,11,0.15); color: #fbbf24; }

.icon-btn {
  width: 28px; height: 28px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-3);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.12s;
}
.icon-btn:hover { background: var(--bg-hover); color: var(--text-1); border-color: var(--border); }
.icon-btn.danger:hover { background: rgba(239,68,68,0.1); color: var(--danger); border-color: rgba(239,68,68,0.3); }

.acc-balance {
  padding: 0 16px 14px;
  border-bottom: 1px solid var(--border);
}
.balance-label { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
.balance-value { font-size: 26px; font-weight: 700; color: var(--text-1); letter-spacing: -0.02em; }
.balance-pnl { font-size: 12px; margin-top: 4px; font-weight: 500; }

.acc-stats {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-bottom: 1px solid var(--border);
}
.acc-stat { display: flex; align-items: center; justify-content: space-between; font-size: 12px; }
.stat-l { color: var(--text-3); }
.stat-r { color: var(--text-2); }

.acc-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
}
.btn-action {
  flex: 1;
  padding: 7px 0;
  border-radius: var(--radius-md);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid;
  transition: all 0.12s;
}
.btn-action.deposit  { background: rgba(59,130,246,0.1);  border-color: rgba(59,130,246,0.3);  color: #60a5fa; }
.btn-action.withdraw { background: rgba(239,68,68,0.08);  border-color: rgba(239,68,68,0.25);  color: #f87171; }
.btn-action.detail   { background: var(--bg-elevated); border-color: var(--border); color: var(--text-2); }
.btn-action:hover { filter: brightness(1.15); }

/* ── Loading ──────────────────────────────────── */
.loading-state {
  display: flex; align-items: center; gap: 10px;
  padding: 40px 0; color: var(--text-3); font-size: 13px;
}

/* ── Modal ────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center;
  padding: 16px;
}
.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  width: 100%; max-width: 480px;
  box-shadow: var(--shadow-float);
  display: flex; flex-direction: column;
  max-height: 90vh;
}
.modal-sm { max-width: 380px; }
.modal-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--border);
}
.modal-title { font-size: 15px; font-weight: 600; color: var(--text-1); }
.modal-close {
  background: none; border: none; color: var(--text-3);
  font-size: 20px; cursor: pointer; line-height: 1; padding: 0;
  width: 24px; height: 24px; display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
}
.modal-close:hover { color: var(--text-1); background: var(--bg-hover); }

.modal-body {
  padding: 20px;
  display: flex; flex-direction: column; gap: 14px;
  overflow-y: auto;
}
.modal-foot {
  display: flex; gap: 10px; justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
}

.field { display: flex; flex-direction: column; gap: 6px; }

/* Type selector */
.type-selector { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.type-opt {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer; text-align: left;
  transition: all 0.12s;
}
.type-opt:hover { border-color: var(--border-light); }
.type-opt.active { border-color: var(--accent); background: var(--accent-dim); }
.type-icon { font-size: 20px; flex-shrink: 0; }
.type-opt-label { font-size: 13px; font-weight: 600; color: var(--text-1); }
.type-opt-sub { font-size: 11px; color: var(--text-3); margin-top: 1px; }

/* Color picker */
.color-picker { display: flex; gap: 8px; flex-wrap: wrap; }
.color-dot {
  width: 26px; height: 26px; border-radius: 50%;
  border: 2px solid transparent; cursor: pointer;
  transition: transform 0.12s, border-color 0.12s;
}
.color-dot:hover { transform: scale(1.15); }
.color-dot.selected { border-color: #fff; transform: scale(1.15); }

/* Fund modal */
.fund-acc-info {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-left: 3px solid;
  border-radius: var(--radius-md);
}
.fund-acc-name { font-size: 13px; font-weight: 600; color: var(--text-1); }
.fund-acc-balance { font-size: 12px; color: var(--text-2); }

.quick-amounts { display: flex; gap: 6px; flex-wrap: wrap; }
.quick-btn {
  padding: 4px 10px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-2);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.12s;
}
.quick-btn:hover { border-color: var(--accent); color: var(--accent); }

.btn-danger { background: var(--danger) !important; }
.btn-danger:hover:not(:disabled) { background: #dc2626 !important; }

/* ── Drawer ───────────────────────────────────── */
.drawer-overlay {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,0.55); backdrop-filter: blur(2px);
  display: flex; justify-content: flex-end;
}
.drawer {
  width: 480px; max-width: 95vw;
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }

.drawer-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(to bottom, color-mix(in srgb, var(--acc-color, var(--accent)) 8%, var(--bg-base)), var(--bg-surface));
  border-top: 3px solid var(--acc-color, var(--accent));
}
.drawer-title-row { display: flex; align-items: center; gap: 10px; }
.drawer-dot { width: 10px; height: 10px; border-radius: 50%; }
.drawer-title { font-size: 16px; font-weight: 700; color: var(--text-1); }

.drawer-summary {
  display: grid; grid-template-columns: repeat(4, 1fr);
  border-bottom: 1px solid var(--border);
}
.ds-item {
  padding: 14px 16px;
  border-right: 1px solid var(--border);
}
.ds-item:last-child { border-right: none; }
.ds-label { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 5px; }
.ds-value { font-size: 15px; font-weight: 700; }

.drawer-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-base);
}
.dtab {
  padding: 10px 18px;
  background: none; border: none;
  font-size: 13px; font-weight: 500;
  color: var(--text-3); cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
  transition: color 0.12s, border-color 0.12s;
}
.dtab:hover { color: var(--text-1); }
.dtab.active { color: var(--acc-color, var(--accent)); border-bottom-color: var(--acc-color, var(--accent)); }

.drawer-content { flex: 1; overflow-y: auto; }

/* Fund table inside drawer */
.drawer-content .data-table { font-size: 12px; }
.op-badge {
  font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px;
}
.op-badge.deposit  { background: rgba(59,130,246,0.15); color: #60a5fa; }
.op-badge.withdraw { background: rgba(239,68,68,0.12);  color: #f87171; }

/* Log list */
.log-list { display: flex; flex-direction: column; padding: 8px 0; }
.log-row {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
.log-row:last-child { border-bottom: none; }
.log-dot {
  width: 8px; height: 8px; border-radius: 50%;
  flex-shrink: 0; margin-top: 5px;
  background: var(--accent);
}
.log-dot.created  { background: var(--success); }
.log-dot.deposit  { background: #60a5fa; }
.log-dot.withdraw { background: var(--danger); }
.log-dot.updated  { background: var(--warning); }

.log-body { flex: 1; min-width: 0; }
.log-detail { font-size: 12px; color: var(--text-1); line-height: 1.5; }
.log-time   { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.drawer-foot {
  display: flex; gap: 10px;
  padding: 14px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-base);
}
.drawer-foot .btn-action { flex: 1; }

/* ── Responsive ───────────────────────────────── */
@media (max-width: 768px) {
  .account-view { padding: 12px; gap: 14px; }
  .summary-row { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .sum-value { font-size: 18px; }
  .accounts-grid { grid-template-columns: 1fr; }
  .drawer { width: 100%; max-width: 100%; position: fixed; inset: auto 0 0 0; height: 90vh; border-left: none; border-top: 1px solid var(--border); border-radius: var(--radius-xl) var(--radius-xl) 0 0; }
  .drawer-overlay { align-items: flex-end; justify-content: stretch; }
  .drawer-summary { grid-template-columns: repeat(2, 1fr); }
  .type-selector { grid-template-columns: 1fr; }
  .modal { max-width: 100%; margin: 0; border-radius: var(--radius-xl) var(--radius-xl) 0 0; align-self: flex-end; }
  .modal-overlay { align-items: flex-end; }
}
@media (max-width: 480px) {
  .summary-row { grid-template-columns: 1fr 1fr; }
}
</style>
