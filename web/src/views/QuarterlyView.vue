<template>
  <div class="quarterly-wrap">

    <!-- ── Header：一级板块「季报分析」+ 二级 Tab ─────────────────────── -->
    <div class="q-header">
      <div class="q-title-row">
        <div class="q-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          季报分析
        </div>
        <div class="q-tabs">
          <button
            v-for="t in TABS" :key="t.key"
            :class="['q-tab', { active: tab === t.key }]"
            :disabled="loading"
            @click="switchTab(t.key)"
          >{{ t.label }}</button>
        </div>
      </div>
      <button class="q-refresh" :disabled="busy" @click="refresh">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        {{ busy ? '生成中…' : '重新分析' }}
      </button>
    </div>

    <!-- Loading / Error -->
    <div v-if="loading" class="state-card">
      <div class="loading-ring"></div>
      <div class="state-text">正在拉取业绩榜单并分析，请稍候…</div>
      <div class="state-sub">首次生成约需 20-40 秒</div>
    </div>
    <div v-else-if="error" class="state-card error">
      <div class="state-text">{{ error }}</div>
      <button class="q-refresh" @click="load()">重试</button>
    </div>

    <!-- ════════════════ 净利润断层 ════════════════ -->
    <template v-if="!loading && !error && tab === 'jegap' && jegap">
      <div class="q-meta">
        <span class="meta-period">{{ jegap.funnel?.period_label }}</span>
        <span class="meta-sep">·</span>
        <span>生成于 {{ fmtTime(jegap.generated_at) }}</span>
        <span class="meta-sep">·</span>
        <span>{{ jegap.picks?.length || 0 }} 只断层标的</span>
      </div>

      <div class="q-explain jegap">
        <strong>净利润断层 · 业绩超预期 + 向上跳空</strong>
        股票池：<b>全市场</b>（已取消四大行业限制）。选股：当季度业绩（财报/预告）<b>净利润同比 &gt; 20%</b>
        （以增速近似「超分析师预期」），且业绩公告后<b>首个交易日高开 ≥ 3% 并收阳线</b>——
        跳空代表市场对业绩报告的认可程度与情绪。仅分析<b>本季度</b>已披露业绩/预告的标的，并标注<b>单季净利环比</b>。
        回踩缺口下沿不破再跟进，<b>跌破缺口下沿（缺口回补）即断层失效止损。</b>
      </div>

      <!-- 选股漏斗 -->
      <div v-if="jegap.funnel" class="funnel-card">
        <div class="funnel-head">
          <span class="funnel-title">选股漏斗</span>
          <span class="funnel-sub">净利润断层 · 从预增公告逐级筛到最终排序</span>
        </div>
        <div class="funnel-flow">
          <template v-for="(s, i) in jegapStages" :key="s.key">
            <div class="fn-stage" :class="{ 'fn-final': i === jegapStages.length - 1 }">
              <div class="fn-bar" :style="{ width: s.barPct + '%', background: s.color }"></div>
              <div class="fn-stage-body">
                <div class="fn-val">{{ s.value }}<span class="fn-unit">只</span></div>
                <div class="fn-lbl">{{ s.label }}</div>
                <div class="fn-desc">{{ s.desc }}</div>
              </div>
            </div>
            <div v-if="i < jegapStages.length - 1" class="fn-arrow">›</div>
          </template>
        </div>
      </div>

      <div class="q-summary">{{ jegap.market_summary }}</div>
      <div v-if="jegap.operation_strategy" class="q-op">操作思路：{{ jegap.operation_strategy }}</div>

      <div v-if="!jegap.picks?.length" class="empty-card">
        当前无新形成的净利润断层标的（可能当季披露窗已过较久或断层已回补缺口）。
      </div>

      <div v-else class="picks-grid">
        <div v-for="pick in jegap.picks" :key="pick.code" class="pick-card">
          <div class="card-head">
            <div class="card-rank">#{{ pick.rank }}</div>
            <span class="entry-badge" :class="'eb-' + (pick.entry_state || 'buy')">{{ pick.entry_label }}</span>
            <div class="card-stock">
              <div class="stock-name">{{ pick.name }}</div>
              <div class="stock-code">{{ pick.code }}</div>
            </div>
            <div class="card-tags">
              <span class="tag-sector" v-if="pick.sector">{{ pick.sector }}</span>
              <span :class="['tag-risk', 'risk-' + (pick.risk_level || '中')]">{{ pick.risk_level || '中' }}险</span>
            </div>
          </div>

          <div class="card-price" v-if="pick.price">
            <span class="price-val">¥{{ pick.price?.toFixed(2) }}</span>
            <span v-if="pick.change_pct != null" :class="['price-change', pick.change_pct >= 0 ? 'up' : 'down']">
              {{ pick.change_pct >= 0 ? '+' : '' }}{{ pick.change_pct?.toFixed(2) }}%
            </span>
            <span v-if="pick.pe" class="price-pe">PE {{ pick.pe?.toFixed(1) }}</span>
          </div>

          <!-- 断层信息条 -->
          <div class="gap-chips">
            <span class="g-chip g-growth">净利同比 {{ fmtPct(pick.momentum?.growth) }}</span>
            <span v-if="pick.momentum?.qoq != null || pick.momentum?.qoq_note" class="g-chip g-qoq">
              环比 {{ pick.momentum?.qoq != null ? fmtPct(pick.momentum.qoq) : pick.momentum?.qoq_note }}
            </span>
            <span class="g-chip g-gap">高开 {{ fmtPct(pick.momentum?.gap_open_pct) }}</span>
            <span class="g-chip g-date">{{ pick.momentum?.days_since === 0 ? '今日断层' : pick.momentum?.days_since + '日前断层' }}</span>
            <span v-if="pick.momentum?.ran_up" class="g-chip g-rise">断层后{{ fmtPct(pick.momentum?.rise_since) }}</span>
            <span class="g-chip g-src">{{ pick.momentum?.source }}</span>
          </div>

          <div class="card-reason">{{ pick.reason }}</div>

          <div class="card-levels" v-if="pick.buy_price || pick.stop_price || pick.target_price">
            <div class="lv-item lv-buy" v-if="pick.buy_price"><div class="lv-lbl">参考买入</div><div class="lv-val">{{ pick.buy_price }}</div></div>
            <div class="lv-item lv-stop" v-if="pick.stop_price"><div class="lv-lbl">止损(缺口下沿)</div><div class="lv-val">{{ pick.stop_price }}</div></div>
            <div class="lv-item lv-target" v-if="pick.target_price"><div class="lv-lbl">目标价</div><div class="lv-val">{{ pick.target_price }}</div></div>
          </div>

          <div class="card-checklist" v-if="pick.checklist?.length">
            <div class="cl-title">操作前置条件</div>
            <div v-for="item in pick.checklist" :key="item" class="cl-item">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              {{ item }}
            </div>
          </div>

          <div class="card-targets">
            <span class="t-up">目标 +{{ pick.target_pct }}%</span>
            <span class="t-down">止损 -{{ pick.stop_pct }}%</span>
            <span class="t-hold">{{ pick.holding_period }}</span>
          </div>

          <div class="card-conf">
            <div class="conf-row"><span>策略置信度</span><span>{{ pick.confidence }}%</span></div>
            <div class="conf-bar"><div class="conf-fill" :style="{ width: pick.confidence + '%', background: confColor(pick.confidence) }"></div></div>
          </div>

          <div class="card-actions">
            <router-link :to="'/stock/' + pick.code" class="act-btn" target="_blank" rel="noopener">K线</router-link>
            <router-link :to="'/backtest?symbols=' + pick.code" class="act-btn" target="_blank" rel="noopener">回测</router-link>
          </div>
        </div>
      </div>
    </template>

    <!-- ════════════════ 季报预增 ════════════════ -->
    <template v-if="!loading && !error && tab === 'preincrease' && preinc">
      <div class="q-meta">
        <span class="meta-period">{{ preinc.period_label }}</span>
        <span class="meta-sep" v-if="preinc.generated_at">·</span>
        <span v-if="preinc.generated_at">生成于 {{ fmtTime(preinc.generated_at) }}</span>
        <span class="meta-sep">·</span>
        <span>{{ preinc.count || 0 }} 只预增推荐</span>
      </div>

      <div class="q-explain preinc">
        <strong>季报预增 · 多源线索 + AI 预测当季业绩</strong>
        从<b>机构荐股 / 研报 / 公众号 / 韭研公社</b>等渠道搜索「预增 / 超预期 / 扭亏」等线索，
        结合东方财富<b>官方业绩预告</b>，对<b>本季度（{{ preinc.period_label || '当季' }}）</b>逐个<b>预测</b>每个标的的
        <b>预增幅度（同比）、环比趋势与理由</b>后给出推荐——仅预测有预增/扭亏线索的标的，全部列出不删减。
        预增幅度优先采用官方预告的净利同比数字，无官方预告者标注为卖方/媒体预估。
      </div>

      <!-- 线索源统计 -->
      <div v-if="preinc.by_source && Object.keys(preinc.by_source).length" class="src-bar">
        <span class="src-bar-lbl">线索源：</span>
        <span v-for="(n, src) in preinc.by_source" :key="src" class="src-chip">{{ src }} {{ n }}</span>
        <span class="src-chip total" v-if="preinc.signal_count">共 {{ preinc.signal_count }} 条 · 官方预告 {{ preinc.forecast_count || 0 }} 只</span>
      </div>

      <!-- 生成中 -->
      <div v-if="preinc.pending" class="state-card">
        <div class="loading-ring"></div>
        <div class="state-text">{{ preinc.summary }}</div>
        <div class="state-sub">AI 正在逐个分析预增幅度与理由</div>
      </div>

      <template v-else>
        <div class="q-summary">{{ preinc.summary }}</div>

        <div v-if="!preinc.picks?.length" class="empty-card">
          近期暂未从机构荐股/研报/公众号/韭研公社捕捉到明显的业绩预增线索。
        </div>

        <div v-else class="picks-grid">
          <div v-for="pick in preinc.picks" :key="pick.code || pick.name" class="pick-card">
            <div class="card-head">
              <div class="card-rank">#{{ pick.rank }}</div>
              <span class="entry-badge" :class="confBadge(pick.confidence)">{{ pick.confidence || '中' }}信心</span>
              <div class="card-stock">
                <div class="stock-name">{{ pick.name }}</div>
                <div class="stock-code">{{ pick.code || '—' }}</div>
              </div>
              <span class="src-tag" :class="pick.increase_source === '官方预告' ? 'src-rp' : 'src-fc'">
                {{ pick.increase_source || '观点' }}
              </span>
            </div>

            <div class="card-price" v-if="pick.price">
              <span class="price-val">¥{{ pick.price?.toFixed(2) }}</span>
              <span v-if="pick.change_pct != null" :class="['price-change', pick.change_pct >= 0 ? 'up' : 'down']">
                {{ pick.change_pct >= 0 ? '+' : '' }}{{ pick.change_pct?.toFixed(2) }}%
              </span>
            </div>

            <div class="gap-chips">
              <span class="g-chip g-growth">预增 {{ pick.increase || '—' }}</span>
              <span v-if="pick.qoq" class="g-chip g-qoq">环比 {{ pick.qoq }}</span>
              <span v-if="pick.notice_date" class="g-chip g-date">{{ pick.notice_date }} 预告</span>
              <span v-if="pick.catalyst" class="g-chip g-src">{{ pick.catalyst }}</span>
            </div>

            <div class="card-reason">{{ pick.reason }}</div>

            <div v-if="pick.evidence?.length" class="evidence-box">
              <div class="ev-title">线索依据</div>
              <div v-for="(e, i) in pick.evidence" :key="i" class="ev-item">· {{ e }}</div>
            </div>

            <div class="card-actions" v-if="pick.code">
              <router-link :to="'/stock/' + pick.code" class="act-btn" target="_blank" rel="noopener">个股详情</router-link>
              <router-link :to="'/backtest?symbols=' + pick.code" class="act-btn" target="_blank" rel="noopener">回测</router-link>
            </div>
          </div>
        </div>

        <!-- 官方业绩预告增幅榜（参考） -->
        <div v-if="preinc.forecast_top?.length" class="forecast-ref">
          <button class="ref-toggle" @click="showForecast = !showForecast">
            {{ showForecast ? '收起' : '展开' }}官方业绩预告增幅榜（{{ preinc.forecast_count }} 只）
          </button>
          <div v-if="showForecast" class="table-scroll">
            <table class="preinc-table">
              <thead>
                <tr><th>#</th><th>名称</th><th>代码</th><th class="num">净利同比</th><th>类型</th><th>公告日</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in preinc.forecast_top" :key="r.code">
                  <td class="dim">{{ i + 1 }}</td>
                  <td class="t-name">{{ r.name }}</td>
                  <td class="t-code">{{ r.code }}</td>
                  <td class="num strong up">{{ fmtPct(r.growth) }}</td>
                  <td class="dim">{{ r.predict_type || '—' }}</td>
                  <td class="dim">{{ r.notice_date }}</td>
                  <td><router-link :to="'/stock/' + r.code" class="t-link" target="_blank" rel="noopener">详情</router-link></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>

    <!-- ════════════════ 每日线索日志 ════════════════ -->
    <div v-if="!loading && !error && currentClue.length" class="clue-log">
      <button class="ref-toggle" @click="showClue = !showClue">
        {{ showClue ? '收起' : '展开' }}每日线索日志 · 每天新增推荐（近 {{ currentClue.length }} 天）
      </button>
      <div v-if="showClue" class="clue-body">
        <div v-for="e in currentClue" :key="e.date" class="clue-day">
          <div class="clue-date">{{ e.date }} <span class="clue-cnt">新增 {{ e.count }} 只</span></div>
          <div class="clue-items">
            <router-link
              v-for="it in e.new" :key="it.code"
              :to="'/stock/' + it.code" class="clue-chip" target="_blank" rel="noopener"
            >
              <b>{{ it.name }}</b>
              <span class="clue-code">{{ it.code }}</span>
              <span class="clue-brief">{{ it.brief }}</span>
            </router-link>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!loading && !error" class="disclaimer">
      ⚠️ 以上为基于多源公开线索 + 东方财富业绩预告的 AI 归纳结果（非投资建议）。预增幅度以官方预告为准，
      卖方/媒体预估存在不确定性；净利润断层「净利同比 &gt; 20%」为「超分析师预期」的近似替代，
      断层判定依赖本地日 K 缓存。请结合业绩可持续性自行判断。
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

const TABS = [
  { key: 'jegap', label: '净利润断层' },
  { key: 'preincrease', label: '季报预增' },
]
const tab = ref('jegap')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const jegap = ref(null)
const preinc = ref(null)
const showForecast = ref(false)
const showClue = ref(false)
const clueLog = ref({ jegap: [], preincrease: [] })
let preincTimer = null

const currentClue = computed(() => clueLog.value?.[tab.value] || [])

async function loadClueLog() {
  try {
    const res = await axios.get('/api/quarterly/clue-log', { params: { days: 30 } })
    clueLog.value = res.data || { jegap: [], preincrease: [] }
  } catch { /* 静默 */ }
}

// 漏斗（净利润断层）
const jegapStages = computed(() => {
  const f = jegap.value?.funnel
  if (!f) return []
  const raw = [
    { key: 'a', label: '预增公告', value: f.market_total, color: '#64748b', desc: '财报+预告抓取条数' },
    { key: 'b', label: '全市场预增', value: f.after_filter, color: '#0891b2', desc: '全市场·净利同比>20%·去重' },
    { key: 'c', label: '可判定', value: f.scored, color: '#2563eb', desc: '有日 K 缓存可算断层' },
    { key: 'd', label: '形成断层', value: f.buy_points, color: '#7c3aed', desc: '公告后首日高开≥3%且收阳' },
    { key: 'e', label: '近窗断层', value: f.selected, color: '#d97706', desc: '断层日落在近窗口内' },
    { key: 'f', label: '入选排序', value: f.recommended ?? (jegap.value?.picks?.length || 0), color: '#dc2626', desc: `可参与 ${f.actionable ?? '—'} 只 + 已兑现/回补(观察)` },
  ]
  const max = Math.max(...raw.map(s => s.value || 0), 1)
  return raw.map(s => ({ ...s, barPct: Math.max(6, Math.round(Math.log10((s.value || 0) + 1) / Math.log10(max + 1) * 100)) }))
})

function fmtPct(v) {
  if (v == null) return '—'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%'
}
function fmtTime(t) {
  if (!t) return ''
  try { return new Date(t).toLocaleString('zh-CN', { hour12: false }).slice(5) } catch { return t }
}
function confColor(c) {
  if (c >= 80) return '#16a34a'
  if (c >= 65) return '#65a30d'
  if (c >= 50) return '#d97706'
  return '#dc2626'
}
function confBadge(c) {
  return { '高': 'eb-buy', '中': 'eb-hold', '低': 'eb-sell' }[c] || 'eb-hold'
}

async function load() {
  loading.value = true; error.value = ''
  try {
    if (tab.value === 'jegap') {
      const res = await axios.get('/api/quarterly/jegap')
      jegap.value = res.data
    } else {
      const res = await axios.get('/api/quarterly/preincrease')
      preinc.value = res.data
      // 季报预增首次为 AI 后台生成，pending 时轮询拉取结果
      if (preinc.value?.pending) schedulePreincPoll()
    }
  } catch (e) {
    error.value = e.response?.data?.detail || '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function schedulePreincPoll() {
  if (preincTimer) clearTimeout(preincTimer)
  preincTimer = setTimeout(async () => {
    try {
      const res = await axios.get('/api/quarterly/preincrease')
      preinc.value = res.data
      if (preinc.value?.pending) schedulePreincPoll()
    } catch { /* 静默重试下一轮 */ schedulePreincPoll() }
  }, 15000)
}

async function switchTab(key) {
  if (key === tab.value || loading.value) return
  tab.value = key
  if ((key === 'jegap' && !jegap.value) || (key === 'preincrease' && !preinc.value)) {
    await load()
  }
}

async function refresh() {
  if (busy.value) return
  busy.value = true
  try {
    const ep = tab.value === 'jegap' ? '/api/quarterly/jegap/refresh' : '/api/quarterly/preincrease/refresh'
    await axios.post(ep, null, { params: { force: true } })
    // 后台生成，轮询拉取最新
    setTimeout(async () => { await load(); busy.value = false }, 30000)
  } catch (e) {
    error.value = e.response?.data?.detail || '触发失败'
    busy.value = false
  }
}

onMounted(() => { load(); loadClueLog() })
onUnmounted(() => { if (preincTimer) clearTimeout(preincTimer) })
</script>

<style scoped>
.quarterly-wrap { max-width: 1180px; margin: 0 auto; padding: 18px 20px 60px; }

/* Header */
.q-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.q-title-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.q-badge { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: 15px; color: var(--text-1); }
.q-badge svg { color: #0891b2; }
.q-tabs { display: flex; gap: 6px; background: var(--bg-2, #f1f5f9); padding: 3px; border-radius: 10px; }
.q-tab { border: none; background: transparent; padding: 7px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; color: var(--text-2); cursor: pointer; transition: all .15s; }
.q-tab.active { background: var(--bg-card, #fff); color: #0891b2; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.q-tab:disabled { opacity: .5; cursor: not-allowed; }
.q-refresh { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--border, #e2e8f0); background: var(--bg-card, #fff); color: var(--text-2); padding: 7px 14px; border-radius: 8px; font-size: 12.5px; cursor: pointer; }
.q-refresh:disabled { opacity: .5; cursor: not-allowed; }

/* State */
.state-card { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 60px 20px; color: var(--text-2); }
.state-card.error { color: #dc2626; }
.loading-ring { width: 32px; height: 32px; border: 3px solid var(--border, #e2e8f0); border-top-color: #0891b2; border-radius: 50%; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.state-sub { font-size: 12px; opacity: .7; }

/* Meta + explain */
.q-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: var(--text-2); margin-bottom: 12px; }
.meta-period { font-weight: 700; color: #0891b2; }
.meta-sep { opacity: .4; }
.q-explain { border-radius: var(--radius-lg, 12px); padding: 12px 16px; font-size: 12.5px; line-height: 1.7; color: var(--text-2); margin-bottom: 14px; }
.q-explain strong { margin-right: 6px; }
.q-explain b { color: var(--text-1); }
.q-explain.jegap { background: rgba(8,145,178,0.06); border: 1px solid rgba(8,145,178,0.25); }
.q-explain.jegap strong { color: #0891b2; }
.q-explain.preinc { background: rgba(22,163,74,0.06); border: 1px solid rgba(22,163,74,0.25); }
.q-explain.preinc strong { color: #16a34a; }
.q-summary { font-size: 13px; line-height: 1.7; color: var(--text-1); margin-bottom: 6px; }
.q-op { font-size: 12.5px; line-height: 1.7; color: var(--text-2); margin-bottom: 14px; }

/* Funnel */
.funnel-card { background: var(--bg-card, #fff); border: 1px solid var(--border, #e2e8f0); border-radius: var(--radius-lg, 12px); padding: 14px 16px; margin-bottom: 14px; }
.funnel-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.funnel-title { font-weight: 700; font-size: 13px; color: var(--text-1); }
.funnel-sub { font-size: 11.5px; color: var(--text-2); }
.funnel-flow { display: flex; align-items: stretch; gap: 4px; overflow-x: auto; padding-bottom: 4px; }
.fn-stage { position: relative; flex: 1; min-width: 96px; background: var(--bg-2, #f8fafc); border-radius: 8px; padding: 10px 10px 12px; overflow: hidden; }
.fn-bar { position: absolute; left: 0; bottom: 0; height: 3px; border-radius: 2px; }
.fn-val { font-size: 18px; font-weight: 800; color: var(--text-1); line-height: 1; }
.fn-unit { font-size: 11px; font-weight: 500; color: var(--text-2); margin-left: 2px; }
.fn-lbl { font-size: 12px; font-weight: 600; color: var(--text-1); margin-top: 4px; }
.fn-desc { font-size: 10.5px; color: var(--text-2); margin-top: 3px; line-height: 1.4; }
.fn-arrow { display: flex; align-items: center; color: var(--text-3, #94a3b8); font-size: 20px; }

/* Cards */
.picks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; }
.pick-card { background: var(--bg-card, #fff); border: 1px solid var(--border, #e2e8f0); border-radius: var(--radius-lg, 12px); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.card-head { display: flex; align-items: center; gap: 8px; }
.card-rank { font-weight: 800; color: #0891b2; font-size: 14px; }
.entry-badge { font-size: 10.5px; padding: 1px 7px; border-radius: 5px; font-weight: 600; }
.eb-buy { background: rgba(22,163,74,.15); color: #16a34a; }
.eb-hold { background: rgba(245,158,11,.15); color: #b45309; }
.eb-sell { background: rgba(220,38,38,.12); color: #dc2626; }
.g-rise { background: rgba(217,119,6,.1); color: #d97706; }
.card-stock { flex: 1; }
.stock-name { font-weight: 700; font-size: 14px; color: var(--text-1); }
.stock-code { font-size: 11px; color: var(--text-2); }
.card-tags { display: flex; gap: 5px; }
.tag-sector { font-size: 11px; background: rgba(8,145,178,.12); color: #0e7490; padding: 2px 7px; border-radius: 5px; }
.tag-sector.sm { font-size: 10.5px; padding: 1px 5px; }
.tag-risk { font-size: 11px; padding: 2px 7px; border-radius: 5px; }
.risk-低 { background: rgba(22,163,74,.12); color: #16a34a; }
.risk-中 { background: rgba(217,119,6,.12); color: #d97706; }
.risk-高 { background: rgba(220,38,38,.12); color: #dc2626; }
.card-price { display: flex; align-items: baseline; gap: 8px; }
.price-val { font-size: 18px; font-weight: 800; color: var(--text-1); }
.price-change.up { color: #dc2626; } .price-change.down { color: #16a34a; }
.price-pe { font-size: 11px; color: var(--text-2); margin-left: auto; }
.gap-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.g-chip { font-size: 11px; padding: 2px 8px; border-radius: 6px; font-weight: 600; }
.g-growth { background: rgba(220,38,38,.1); color: #dc2626; }
.g-qoq { background: rgba(124,58,237,.1); color: #7c3aed; }
.g-gap { background: rgba(234,88,12,.1); color: #ea580c; }
.g-date { background: rgba(8,145,178,.1); color: #0891b2; }
.g-src { background: var(--bg-2, #f1f5f9); color: var(--text-2); }
.card-reason { font-size: 12.5px; line-height: 1.65; color: var(--text-2); }
.card-levels { display: flex; gap: 8px; }
.lv-item { flex: 1; text-align: center; background: var(--bg-2, #f8fafc); border-radius: 8px; padding: 7px 4px; }
.lv-lbl { font-size: 10px; color: var(--text-2); }
.lv-val { font-size: 14px; font-weight: 700; margin-top: 2px; }
.lv-buy .lv-val { color: #dc2626; } .lv-stop .lv-val { color: #16a34a; } .lv-target .lv-val { color: #0891b2; }
.card-checklist { background: var(--bg-2, #f8fafc); border-radius: 8px; padding: 9px 11px; }
.cl-title { font-size: 11px; font-weight: 700; color: var(--text-1); margin-bottom: 5px; }
.cl-item { display: flex; align-items: flex-start; gap: 5px; font-size: 11.5px; line-height: 1.55; color: var(--text-2); margin-top: 3px; }
.cl-item svg { color: #16a34a; flex-shrink: 0; margin-top: 3px; }
.card-targets { display: flex; gap: 10px; font-size: 11.5px; font-weight: 600; }
.t-up { color: #dc2626; } .t-down { color: #16a34a; } .t-hold { color: var(--text-2); margin-left: auto; }
.card-conf .conf-row { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-2); margin-bottom: 4px; }
.conf-bar { height: 5px; background: var(--bg-2, #e2e8f0); border-radius: 3px; overflow: hidden; }
.conf-fill { height: 100%; border-radius: 3px; }
.card-actions { display: flex; gap: 8px; }
.act-btn { flex: 1; text-align: center; font-size: 12px; padding: 7px; border-radius: 8px; background: var(--bg-2, #f1f5f9); color: var(--text-1); text-decoration: none; }
.act-btn:hover { background: rgba(8,145,178,.12); color: #0891b2; }

/* 季报预增：线索源条 + 证据 + 官方预告参考 */
.src-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 12px; font-size: 12px; }
.src-bar-lbl { color: var(--text-2); }
.src-chip { background: var(--bg-2, #f1f5f9); color: var(--text-2); padding: 3px 9px; border-radius: 20px; }
.src-chip.total { background: rgba(22,163,74,.1); color: #16a34a; }
.evidence-box { background: var(--bg-2, #f8fafc); border-radius: 8px; padding: 8px 11px; }
.ev-title { font-size: 11px; font-weight: 700; color: var(--text-1); margin-bottom: 4px; }
.ev-item { font-size: 11.5px; line-height: 1.55; color: var(--text-2); }
.forecast-ref { margin-top: 18px; }
.ref-toggle { border: 1px solid var(--border, #e2e8f0); background: var(--bg-card, #fff); color: var(--text-2); padding: 7px 14px; border-radius: 8px; font-size: 12.5px; cursor: pointer; margin-bottom: 10px; }
.ref-toggle:hover { color: #0891b2; border-color: #0891b2; }
.table-scroll { overflow-x: auto; border: 1px solid var(--border, #e2e8f0); border-radius: var(--radius-lg, 12px); }
.preinc-table { width: 100%; border-collapse: collapse; font-size: 12.5px; min-width: 760px; }
.preinc-table th, .preinc-table td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border, #f1f5f9); white-space: nowrap; }
.preinc-table th { background: var(--bg-2, #f8fafc); font-weight: 600; color: var(--text-2); font-size: 11.5px; position: sticky; top: 0; }
.preinc-table th.num, .preinc-table td.num { text-align: right; }
.preinc-table tbody tr:hover { background: rgba(8,145,178,.04); }
.t-name { font-weight: 600; color: var(--text-1); }
.t-code { font-size: 10.5px; color: var(--text-2); }
.t-ind { font-size: 11px; color: var(--text-2); }
.num.strong { font-weight: 700; }
.up { color: #dc2626; } .down { color: #16a34a; } .dim { color: var(--text-2); }
.src-tag { font-size: 10.5px; padding: 1px 6px; border-radius: 5px; }
.src-fc { background: rgba(124,58,237,.12); color: #7c3aed; }
.src-rp { background: rgba(8,145,178,.12); color: #0891b2; }
.t-link { color: #0891b2; text-decoration: none; font-size: 12px; }

/* 每日线索日志 */
.clue-log { margin-top: 18px; }
.clue-body { border: 1px solid var(--border, #e2e8f0); border-radius: var(--radius-lg, 12px); padding: 10px 14px; }
.clue-day { padding: 10px 0; border-bottom: 1px dashed var(--border, #eef2f7); }
.clue-day:last-child { border-bottom: none; }
.clue-date { font-size: 12.5px; font-weight: 700; color: var(--text-1); margin-bottom: 7px; }
.clue-cnt { font-size: 11px; font-weight: 600; color: #16a34a; background: rgba(22,163,74,.1); padding: 1px 7px; border-radius: 10px; margin-left: 6px; }
.clue-items { display: flex; flex-wrap: wrap; gap: 7px; }
.clue-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--bg-2, #f8fafc); border: 1px solid var(--border, #e2e8f0); border-radius: 8px; padding: 5px 9px; text-decoration: none; font-size: 12px; }
.clue-chip:hover { border-color: #0891b2; }
.clue-chip b { color: var(--text-1); font-weight: 700; }
.clue-code { font-size: 10.5px; color: var(--text-2); }
.clue-brief { font-size: 11px; color: #0891b2; }

.empty-card { padding: 40px 20px; text-align: center; color: var(--text-2); background: var(--bg-2, #f8fafc); border-radius: var(--radius-lg, 12px); }
.disclaimer { margin-top: 18px; font-size: 11.5px; line-height: 1.6; color: var(--text-3, #94a3b8); }

/* 移动端适配 */
@media (max-width: 640px) {
  .quarterly-wrap { padding: 14px 12px 50px; }
  .q-header { flex-direction: column; align-items: stretch; }
  .q-title-row { justify-content: space-between; }
  .q-tabs { flex: 1; }
  .q-tab { flex: 1; text-align: center; padding: 8px 10px; }
  .picks-grid { grid-template-columns: 1fr; }
  .funnel-flow { gap: 2px; }
  .fn-stage { min-width: 84px; }
}
</style>
