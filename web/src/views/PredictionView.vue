<template>
  <div class="pred-wrap">
    <!-- Header -->
    <div class="pred-header">
      <div class="header-left">
        <div class="page-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
          AI 预测验证
        </div>
        <span class="header-sub">记录每日AI选股预测，次日验证实际结果</span>
      </div>
      <div class="header-right">
        <span v-if="verifyMsg" :class="['verify-msg', verifyMsg.type]">{{ verifyMsg.text }}</span>
        <button class="btn-verify" @click="triggerVerify" :disabled="verifying">
          {{ verifying ? '验证中...' : '验证昨日预测' }}
        </button>
      </div>
    </div>

    <!-- Stats bar -->
    <div class="stats-bar" v-if="stats.total > 0">
      <div class="stat-card">
        <div class="stat-val">{{ stats.total }}</div>
        <div class="stat-lbl">历史预测</div>
      </div>
      <div class="stat-card accent">
        <div class="stat-val">{{ stats.accuracy_pct }}%</div>
        <div class="stat-lbl">方向准确率</div>
      </div>
      <div class="stat-card green">
        <div class="stat-val">{{ stats.hit_target }}</div>
        <div class="stat-lbl">达到目标价</div>
      </div>
      <div class="stat-card red">
        <div class="stat-val">{{ stats.hit_stop }}</div>
        <div class="stat-lbl">触及止损</div>
      </div>
      <div class="stat-card">
        <div class="stat-val">{{ stats.avg_change_pct != null ? stats.avg_change_pct + '%' : '-' }}</div>
        <div class="stat-lbl">平均涨跌幅</div>
      </div>
    </div>

    <!-- Filter bar -->
    <div class="filter-bar">
      <select v-model="filterVerified" @change="load">
        <option :value="null">全部状态</option>
        <option :value="false">待验证</option>
        <option :value="true">已验证</option>
      </select>
      <input v-model="filterDate" type="date" @change="load" placeholder="按日期筛选" />
      <span class="total-hint">共 {{ total }} 条</span>
    </div>

    <!-- Table -->
    <div class="pred-table-wrap">
      <table class="pred-table" v-if="predictions.length">
        <thead>
          <tr>
            <th>日期</th><th>股票</th><th>买入价</th><th>止损价</th><th>目标价</th>
            <th>置信度</th><th>风险</th><th>实际收盘</th><th>涨跌</th><th>结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in predictions" :key="p.id">
            <td class="td-date">{{ p.date }}</td>
            <td class="td-stock">
              <span class="stock-name">{{ p.name }}</span>
              <span class="stock-code">{{ p.code }}</span>
            </td>
            <td>{{ p.buy_price ?? '-' }}</td>
            <td class="td-stop">{{ p.stop_price ?? '-' }}</td>
            <td class="td-target">{{ p.target_price ?? '-' }}</td>
            <td>
              <div class="conf-bar">
                <div class="conf-fill" :style="{ width: (p.confidence || 0) + '%' }"></div>
                <span>{{ p.confidence ?? '-' }}</span>
              </div>
            </td>
            <td><span :class="['risk-badge', 'risk-' + (p.risk_level || '中')]">{{ p.risk_level ?? '-' }}</span></td>
            <td>{{ p.actual_close ?? '-' }}</td>
            <td :class="changeClass(p.actual_change_pct)">
              {{ p.actual_change_pct != null ? (p.actual_change_pct > 0 ? '+' : '') + p.actual_change_pct + '%' : '-' }}
            </td>
            <td><span :class="['outcome-badge', 'outcome-' + (p.outcome || 'open')]">{{ outcomeLabel(p.outcome) }}</span></td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="!loading" class="empty-state">
        <p>暂无预测记录</p>
        <p class="empty-sub">AI选股后会自动生成预测记录，次日可验证</p>
      </div>
      <div v-if="loading" class="loading-msg">加载中...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const predictions = ref([])
const stats = ref({})
const total = ref(0)
const loading = ref(false)
const verifying = ref(false)
const verifyMsg = ref(null)
const filterVerified = ref(null)
const filterDate = ref('')

async function load() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (filterVerified.value !== null) params.verified = filterVerified.value
    if (filterDate.value) params.date = filterDate.value
    const [predsRes, statsRes] = await Promise.all([
      axios.get('/api/predictions/', { params }),
      axios.get('/api/predictions/stats'),
    ])
    predictions.value = predsRes.data.predictions
    total.value = predsRes.data.total
    stats.value = statsRes.data
  } finally {
    loading.value = false
  }
}

async function triggerVerify() {
  verifying.value = true
  verifyMsg.value = null
  try {
    const res = await axios.post('/api/predictions/verify')
    verifyMsg.value = { type: 'ok', text: res.data.message || '验证任务已启动，稍后刷新' }
    setTimeout(() => {
      load()
      setTimeout(() => { verifyMsg.value = null }, 2000)
    }, 3000)
  } catch (e) {
    verifyMsg.value = { type: 'err', text: e.response?.data?.detail || '验证失败，请重试' }
  } finally {
    verifying.value = false
  }
}

function outcomeLabel(outcome) {
  const map = {
    hit_target: '达目标', hit_stop: '触止损', positive: '正收益',
    negative: '负收益', neutral: '持平', open: '待验证',
  }
  return map[outcome] || outcome || '待验证'
}

function changeClass(v) {
  if (v == null) return ''
  return v > 0 ? 'td-up' : v < 0 ? 'td-down' : ''
}

onMounted(load)
</script>

<style scoped>
.pred-wrap { padding: 20px; display: flex; flex-direction: column; gap: 16px; }

.pred-header { display: flex; justify-content: space-between; align-items: center; }
.page-badge { display: inline-flex; align-items: center; gap: 6px; background: var(--accent-dim); color: var(--accent); padding: 5px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.header-sub { font-size: 12px; color: var(--text-3); margin-left: 10px; }
.btn-verify { background: var(--accent); color: #fff; border: none; border-radius: var(--radius-md); padding: 7px 16px; font-size: 13px; cursor: pointer; }
.btn-verify:disabled { opacity: 0.6; cursor: not-allowed; }
.verify-msg { font-size: 12px; padding: 4px 10px; border-radius: 6px; margin-right: 8px; }
.verify-msg.ok { background: #dcfce7; color: #166534; }
.verify-msg.err { background: #fee2e2; color: #991b1b; }

.stats-bar { display: flex; gap: 12px; flex-wrap: wrap; }
.stat-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px 20px; min-width: 100px; }
.stat-card.accent .stat-val { color: var(--accent); }
.stat-card.green .stat-val { color: #22c55e; }
.stat-card.red .stat-val { color: #ef4444; }
.stat-val { font-size: 22px; font-weight: 700; color: var(--text-1); }
.stat-lbl { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.filter-bar { display: flex; gap: 10px; align-items: center; }
.filter-bar select, .filter-bar input { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 6px 10px; font-size: 13px; }
.total-hint { font-size: 12px; color: var(--text-3); margin-left: auto; }

.pred-table-wrap { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); overflow: auto; }
.pred-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pred-table th { background: var(--bg-hover); color: var(--text-2); font-weight: 600; padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
.pred-table td { padding: 9px 12px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.pred-table tr:last-child td { border-bottom: none; }
.td-date { font-size: 12px; color: var(--text-3); }
.stock-name { font-weight: 600; }
.stock-code { font-size: 11px; color: var(--text-3); margin-left: 4px; }
.td-stop { color: #ef4444; }
.td-target { color: #22c55e; }
.td-up { color: #ef4444; font-weight: 600; }
.td-down { color: #22c55e; font-weight: 600; }

.conf-bar { display: flex; align-items: center; gap: 6px; }
.conf-fill { height: 4px; background: var(--accent); border-radius: 2px; min-width: 2px; }
.conf-bar span { font-size: 11px; color: var(--text-3); }

.risk-badge { padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.risk-低 { background: #dcfce7; color: #166534; }
.risk-中 { background: #fef9c3; color: #854d0e; }
.risk-高 { background: #fee2e2; color: #991b1b; }

.outcome-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.outcome-hit_target { background: #dcfce7; color: #166534; }
.outcome-positive { background: #dbeafe; color: #1e40af; }
.outcome-hit_stop { background: #fee2e2; color: #991b1b; }
.outcome-negative { background: #fef2f2; color: #b91c1c; }
.outcome-neutral { background: var(--bg-hover); color: var(--text-2); }
.outcome-open { background: var(--bg-hover); color: var(--text-3); }

.empty-state { padding: 48px; text-align: center; color: var(--text-2); }
.empty-sub { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.loading-msg { padding: 24px; text-align: center; color: var(--text-3); }
</style>
