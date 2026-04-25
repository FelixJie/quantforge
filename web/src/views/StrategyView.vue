<template>
  <div class="strategy-view">
    <!-- Search + filters -->
    <div class="toolbar">
      <div class="search-wrap">
        <svg class="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input class="search-input" v-model="query" placeholder="搜索策略名称、标签、逻辑..." />
        <button v-if="query" class="clear-btn" @click="query = ''">×</button>
      </div>
      <div class="cat-filters">
        <button
          v-for="cat in categories" :key="cat.key"
          :class="['cat-btn', activeCat === cat.key ? 'active' : '']"
          :style="activeCat === cat.key ? { borderColor: cat.color, color: cat.color, background: cat.color + '18' } : {}"
          @click="activeCat = activeCat === cat.key ? 'all' : cat.key"
        >{{ cat.label }}
          <span class="cat-count">{{ cat.count }}</span>
        </button>
      </div>
    </div>

    <!-- Recommendations -->
    <div class="rec-section" v-if="!query && activeCat === 'all'">
      <div class="rec-header">
        <span class="section-label">推荐方案</span>
        <span class="text-3" style="font-size:11px">根据不同行情场景选择策略组合</span>
      </div>
      <div class="rec-grid">
        <div v-for="rec in recommendations" :key="rec.label" class="rec-card" :style="{ '--rc': rec.color }">
          <div class="rec-icon" v-html="rec.svg"></div>
          <div class="rec-body">
            <div class="rec-label">{{ rec.label }}</div>
            <div class="rec-desc">{{ rec.desc }}</div>
            <div class="rec-chips">
              <span
                v-for="name in rec.strategies" :key="name"
                class="rec-chip"
                @click="openDetail(strategyByName(name))"
              >{{ displayName(name) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Strategy count -->
    <div class="count-bar" v-if="filteredStrategies.length">
      <span class="text-2" style="font-size:12px">{{ filteredStrategies.length }} 个策略</span>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-row">
      <span class="spinner"></span>
      <span class="text-2">加载策略库...</span>
    </div>

    <!-- Grid -->
    <div class="strategy-grid" v-if="!loading && filteredStrategies.length">
      <div
        v-for="s in filteredStrategies" :key="s.name"
        class="s-card card"
        :style="{ '--cc': s.category_color || 'var(--accent)' }"
        @click="openDetail(s)"
      >
        <!-- ID badge -->
        <div class="s-id-row">
          <span class="s-id mono">{{ s.id }}</span>
          <span class="s-badge badge" :class="catBadge(s.category)">{{ s.category_label }}</span>
        </div>

        <!-- Header -->
        <div class="s-head">
          <span class="s-name">{{ s.display_name || s.name }}</span>
          <span class="s-class text-3 mono">{{ s.class_name }}</span>
        </div>

        <!-- Description -->
        <p class="s-desc">{{ s.description }}</p>

        <!-- Info rows -->
        <div class="s-info-row" v-if="s.logic">
          <span class="info-key">逻辑</span>
          <span class="info-val">{{ s.logic }}</span>
        </div>
        <div class="s-info-row" v-if="s.suitable">
          <span class="info-key">适合</span>
          <span class="info-val">{{ s.suitable }}</span>
        </div>
        <div class="s-info-row" v-if="s.risk">
          <span class="info-key">风险</span>
          <span class="info-val risk" :class="riskCls(s.risk)">{{ s.risk }}</span>
        </div>

        <!-- Tags -->
        <div class="s-tags" v-if="s.tags?.length">
          <span v-for="t in s.tags" :key="t" class="s-tag">{{ t }}</span>
        </div>

        <!-- Capability badges (YAML strategies) -->
        <div class="s-caps" v-if="s.source === 'yaml'" @click.stop>
          <span class="cap-badge cap-yaml">YAML</span>
          <span class="cap-badge cap-screen" v-if="s.has_screener">选股筛选</span>
          <span class="cap-badge cap-signal">AI信号</span>
          <span class="cap-badge cap-bt" v-if="s.has_backtest">可回测</span>
        </div>

        <!-- Actions -->
        <div class="s-actions" @click.stop>
          <code class="mod-path text-3">{{ s.source === 'yaml' ? 'YAML · ' + (s.execution_display || '-') : shortPath(s.module_path) }}</code>
          <div class="action-btns" v-if="s.source !== 'yaml'">
            <router-link :to="{ path: '/backtest', query: { strategy: s.module_path } }" class="btn-ghost">回测</router-link>
            <router-link :to="{ path: '/live', query: { strategy: s.module_path } }" class="btn-live">模拟 ▶</router-link>
          </div>
          <div class="action-btns" v-else>
            <router-link :to="{ path: '/screener', query: { strategy: 'yaml_' + s.yaml_name } }" class="btn-ghost" v-if="s.has_screener">筛选</router-link>
            <router-link :to="{ path: '/yaml-strategy', query: { strategy: s.yaml_name } }" class="btn-ghost">问股</router-link>
            <router-link v-if="s.has_backtest" :to="{ path: '/backtest', query: { strategy: s.module_path } }" class="btn-live">回测 ▶</router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty -->
    <div v-if="!loading && filteredStrategies.length === 0" class="empty-state card">
      <p>没有找到匹配的策略</p>
      <p class="empty-hint">尝试其他关键词或清除筛选</p>
    </div>

    <!-- Detail Drawer -->
    <Teleport to="body">
      <div v-if="detailStrategy" class="drawer-overlay" @click.self="closeDetail">
        <div class="drawer" :style="{ '--dc': detailStrategy.category_color || 'var(--accent)' }">
          <!-- Drawer header -->
          <div class="drawer-header">
            <div class="drawer-header-left">
              <span class="drawer-id mono">{{ detailStrategy.id }}</span>
              <div>
                <div class="drawer-title">{{ detailStrategy.display_name }}</div>
                <div class="drawer-class mono text-3">{{ detailStrategy.class_name }}</div>
              </div>
            </div>
            <button class="drawer-close" @click="closeDetail">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <div class="drawer-body">
            <!-- Category + Tags -->
            <div class="drawer-meta">
              <span class="badge" :class="catBadge(detailStrategy.category)">{{ detailStrategy.category_label }}</span>
              <span v-for="t in detailStrategy.tags" :key="t" class="s-tag">{{ t }}</span>
            </div>

            <!-- Description -->
            <div class="drawer-section">
              <div class="drawer-section-title">策略简介</div>
              <p class="drawer-desc">{{ detailStrategy.description }}</p>
            </div>

            <!-- Logic / Suitable / Risk -->
            <div class="drawer-section">
              <div class="drawer-section-title">策略属性</div>
              <div class="detail-grid">
                <div class="detail-row" v-if="detailStrategy.logic">
                  <span class="detail-key">交易逻辑</span>
                  <span class="detail-val">{{ detailStrategy.logic }}</span>
                </div>
                <div class="detail-row" v-if="detailStrategy.suitable">
                  <span class="detail-key">适合行情</span>
                  <span class="detail-val">{{ detailStrategy.suitable }}</span>
                </div>
                <div class="detail-row" v-if="detailStrategy.risk">
                  <span class="detail-key">风险等级</span>
                  <span class="detail-val risk" :class="riskCls(detailStrategy.risk)">{{ detailStrategy.risk }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-key">策略ID</span>
                  <code class="detail-val mono">{{ detailStrategy.id }}</code>
                </div>
                <div class="detail-row">
                  <span class="detail-key">分类</span>
                  <span class="detail-val">{{ detailStrategy.category_label }}</span>
                </div>
              </div>
            </div>

            <!-- Parameters -->
            <div class="drawer-section" v-if="detailStrategy.parameters?.length">
              <div class="drawer-section-title">参数说明</div>
              <table class="params-table">
                <thead><tr><th>参数名</th><th>说明</th></tr></thead>
                <tbody>
                  <tr v-for="p in detailStrategy.parameters" :key="p">
                    <td><code class="param-token">{{ p }}</code></td>
                    <td class="param-desc">{{ detailStrategy.params_desc?.[p] || '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- YAML: Three-channel section -->
            <div class="drawer-section" v-if="detailStrategy.source === 'yaml'">
              <div class="drawer-section-title">三通道能力</div>
              <div class="three-channels">
                <div class="channel-card" :class="detailStrategy.has_screener ? 'active' : 'inactive'">
                  <div class="ch-icon">📊</div>
                  <div class="ch-label">选股筛选</div>
                  <div class="ch-desc">{{ detailStrategy.has_screener ? '已配置筛选条件，可在选股页使用' : '未配置' }}</div>
                  <router-link v-if="detailStrategy.has_screener"
                    :to="{ path: '/screener', query: { strategy: 'yaml_' + detailStrategy.yaml_name } }"
                    class="ch-link" @click="closeDetail">去筛选 →</router-link>
                </div>
                <div class="channel-card active">
                  <div class="ch-icon">🤖</div>
                  <div class="ch-label">AI信号问股</div>
                  <div class="ch-desc">LLM解析策略规则，对单只股票给出操作信号</div>
                  <router-link
                    :to="{ path: '/yaml-strategy', query: { strategy: detailStrategy.yaml_name } }"
                    class="ch-link" @click="closeDetail">去问股 →</router-link>
                </div>
                <div class="channel-card" :class="detailStrategy.has_backtest ? 'active' : 'inactive'">
                  <div class="ch-icon">📈</div>
                  <div class="ch-label">回测/实盘</div>
                  <div class="ch-desc">{{ detailStrategy.has_backtest ? '对应策略：' + (detailStrategy.execution_display || '-') : '未配置执行类' }}</div>
                  <router-link v-if="detailStrategy.has_backtest"
                    :to="{ path: '/backtest', query: { strategy: detailStrategy.module_path } }"
                    class="ch-link" @click="closeDetail">去回测 →</router-link>
                </div>
              </div>
            </div>

            <!-- Module path (builtin only) -->
            <div class="drawer-section" v-if="detailStrategy.source !== 'yaml'">
              <div class="drawer-section-title">模块路径</div>
              <code class="full-path mono">{{ detailStrategy.module_path }}</code>
            </div>

            <!-- YAML links for builtin strategies -->
            <div class="drawer-section" v-if="detailStrategy.yaml_links?.length">
              <div class="drawer-section-title">关联YAML策略</div>
              <div class="yaml-links">
                <router-link
                  v-for="yn in detailStrategy.yaml_links" :key="yn"
                  :to="{ path: '/yaml-strategy', query: { strategy: yn } }"
                  class="yaml-link-chip" @click="closeDetail"
                >{{ yn }}</router-link>
              </div>
            </div>
          </div>

          <!-- Drawer footer -->
          <div class="drawer-footer" v-if="detailStrategy.source !== 'yaml'">
            <router-link
              :to="{ path: '/backtest', query: { strategy: detailStrategy.module_path } }"
              class="btn-ghost"
              @click="closeDetail"
            >去回测</router-link>
            <router-link
              :to="{ path: '/live', query: { strategy: detailStrategy.module_path } }"
              class="btn-primary"
              @click="closeDetail"
            >启动模拟 ▶</router-link>
          </div>
          <div class="drawer-footer" v-else>
            <router-link v-if="detailStrategy.has_screener"
              :to="{ path: '/screener', query: { strategy: 'yaml_' + detailStrategy.yaml_name } }"
              class="btn-ghost" @click="closeDetail">筛选股票</router-link>
            <router-link
              :to="{ path: '/yaml-strategy', query: { strategy: detailStrategy.yaml_name } }"
              class="btn-ghost" @click="closeDetail">AI问股</router-link>
            <router-link v-if="detailStrategy.has_backtest"
              :to="{ path: '/backtest', query: { strategy: detailStrategy.module_path } }"
              class="btn-primary" @click="closeDetail">回测 ▶</router-link>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const strategies = ref([])
const loading    = ref(true)
const query      = ref('')
const activeCat  = ref('all')
const detailStrategy = ref(null)

const recommendations = [
  {
    label: '趋势行情',
    desc: '单边上涨时，趋势跟随策略效果最佳',
    color: '#3b82f6',
    strategies: ['dual_ma', 'macd', 'turtle_breakout', 'chandelier_exit'],
    svg: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  },
  {
    label: '震荡行情',
    desc: '横盘震荡时，均值回归和网格策略更稳',
    color: '#22c55e',
    strategies: ['rsi_mean_revert', 'keltner_channel', 'grid_trading'],
    svg: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-9 4 18 3-9h4"/></svg>`,
  },
  {
    label: 'AI驱动',
    desc: '数据充足时，机器学习策略自动学习规律',
    color: '#f59e0b',
    strategies: ['ensemble_voting', 'ml_alpha', 'adaptive_momentum'],
    svg: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>`,
  },
  {
    label: '突破放量',
    desc: '量价共振确认真实突破，过滤假信号',
    color: '#a855f7',
    strategies: ['volume_price_breakout', 'bollinger_breakout', 'turtle_breakout'],
    svg: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  },
]

const categories = computed(() => {
  const catMap = {}
  for (const s of strategies.value.filter(s => !s.error)) {
    if (!s.category) continue
    if (!catMap[s.category]) catMap[s.category] = { key: s.category, label: s.category_label || s.category, color: s.category_color || '#718096', count: 0 }
    catMap[s.category].count++
  }
  return [
    { key: 'all', label: '全部', color: 'var(--text-2)', count: strategies.value.filter(s => !s.error).length },
    ...Object.values(catMap),
  ]
})

const filteredStrategies = computed(() => {
  let list = strategies.value.filter(s => !s.error)
  if (activeCat.value !== 'all') list = list.filter(s => s.category === activeCat.value)
  if (query.value.trim()) {
    const q = query.value.toLowerCase()
    list = list.filter(s =>
      (s.display_name || s.name).toLowerCase().includes(q) ||
      s.description?.toLowerCase().includes(q) ||
      s.tags?.some(t => t.toLowerCase().includes(q)) ||
      s.logic?.toLowerCase().includes(q) ||
      s.id?.toLowerCase().includes(q)
    )
  }
  return list
})

function strategyByName(name) { return strategies.value.find(s => s.name === name) }
function displayName(name) { return strategyByName(name)?.display_name || name }
function shortPath(p) { return p ? p.split('.').slice(-2).join('.') : '' }
function riskCls(r) { return r?.includes('低') ? 'risk-low' : r?.includes('高') ? 'risk-high' : 'risk-mid' }
function catBadge(cat) {
  return { trend_following: 'badge-blue', mean_reversion: 'badge-green', adaptive: 'badge-purple', ml: 'badge-amber' }[cat] || 'badge-gray'
}

function openDetail(s) {
  if (!s) return
  detailStrategy.value = s
  document.body.style.overflow = 'hidden'
}
function closeDetail() {
  detailStrategy.value = null
  document.body.style.overflow = ''
}

function onKeydown(e) { if (e.key === 'Escape') closeDetail() }
onMounted(async () => {
  try { const r = await axios.get('/api/strategy/'); strategies.value = r.data } catch {}
  loading.value = false
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => { window.removeEventListener('keydown', onKeydown); document.body.style.overflow = '' })
</script>

<style scoped>
.strategy-view { padding: 24px; display: flex; flex-direction: column; gap: 16px; }

/* Toolbar */
.toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.search-wrap {
  position: relative; display: flex; align-items: center;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 0 10px; gap: 7px;
  min-width: 240px; transition: border-color 0.15s;
}
.search-wrap:focus-within { border-color: var(--accent); }
.search-icon { color: var(--text-3); flex-shrink: 0; }
.search-input { background: transparent; border: none; outline: none; color: var(--text-1); font-size: 13px; padding: 7px 0; flex: 1; font-family: var(--font-body); }
.search-input::placeholder { color: var(--text-3); }
.clear-btn { background: none; border: none; color: var(--text-3); font-size: 16px; cursor: pointer; padding: 0 2px; line-height: 1; }
.clear-btn:hover { color: var(--text-1); }

.cat-filters { display: flex; gap: 6px; flex-wrap: wrap; }
.cat-btn {
  background: var(--bg-surface); border: 1px solid var(--border);
  color: var(--text-2); border-radius: 20px; padding: 4px 12px; font-size: 12px; cursor: pointer;
  transition: all 0.12s; display: flex; align-items: center; gap: 5px;
}
.cat-btn:hover:not(.active) { background: var(--bg-hover); color: var(--text-1); }
.cat-count { font-size: 10px; opacity: 0.7; }

/* Recommendations */
.rec-header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.section-label { font-size: 12px; font-weight: 600; color: var(--text-1); text-transform: uppercase; letter-spacing: 0.06em; }
.rec-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.rec-card {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-top: 2px solid var(--rc, var(--accent));
  border-radius: var(--radius-lg); padding: 14px;
  display: flex; gap: 10px;
}
.rec-icon { color: var(--rc, var(--accent)); flex-shrink: 0; margin-top: 2px; }
.rec-label { font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 3px; }
.rec-desc { font-size: 11px; color: var(--text-2); margin-bottom: 8px; line-height: 1.4; }
.rec-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.rec-chip {
  font-size: 10px; padding: 2px 7px;
  background: color-mix(in srgb, var(--rc, var(--accent)) 15%, transparent);
  color: var(--rc, var(--accent));
  border-radius: 3px; cursor: pointer;
  transition: opacity 0.12s;
}
.rec-chip:hover { opacity: 0.75; }

.count-bar { display: flex; align-items: center; }
.loading-row { display: flex; align-items: center; gap: 10px; padding: 16px 0; }

/* Strategy grid */
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }

.s-card {
  padding: 16px 18px;
  border-left: 3px solid var(--cc, var(--accent));
  display: flex; flex-direction: column; gap: 9px;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.1s;
}
.s-card:hover {
  box-shadow: 0 0 0 1px var(--cc, var(--accent))44, var(--shadow-card);
  transform: translateY(-1px);
}

.s-id-row { display: flex; align-items: center; justify-content: space-between; }
.s-id { font-size: 10px; color: var(--cc, var(--accent)); letter-spacing: 0.05em; font-weight: 700; }
.s-badge { font-size: 10px; border-radius: 3px; }

.s-head { display: flex; flex-direction: column; gap: 2px; }
.s-name { font-size: 15px; font-weight: 700; color: var(--text-1); }
.s-class { font-size: 11px; }

.s-desc { font-size: 12px; color: var(--text-2); line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

.s-info-row { display: flex; gap: 8px; font-size: 12px; }
.info-key { color: var(--text-3); min-width: 28px; flex-shrink: 0; font-size: 11px; font-weight: 500; text-transform: uppercase; }
.info-val { color: var(--text-2); line-height: 1.4; }
.risk { font-weight: 600; }
.risk-low  { color: var(--success); }
.risk-mid  { color: var(--warning); }
.risk-high { color: var(--danger); }

.s-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.s-tag { font-size: 10px; padding: 2px 7px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 3px; color: var(--text-3); }

.s-actions { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; border-top: 1px solid var(--border); margin-top: auto; }
.mod-path { font-size: 10px; font-family: var(--font-mono); }
.action-btns { display: flex; gap: 6px; }
.btn-live { font-size: 12px; text-decoration: none; padding: 4px 10px; border-radius: var(--radius-sm); border: 1px solid rgba(34,197,94,0.3); color: var(--success); background: rgba(34,197,94,0.08); transition: background 0.12s; }
.btn-live:hover { background: rgba(34,197,94,0.15); }

/* Detail Drawer */
.drawer-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(2px);
  display: flex; align-items: stretch; justify-content: flex-end;
}
.drawer {
  width: 480px;
  max-width: 95vw;
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn {
  from { transform: translateX(60px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}

.drawer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(to bottom, color-mix(in srgb, var(--dc) 8%, var(--bg-base)), var(--bg-surface));
  border-top: 3px solid var(--dc);
}
.drawer-header-left { display: flex; align-items: center; gap: 14px; }
.drawer-id {
  font-size: 11px; font-weight: 700; letter-spacing: 0.06em;
  color: var(--dc); background: color-mix(in srgb, var(--dc) 15%, transparent);
  padding: 4px 8px; border-radius: 4px;
}
.drawer-title { font-size: 18px; font-weight: 700; color: var(--text-1); }
.drawer-class { font-size: 11px; margin-top: 2px; }
.drawer-close {
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-sm); width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  color: var(--text-3); cursor: pointer; transition: all 0.12s; flex-shrink: 0;
}
.drawer-close:hover { border-color: var(--danger); color: var(--danger); }

.drawer-body { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 20px; }

.drawer-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

.drawer-section {}
.drawer-section-title {
  font-size: 11px; font-weight: 600; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.06em;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.drawer-desc { font-size: 13px; color: var(--text-2); line-height: 1.7; }

.detail-grid { display: flex; flex-direction: column; gap: 8px; }
.detail-row { display: flex; gap: 12px; font-size: 13px; }
.detail-key { color: var(--text-3); min-width: 72px; flex-shrink: 0; font-size: 11px; font-weight: 500; text-transform: uppercase; padding-top: 1px; }
.detail-val { color: var(--text-1); line-height: 1.5; }

.params-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.params-table th { text-align: left; color: var(--text-3); font-weight: 500; font-size: 11px; text-transform: uppercase; padding: 6px 8px; border-bottom: 1px solid var(--border); }
.params-table td { padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: top; }
.params-table tr:last-child td { border-bottom: none; }
.param-token { font-family: var(--font-mono); background: var(--bg-base); border: 1px solid var(--border); border-radius: 3px; padding: 2px 6px; color: var(--accent); font-size: 11px; }
.param-desc { color: var(--text-2); }

.full-path { font-family: var(--font-mono); font-size: 11px; color: var(--text-2); background: var(--bg-base); padding: 8px 12px; border-radius: var(--radius-sm); border: 1px solid var(--border); display: block; word-break: break-all; }

.drawer-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border);
  display: flex; gap: 10px; justify-content: flex-end;
  background: var(--bg-base);
}
.drawer-footer .btn-primary { text-decoration: none; padding: 8px 16px; }
.drawer-footer .btn-ghost { text-decoration: none; padding: 8px 14px; }

/* ── Capability badges on card ─────────── */
.s-caps { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 6px; }
.cap-badge { padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.03em; }
.cap-yaml   { background: #ede9fe; color: #6d28d9; }
.cap-screen { background: #dbeafe; color: #1d4ed8; }
.cap-signal { background: #dcfce7; color: #15803d; }
.cap-bt     { background: #fef9c3; color: #92400e; }

/* ── Three-channel section in drawer ─────── */
.three-channels { display: flex; gap: 10px; }
.channel-card { flex: 1; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; display: flex; flex-direction: column; gap: 5px; }
.channel-card.active { border-color: var(--accent); }
.channel-card.inactive { opacity: 0.45; }
.ch-icon { font-size: 18px; }
.ch-label { font-size: 12px; font-weight: 700; color: var(--text-1); }
.ch-desc { font-size: 11px; color: var(--text-3); line-height: 1.4; flex: 1; }
.ch-link { font-size: 11px; color: var(--accent); text-decoration: none; font-weight: 600; }
.ch-link:hover { text-decoration: underline; }

/* ── YAML link chips ─────────────────────── */
.yaml-links { display: flex; gap: 6px; flex-wrap: wrap; }
.yaml-link-chip { background: var(--accent-dim); color: var(--accent); border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; text-decoration: none; }
.yaml-link-chip:hover { opacity: 0.8; }

@media (max-width: 768px) {
  .rec-grid { grid-template-columns: repeat(2, 1fr); }
  .strategy-grid { grid-template-columns: 1fr; }
  .drawer { width: 100%; max-width: 100%; position: fixed; inset: auto 0 0 0; height: 85vh; border-left: none; border-top: 1px solid var(--border); border-radius: var(--radius-xl) var(--radius-xl) 0 0; }
  .three-channels { flex-direction: column; }
}
@media (max-width: 480px) {
  .rec-grid { grid-template-columns: 1fr; }
}
</style>
