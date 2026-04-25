<template>
  <div class="dashboard">
    <!-- Stat cards row -->
    <div class="stats-row">
      <div class="metric-card" v-for="m in stats" :key="m.label">
        <div class="metric-label">{{ m.label }}</div>
        <div class="metric-value" :style="m.color ? { color: m.color } : {}">{{ m.value }}</div>
        <div class="metric-sub">{{ m.sub }}</div>
      </div>
    </div>

    <div class="main-grid">
      <!-- Recent backtests -->
      <div class="panel">
        <div class="panel-header">
          <span class="panel-title">最近回测</span>
          <router-link to="/backtest" class="panel-link">新建 →</router-link>
        </div>
        <div v-if="loadingJobs" class="panel-loading">
          <span class="spinner spinner-sm"></span> 加载中...
        </div>
        <div v-else-if="recentJobs.length === 0" class="empty-state">
          <p>暂无回测记录</p>
          <p class="empty-hint">前往回测页面运行第一个策略</p>
        </div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>策略</th>
              <th>标的</th>
              <th>状态</th>
              <th>收益率</th>
              <th>夏普</th>
              <th>最大回撤</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="job in recentJobs" :key="job.job_id">
              <td>
                <span class="strategy-name">{{ strategyName(job.strategy) }}</span>
              </td>
              <td class="mono text-2">{{ job.symbol || (job.symbols?.[0] ?? '-') }}</td>
              <td>
                <span :class="['badge', statusBadge(job.status)]">{{ statusLabel(job.status) }}</span>
              </td>
              <td :class="(job.summary?.total_return ?? 0) >= 0 ? 'pos' : 'neg'">
                {{ job.summary ? pct(job.summary.total_return) : '-' }}
              </td>
              <td class="mono">{{ job.summary ? job.summary.sharpe_ratio.toFixed(2) : '-' }}</td>
              <td class="neg">{{ job.summary ? pct(job.summary.max_drawdown) : '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Right column -->
      <div class="right-col">
        <!-- Portfolio summary -->
        <div class="panel" v-if="portfolio">
          <div class="panel-header">
            <span class="panel-title">模拟交易</span>
            <router-link to="/live" class="panel-link">查看 →</router-link>
          </div>
          <div class="portfolio-row">
            <div class="p-item">
              <div class="p-label">总资产</div>
              <div class="p-value mono">¥{{ fmt(portfolio.total_balance) }}</div>
            </div>
            <div class="p-item">
              <div class="p-label">浮动盈亏</div>
              <div class="p-value mono" :class="portfolio.total_unrealized_pnl >= 0 ? 'pos' : 'neg'">
                {{ fmtPnl(portfolio.total_unrealized_pnl) }}
              </div>
            </div>
            <div class="p-item">
              <div class="p-label">运行策略</div>
              <div class="p-value">{{ portfolio.running_count }} 个</div>
            </div>
          </div>
        </div>

        <!-- Strategy library -->
        <div class="panel">
          <div class="panel-header">
            <span class="panel-title">策略库</span>
            <router-link to="/screener" class="panel-link">全部 →</router-link>
          </div>
          <div class="strategy-chips">
            <router-link
              v-for="s in strategies.slice(0, 6)" :key="s.name"
              :to="{ path: '/backtest', query: { strategy: s.module_path } }"
              class="strategy-chip"
              :style="{ '--chip-color': s.category_color || 'var(--accent)' }"
            >
              <span class="chip-dot"></span>
              <span class="chip-name">{{ s.display_name || s.name }}</span>
              <span class="chip-cat">{{ s.category_label }}</span>
            </router-link>
          </div>
        </div>

        <!-- Quick actions -->
        <div class="quick-actions">
          <router-link to="/backtest" class="qa-card">
            <div class="qa-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M9 3h6l1 9H8L9 3z"/><path d="M6.1 15a3 3 0 0 0 2.19 5h7.42a3 3 0 0 0 2.19-5L15 12H9L6.1 15z"/>
              </svg>
            </div>
            <span class="qa-label">运行回测</span>
          </router-link>
          <router-link to="/screener" class="qa-card">
            <div class="qa-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
            </div>
            <span class="qa-label">选股推荐</span>
          </router-link>
          <router-link to="/market-hub" class="qa-card">
            <div class="qa-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>
              </svg>
            </div>
            <span class="qa-label">市场全景</span>
          </router-link>
          <router-link to="/ai-picks" class="qa-card">
            <div class="qa-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
              </svg>
            </div>
            <span class="qa-label">今日推荐</span>
          </router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const recentJobs = ref([])
const strategies  = ref([])
const portfolio   = ref(null)
const loadingJobs = ref(true)

const strategyMap = computed(() => {
  const m = {}
  for (const s of strategies.value) {
    m[s.module_path] = s.display_name || s.name
    if (s.name) m[s.name] = s.display_name || s.name
  }
  return m
})

function strategyName(path) {
  if (!path) return '-'
  return strategyMap.value[path] || path.split('.').pop()
}

const stats = computed(() => {
  const done = recentJobs.value.filter(j => j.status === 'done')
  const avgRet = done.length ? done.reduce((s, j) => s + (j.summary?.total_return || 0), 0) / done.length : null
  const bestSharpe = done.length ? Math.max(...done.map(j => j.summary?.sharpe_ratio || 0)) : null
  return [
    { label: '回测总数', value: recentJobs.value.length || '-', sub: '历史累计' },
    { label: '成功完成', value: done.length || '-', sub: '有效回测', color: done.length ? 'var(--success)' : null },
    { label: '平均收益率', value: avgRet !== null ? pct(avgRet) : '-', sub: '已完成回测', color: avgRet !== null ? (avgRet >= 0 ? 'var(--profit)' : 'var(--loss)') : null },
    { label: '最高夏普', value: bestSharpe !== null ? bestSharpe.toFixed(2) : '-', sub: '风险调整收益', color: bestSharpe > 1 ? 'var(--accent)' : null },
    { label: '策略数量', value: strategies.value.length || '-', sub: '内置策略库' },
    { label: '模拟会话', value: portfolio.value?.running_count ?? '-', sub: '当前运行中', color: portfolio.value?.running_count > 0 ? 'var(--accent)' : null },
  ]
})

function pct(v) { return v != null ? (v * 100).toFixed(2) + '%' : '-' }
function fmt(v) { return v != null ? v.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) : '-' }
function fmtPnl(v) {
  if (v == null) return '-'
  return (v >= 0 ? '+' : '') + v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function statusBadge(s) {
  return { done: 'badge-green', running: 'badge-blue', error: 'badge-red', queued: 'badge-amber' }[s] || 'badge-gray'
}
function statusLabel(s) {
  return { done: '完成', running: '运行中', error: '失败', queued: '排队' }[s] || s
}

onMounted(async () => {
  await Promise.all([
    axios.get('/api/backtest/').then(r => { recentJobs.value = (r.data || []).slice(-8).reverse() }).catch(() => {}),
    axios.get('/api/strategy/').then(r => { strategies.value = r.data || [] }).catch(() => {}),
    axios.get('/api/portfolio/').then(r => { portfolio.value = r.data }).catch(() => {}),
  ])
  loadingJobs.value = false
})
</script>

<style scoped>
.dashboard { padding: 24px; display: flex; flex-direction: column; gap: 20px; }

.stats-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}

.main-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 16px;
  align-items: start;
}

/* Panel */
.panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-xl); overflow: hidden; margin-bottom: 16px; }
.panel:last-child { margin-bottom: 0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 12px; border-bottom: 1px solid var(--border); }
.panel-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.panel-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.panel-link:hover { text-decoration: underline; }
.panel-loading { display: flex; align-items: center; gap: 8px; padding: 20px 16px; color: var(--text-2); font-size: 12px; }

.strategy-name { font-size: 12px; font-weight: 500; color: var(--text-1); }

/* Portfolio mini */
.portfolio-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px; background: var(--border); }
.p-item { background: var(--bg-surface); padding: 14px 16px; }
.p-label { font-size: 11px; color: var(--text-2); margin-bottom: 5px; }
.p-value { font-size: 16px; font-weight: 700; }

/* Strategy chips */
.strategy-chips { display: flex; flex-direction: column; padding: 8px 0; }
.strategy-chip {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 16px;
  text-decoration: none;
  color: var(--text-1);
  transition: background 0.12s;
  font-size: 12px;
}
.strategy-chip:hover { background: var(--bg-hover); }
.chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--chip-color, var(--accent)); flex-shrink: 0; }
.chip-name { flex: 1; font-weight: 500; }
.chip-cat { font-size: 10px; color: var(--text-3); }

/* Quick actions */
.quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.qa-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  text-decoration: none;
  color: var(--text-2);
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  transition: all 0.15s;
  text-align: center;
}
.qa-card:hover { background: var(--bg-hover); color: var(--text-1); border-color: var(--border-light); }
.qa-icon { color: var(--accent); }
.qa-label { font-size: 12px; font-weight: 500; }

.right-col { display: flex; flex-direction: column; gap: 16px; }
.right-col .panel { margin-bottom: 0; }

@media (max-width: 768px) {
  .dashboard { padding: 12px; gap: 14px; }
  .stats-row { grid-template-columns: repeat(3, 1fr); gap: 8px; }
  .main-grid { grid-template-columns: 1fr; }
  .right-col { gap: 12px; }
  .panel-header { padding: 12px 12px 10px; }
  .data-table-wrap { overflow-x: auto; }
}

@media (max-width: 480px) {
  .stats-row { grid-template-columns: repeat(2, 1fr); }
  .portfolio-row { grid-template-columns: 1fr; }
  .quick-actions { grid-template-columns: 1fr 1fr; }
}
</style>
