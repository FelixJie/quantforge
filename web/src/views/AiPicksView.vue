<template>
  <div class="ai-picks-wrap">

    <!-- ── Header ─────────────────────────────────────────────── -->
    <div class="picks-header">
      <div class="header-left">
        <div class="ai-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          AI 每日精选
        </div>
        <div class="strategy-tabs">
          <button
            v-for="s in STRATEGIES" :key="s.key"
            :class="['strat-tab', { active: strategy === s.key }]"
            :disabled="loading"
            :title="s.desc"
            @click="switchStrategy(s.key)"
          >{{ s.label }}</button>
        </div>
      </div>
      <div class="header-right">
        <button class="btn-history" :class="{ active: showHistory }" @click="showHistory = !showHistory">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          历史记录
        </button>
      </div>
    </div>

    <!-- History panel -->
    <div v-if="showHistory" class="history-panel">
      <div class="history-title">历史推荐记录</div>
      <div v-if="!history.length" class="history-empty">暂无历史记录</div>
      <div v-else class="history-list">
        <div
          v-for="h in history" :key="h.key || h.date"
          class="history-item"
          :class="{ active: (h.key || h.date) === activeKey }"
          @click="loadDate(h.key || h.date)"
        >
          <span class="h-date">{{ formatDate(h.date) }}</span>
          <span v-if="h.slot_label" class="h-slot">{{ h.slot_label }}</span>
          <span v-if="h.strategy_label" class="h-strat">{{ h.strategy_label }}</span>
          <span class="h-count">{{ h.pick_count }} 只</span>
          <span v-if="h.no_buy_point" class="h-noteg">无买点</span>
          <span class="h-summary">{{ h.market_summary?.slice(0, 28) }}...</span>
        </div>
      </div>
    </div>

    <!-- Loading / Error -->
    <div v-if="loading" class="state-card">
      <div class="loading-ring"></div>
      <div class="state-text">AI 正在深度分析候选股票，请稍候...</div>
      <div class="state-sub">首次生成约需 30-60 秒</div>
    </div>
    <div v-else-if="error" class="state-card error">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      <div class="state-text">{{ error }}</div>
      <button class="btn-refresh" @click="load()">重试</button>
    </div>

    <template v-if="!loading && !error && data">
      <div class="header-meta">
        <span class="meta-date">{{ formatDate(data.date) }}</span>
        <span v-if="data.slot_label" class="meta-slot">{{ data.slot_label }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-time">生成于 {{ formatTime(data.generated_at) }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-count">
          从 {{ data.candidate_count }} 只候选中筛出
          {{ data.picks?.length || 0 }} 只{{ data.no_buy_point ? '观察标的' : '买点' }}
        </span>
        <span v-if="isUltra" class="meta-cap">创业板/科创板 · 量能突破 · 盘前竞价滚动更新</span>
        <span v-else-if="isProbe" class="meta-cap">近一个月 · 放量长上影+突破前期高点 · 非ST/非北交所/股价&lt;80</span>
        <span v-else class="meta-cap">已剔除保险/银行/证券板块 · 买点全展示不设上限</span>
      </div>

      <!-- 试盘线说明横幅 -->
      <div v-if="isProbe" class="probe-banner">
        <span class="probe-dot"></span>
        <div>
          <strong>试盘点 · 主力战前侦察</strong>
          「试盘」= 大资金拉升前用小资金突放天量、拉出长上影、低位突破前期高点，借机测试上方抛压与跟风盘。
          条件：非ST/非北交所 · 股价&lt;80 · 当日涨幅0-9.8%且未涨停 · 当日量≥昨日2.5倍 · 长上影 · 突破前期高点；
          <b>已排除大盘跳水日的假试盘、剔除试盘至今已涨过多(入场已过)的标的。</b>
          <b>每张卡片标注「入场点是否已到」——从次日起有效站上试盘线高点=线上看多，跌破=线下看空，务必带好止损！</b>
        </div>
      </div>

      <!-- 超短量价：盘前实时滚动说明 -->
      <div v-if="isUltra" class="ultra-banner">
        <span class="ultra-dot" :class="{ live: ultraLive }"></span>
        <div>
          <strong>超短量价 · 盘前竞价选股</strong>
          条件：创业板/科创板 · 5日均量首次上穿60日均量 · 今日涨幅≥3% · 近10日涨幅≤20%。
          <b>{{ ultraLive ? '当前在竞价窗口(9:20-9:25)内，每30秒自动刷新。' : '盘前9:20-9:25滚动更新；当前展示最近一次扫描结果。' }}</b>
          超短为高风险打法，务必严格止损、当日或次日了结。
        </div>
      </div>

      <!-- ── 选股漏斗：从大盘一步步漏到最终排序 ─────────────────────── -->
      <div v-if="funnelStages.length" class="funnel-card">
        <div class="funnel-head">
          <span class="funnel-title">选股漏斗</span>
          <span class="funnel-sub">{{ isPring ? '普林格 KST 周期' : isUltra ? '超短量价' : isProbe ? '试盘线' : '动能买点' }}策略 · {{ isUltra ? '从创业板/科创板逐级筛到最终排序' : '从全市场逐级筛到最终排序' }}</span>
        </div>
        <div class="funnel-flow">
          <template v-for="(s, i) in funnelStages" :key="s.key">
            <div class="fn-stage" :class="{ 'fn-final': i === funnelStages.length - 1 }">
              <div class="fn-bar" :style="{ width: s.barPct + '%', background: s.color }"></div>
              <div class="fn-stage-body">
                <div class="fn-val">{{ s.value }}<span class="fn-unit">只</span></div>
                <div class="fn-lbl">{{ s.label }}</div>
                <div class="fn-desc">{{ s.desc }}</div>
              </div>
              <div v-if="s.drop != null" class="fn-drop">剔除 {{ s.drop }}</div>
            </div>
            <div v-if="i < funnelStages.length - 1" class="fn-arrow">›</div>
          </template>
        </div>
      </div>

      <!-- 今日无明确买点提示 -->
      <div v-if="data.no_buy_point" class="no-buy-banner">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        <div v-if="isUltra">
          <strong>当前暂无符合条件的超短标的</strong> —— 创业板/科创板中暂无同时满足
          「5日均量首次上穿60日均量 + 今日涨幅≥3% + 近10日涨幅≤20%」的个股，建议空仓等待或继续观望。
        </div>
        <div v-else-if="isProbe">
          <strong>近一个月暂无试盘线标的</strong> —— 全市场暂无满足「放量长上影 + 低位突破前期高点」的试盘线个股，
          主力暂未出手，建议耐心等待。
        </div>
        <div v-else>
          <strong>今日无首次买点</strong> —— 全市场扫描后未发现今日首次触发动能买点的标的。
          以下为当前<b>动能较强的观察标的</b>，并非可立即进场的买点，建议以观察为主、轻仓试探，待回踩或突破确认后再考虑。
        </div>
      </div>

      <!-- Market summary -->
      <div class="market-summary">
        <div class="summary-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        </div>
        <div class="summary-text">{{ data.market_summary }}</div>
      </div>

      <div class="op-strategy" v-if="data.operation_strategy">
        <span class="op-label">操作策略</span>
        <span class="op-text">{{ data.operation_strategy }}</span>
      </div>

      <!-- 该策略「今日胜率」多周期：实时(今日开盘价→现价) / 持有 3·7·30 日 -->
      <div class="winrate-strip" v-if="winHorizons.length">
        <span class="wr-title">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 5-6"/></svg>
          {{ stratLabel }}·胜率
        </span>
        <div class="wr-cells">
          <div v-for="h in winHorizons" :key="h.key" class="wr-cell" :title="winTip(h)">
            <div class="wr-h">{{ h.label }}</div>
            <div class="wr-rate" :style="{ color: wrColor(h.win_rate) }">{{ h.win_rate != null ? h.win_rate + '%' : '—' }}</div>
            <div class="wr-avg" :class="h.avg_change == null ? '' : (h.avg_change >= 0 ? 'up' : 'down')">{{ h.avg_change != null ? (h.avg_change >= 0 ? '+' : '') + h.avg_change + '%' : '—' }}</div>
            <div class="wr-n">{{ h.evaluated || 0 }} 只</div>
          </div>
        </div>
        <span class="wr-hint">{{ winLoading ? '加载中…' : '实时=今日开盘价买入截至现价；3/7/30日=历史推荐持有N日聚合' }}</span>
      </div>

      <!-- 分板块筛选：行业 / 概念 维度切换 -->
      <div v-if="sectorOptions.length > 1 || hasConcepts" class="sector-filter">
        <span class="sf-label">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
          筛选
        </span>
        <div class="sf-dim">
          <button :class="['sf-dim-btn', { active: filterDim === 'industry' }]" @click="setDim('industry')">申万行业</button>
          <button :class="['sf-dim-btn', { active: filterDim === 'concept' }]" @click="setDim('concept')" :disabled="!hasConcepts">概念</button>
        </div>
        <div class="sf-chips">
          <button :class="['sf-chip', { active: !selectedSectors.length }]" @click="clearSectors">
            全部{{ filterDim === 'concept' ? '概念' : '行业' }}（{{ allPicks.length }}）
          </button>
          <button v-for="s in sectorOptions" :key="s.name"
                  :class="['sf-chip', { active: isSelected(s.name) }]"
                  @click="toggleSector(s.name)">
            {{ s.name }}（{{ s.count }}）
          </button>
        </div>
        <span class="sf-count">
          {{ selectedSectors.length
            ? `已选 ${selectedSectors.length} 个`
            : `${sectorOptions.length} 个${filterDim === 'concept' ? '概念' : '行业'}` }}
        </span>
      </div>

      <!-- Picks grid -->
      <div class="picks-grid">
        <div
          v-for="pick in pagedPicks" :key="pick.code"
          class="pick-card"
          :class="['risk-' + (pick.risk_level || '中'), { 'is-observe': pick.no_buy_point }]"
        >
          <div class="card-head">
            <div class="card-rank">#{{ pick.rank }}</div>
            <span v-if="pick.no_buy_point" class="observe-badge">观察</span>
            <div class="card-stock">
              <div class="stock-name">{{ pick.name }}</div>
              <div class="stock-code">{{ pick.code }}</div>
            </div>
            <div class="card-tags">
              <span class="tag-sector" v-if="pick.sector">{{ pick.sector }}</span>
              <span :class="['tag-risk', 'risk-' + (pick.risk_level || '中')]">{{ pick.risk_level || '中' }}险</span>
            </div>
          </div>

          <!-- 试盘点：入场点是否已到（醒目标注） -->
          <div v-if="isProbe && pick.entry_state" class="probe-entry" :class="'pe-' + pick.entry_state">
            <span class="pe-badge">
              <svg v-if="pick.entry_ready" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
              <svg v-else-if="pick.entry_state === 'failed'" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/></svg>
              {{ pick.entry_label }}
            </span>
            <span class="pe-note">{{ pick.entry_note }}</span>
          </div>

          <div class="card-price" v-if="pick.price || pick.change_pct !== undefined">
            <span class="price-val" v-if="pick.price">¥{{ pick.price?.toFixed(2) }}</span>
            <span v-if="pick.change_pct !== undefined && pick.change_pct !== null" :class="['price-change', pick.change_pct >= 0 ? 'up' : 'down']">
              {{ pick.change_pct >= 0 ? '+' : '' }}{{ pick.change_pct?.toFixed(2) }}%
            </span>
            <div class="price-meta">
              <span v-if="pick.pe">PE {{ pick.pe?.toFixed(1) }}</span>
              <span v-if="pick.pb">PB {{ pick.pb?.toFixed(2) }}</span>
            </div>
          </div>

          <div class="card-reason">{{ pick.reason }}</div>

          <div class="card-signals" v-if="pick.signals?.length">
            <span v-for="sig in pick.signals" :key="sig" class="signal-tag">{{ sig }}</span>
          </div>

          <div class="card-momentum" v-if="pick.momentum">
            <span class="momo-chip momo-score">{{ isPring ? '综合' : isUltra ? '量价' : isProbe ? '试盘' : '动能' }} {{ pick.momentum.score }}</span>
            <span class="momo-chip" :class="'momo-state-' + (pick.momentum.state || 'hold')">
              {{ isProbe ? (pick.momentum.status_label || stateLabel(pick.momentum.state)) : stateLabel(pick.momentum.state) }}
            </span>
            <!-- 试盘专属：试盘日 + 量比 + 健康度 -->
            <template v-if="isProbe">
              <span class="momo-chip momo-stage" v-if="pick.momentum.days_since != null">{{ pick.momentum.days_since === 0 ? '今日试盘' : pick.momentum.days_since + '日前试盘' }}</span>
              <span class="momo-chip momo-dir" v-if="pick.momentum.vol_ratio">放量 {{ pick.momentum.vol_ratio }}x</span>
              <span class="momo-chip momo-cross" v-if="pick.momentum.pullback_ok">缩量回踩</span>
              <span class="momo-chip momo-fail" v-if="pick.momentum.giveup">主力放弃</span>
            </template>
            <!-- 普林格专属：所处阶段 + KST金叉 -->
            <template v-if="isPring">
              <span class="momo-chip momo-stage" v-if="pick.momentum.stage_label">{{ pick.momentum.stage_label }}</span>
              <span class="momo-chip momo-cross" v-if="pick.momentum.golden_cross">KST金叉</span>
              <span class="momo-chip momo-dir" v-if="pick.momentum.kst != null">KST {{ pick.momentum.kst }}</span>
            </template>
            <span class="momo-chip momo-dir" v-else-if="pick.momentum.direction">{{ dirLabel(pick.momentum.direction) }}</span>
            <span class="momo-chip momo-rr" v-if="pick.momentum.rr">盈亏比 {{ pick.momentum.rr }}</span>
          </div>

          <!-- 四维动能（仅动能策略）：自身历史 / 与价格 / 与大盘 / 反向压力 -->
          <div class="card-dims" v-if="!isPring && !isUltra && !isProbe && pick.momentum && pick.momentum.dimensions">
            <span class="dims-title">四维动能</span>
            <span
              v-for="dim in dimList(pick.momentum.dimensions)"
              :key="dim.key"
              class="dim-chip"
              :class="dim.cls"
              :title="dim.desc"
            >{{ dim.name }} <b>{{ dim.label }}</b><i v-if="dim.score != null">{{ dim.scoreText }}</i></span>
          </div>

          <div class="card-price-levels" v-if="pick.buy_price || pick.stop_price || pick.target_price">
            <div class="pl-item pl-buy" v-if="pick.buy_price"><div class="pl-lbl">买入价</div><div class="pl-val">{{ pick.buy_price }}</div></div>
            <div class="pl-item pl-warn" v-if="isProbe && pick.warn_price"><div class="pl-lbl">黄牌 -3%</div><div class="pl-val">{{ pick.warn_price }}</div></div>
            <div class="pl-item pl-stop" v-if="pick.stop_price"><div class="pl-lbl">{{ isProbe ? '红牌止损' : '止损价' }}</div><div class="pl-val">{{ pick.stop_price }}</div></div>
            <div class="pl-item pl-target" v-if="pick.target_price"><div class="pl-lbl">目标价</div><div class="pl-val">{{ pick.target_price }}</div></div>
          </div>

          <div class="card-checklist" v-if="pick.checklist?.length">
            <div class="checklist-title">操作前置条件</div>
            <div v-for="item in pick.checklist" :key="item" class="checklist-item">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              {{ item }}
            </div>
          </div>

          <div class="card-targets">
            <div class="target-item target-up">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>
              目标 +{{ pick.target_pct }}%
            </div>
            <div class="target-sep"></div>
            <div class="target-item target-down">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/></svg>
              止损 -{{ pick.stop_pct }}%
            </div>
            <div class="target-sep"></div>
            <div class="target-item target-period">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/></svg>
              {{ pick.holding_period || '1-2周' }}
            </div>
          </div>

          <div class="card-confidence">
            <div class="conf-label"><span>AI 置信度</span><span class="conf-val">{{ pick.confidence }}%</span></div>
            <div class="conf-bar"><div class="conf-fill" :style="{ width: pick.confidence + '%', background: confidenceColor(pick.confidence) }"></div></div>
          </div>

          <div class="card-actions">
            <router-link :to="'/stock/' + pick.code" class="act-btn act-chart" target="_blank" rel="noopener">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
              K线
            </router-link>
            <router-link :to="backtestLink(pick.code)" class="act-btn act-backtest" target="_blank" rel="noopener">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6l1 9H8L9 3z"/><path d="M6.1 15a3 3 0 0 0 2.19 5h7.42a3 3 0 0 0 2.19-5L15 12H9L6.1 15z"/></svg>
              回测
            </router-link>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div v-if="totalPages > 1" class="picks-pagination">
        <button class="pg-btn" @click="gotoPage(page - 1)" :disabled="page === 1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <button
          v-for="p in totalPages" :key="p"
          :class="['pg-num', { active: p === page }]"
          @click="gotoPage(p)"
        >{{ p }}</button>
        <button class="pg-btn" @click="gotoPage(page + 1)" :disabled="page >= totalPages">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
        </button>
        <span class="pg-info">共 {{ filteredPicks.length }} 只 · {{ page }}/{{ totalPages }} 页</span>
      </div>

      <div class="disclaimer">⚠️ {{ (isUltra || isProbe) ? '以上为规则化扫描结果（非 AI 生成），仅供参考，不构成投资建议；试盘/超短风险高，务必带好止损。' : '以上内容由 AI 模型基于量化因子数据分析生成，仅供参考，不构成投资建议。' }}</div>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

// 荐股例行由后台计划任务生成；手动「重新分析」已完全收口到后台管理
// （/admin → AI 荐股 tab，仅管理员可重跑）。本页对所有用户只读最新结果。

// ── 选股策略 Tab（动能买点 / 普林格KST周期）────────────────────────────────
const STRATEGIES = [
  { key: 'momentum', label: '动能买点', desc: '今日首次触发动能买点，短中线' },
  { key: 'pring', label: '普林格KST周期', desc: 'KST动量+六阶段，中长线' },
  { key: 'ultra', label: '超短量价', desc: '盘前9:20-9:25量价突破，创业板/科创板超短' },
  { key: 'probe', label: '试盘点', desc: '近一个月放量长上影+低位突破前期高点，主力试盘' },
]
const strategy = ref('momentum')
const isPring = computed(() => strategy.value === 'pring')
const isUltra = computed(() => strategy.value === 'ultra')
const isProbe = computed(() => strategy.value === 'probe')

// 当前策略对应的可回测策略类（仅动能/普林格有日线单标的回测版；
// 超短量价/试盘点为盘前/事件型，无法在日线回测引擎中如实还原，回测不带策略预选）。
const BT_STRATEGY_MAP = {
  momentum: 'strategies.examples.ai_pick_strategies.MomentumPickStrategy',
  pring:    'strategies.examples.ai_pick_strategies.PringPickStrategy',
}
function backtestLink(code) {
  const s = BT_STRATEGY_MAP[strategy.value]
  return '/backtest?symbols=' + code + (s ? '&strategy=' + encodeURIComponent(s) : '')
}

// 超短量价：是否处于盘前竞价窗口(交易日 9:20-9:25)——窗口内每30s自动刷新
const clockNow = ref(new Date())
const ultraLive = computed(() => {
  if (!isUltra.value) return false
  const d = clockNow.value
  const wd = d.getDay()
  if (wd === 0 || wd === 6) return false
  const hm = d.getHours() * 60 + d.getMinutes()
  return hm >= (9 * 60 + 20) && hm <= (9 * 60 + 25)
})

const data = ref(null)
const loading = ref(false)
const error = ref('')
const showHistory = ref(false)
const history = ref([])
const activeKey = ref('')   // 当前加载的历史键(日期_时段)，用于高亮历史列表

// ── 该策略「今日胜率」多周期(实时/3日/7日/30日)────────────────────────────────
const winrate = ref(null)
const winLoading = ref(false)
const winHorizons = computed(() => winrate.value?.horizons || [])
const stratLabel = computed(() => (STRATEGIES.find(s => s.key === strategy.value) || {}).label || '策略')
function wrColor(v) {
  if (v == null) return 'var(--text-3)'
  if (v >= 60) return 'var(--up)'
  if (v >= 40) return 'var(--accent)'
  return 'var(--down)'
}
function winTip(h) {
  if (h.is_realtime) return `今日推荐 ${h.total || 0} 只，已取到开盘价的 ${h.evaluated || 0} 只：胜${h.win || 0}/负${h.loss || 0}`
  return `历史推荐持有${h.label}样本 ${h.evaluated || 0} 只：胜${h.win || 0}/负${h.loss || 0}`
}
async function fetchWinrate() {
  winLoading.value = true
  try {
    const r = await axios.get('/api/predictions/strategy-winrate', { params: { pick_strategy: strategy.value } })
    winrate.value = r.data
  } catch { /* 保留旧值 */ } finally {
    winLoading.value = false
  }
}

// ── 行业 / 概念 筛选（多选 + 按账户保存习惯）──────────────────────────────────
// 行业维度用「申万一级行业」(后端 sw_industry)，缺失才回退新浪行业/权威 sector；
// 概念维度取同花顺概念成分。两维度均支持多选，空 = 全部；缺失归到「其他」。
// 选中项按账户存 localStorage，下次进来自动回填（行业习惯长期保留，概念也一并记忆）。
const filterDim = ref('industry')   // 'industry' | 'concept'
const selectedSectors = ref([])     // 多选，空数组 = 全部
function pickIndustry(p) { return (p?.sw_industry || p?.industry || p?.sector || '').trim() || '其他' }
function pickConcepts(p) { return Array.isArray(p?.concepts) ? p.concepts.filter(Boolean) : [] }
const hasConcepts = computed(() => allPicks.value.some(p => pickConcepts(p).length))

// 选择习惯持久化：按账户 + 维度分槽存
function _prefKey() { return `aipicks_sector_filter_${auth.user?.id || 'anon'}` }
function _loadPrefs() {
  try { return JSON.parse(localStorage.getItem(_prefKey()) || '{}') } catch { return {} }
}
function _savePref(dim, list) {
  const prefs = _loadPrefs()
  prefs[dim] = [...list]
  try { localStorage.setItem(_prefKey(), JSON.stringify(prefs)) } catch { /* ignore */ }
}
function _restorePref(dim) {
  const prefs = _loadPrefs()
  selectedSectors.value = Array.isArray(prefs[dim]) ? prefs[dim] : []
}

const sectorOptions = computed(() => {
  const counts = new Map()
  for (const p of allPicks.value) {
    if (filterDim.value === 'concept') {
      for (const c of pickConcepts(p)) counts.set(c, (counts.get(c) || 0) + 1)
    } else {
      const s = pickIndustry(p)
      counts.set(s, (counts.get(s) || 0) + 1)
    }
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
})
const filteredPicks = computed(() => {
  if (!selectedSectors.value.length) return allPicks.value
  const sel = new Set(selectedSectors.value)
  return filterDim.value === 'concept'
    ? allPicks.value.filter(p => pickConcepts(p).some(c => sel.has(c)))
    : allPicks.value.filter(p => sel.has(pickIndustry(p)))
})
function isSelected(name) { return selectedSectors.value.includes(name) }
function toggleSector(name) {
  const i = selectedSectors.value.indexOf(name)
  if (i >= 0) selectedSectors.value.splice(i, 1)
  else selectedSectors.value.push(name)
  _savePref(filterDim.value, selectedSectors.value)
  page.value = 1
}
function clearSectors() {
  if (!selectedSectors.value.length) return
  selectedSectors.value = []
  _savePref(filterDim.value, [])
  page.value = 1
}
function setDim(dim) {
  if (filterDim.value === dim) return
  filterDim.value = dim
  _restorePref(dim)   // 切换维度回填该维度已保存的选择
  page.value = 1
}

// ── 分页 ──────────────────────────────────────────────────────────────────
const PAGE_SIZE = 12
const page = ref(1)
const allPicks = computed(() => data.value?.picks || [])
const totalPages = computed(() => Math.max(1, Math.ceil(filteredPicks.value.length / PAGE_SIZE)))
const pagedPicks = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return filteredPicks.value.slice(start, start + PAGE_SIZE)
})
function gotoPage(p) {
  if (p < 1 || p > totalPages.value) return
  page.value = p
  // 翻页后滚回推荐区顶部
  document.querySelector('.picks-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// ── 选股漏斗：从全市场逐级筛到最终排序 ──────────────────────────────────────
const funnel = computed(() => data.value?.funnel || null)
const funnelStages = computed(() => {
  const f = funnel.value
  if (!f || !f.market_total) return []
  let raw
  if (isUltra.value) {
    // 超短量价：纯规则化漏斗（不走 AI）
    raw = [
      { key: 'market', label: '创业/科创板', value: f.market_total, color: '#64748b',
        desc: '创业板+科创板全部' },
      { key: 'filter', label: '剔退市', value: f.after_filter, color: '#0891b2',
        desc: '仅剔退市股（保留 ST）' },
      { key: 'scored', label: '可评分', value: f.scored, color: '#2563eb',
        desc: '有日 K 缓存可计算' },
      { key: 'buy', label: '量能上穿', value: f.buy_points, color: '#7c3aed',
        desc: '5日均量首次上穿60日+近10日涨幅≤20%' },
      { key: 'selected', label: '今日≥3%', value: f.selected, color: '#d97706',
        desc: '叠加今日涨幅≥3%' },
      { key: 'final', label: '入选排序', value: f.recommended ?? (data.value?.picks?.length || 0),
        color: '#dc2626', desc: '按今日涨幅+量比排序' },
    ]
  } else if (isProbe.value) {
    // 试盘线：纯规则化漏斗（不走 AI）
    raw = [
      { key: 'market', label: '全市场', value: f.market_total, color: '#64748b',
        desc: '快照全部 A 股' },
      { key: 'filter', label: '流动性过滤', value: f.after_filter, color: '#0891b2',
        desc: '剔退市/低成交额/金融板块' },
      { key: 'scored', label: '可评分', value: f.scored, color: '#2563eb',
        desc: '有日 K 缓存可计算' },
      { key: 'buy', label: '试盘线', value: f.buy_points, color: '#7c3aed',
        desc: '放量长上影+突破前期高点(已排除大盘跳水日)' },
      { key: 'selected', label: '涨幅可控', value: f.selected ?? f.buy_points, color: '#d97706',
        desc: '剔除试盘至今已涨过多(入场已过)' },
      { key: 'final', label: '入选排序', value: f.recommended ?? (data.value?.picks?.length || 0),
        color: '#dc2626', desc: '入场点已到优先·按试盘日远近排序' },
    ]
  } else {
    const buyLabel = isPring.value ? '周期买点' : '动能买点'
    raw = [
      { key: 'market', label: '全市场', value: f.market_total, color: '#64748b',
        desc: '快照全部 A 股' },
      { key: 'filter', label: '流动性过滤', value: f.after_filter, color: '#0891b2',
        desc: '剔退市/低成交额/保险银行证券/老登行业（保留 ST/涨停）' },
      { key: 'scored', label: '可评分', value: f.scored, color: '#2563eb',
        desc: '有 K 线缓存、能算指标' },
      { key: 'buy', label: buyLabel, value: f.buy_points, color: '#7c3aed',
        desc: isPring.value ? '站上信号线+长周期向上' : '近期首次触发买点' },
      { key: 'selected', label: '交给 AI', value: f.selected, color: '#d97706',
        desc: '全部买点交给 AI 评选' },
      { key: 'final', label: 'AI 产出排序', value: f.recommended ?? (data.value?.picks?.length || 0),
        color: '#dc2626', desc: 'AI 精选并按优先级排序（不设上限）' },
    ]
  }
  const max = Math.max(...raw.map(s => s.value || 0), 1)
  return raw.map((s, i) => {
    const prev = i > 0 ? raw[i - 1].value : null
    const drop = (prev != null && s.value != null && prev >= s.value) ? prev - s.value : null
    // 对数刻度让 5000→30 这种悬殊差也能看清每级（线性会把后几级压成一条线）
    const barPct = Math.max(6, Math.round(Math.log10((s.value || 0) + 1) / Math.log10(max + 1) * 100))
    return { ...s, drop, barPct }
  })
})

async function load(dateKey) {
  loading.value = true; error.value = ''
  try {
    const url = dateKey
      ? `/api/ai-picks/history-date/${dateKey}`
      : `/api/ai-picks/daily?strategy=${strategy.value}`
    const res = await axios.get(url)
    data.value = res.data
    page.value = 1
    filterDim.value = 'industry' // 维度回到行业
    _restorePref('industry')     // 回填该账户保存的行业筛选习惯
    // 历史项可能属于另一策略：同步当前策略到返回值，使 Tab 高亮一致
    if (res.data.strategy) strategy.value = res.data.strategy
    // 记录当前键：历史项点进来用传入的 key，最新一次用返回里的 date_slot 组合
    activeKey.value = dateKey || (res.data.slot ? `${res.data.date}_${res.data.slot}` : res.data.date)
  } catch (e) {
    error.value = e.response?.data?.detail || '加载失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

// 切换策略：加载该策略当天最新一份 + 该策略历史
async function switchStrategy(key) {
  if (key === strategy.value || loading.value) return
  strategy.value = key
  await Promise.all([load(), loadHistory(), fetchWinrate()])
  startPoll()
}

// ── 超短量价：竞价窗口内每30s自动刷新 ──────────────────────────────────────
let pollTimer = null
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }
function startPoll() {
  stopPoll()
  if (!isUltra.value) return
  pollTimer = setInterval(() => {
    // 仅在竞价窗口内、非历史浏览、非加载中时静默刷新，避免无谓请求
    if (isUltra.value && ultraLive.value && !showHistory.value && !loading.value) load()
  }, 30000)
}

async function loadDate(dateKey) {
  await load(dateKey)
  showHistory.value = false
}

async function loadHistory() {
  try {
    const res = await axios.get(`/api/ai-picks/history?strategy=${strategy.value}`)
    history.value = res.data.history || []
  } catch {}
}

// 信心条用蓝→灰梯度：红绿留给涨跌语义（与首页 confColor 一致）
function confidenceColor(v) {
  if (v >= 80) return '#1d4ed8'
  if (v >= 60) return '#2563eb'
  if (v >= 40) return '#d97706'
  return '#94a3b8'
}

const STATE_CN = { buy: '买点', hold: '持有', reduce: '减仓', sell: '卖点' }
const DIR_CN = { accelerating: '加速↑', rising: '上行↑', flat: '走平', falling: '下行↓' }
function stateLabel(s) { return STATE_CN[s] || s || '持有' }
function dirLabel(d) { return DIR_CN[d] || d }

// 四维动能：把后端 dimensions 对象整理成卡片用的数组（含正负配色）
const DIM_META = [
  { key: 'self_history', name: '自身史' },
  { key: 'mom_vs_price', name: '与价' },
  { key: 'vs_market', name: '大盘' },
  { key: 'reverse', name: '反向' },
]
function dimList(dims) {
  if (!dims) return []
  return DIM_META.map(({ key, name }) => {
    const d = dims[key] || {}
    const score = d.score
    // 维度3 用实际基准名（所属行业/大盘）当 chip 标题，比固定写「大盘」更准
    if (key === 'vs_market' && d.benchmark) name = d.benchmark
    // 反向维度是「压力」(0~100，越高越偏空)；其余是有向分(-100~100，正为多)
    let cls = 'dim-neutral'
    if (key === 'reverse') {
      cls = score >= 55 ? 'dim-bad' : score >= 25 ? 'dim-warn' : 'dim-good'
    } else if (score != null) {
      cls = score >= 12 ? 'dim-good' : score <= -12 ? 'dim-bad' : 'dim-neutral'
    }
    const scoreText = score == null ? ''
      : key === 'reverse' ? ` ${Math.round(score)}`
      : ` ${score > 0 ? '+' : ''}${Math.round(score)}`
    return { key, name, label: d.label || '—', desc: d.desc || '', score, scoreText, cls }
  })
}

function formatDate(s) {
  if (!s) return ''
  const [y, m, d] = s.split('-')
  return `${y}年${parseInt(m)}月${parseInt(d)}日`
}

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

let clockTimer = null
onMounted(async () => {
  clockTimer = setInterval(() => { clockNow.value = new Date() }, 20000)
  await Promise.all([load(), loadHistory(), fetchWinrate()])
  startPoll()
})
onUnmounted(() => {
  stopPoll()
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped>
.ai-picks-wrap { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; min-height: 100%; }

/* Header */
.picks-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.header-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ai-badge { display: flex; align-items: center; gap: 6px; background: var(--accent); color: #fff; font-size: 13px; font-weight: 600; padding: 5px 12px; border-radius: 20px; }

/* 策略 Tab */
.strategy-tabs { display: inline-flex; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; }
.strat-tab { border: none; background: transparent; color: var(--text-3); font-size: 12.5px; font-weight: 500; padding: 5px 14px; border-radius: calc(var(--radius-md) - 2px); cursor: pointer; transition: all 0.15s; white-space: nowrap; }
.strat-tab:hover:not(:disabled) { color: var(--text-1); }
.strat-tab.active { background: var(--accent); color: #fff; }
.strat-tab:disabled { opacity: 0.6; cursor: default; }
.header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.header-meta { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); flex-wrap: wrap; }
.meta-sep { color: var(--border); }
.meta-slot { font-size: 11px; font-weight: 600; color: #7c3aed; background: rgba(124,58,237,0.12); padding: 1px 8px; border-radius: 10px; }
.meta-cap { font-size: 11px; color: var(--text-3); background: var(--bg-hover); padding: 1px 8px; border-radius: 10px; }

/* ── 选股漏斗 ─────────────────────────────────────────── */
.funnel-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; }
.funnel-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.funnel-title { font-size: 13px; font-weight: 700; color: var(--text-1); }
.funnel-sub { font-size: 11px; color: var(--text-3); }
.funnel-flow { display: flex; align-items: stretch; gap: 0; flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.fn-stage { position: relative; flex: 1 1 0; min-width: 92px; display: flex; flex-direction: column; padding: 8px 10px 22px; border-radius: var(--radius-md); background: var(--bg-base); }
.fn-stage.fn-final { background: rgba(220,38,38,0.06); border: 1px solid rgba(220,38,38,0.25); }
.fn-bar { height: 4px; border-radius: 2px; margin-bottom: 8px; transition: width 0.4s; }
.fn-stage-body { display: flex; flex-direction: column; gap: 2px; }
.fn-val { font-size: 19px; font-weight: 800; font-family: var(--font-mono); color: var(--text-1); line-height: 1; }
.fn-unit { font-size: 11px; font-weight: 500; color: var(--text-3); margin-left: 2px; }
.fn-lbl { font-size: 12px; font-weight: 600; color: var(--text-2); }
.fn-desc { font-size: 10px; color: var(--text-3); line-height: 1.4; }
.fn-drop { position: absolute; bottom: 6px; left: 10px; font-size: 9.5px; color: #16a34a; font-family: var(--font-mono); }
.fn-arrow { display: flex; align-items: center; padding: 0 2px; font-size: 20px; color: var(--text-3); font-weight: 700; flex-shrink: 0; }

@media (max-width: 768px) {
  .funnel-flow { gap: 0; }
  .fn-stage { min-width: 100px; }
}

/* 超短量价说明横幅 */
.ultra-banner { display: flex; align-items: flex-start; gap: 10px; background: rgba(220,38,38,0.06); border: 1px solid rgba(220,38,38,0.25); border-radius: var(--radius-lg); padding: 12px 16px; font-size: 12.5px; line-height: 1.6; color: var(--text-2); }
.ultra-banner strong { color: #dc2626; margin-right: 4px; }
.ultra-banner b { color: var(--text-1); }
.ultra-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; margin-top: 5px; }
.ultra-dot.live { background: #16a34a; box-shadow: 0 0 0 0 rgba(22,163,74,0.5); animation: ultra-pulse 1.6s infinite; }
@keyframes ultra-pulse { 0% { box-shadow: 0 0 0 0 rgba(22,163,74,0.45); } 70% { box-shadow: 0 0 0 7px rgba(22,163,74,0); } 100% { box-shadow: 0 0 0 0 rgba(22,163,74,0); } }

/* 试盘线说明横幅 */
.probe-banner { display: flex; align-items: flex-start; gap: 10px; background: rgba(124,58,237,0.06); border: 1px solid rgba(124,58,237,0.25); border-radius: var(--radius-lg); padding: 12px 16px; font-size: 12.5px; line-height: 1.6; color: var(--text-2); }
.probe-banner strong { color: #7c3aed; margin-right: 4px; }
.probe-banner b { color: #dc2626; }
.probe-dot { width: 9px; height: 9px; border-radius: 50%; background: #7c3aed; flex-shrink: 0; margin-top: 5px; }

/* 试盘点·入场状态条 */
.probe-entry { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; border-radius: var(--radius-sm); border: 1px solid var(--border); background: var(--bg-hover); }
.pe-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; width: fit-content; }
.pe-note { font-size: 11px; color: var(--text-3); line-height: 1.5; }
/* 入场点已到=绿(可进)、临近=蓝、今日试盘=紫、等待=灰、破位=红 */
.probe-entry.pe-ready { background: rgba(22,163,74,0.1); border-color: rgba(22,163,74,0.4); }
.probe-entry.pe-ready .pe-badge { color: #16a34a; }
.probe-entry.pe-near { background: rgba(37,99,235,0.08); border-color: rgba(37,99,235,0.35); }
.probe-entry.pe-near .pe-badge { color: #2563eb; }
.probe-entry.pe-today { background: rgba(124,58,237,0.08); border-color: rgba(124,58,237,0.3); }
.probe-entry.pe-today .pe-badge { color: #7c3aed; }
.probe-entry.pe-watch .pe-badge { color: var(--text-2); }
.probe-entry.pe-failed { background: rgba(239,68,68,0.08); border-color: rgba(239,68,68,0.35); }
.probe-entry.pe-failed .pe-badge { color: #dc2626; }

/* 今日无明确买点横幅 */
.no-buy-banner { display: flex; align-items: flex-start; gap: 10px; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); border-radius: var(--radius-lg); padding: 12px 16px; font-size: 12.5px; line-height: 1.6; color: var(--text-2); }
.no-buy-banner svg { color: #d97706; flex-shrink: 0; margin-top: 2px; }
.no-buy-banner strong { color: #b45309; }

/* 观察标的角标 + 卡片样式 */
.observe-badge { font-size: 10px; font-weight: 700; color: #d97706; background: rgba(245,158,11,0.15); padding: 2px 7px; border-radius: 10px; white-space: nowrap; }
.pick-card.is-observe { border-style: dashed; border-color: rgba(245,158,11,0.4); }
.pick-card.is-observe:hover { border-color: #d97706; }

.h-slot { font-size: 10px; color: #7c3aed; background: rgba(124,58,237,0.1); padding: 1px 6px; border-radius: 8px; white-space: nowrap; }
.h-strat { font-size: 10px; color: #0891b2; background: rgba(8,145,178,0.1); padding: 1px 6px; border-radius: 8px; white-space: nowrap; }
.h-noteg { font-size: 10px; color: #d97706; background: rgba(245,158,11,0.12); padding: 1px 6px; border-radius: 8px; white-space: nowrap; }

/* Buttons */
.btn-history { display: flex; align-items: center; gap: 5px; padding: 6px 12px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-2); font-size: 12px; cursor: pointer; }
.btn-history:hover, .btn-history.active { border-color: var(--accent); color: var(--accent); }
.btn-refresh { display: flex; align-items: center; gap: 5px; padding: 6px 14px; border-radius: var(--radius-md); border: none; background: var(--accent); color: #fff; font-size: 12px; font-weight: 500; cursor: pointer; }
.btn-refresh:disabled { opacity: 0.5; cursor: default; }

/* History panel */
.history-panel { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; }
.history-title { font-size: 12px; font-weight: 600; color: var(--text-2); margin-bottom: 10px; }
.history-empty { font-size: 12px; color: var(--text-3); }
.history-list { display: flex; flex-direction: column; gap: 4px; }
.history-item { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: var(--radius-md); cursor: pointer; font-size: 12px; }
.history-item:hover { background: var(--bg-hover); }
.history-item.active { background: var(--accent-dim); }
.h-date { color: var(--text-1); font-weight: 500; white-space: nowrap; }
.h-count { color: var(--accent); font-weight: 600; white-space: nowrap; }
.h-summary { color: var(--text-3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* States */
.state-card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; padding: 60px 24px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.state-text { font-size: 14px; color: var(--text-1); font-weight: 500; }
.state-sub { font-size: 12px; color: var(--text-3); }
@keyframes ring { to { transform: rotate(360deg); } }
.loading-ring { width: 36px; height: 36px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: ring 0.8s linear infinite; }

/* Market summary */
.market-summary { display: flex; align-items: flex-start; gap: 10px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; color: var(--text-2); }
.summary-icon { margin-top: 1px; flex-shrink: 0; }
.summary-text { font-size: 13px; line-height: 1.6; }

.op-strategy { display: flex; align-items: center; gap: 8px; background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); border-radius: var(--radius-md); padding: 8px 14px; }
.op-label { font-size: 11px; font-weight: 700; color: #d97706; white-space: nowrap; }
.op-text { font-size: 12px; color: var(--text-1); }

/* 该策略多周期胜率条 */
.winrate-strip { display: flex; align-items: center; gap: 12px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 10px 14px; flex-wrap: wrap; }
.wr-title { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 700; color: var(--text-2); white-space: nowrap; flex-shrink: 0; }
.wr-cells { display: flex; gap: 8px; flex: 1; min-width: 0; }
.wr-cell { flex: 1; min-width: 78px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 6px 8px; text-align: center; }
.wr-h { font-size: 10px; color: var(--text-3); font-weight: 600; }
.wr-rate { font-size: 18px; font-weight: 800; font-family: var(--font-mono); line-height: 1.15; }
.wr-avg { font-size: 11px; font-weight: 600; font-family: var(--font-mono); }
.wr-avg.up { color: var(--up); }
.wr-avg.down { color: var(--down); }
.wr-n { font-size: 9.5px; color: var(--text-3); }
.wr-hint { font-size: 10.5px; color: var(--text-3); white-space: nowrap; }

/* 分板块筛选 */
.sector-filter { display: flex; align-items: flex-start; gap: 8px; }
.sf-chips { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; min-width: 0; max-height: 96px; overflow-y: auto; padding: 1px; }
.sf-chip { border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-2); font-size: 12px; font-weight: 500; padding: 4px 11px; border-radius: 14px; cursor: pointer; white-space: nowrap; transition: all 0.12s; }
.sf-chip:hover { border-color: var(--accent); color: var(--text-1); }
.sf-chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.sf-dim { display: inline-flex; gap: 2px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 2px; flex-shrink: 0; }
.sf-dim-btn { border: none; background: transparent; color: var(--text-3); font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: calc(var(--radius-md) - 2px); cursor: pointer; transition: all 0.12s; }
.sf-dim-btn.active { background: var(--accent); color: #fff; }
.sf-dim-btn:disabled { opacity: 0.4; cursor: default; }
.sf-label { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; color: var(--text-3); white-space: nowrap; flex-shrink: 0; }
.sf-count { font-size: 11px; color: var(--text-3); white-space: nowrap; margin-left: auto; flex-shrink: 0; }

/* Picks grid */
.picks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }

.pick-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: border-color 0.15s; }
.pick-card:hover { border-color: var(--accent); }

.card-head { display: flex; align-items: flex-start; gap: 10px; }
.card-rank { font-size: 11px; font-weight: 700; color: var(--text-3); background: var(--bg-hover); padding: 2px 7px; border-radius: 10px; white-space: nowrap; }
.card-stock { flex: 1; }
.stock-name { font-size: 14px; font-weight: 700; color: var(--text-1); }
.stock-code { font-size: 11px; color: var(--text-3); margin-top: 2px; font-family: var(--font-mono); }
.card-tags { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.tag-sector { font-size: 10px; color: var(--text-3); background: var(--bg-hover); padding: 2px 6px; border-radius: 6px; }
.tag-risk { font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 600; }
.risk-低 .tag-risk.risk-低, .tag-risk.risk-低 { background: rgba(34,197,94,0.15); color: #16a34a; }
.risk-中 .tag-risk.risk-中, .tag-risk.risk-中 { background: rgba(245,158,11,0.15); color: #b45309; }
.risk-高 .tag-risk.risk-高, .tag-risk.risk-高 { background: rgba(239,68,68,0.15); color: #dc2626; }

.card-price { display: flex; align-items: center; gap: 8px; }
.price-val { font-size: 18px; font-weight: 700; color: var(--text-1); }
.price-change { font-size: 13px; font-weight: 600; }
.price-change.up { color: var(--up); }
.price-change.down { color: var(--down); }
.price-meta { margin-left: auto; display: flex; gap: 6px; font-size: 11px; color: var(--text-3); }

.card-reason { font-size: 12px; color: var(--text-2); line-height: 1.6; }

.card-signals { display: flex; flex-wrap: wrap; gap: 5px; }
.signal-tag { font-size: 10px; padding: 2px 7px; background: var(--accent-dim); color: var(--accent); border-radius: 10px; }

.card-momentum { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.momo-chip { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; border: 1px solid var(--border); color: var(--text-2); background: var(--bg-hover); }
.momo-score { color: var(--amber); border-color: rgba(217,119,6,.35); background: rgba(217,119,6,.1); }
/* 买卖状态：买=蓝、卖/减=金、持有=灰，与个股详情页 st-* 一致（红绿留给涨跌） */
.momo-state-buy { color: #2563eb; border-color: rgba(37,99,235,.35); background: rgba(37,99,235,.1); }
.momo-state-hold { color: var(--text-2); border-color: var(--border); background: var(--bg-hover); }
.momo-state-reduce { color: #d97706; border-color: rgba(217,119,6,.35); background: rgba(217,119,6,.1); }
.momo-state-sell { color: #d97706; border-color: rgba(217,119,6,.45); background: rgba(217,119,6,.14); }
.momo-dir, .momo-rr { color: var(--text-3); }
.momo-stage { color: #0891b2; border-color: rgba(8,145,178,.35); background: rgba(8,145,178,.1); }
.momo-cross { color: #16a34a; border-color: rgba(22,163,74,.4); background: rgba(22,163,74,.12); font-weight: 700; }
.momo-fail { color: #dc2626; border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.12); font-weight: 700; }

/* 四维动能：自身史 / 与价 / 大盘 / 反向，正多负空配色（红绿留给涨跌，多用蓝、空用金/红） */
.card-dims { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.dims-title { font-size: 10px; color: var(--text-3); font-weight: 600; margin-right: 2px; }
.dim-chip { font-size: 10px; padding: 2px 7px; border-radius: 9px; border: 1px solid var(--border); color: var(--text-2); background: var(--bg-hover); display: inline-flex; align-items: center; gap: 3px; }
.dim-chip b { font-weight: 700; }
.dim-chip i { font-style: normal; opacity: .7; font-size: 9px; }
.dim-good { color: #2563eb; border-color: rgba(37,99,235,.3); background: rgba(37,99,235,.08); }
.dim-warn { color: #d97706; border-color: rgba(217,119,6,.32); background: rgba(217,119,6,.09); }
.dim-bad { color: #dc2626; border-color: rgba(239,68,68,.38); background: rgba(239,68,68,.1); }
.dim-neutral { color: var(--text-3); }

.card-price-levels { display: flex; gap: 8px; }
.pl-item { flex: 1; background: var(--bg-hover); border-radius: var(--radius-sm); padding: 6px 8px; text-align: center; }
.pl-lbl { font-size: 10px; color: var(--text-3); margin-bottom: 2px; }
.pl-val { font-size: 13px; font-weight: 700; }
/* 目标=红(涨)、止损=绿(跌)，与卡片底部 target-up/down 及全站语义一致 */
.pl-buy .pl-val { color: var(--accent); }
.pl-warn .pl-val { color: #d97706; }
.pl-stop .pl-val { color: var(--down); }
.pl-target .pl-val { color: var(--up); }

.card-checklist { background: var(--bg-hover); border-radius: var(--radius-sm); padding: 8px 10px; }
.checklist-title { font-size: 10px; color: var(--text-3); font-weight: 600; margin-bottom: 5px; }
.checklist-item { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-2); margin-top: 3px; }

.card-targets { display: flex; align-items: center; gap: 6px; }
.target-item { display: flex; align-items: center; gap: 4px; font-size: 11px; }
.target-up { color: var(--up); }
.target-down { color: var(--down); }
.target-period { color: var(--text-3); }
.target-sep { width: 1px; height: 12px; background: var(--border); }

.card-confidence { display: flex; flex-direction: column; gap: 4px; }
.conf-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); }
.conf-val { font-weight: 600; color: var(--text-1); }
.conf-bar { height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.conf-fill { height: 100%; border-radius: 2px; transition: width 0.4s; }

.card-actions { display: flex; gap: 6px; margin-top: 2px; }
.act-btn { flex: 1; display: flex; align-items: center; justify-content: center; gap: 4px; padding: 5px 8px; border-radius: var(--radius-sm); font-size: 11px; font-weight: 500; text-decoration: none; border: 1px solid var(--border); color: var(--text-2); background: var(--bg-hover); transition: all 0.12s; }
.act-btn:hover { border-color: var(--accent); color: var(--accent); }

/* 分页 */
.picks-pagination { display: flex; align-items: center; justify-content: center; gap: 6px; flex-wrap: wrap; padding: 6px 0; }
.pg-btn, .pg-num { display: flex; align-items: center; justify-content: center; min-width: 30px; height: 30px; padding: 0 8px; border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-2); border-radius: var(--radius-md); cursor: pointer; font-size: 12px; transition: all 0.12s; }
.pg-btn:disabled { opacity: 0.4; cursor: default; }
.pg-btn:hover:not(:disabled), .pg-num:hover { border-color: var(--accent); color: var(--accent); }
.pg-num.active { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
.pg-info { font-size: 11px; color: var(--text-3); margin-left: 8px; font-family: var(--font-mono); }

.disclaimer { font-size: 11px; color: var(--text-3); text-align: center; padding: 4px; }

/* ── 移动端适配 ─────────────────────────────────────────── */
@media (max-width: 768px) {
  .ai-picks-wrap { padding: 12px; gap: 12px; }

  /* 头部：策略 tabs 独占一行、可横向滑动 */
  .picks-header { flex-direction: column; align-items: flex-start; gap: 10px; }
  .header-left { flex-direction: column; align-items: flex-start; gap: 8px; width: 100%; }
  .strategy-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; align-self: stretch; }
  .strat-tab { flex-shrink: 0; }
  .header-right { width: 100%; }
  .btn-history, .btn-refresh { flex: 1; justify-content: center; padding: 9px 12px; }

  /* 历史项换行展示，摘要单独成行 */
  .history-item { flex-wrap: wrap; }
  .h-summary { flex-basis: 100%; }

  /* 胜率条：标题独行、四格平铺 */
  .winrate-strip { gap: 8px; }
  .wr-title { width: 100%; }
  .wr-cells { width: 100%; }
  .wr-cell { min-width: 0; padding: 6px 4px; }
  .wr-rate { font-size: 16px; }
  .wr-hint { display: none; }

  /* 板块筛选：维度切换 + 多选标签换行铺满便于触控 */
  .sector-filter { flex-wrap: wrap; }
  .sf-chips { width: 100%; max-height: 132px; }
  .sf-count { display: none; }

  /* 推荐卡单列铺满 */
  .picks-grid { grid-template-columns: 1fr; gap: 12px; }
  .pick-card { padding: 14px; }

  /* 操作按钮加大触控高度 */
  .card-actions { gap: 8px; }
  .act-btn { padding: 9px 8px; min-height: 38px; }

  /* 目标条窄屏换行避免挤压 */
  .card-targets { flex-wrap: wrap; gap: 8px; }
  .header-meta { flex-wrap: wrap; }
}
</style>
