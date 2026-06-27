<template>
  <div class="sad" v-if="overview || loading">
    <!-- ══ 行情头 ══ -->
    <div class="quote-head card" v-if="overview">
      <div class="qh-main">
        <div class="qh-title">
          <span class="qh-name">{{ overview.name }}</span>
          <span class="qh-code">{{ overview.symbol }}</span>
          <span class="qh-market">{{ overview.market }}</span>
        </div>
        <div class="qh-price-row">
          <span class="qh-price" :class="chgClass(overview.change_pct)">{{ fmtPrice(overview.price ?? overview.yesterday_close) }}</span>
          <span class="qh-chg" :class="chgClass(overview.change_pct)">
            {{ fmtSigned(overview.change_amt) }} &nbsp; {{ fmtChg(overview.change_pct) }}
          </span>
        </div>
      </div>
      <div class="qh-metrics">
        <span v-for="m in shownMetrics" :key="m.key" class="qh-metric">
          <i class="qm-lbl">{{ m.label }}</i><b class="qm-val" :class="m.cls">{{ m.value }}</b>
        </span>
        <button class="qh-gear" @click="metricPicker = !metricPicker" title="配置指标">⚙</button>
        <!-- 指标选择浮层 -->
        <div v-if="metricPicker" class="popover metric-pop" @click.stop>
          <div class="pop-title">显示指标（行情头）</div>
          <div class="pop-grid">
            <label v-for="m in ALL_METRICS" :key="m.key" class="pop-chk">
              <input type="checkbox" :checked="metricKeys.includes(m.key)" @change="toggleMetric(m.key)" />
              {{ m.label }}
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- ══ 今日首次买入信号（醒目提示）══ -->
    <div class="fresh-buy card" v-if="freshBuy">
      <span class="fb-badge">⭐ 今日首次买入信号</span>
      <span class="fb-date">{{ freshBuy.date }} 动能转强突破</span>
      <span class="fb-levels">
        <em v-if="freshBuy.buy_price != null">买入 {{ fmtPrice(freshBuy.buy_price) }}</em>
        <em v-if="freshBuy.target_price != null" class="up">目标 {{ fmtPrice(freshBuy.target_price) }}<i v-if="freshBuy.target_pct"> +{{ freshBuy.target_pct }}%</i></em>
        <em v-if="freshBuy.stop_price != null" class="down">止损 {{ fmtPrice(freshBuy.stop_price) }}<i v-if="freshBuy.stop_pct"> -{{ freshBuy.stop_pct }}%</i></em>
      </span>
    </div>

    <!-- ══ 信息栏：行业/概念 + 核心竞争力 + 风险点 + 机构荐股 ══ -->
    <div class="info-card card" v-if="profile || loadingProfile || repSummary?.count">
      <div v-if="loadingProfile && !profile" class="ic-loading">
        <span class="spinner"></span><span class="text-3">AI 速览生成中…</span>
      </div>
      <template v-else-if="profile">
        <!-- 行业 / 概念 -->
        <div class="ic-tags">
          <span v-if="profile.industry" class="ic-chip ic-industry">行业 · {{ profile.industry }}</span>
          <span v-for="c in profile.concepts" :key="c"
                :class="['ic-chip', c === profile.top_concept ? 'ic-top' : '']">{{ c }}</span>
        </div>
        <div v-if="profile.top_concept_reason" class="ic-reason text-3">
          最相关概念「<b>{{ profile.top_concept }}</b>」：{{ profile.top_concept_reason }}
        </div>

        <!-- 核心竞争力 / 风险点 -->
        <div class="ic-cols">
          <div class="ic-col ic-strength">
            <div class="ic-col-title">核心竞争力</div>
            <ul><li v-for="(s, i) in profile.strengths" :key="i">{{ s }}</li></ul>
          </div>
          <div class="ic-col ic-risk">
            <div class="ic-col-title">风险点</div>
            <ul><li v-for="(r, i) in profile.risks" :key="i">{{ r }}</li></ul>
          </div>
        </div>
      </template>

      <!-- 机构荐股速览（来自机构研报一致预期）-->
      <div v-if="repSummary?.count" class="ic-rep">
        <div class="ic-rep-head">
          <span class="ic-col-title">机构荐股</span>
          <span class="rep-sub text-3">近 {{ repSummary.count }} 篇 · 最新 {{ repSummary.latest_date }}</span>
          <div style="flex:1"></div>
          <span v-if="repSummary.top_rating" :class="['rep-toprating', ratingCls(repSummary.top_rating)]">{{ repSummary.top_rating }}</span>
        </div>
        <div class="ic-rep-body">
          <span v-for="(n, name) in repSummary.ratings" :key="name" :class="['rating-chip2', ratingCls(name)]">{{ name }} <b>{{ n }}</b></span>
          <span v-if="repSummary.target" class="ic-rep-tgt">
            一致目标价 <b>{{ repSummary.target.avg }}</b>
            <em v-if="targetUpside(repSummary.target.avg) != null" :class="targetUpside(repSummary.target.avg) >= 0 ? 'up' : 'down'">
              {{ targetUpside(repSummary.target.avg) >= 0 ? '+' : '' }}{{ targetUpside(repSummary.target.avg) }}%</em>
          </span>
        </div>
      </div>
    </div>

    <!-- ══ 动能买卖点快照 ══ -->
    <div class="mom-card card" v-if="mom">
      <div class="mom-gauge">
        <div class="mom-score" :class="mom.scoreCls">{{ mom.score ?? '-' }}</div>
        <div class="mom-meta">
          <span class="mom-state" :class="mom.stateCls">{{ mom.stateLabel }}</span>
          <span class="mom-dir text-3">{{ mom.dirLabel }} · 动能</span>
        </div>
      </div>
      <div class="mom-levels">
        <div class="mlv"><i class="mlv-lbl">建议买入</i><b class="mlv-val up">{{ fmtPrice(mom.buy_price) }}</b></div>
        <div class="mlv"><i class="mlv-lbl">止损</i><b class="mlv-val down">{{ fmtPrice(mom.stop_price) }}<em v-if="mom.stop_pct">-{{ mom.stop_pct }}%</em></b></div>
        <div class="mlv"><i class="mlv-lbl">目标</i><b class="mlv-val up">{{ fmtPrice(mom.target_price) }}<em v-if="mom.target_pct">+{{ mom.target_pct }}%</em></b></div>
        <div class="mlv"><i class="mlv-lbl">盈亏比</i><b class="mlv-val">{{ mom.rr ?? '-' }}</b></div>
      </div>
      <div class="mom-hint text-3">规则评分(MACD/RSI/动量/量能)+ATR锚定，仅供参考</div>
    </div>

    <!-- ══ 风险预警 + 目标价分析 ══ -->
    <div class="rt-row" v-if="mom">
      <!-- 风险预警 -->
      <div class="rt-card card">
        <div class="rt-head">
          <span class="rt-title">⚠ 风险预警</span>
          <span class="rt-level" :class="'rl-' + (risk?.level || '低')">{{ risk?.level || '低' }}风险</span>
        </div>
        <ul class="risk-list" v-if="risk?.items?.length">
          <li v-for="(it, i) in risk.items" :key="i" class="risk-item">
            <span class="ri-dot" :class="'rl-' + it.level"></span>
            <span class="ri-msg">{{ it.msg }}</span>
          </li>
        </ul>
        <div v-else class="rt-empty text-3">暂无显著风险信号</div>
        <div class="rt-metrics text-3" v-if="risk">
          <span v-if="risk.rsi != null">RSI {{ risk.rsi }}</span>
          <span v-if="risk.atr_pct != null">波幅 {{ risk.atr_pct }}%</span>
          <span v-if="risk.drawdown_pct != null">回撤 {{ risk.drawdown_pct }}%</span>
          <span v-if="risk.valuation?.pe_ttm != null">PE {{ risk.valuation.pe_ttm }}</span>
          <span v-if="risk.valuation?.pb != null">PB {{ risk.valuation.pb }}</span>
        </div>
      </div>

      <!-- 目标价分析 -->
      <div class="rt-card card">
        <div class="rt-head"><span class="rt-title">🎯 目标价分析</span></div>
        <div class="tgt-grid">
          <div class="tgt-block">
            <div class="tgt-lbl text-3">技术目标价</div>
            <div class="tgt-val">{{ fmtPrice(target?.tech_target) }}
              <em v-if="target?.tech_upside_pct != null" :class="target.tech_upside_pct >= 0 ? 'up' : 'down'">
                {{ target.tech_upside_pct >= 0 ? '+' : '' }}{{ target.tech_upside_pct }}%</em>
            </div>
            <div class="tgt-sub text-3">{{ target?.tech_method || '—' }}</div>
          </div>
          <div class="tgt-block" v-if="target?.consensus">
            <div class="tgt-lbl text-3">研报一致目标价(中位)</div>
            <div class="tgt-val">{{ fmtPrice(target.consensus.median) }}
              <em v-if="target.consensus.upside_pct != null" :class="target.consensus.upside_pct >= 0 ? 'up' : 'down'">
                {{ target.consensus.upside_pct >= 0 ? '+' : '' }}{{ target.consensus.upside_pct }}%</em>
            </div>
            <div class="tgt-sub text-3">{{ target.consensus.count }}家覆盖 · 区间 {{ target.consensus.low }}~{{ target.consensus.high }}<template v-if="target.consensus.derived"> · EPS×预测PE反推</template></div>
          </div>
          <div class="tgt-block" v-else>
            <div class="tgt-lbl text-3">研报一致目标价</div>
            <div class="tgt-val text-3" style="font-size:14px">暂无近半年研报目标价</div>
          </div>
        </div>
        <div class="tgt-ratings" v-if="target?.consensus?.ratings && Object.keys(target.consensus.ratings).length">
          <span v-for="(n, rt) in target.consensus.ratings" :key="rt" class="rating-chip">{{ rt }} {{ n }}</span>
        </div>
        <div class="tgt-recent" v-if="target?.consensus?.recent?.length">
          <div v-for="(r, i) in target.consensus.recent" :key="i" class="recent-row text-3">
            <span class="rr-org">{{ r.org }}</span>
            <span class="rr-rating">{{ r.rating }}</span>
            <span class="rr-target mono">{{ r.target }}</span>
            <span class="rr-date">{{ r.date }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ══ 周期 + 指标工具条 ══ -->
    <div class="chart-toolbar card">
      <div class="period-tabs">
        <button v-for="p in PERIODS" :key="p.key"
          :class="['ptab', period === p.key ? 'active' : '']" @click="setPeriod(p.key)">{{ p.label }}</button>
      </div>
      <div class="tb-spacer"></div>
      <div class="ind-config" v-if="period !== 'fenshi'">
        <button class="ind-btn-toggle" @click="overlayPicker = !overlayPicker">主图指标 ▾</button>
        <div v-if="overlayPicker" class="popover ind-pop" @click.stop>
          <div class="pop-title">主图叠加</div>
          <label v-for="o in OVERLAYS" :key="o.key" class="pop-chk">
            <input type="checkbox" :checked="overlays.includes(o.key)" @change="toggleOverlay(o.key)" />
            <span class="ind-dot" :style="{ background: o.color }"></span>{{ o.label }}
          </label>
        </div>
      </div>
      <div class="ind-config">
        <button class="ind-btn-toggle" @click="subPicker = !subPicker">副图指标 ▾</button>
        <div v-if="subPicker" class="popover ind-pop" @click.stop>
          <div class="pop-title">副图（可多选）</div>
          <label v-for="s in activeSubList" :key="s.key" class="pop-chk">
            <input type="checkbox" :checked="activeSubSel.includes(s.key)" @change="toggleActiveSub(s.key)" />
            {{ s.label }}
          </label>
        </div>
      </div>
    </div>

    <!-- ══ 图表 ══ -->
    <div class="chart-card card">
      <div v-if="loadingBars" class="chart-loading"><span class="spinner"></span><span class="text-2">加载{{ periodLabel }}…</span></div>
      <template v-else>
        <v-chart v-if="period === 'fenshi'" :option="fenshiOption" autoresize :style="{ height: chartHeight + 'px' }" />
        <v-chart v-else :option="klineOption" autoresize :style="{ height: chartHeight + 'px' }" @datazoom="onZoom" />
        <div v-if="!loadingBars && !bars.length" class="chart-empty">暂无{{ periodLabel }}数据</div>
      </template>
    </div>

    <!-- ══ 下方信息 tab ══ -->
    <div class="info-tabs">
      <button v-for="t in INFO_TABS" :key="t.key"
        :class="['itab', infoTab === t.key ? 'active' : '']" @click="switchInfo(t.key)">{{ t.label }}</button>
    </div>

    <!-- 基本面 -->
    <div v-show="infoTab === 'fundamental'" class="info-pane">
      <div class="fund-metrics">
        <div class="fund-card card" v-for="m in fundMetrics" :key="m.label">
          <div class="fund-val" :class="m.cls">{{ m.value }}</div>
          <div class="fund-lbl">{{ m.label }}</div>
          <div class="fund-hint" v-if="m.hint">{{ m.hint }}</div>
        </div>
      </div>
      <div class="section-card card" v-if="fundamental?.holders?.length">
        <div class="section-title">十大股东（最新两期）</div>
        <table class="data-table">
          <thead><tr><th>报告期</th><th>股东名称</th><th>持股数(万)</th><th>持股比例</th><th>变动</th></tr></thead>
          <tbody>
            <tr v-for="h in fundamental.holders" :key="h.name+h.report_date">
              <td class="td-ts">{{ h.report_date }}</td>
              <td class="fw-600">{{ h.name }}</td>
              <td class="mono">{{ h.shares ? (h.shares/10000).toFixed(0) : '-' }}</td>
              <td class="mono">{{ h.pct?.toFixed(2) ?? '-' }}%</td>
              <td :class="h.change?.includes('增') ? 'pos' : h.change?.includes('减') ? 'neg' : ''">{{ h.change }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="section-card card" v-if="fundamental?.billboard?.length">
        <div class="section-title">近期龙虎榜</div>
        <table class="data-table">
          <thead><tr><th>日期</th><th>收盘价</th><th>涨跌幅</th><th>上榜原因</th></tr></thead>
          <tbody>
            <tr v-for="b in fundamental.billboard" :key="b.date+b.reason">
              <td class="td-ts">{{ b.date }}</td><td class="mono">{{ b.close }}</td>
              <td :class="chgClass(b.change_pct)">{{ fmtChg(b.change_pct) }}</td>
              <td class="text-2" style="font-size:12px">{{ b.reason }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="loadingFund" class="card loading-card"><span class="spinner"></span><span class="text-2">加载中...</span></div>
    </div>

    <!-- 机构荐股 -->
    <div v-show="infoTab === 'reports'" class="info-pane">
      <div v-if="loadingReports" class="card loading-card"><span class="spinner"></span><span class="text-2">加载机构研报...</span></div>
      <template v-else-if="repSummary?.count">
        <!-- 概览：篇数 + 最高评级 + 评级分布 -->
        <div class="section-card card">
          <div class="rep-head">
            <span class="section-title" style="margin:0">机构评级</span>
            <span class="rep-sub text-3">近 {{ repSummary.count }} 篇 · 最新 {{ repSummary.latest_date }}</span>
            <div style="flex:1"></div>
            <span v-if="repSummary.top_rating" :class="['rep-toprating', ratingCls(repSummary.top_rating)]">{{ repSummary.top_rating }}</span>
          </div>
          <div class="rating-chips">
            <span v-for="(n, name) in repSummary.ratings" :key="name" :class="['rating-chip2', ratingCls(name)]">{{ name }} <b>{{ n }}</b></span>
          </div>
        </div>

        <!-- 目标价：一致 / 最高 / 最低 -->
        <div class="section-card card" v-if="repSummary.target">
          <div class="section-title">机构目标价</div>
          <div class="rep-targets">
            <div class="rt-item rt-avg">
              <span class="rt-lbl">一致目标价</span>
              <span class="rt-val">{{ repSummary.target.avg }}</span>
              <span v-if="targetUpside(repSummary.target.avg) != null" :class="['rt-up', targetUpside(repSummary.target.avg) >= 0 ? 'up' : 'down']">
                {{ targetUpside(repSummary.target.avg) >= 0 ? '+' : '' }}{{ targetUpside(repSummary.target.avg) }}%
              </span>
            </div>
            <div class="rt-item"><span class="rt-lbl">最高</span><span class="rt-val">{{ repSummary.target.high }}</span></div>
            <div class="rt-item"><span class="rt-lbl">最低</span><span class="rt-val">{{ repSummary.target.low }}</span></div>
            <div class="rt-item"><span class="rt-lbl">给价机构</span><span class="rt-val">{{ repSummary.target.count }}家</span></div>
          </div>
        </div>

        <!-- 一致预期 EPS/PE -->
        <div class="section-card card">
          <div class="section-title">一致预期</div>
          <div class="consensus">
            <div class="cons-item"><span class="ck">今年</span><span class="cv">EPS {{ fmtNum(repSummary.eps_this) }}</span><span class="ck2">PE {{ fmtNum(repSummary.pe_this) }}</span></div>
            <div class="cons-item"><span class="ck">明年</span><span class="cv">EPS {{ fmtNum(repSummary.eps_next) }}</span><span class="ck2">PE {{ fmtNum(repSummary.pe_next) }}</span></div>
            <div class="cons-item"><span class="ck">后年</span><span class="cv">EPS {{ fmtNum(repSummary.eps_next2) }}</span><span class="ck2">PE {{ fmtNum(repSummary.pe_next2) }}</span></div>
          </div>
        </div>

        <!-- 研报列表（点击展开正文） -->
        <div class="section-card card" v-if="reports.length">
          <div class="section-title">近期研报（点击查看内容）</div>
          <div class="rep-list">
            <template v-for="r in reports" :key="r.info_code">
              <div class="rep-row" :class="{ open: expanded === r.info_code }"
                   @click="toggleReport(r.info_code)" title="点击查看研报内容">
                <span class="rep-caret">{{ expanded === r.info_code ? '▾' : '▸' }}</span>
                <span :class="['rep-rating', ratingCls(r.rating)]">{{ r.rating || '—' }}</span>
                <span class="rep-title">{{ r.title }}</span>
                <span class="rep-org">{{ r.org }}</span>
                <span class="rep-tp" v-if="r.target_price">目标 {{ r.target_price }}</span>
                <span class="rep-date mono">{{ r.publish_date }}</span>
              </div>
              <div v-if="expanded === r.info_code" class="rep-body">
                <div v-if="reportText[r.info_code]?.loading" class="rep-body-loading">
                  <span class="spinner"></span><span class="text-3">加载研报正文...</span>
                </div>
                <template v-else>
                  <pre v-if="reportText[r.info_code]?.text" class="rep-text">{{ reportText[r.info_code].text }}</pre>
                  <div v-else class="rep-body-empty text-3">未能提取该研报正文（东财反爬/无 PDF）。</div>
                  <a class="rep-pdf-link" :href="reportText[r.info_code]?.pdf_url || pdfUrl(r.info_code)"
                     target="_blank" rel="noopener">打开 PDF 原文 →</a>
                </template>
              </div>
            </template>
          </div>
        </div>
      </template>
      <div v-else class="card empty-card"><span class="text-3">暂无机构研报覆盖（小盘股常无机构覆盖）</span></div>
    </div>

    <!-- 消息面 -->
    <div v-show="infoTab === 'news'" class="info-pane">
      <div v-if="loadingNews" class="card loading-card"><span class="spinner"></span><span class="text-2">加载公告...</span></div>
      <div v-else-if="newsItems.length" class="news-list card">
        <div class="list-header text-3">{{ overview?.name }} · {{ newsItems.length }} 条公告</div>
        <div v-for="item in newsItems" :key="item.title+item.date" class="news-item" @click="item._exp = !item._exp">
          <div class="ni-row">
            <span :class="['sdot', item.sentiment]"></span>
            <span class="ni-title">{{ item.title }}</span>
            <span class="ni-time">{{ item.date }} {{ item.time }}</span>
          </div>
          <div v-if="item._exp && item.url" class="ni-link"><a :href="item.url" target="_blank" rel="noopener">查看原文 →</a></div>
        </div>
      </div>
      <div v-else class="card empty-card"><span class="text-3">暂无公告数据</span></div>
    </div>

    <!-- AI 深度分析（公司一页纸）-->
    <div v-show="infoTab === 'onepager'" class="info-pane">
      <div class="card onepager-card">
        <div class="op-head">
          <span class="ai-badge">📋 公司一页纸 · 买方视角深度投研</span>
          <span v-if="onepager?.generated_at" class="op-sub text-3">生成于 {{ onepager.generated_at.replace('T', ' ') }}</span>
          <div class="op-spacer"></div>
          <button v-if="onepager || onepagerError" class="btn-ghost btn-sm" :disabled="loadingOnepager" @click="loadOnepager(true)">重新生成</button>
        </div>

        <div v-if="loadingOnepager" class="op-loading">
          <span class="spinner"></span>
          <div class="op-loading-text">
            <div class="text-1">AI 正在精读财务、研报、公告，撰写公司一页纸…</div>
            <div class="text-3">含 11 章节 + 表格 + 逻辑图，通常需 30~90 秒，请稍候</div>
          </div>
        </div>
        <div v-else-if="onepagerError" class="op-error">
          <span class="text-2">{{ onepagerError }}</span>
          <button class="btn-primary btn-sm" @click="loadOnepager(true)">重试</button>
        </div>
        <div v-else-if="onepager?.html" class="op-body markdown-body" v-html="onepager.html"></div>
        <div v-else class="op-empty text-3">点击「AI 深度分析」开始生成</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import VChart from '../charts'
import axios from 'axios'
import { marked } from 'marked'
import * as TA from '../utils/indicators.js'

marked.setOptions({ breaks: true, gfm: true })

// mermaid(~含 cytoscape/katex 等数百KB)按需加载：只有当研报里真出现
// mermaid 代码块时才动态拉库并初始化一次，避免撑大 StockPage 首包。
let _mermaidPromise = null
function loadMermaid() {
  if (!_mermaidPromise) {
    _mermaidPromise = import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose', fontFamily: 'inherit' })
      return mermaid
    })
  }
  return _mermaidPromise
}

const props = defineProps({ symbol: { type: String, required: true } })
const emit = defineEmits(['loaded'])

// A股配色：红涨绿跌（与 global.css 的 --up/--down 令牌保持同值）
const UP = '#dc2626', DOWN = '#16a34a'
const GRID = '#eef1f5', AXIS = '#8a94a6', BG = 'transparent'

// ── 配置（持久化）──────────────────────────────────────────────
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v) } catch { return d } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} },
}

const PERIODS = [
  { key: 'fenshi', label: '分时' }, { key: 'day', label: '日K' },
  { key: 'week', label: '周K' }, { key: 'month', label: '月K' },
  { key: 'm5', label: '5分' }, { key: 'm15', label: '15分' },
  { key: 'm30', label: '30分' }, { key: 'm60', label: '60分' },
]
const OVERLAYS = [
  { key: 'ma5', label: 'MA5', color: '#b45309', fn: b => TA.MA(TA.closes(b), 5) },
  { key: 'ma10', label: 'MA10', color: '#16a34a', fn: b => TA.MA(TA.closes(b), 10) },
  { key: 'ma20', label: 'MA20', color: '#2563eb', fn: b => TA.MA(TA.closes(b), 20) },
  { key: 'ma60', label: 'MA60', color: '#7c3aed', fn: b => TA.MA(TA.closes(b), 60) },
  { key: 'ema12', label: 'EMA12', color: '#db2777', fn: b => TA.EMA(TA.closes(b), 12) },
  { key: 'ema26', label: 'EMA26', color: '#0891b2', fn: b => TA.EMA(TA.closes(b), 26) },
  { key: 'boll', label: 'BOLL', color: '#9333ea' },
  { key: 'sar', label: 'SAR', color: '#ea580c' },
]
const SUBS = [
  { key: 'vol', label: 'VOL' }, { key: 'macd', label: 'MACD' },
  { key: 'kdj', label: 'KDJ' }, { key: 'rsi', label: 'RSI' },
  { key: 'momentum', label: '动能' },
]
// 分时专属副图（量/MACD 与日K同名但数据源不同；量比/偏离为分时特有）
const FENSHI_SUBS = [
  { key: 'fsvol', label: '分时量' }, { key: 'macd', label: 'MACD' },
  { key: 'fsvr', label: '分时量比' }, { key: 'dev', label: '均价偏离' },
]
const ALL_METRICS = [
  { key: 'open', label: '今开' }, { key: 'yesterday_close', label: '昨收' },
  { key: 'high', label: '最高' }, { key: 'low', label: '最低' },
  { key: 'avg_price', label: '均价' },
  { key: 'limit_up', label: '涨停' }, { key: 'limit_down', label: '跌停' },
  { key: 'volume', label: '成交量' }, { key: 'turnover_amount', label: '成交额' },
  { key: 'turnover_rate', label: '换手' }, { key: 'amplitude', label: '振幅' },
  { key: 'vol_ratio', label: '量比' },
  { key: 'w52_high', label: '52周高' }, { key: 'w52_low', label: '52周低' },
  { key: 'pe_ttm', label: 'PE(TTM)' }, { key: 'pe_static', label: 'PE(静)' },
  { key: 'pb', label: 'PB' },
  { key: 'roe', label: 'ROE' }, { key: 'gross_margin', label: '毛利率' },
  { key: 'total_shares', label: '总股本' },
  { key: 'market_cap', label: '总市值' }, { key: 'circ_cap', label: '流通市值' },
]
const INFO_TABS = [
  { key: 'fundamental', label: '基本面' }, { key: 'reports', label: '机构荐股' },
  { key: 'news', label: '消息面' },
  { key: 'onepager', label: 'AI 深度分析' },
]

// 精简默认（同花顺式）：图表默认只挂少量指标，其余靠工具条/⚙ 自己加。
// 默认值变更需 bump SA_PREFS_VER，老用户 localStorage 里的旧默认会被重置一次。
const SA_PREFS_VER = 2
const DEFAULTS = {
  overlays: ['ma5', 'ma10', 'ma20'],
  subs: ['vol'],
  fsSubs: ['fsvol'],
  metrics: ['high', 'low', 'turnover_amount', 'turnover_rate', 'vol_ratio', 'pe_ttm', 'pb', 'market_cap'],
}
if (LS.get('sa_prefs_ver', 0) < SA_PREFS_VER) {
  LS.set('sa_overlays', DEFAULTS.overlays)
  LS.set('sa_subs', DEFAULTS.subs)
  LS.set('sa_fssubs', DEFAULTS.fsSubs)
  LS.set('sa_metrics', DEFAULTS.metrics)
  LS.set('sa_prefs_ver', SA_PREFS_VER)
}

const period = ref(LS.get('sa_period', 'day'))
const overlays = ref(LS.get('sa_overlays', DEFAULTS.overlays))
const subs = ref(LS.get('sa_subs', DEFAULTS.subs))
const fsSubs = ref(LS.get('sa_fssubs', DEFAULTS.fsSubs))
const metricKeys = ref(LS.get('sa_metrics', DEFAULTS.metrics))
const overlayPicker = ref(false), subPicker = ref(false), metricPicker = ref(false)
const infoTab = ref('fundamental')

// 机构荐股（研报）
const reports = ref([])
const repSummary = ref(null)
const loadingReports = ref(false)
const expanded = ref(null)            // 当前展开的研报 info_code
const reportText = ref({})            // info_code -> { loading, text, pdf_url }

function setPeriod(p) { period.value = p; LS.set('sa_period', p); loadBars() }
function toggleOverlay(k) { overlays.value = overlays.value.includes(k) ? overlays.value.filter(x => x !== k) : [...overlays.value, k]; LS.set('sa_overlays', overlays.value) }
function toggleSub(k) { subs.value = subs.value.includes(k) ? subs.value.filter(x => x !== k) : [...subs.value, k]; LS.set('sa_subs', subs.value) }
function toggleFsSub(k) { fsSubs.value = fsSubs.value.includes(k) ? fsSubs.value.filter(x => x !== k) : [...fsSubs.value, k]; LS.set('sa_fssubs', fsSubs.value) }
// 副图工具条按周期切换：分时用 FENSHI_SUBS，其它用 SUBS
const activeSubList = computed(() => period.value === 'fenshi' ? FENSHI_SUBS : SUBS)
const activeSubSel = computed(() => period.value === 'fenshi' ? fsSubs.value : subs.value)
function toggleActiveSub(k) { period.value === 'fenshi' ? toggleFsSub(k) : toggleSub(k) }
function toggleMetric(k) { metricKeys.value = metricKeys.value.includes(k) ? metricKeys.value.filter(x => x !== k) : [...metricKeys.value, k]; LS.set('sa_metrics', metricKeys.value) }

// 点击空白关浮层
function closePopovers() { overlayPicker.value = subPicker.value = metricPicker.value = false }
window.addEventListener('click', closePopovers)
onBeforeUnmount(() => window.removeEventListener('click', closePopovers))

// ── 数据 ───────────────────────────────────────────────────────
const overview = ref(null), fundamental = ref(null), newsItems = ref([])
const momentum = ref(null)
const profile = ref(null), loadingProfile = ref(false)
const bars = ref([])
const fenshi = ref({ points: [], pre_close: null })
const loading = ref(false), loadingBars = ref(false)
const loadingFund = ref(false), loadingNews = ref(false)
const zoomStart = ref(60)

const periodLabel = computed(() => PERIODS.find(p => p.key === period.value)?.label || 'K线')

async function loadOverview() {
  loading.value = true
  try {
    const r = await axios.get(`/api/stock-analysis/${props.symbol}/overview`)
    overview.value = r.data
    emit('loaded', r.data)
  } catch {} finally { loading.value = false }
}

async function loadBars() {
  loadingBars.value = true
  try {
    if (period.value === 'fenshi') {
      const r = await axios.get(`/api/market/minute/${props.symbol}`)
      fenshi.value = { points: r.data.points || [], pre_close: r.data.pre_close ?? overview.value?.yesterday_close }
      bars.value = fenshi.value.points
    } else {
      const r = await axios.get(`/api/market/kline/${props.symbol}`, { params: { period: period.value, count: 320 } })
      bars.value = r.data.bars || []
      zoomStart.value = bars.value.length > 120 ? Math.round((1 - 120 / bars.value.length) * 100) : 0
    }
  } catch { bars.value = [] } finally { loadingBars.value = false }
}

async function loadMomentum() {
  momentum.value = null
  try {
    const r = await axios.get(`/api/stock-analysis/${props.symbol}/momentum`, { params: { days: 180 } })
    momentum.value = r.data
  } catch { momentum.value = null }
}

async function loadFundamental() {
  if (fundamental.value) return
  loadingFund.value = true
  try { const r = await axios.get(`/api/stock-analysis/${props.symbol}/fundamental`); fundamental.value = r.data } catch {} finally { loadingFund.value = false }
}
async function loadNews() {
  if (newsItems.value.length) return
  loadingNews.value = true
  // 消息面只看该股自己的公告（ann_only），不混入个股新闻/快讯
  try { const r = await axios.get(`/api/news/stock/${props.symbol}`, { params: { count: 30, ann_only: true } }); newsItems.value = (r.data.items || []).map(i => ({ ...i, _exp: false })) } catch {} finally { loadingNews.value = false }
}

// 信息栏：行业/概念 + 核心竞争力 + 风险点（轻量 AI，按 symbol+日落库缓存）
async function loadProfile() {
  loadingProfile.value = true
  try { const r = await axios.get(`/api/stock-analysis/${props.symbol}/profile`); profile.value = r.data }
  catch { profile.value = null }
  finally { loadingProfile.value = false }
}

// ── AI 深度分析（公司一页纸）：点开才触发，按 symbol+日期落库缓存，跨天更新 ──
const onepager = ref(null)          // { report, html, generated_at }
const loadingOnepager = ref(false)
const onepagerError = ref('')

async function renderOnepagerMermaid() {
  await nextTick()
  const root = document.querySelector('.op-body')
  if (!root) return
  const blocks = root.querySelectorAll('pre code.language-mermaid, code.language-mermaid')
  if (!blocks.length) return   // 没有 mermaid 图块就不拉库
  const mermaid = await loadMermaid()
  let i = 0
  for (const code of blocks) {
    const pre = code.closest('pre') || code
    const src = code.textContent || ''
    try {
      const { svg } = await mermaid.render(`op-mmd-${Date.now()}-${i++}`, src)
      const div = document.createElement('div')
      div.className = 'mermaid-rendered'
      div.innerHTML = svg
      pre.replaceWith(div)
    } catch (e) { console.warn('mermaid render failed', e) }
  }
}

// 静默预载：只查当天缓存，命中即填充（无需点 Tab 即可即时可看），未命中不触发生成
async function probeOnepager() {
  const code = String(props.symbol || '').toUpperCase().replace(/^(SH|SZ|BJ)/, '').replace(/\.(SH|SZ|BJ)$/, '')
  try {
    const r = await axios.get(`/api/stock-analysis/${code}/onepager`, { params: { cached_only: true } })
    if (r.data?.report) {
      const html = marked.parse(r.data.report)
      onepager.value = { report: r.data.report, html, generated_at: r.data.generated_at || '' }
      await renderOnepagerMermaid()
    }
  } catch {}
}

async function loadOnepager(refresh = false) {
  if (onepager.value && !refresh) return   // 当天已加载，不重复打
  loadingOnepager.value = true
  onepagerError.value = ''
  if (refresh) onepager.value = null
  // onepager 接口要纯 6 位代码，剥掉 SH/SZ/BJ 前后缀
  const code = String(props.symbol || '').toUpperCase().replace(/^(SH|SZ|BJ)/, '').replace(/\.(SH|SZ|BJ)$/, '')
  try {
    const r = await axios.get(`/api/stock-analysis/${code}/onepager`, {
      params: refresh ? { refresh: true } : {},
      timeout: 320000,
    })
    const html = marked.parse(r.data.report || '')
    onepager.value = { report: r.data.report || '', html, generated_at: r.data.generated_at || '' }
    loadingOnepager.value = false
    await renderOnepagerMermaid()
  } catch (e) {
    onepagerError.value = e.response?.data?.detail || 'AI 深度分析生成失败，请重试'
    loadingOnepager.value = false
  }
}
async function loadReports() {
  if (repSummary.value) return  // 已加载过，不重复请求
  // 研报接口要纯 6 位代码，剥掉 SH/SZ/BJ 前后缀
  const code = String(props.symbol || '').toUpperCase().replace(/^(SH|SZ|BJ)/, '').replace(/\.(SH|SZ|BJ)$/, '')
  loadingReports.value = true
  try {
    const [repRes, sumRes] = await Promise.all([
      axios.get(`/api/research/reports/${code}`, { params: { page_size: 20 } }),
      axios.get(`/api/research/summary/${code}`),
    ])
    reports.value = repRes.data.reports || []
    repSummary.value = sumRes.data || {}
  } catch { reports.value = []; repSummary.value = {} }
  finally { loadingReports.value = false }
}
async function toggleReport(infoCode) {
  if (!infoCode) return
  if (expanded.value === infoCode) { expanded.value = null; return }  // 收起
  expanded.value = infoCode
  if (reportText.value[infoCode]) return  // 已取过，复用缓存
  reportText.value = { ...reportText.value, [infoCode]: { loading: true, text: '', pdf_url: pdfUrl(infoCode) } }
  try {
    const { data } = await axios.get(`/api/research/report-text/${infoCode}`)
    reportText.value = { ...reportText.value, [infoCode]: { loading: false, text: data.text || '', pdf_url: data.pdf_url || pdfUrl(infoCode) } }
  } catch {
    reportText.value = { ...reportText.value, [infoCode]: { loading: false, text: '', pdf_url: pdfUrl(infoCode) } }
  }
}
function switchInfo(t) {
  infoTab.value = t
  if (t === 'fundamental') loadFundamental()
  if (t === 'news') loadNews()
  if (t === 'reports') loadReports()
  if (t === 'onepager') loadOnepager()
}

function onZoom(e) { if (e?.batch?.[0]) zoomStart.value = e.batch[0].start }

// ── 图表高度（主图 + 副图栈）─────────────────────────────────
const chartHeight = computed(() => {
  if (period.value === 'fenshi') return 360
  return 380 + subs.value.length * 110
})

// ── K线主图 + 副图 ─────────────────────────────────────────────
const klineOption = computed(() => {
  const b = bars.value
  if (!b.length) return {}
  const dates = b.map(x => x.date || x.datetime)
  const candle = b.map(x => [x.open, x.close, x.low, x.high])

  // 布局：主图 + N 个副图
  const nSub = subs.value.length
  const topPad = 8, bottomPad = 42, gap = 2
  const mainH = nSub ? 56 : 78          // 百分比
  const subH = nSub ? (100 - mainH - 8) / nSub : 0
  const grids = [{ left: 56, right: 16, top: `${topPad}px`, height: `${mainH}%` }]
  const xAxes = [{ type: 'category', data: dates, gridIndex: 0, boundaryGap: true,
    axisLine: { lineStyle: { color: GRID } }, axisLabel: { show: nSub === 0, color: AXIS, fontSize: 10 } }]
  const yAxes = [{ scale: true, gridIndex: 0, splitLine: { lineStyle: { color: GRID } },
    axisLabel: { color: AXIS, fontSize: 10 }, axisLine: { show: false } }]

  const series = [{
    name: 'K', type: 'candlestick', data: candle, xAxisIndex: 0, yAxisIndex: 0,
    itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
    markPoint: momentumMarkPoint(b),
  }]

  // 主图叠加
  for (const o of OVERLAYS) {
    if (!overlays.value.includes(o.key)) continue
    if (o.key === 'boll') {
      const bb = TA.BOLL(TA.closes(b))
      series.push(line('BOLL上', bb.upper, o.color, 0, 0, 'dashed'))
      series.push(line('BOLL中', bb.mid, o.color, 0, 0))
      series.push(line('BOLL下', bb.lower, o.color, 0, 0, 'dashed'))
    } else if (o.key === 'sar') {
      series.push({ name: 'SAR', type: 'scatter', data: TA.SAR(b), xAxisIndex: 0, yAxisIndex: 0,
        symbolSize: 3, itemStyle: { color: o.color } })
    } else {
      series.push(line(o.label, o.fn(b), o.color, 0, 0))
    }
  }

  // 副图
  subs.value.forEach((sk, i) => {
    const gi = i + 1
    const top = topPad + mainH + 4 + i * (subH + 1)
    grids.push({ left: 56, right: 16, top: `${top}%`, height: `${subH}%` })
    xAxes.push({ type: 'category', data: dates, gridIndex: gi, boundaryGap: true,
      axisLine: { lineStyle: { color: GRID } },
      axisLabel: { show: i === nSub - 1, color: AXIS, fontSize: 10 } })
    const isLast = i === nSub - 1
    yAxes.push({ scale: true, gridIndex: gi, splitNumber: 2,
      splitLine: { show: false }, axisLabel: { color: AXIS, fontSize: 9 }, axisLine: { show: false } })
    addSub(sk, gi, series, b)
  })

  return {
    backgroundColor: BG, animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
      backgroundColor: '#fff', borderColor: GRID, textStyle: { color: '#1e293b', fontSize: 11 },
      formatter: klineTooltip },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: grids, xAxis: xAxes, yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: xAxes.map((_, i) => i), start: zoomStart.value, end: 100 },
      { type: 'slider', xAxisIndex: xAxes.map((_, i) => i), height: 16, bottom: 6, start: zoomStart.value, end: 100 },
    ],
    series,
  }
})

function line(name, data, color, gi, yi, dash) {
  return { name, type: 'line', data, xAxisIndex: gi, yAxisIndex: yi, showSymbol: false, smooth: false,
    lineStyle: { color, width: 1, type: dash || 'solid' } }
}

// K线 tooltip：把 candlestick 默认的 open/close/lowest/highest 英文换成中文
function klineTooltip(ps) {
  if (!ps || !ps.length) return ''
  let html = `<div style="font-weight:600;margin-bottom:2px">${ps[0].axisValue}</div>`
  for (const p of ps) {
    if (p.seriesName === 'K') {
      // candlestick data: [-, open, close, low, high]
      const d = p.data
      const open = d[1], close = d[2], low = d[3], high = d[4]
      const up = close >= open
      const c = up ? UP : DOWN
      // 涨幅：相对上一根 K 线收盘（首根用开盘价兜底）
      const prev = bars.value[p.dataIndex - 1]
      const base = prev?.close ?? open
      const chg = base ? (close - base) / base * 100 : 0
      html += `<div style="color:${c}">`
        + `开 <b>${fmtPrice(open)}</b>&nbsp; 收 <b>${fmtPrice(close)}</b><br/>`
        + `高 <b>${fmtPrice(high)}</b>&nbsp; 低 <b>${fmtPrice(low)}</b><br/>`
        + `涨幅 <b>${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</b>`
        + `</div>`
    } else if (p.value != null && !Array.isArray(p.value)) {
      html += `<div>${p.marker}${p.seriesName} <b>${typeof p.value === 'number' ? p.value.toFixed(2) : p.value}</b></div>`
    }
  }
  return html
}

function addSub(key, gi, series, b) {
  if (key === 'vol') {
    series.push({ name: '量', type: 'bar', xAxisIndex: gi, yAxisIndex: gi, data: b.map(x => x.volume),
      itemStyle: { color: p => (b[p.dataIndex].close >= b[p.dataIndex].open) ? UP + '99' : DOWN + '99' } })
  } else if (key === 'macd') {
    const m = TA.MACD(TA.closes(b))
    series.push({ name: 'MACD', type: 'bar', xAxisIndex: gi, yAxisIndex: gi, data: m.hist,
      itemStyle: { color: p => p.value >= 0 ? UP : DOWN } })
    series.push(line('DIF', m.dif, '#2563eb', gi, gi))
    series.push(line('DEA', m.dea, '#b45309', gi, gi))
  } else if (key === 'kdj') {
    const k = TA.KDJ(b)
    series.push(line('K', k.k, '#2563eb', gi, gi))
    series.push(line('D', k.d, '#b45309', gi, gi))
    series.push(line('J', k.j, '#db2777', gi, gi))
  } else if (key === 'rsi') {
    series.push(line('RSI6', TA.RSI(TA.closes(b), 6), '#2563eb', gi, gi))
    series.push(line('RSI12', TA.RSI(TA.closes(b), 12), '#b45309', gi, gi))
  } else if (key === 'momentum') {
    const score = momentumScoreByDate(b)
    series.push({ name: '动能', type: 'line', data: score, xAxisIndex: gi, yAxisIndex: gi,
      showSymbol: false, smooth: true, lineStyle: { color: '#7c3aed', width: 1.4 },
      areaStyle: { color: '#7c3aed18' },
      markLine: { silent: true, symbol: 'none',
        label: { color: AXIS, fontSize: 9, formatter: p => p.value },
        data: [
          { yAxis: 50, lineStyle: { color: '#cbd5e1', type: 'dashed' } },
          { yAxis: momentum.value?.config?.buy_threshold ?? 62, lineStyle: { color: '#2563eb88', type: 'dashed' } },
          { yAxis: momentum.value?.config?.sell_threshold ?? 38, lineStyle: { color: '#f59e0b88', type: 'dashed' } },
        ] } })
  }
}

// K 线上的动能买卖点标注（仅日K，信号为日级别）
function momentumMarkPoint(b) {
  const sig = momentum.value?.signals
  if (period.value !== 'day' || !sig?.length) return undefined
  const idx = new Map()
  b.forEach((x, i) => idx.set(String(x.date || x.datetime), i))
  const data = []
  for (const s of sig) {
    const i = idx.get(String(s.date))
    if (i == null) continue
    const isBuy = s.type === 'buy'
    // 买=蓝、卖=金；与红涨绿跌的 K 线蜡烛完全区分，避免撞色。
    // 买点贴在 K 线下方、卖点贴在上方，符合"低买高卖"直觉。
    const color = isBuy ? '#2563eb' : '#f59e0b'
    data.push({
      name: isBuy ? '买入' : '卖出',
      coord: [i, isBuy ? b[i].low : b[i].high],
      symbol: 'pin',
      symbolRotate: isBuy ? 180 : 0,
      symbolSize: [26, 30],
      symbolOffset: [0, isBuy ? 18 : -18],
      itemStyle: { color, borderColor: '#fff', borderWidth: 1.5,
        shadowColor: 'rgba(0,0,0,.25)', shadowBlur: 3 },
      label: { show: true, color: '#fff', fontSize: 11, fontWeight: 800,
        offset: [0, isBuy ? 4 : -4],
        formatter: () => isBuy ? 'B' : 'S' },
    })
  }
  return data.length ? { data, silent: true } : undefined
}

// 把 /momentum 的逐日 score 对齐到当前显示的 K 线日期上（两端取数 days 不同）
function momentumScoreByDate(b) {
  const m = momentum.value
  if (!m?.dates?.length || !m?.score?.length) return b.map(() => null)
  const map = new Map()
  m.dates.forEach((d, i) => { if (d != null) map.set(String(d), m.score[i]) })
  return b.map(x => { const v = map.get(String(x.date || x.datetime)); return v == null ? null : v })
}

// ── 分时图 ─────────────────────────────────────────────────────
// 分时副图：MACD 基于价格序列；分时量比=当前分钟量/当日累计均量(简化口径，
// 真5日同时刻量比需分时历史落库，成本高)；均价偏离=(价-均价)/均价。
function _fenshiSubData(key, pts, prices, avgs, base) {
  if (key === 'fsvol') {
    return [{ name: '分时量', type: 'bar', data: pts.map(p => p.volume),
      itemStyle: { color: p => (prices[p.dataIndex] >= base ? UP + '99' : DOWN + '99') } }]
  }
  if (key === 'macd') {
    // TA 工具按 close 取值，分时点用 price 当 close。
    const m = TA.MACD(pts.map(p => p.price))
    return [
      { name: 'MACD', type: 'bar', data: m.hist, itemStyle: { color: p => p.value >= 0 ? UP : DOWN } },
      { name: 'DIF', type: 'line', data: m.dif, showSymbol: false, lineStyle: { color: '#2563eb', width: 1 } },
      { name: 'DEA', type: 'line', data: m.dea, showSymbol: false, lineStyle: { color: '#b45309', width: 1 } },
    ]
  }
  if (key === 'fsvr') {
    let cum = 0
    const vr = pts.map((p, i) => {
      cum += (p.volume || 0)
      const meanSoFar = cum / (i + 1)
      return meanSoFar > 0 ? +((p.volume || 0) / meanSoFar).toFixed(2) : 0
    })
    return [
      { name: '分时量比', type: 'line', data: vr, showSymbol: false, lineStyle: { color: '#7c3aed', width: 1 },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#cbd5e1', type: 'dashed' },
          data: [{ yAxis: 1 }], label: { formatter: '1', color: AXIS, fontSize: 9 } } },
    ]
  }
  if (key === 'dev') {
    const dev = pts.map((p, i) => avgs[i] > 0 ? +(((p.price - avgs[i]) / avgs[i]) * 100).toFixed(2) : 0)
    return [
      { name: '均价偏离', type: 'line', data: dev, showSymbol: false, lineStyle: { color: '#0891b2', width: 1 },
        areaStyle: { color: '#0891b220' },
        markLine: { silent: true, symbol: 'none', lineStyle: { color: '#cbd5e1', type: 'dashed' },
          data: [{ yAxis: 0 }] } },
    ]
  }
  return []
}

const fenshiOption = computed(() => {
  const pts = fenshi.value.points
  if (!pts.length) return {}
  const base = fenshi.value.pre_close || pts[0]?.price || 0
  const times = pts.map(p => p.time)
  const prices = pts.map(p => p.price)
  const avgs = pts.map(p => p.avg)
  const isUp = (prices[prices.length - 1] ?? base) >= base
  const range = Math.max(...prices.map(p => Math.abs(p - base)), base * 0.001)
  const main = isUp ? UP : DOWN

  // 布局：主图(价+均价) + N 个分时副图
  const active = fsSubs.value
  const nSub = active.length
  const topPad = 10, gap = 4
  const mainH = nSub ? 56 : 80
  const subH = nSub ? (100 - mainH - 14) / nSub : 0

  const grids = [{ left: 56, right: 56, top: `${topPad}px`, height: `${mainH}%` }]
  const xAxis = [{ type: 'category', data: times, gridIndex: 0, boundaryGap: false,
    axisLabel: { show: nSub === 0, color: AXIS, fontSize: 9 }, axisLine: { lineStyle: { color: GRID } } }]
  const yAxis = [{ scale: false, min: +(base - range).toFixed(2), max: +(base + range).toFixed(2), gridIndex: 0,
    splitLine: { lineStyle: { color: GRID } }, axisLabel: { color: AXIS, fontSize: 10 } }]
  const series = [
    { name: '价格', type: 'line', data: prices, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
      lineStyle: { color: main, width: 1.3 },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: main + '33' }, { offset: 1, color: main + '00' }] } },
      markLine: { silent: true, symbol: 'none', lineStyle: { color: '#cbd5e1' }, data: [{ yAxis: base }],
        label: { formatter: `昨收 ${base}`, color: AXIS, fontSize: 9, position: 'insideStartTop' } } },
    { name: '均价', type: 'line', data: avgs, xAxisIndex: 0, yAxisIndex: 0, showSymbol: false, lineStyle: { color: '#b45309', width: 1 } },
  ]

  active.forEach((sk, i) => {
    const gi = i + 1
    const top = topPad / 5 + mainH + gap + i * (subH + 1.5)
    grids.push({ left: 56, right: 56, top: `${top}%`, height: `${subH}%` })
    xAxis.push({ type: 'category', data: times, gridIndex: gi, boundaryGap: false,
      axisLabel: { show: i === nSub - 1, color: AXIS, fontSize: 9 }, axisLine: { lineStyle: { color: GRID } } })
    yAxis.push({ scale: true, gridIndex: gi, splitNumber: 2, splitLine: { show: false },
      axisLabel: { color: AXIS, fontSize: 9 }, axisLine: { show: false } })
    for (const s of _fenshiSubData(sk, pts, prices, avgs, base)) {
      series.push({ ...s, xAxisIndex: gi, yAxisIndex: gi })
    }
  })

  return {
    backgroundColor: BG, animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
      backgroundColor: '#fff', borderColor: GRID, textStyle: { color: '#1e293b', fontSize: 11 },
      formatter: ps => {
        const pp = ps.find(x => x.seriesName === '价格'); if (!pp) return ''
        const chg = ((pp.value - base) / base * 100)
        let s = `${pp.name}<br/>价 <b style="color:${pp.value>=base?UP:DOWN}">${pp.value}</b> (${chg>=0?'+':''}${chg.toFixed(2)}%)<br/>均 <b style="color:#b45309">${ps.find(x=>x.seriesName==='均价')?.value ?? '-'}</b>`
        const extra = ps.filter(x => ['分时量比', '均价偏离'].includes(x.seriesName))
        for (const e of extra) s += `<br/>${e.seriesName} <b>${e.value}${e.seriesName === '均价偏离' ? '%' : ''}</b>`
        return s
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: grids, xAxis, yAxis, series,
  }
})

// ── 动能买卖点快照 ─────────────────────────────────────────────
const STATE_MAP = {
  buy: { label: '买入', cls: 'st-buy' }, hold: { label: '持有', cls: 'st-hold' },
  reduce: { label: '减仓', cls: 'st-reduce' }, sell: { label: '卖出', cls: 'st-sell' },
}
const DIR_MAP = { accelerating: '加速上行', rising: '上行', flat: '走平', falling: '下行' }
const mom = computed(() => {
  const c = momentum.value?.current
  if (!c) return null
  const st = STATE_MAP[c.state] || { label: '—', cls: 'st-hold' }
  const score = c.score
  // 动能分用蓝(强)/金(弱)/灰(中)，与红涨绿跌的价格色区分
  const scoreCls = score == null ? '' : score >= 62 ? 'sc-strong' : score <= 38 ? 'sc-weak' : 'sc-mid'
  return {
    ...c, score, scoreCls,
    stateLabel: st.label, stateCls: st.cls,
    dirLabel: DIR_MAP[c.direction] || '—',
  }
})
const risk = computed(() => momentum.value?.risk || null)
const target = computed(() => momentum.value?.target || null)

// 今日首次买入信号：最后一个动能信号是 buy，且其日期 == 最新一根日K日期
// （即买点穿越就发生在今天，而非几天前已买点持有中）。用于页顶醒目提示。
const freshBuy = computed(() => {
  const m = momentum.value
  const sigs = m?.signals
  const dates = m?.dates
  if (!Array.isArray(sigs) || !sigs.length || !Array.isArray(dates) || !dates.length) return null
  const last = sigs[sigs.length - 1]
  if (!last || last.type !== 'buy') return null
  const lastBar = String(dates[dates.length - 1] ?? '')
  if (!lastBar || String(last.date ?? '') !== lastBar) return null
  const c = momentum.value?.current || {}
  return {
    date: lastBar,
    buy_price: c.buy_price, stop_price: c.stop_price, target_price: c.target_price,
    stop_pct: c.stop_pct, target_pct: c.target_pct, score: c.score,
  }
})

// 52周高/低：从已加载的日K(bars)算近 250 个交易日的最高/最低
const week52 = computed(() => {
  const b = bars.value
  if (!b || !b.length || period.value === 'fenshi') return { high: null, low: null }
  const window = b.slice(-250)
  const highs = window.map(x => x.high).filter(v => v != null)
  const lows = window.map(x => x.low).filter(v => v != null)
  return {
    high: highs.length ? Math.max(...highs) : null,
    low: lows.length ? Math.min(...lows) : null,
  }
})

// ── 行情头指标 ─────────────────────────────────────────────────
const shownMetrics = computed(() => {
  const o = overview.value; if (!o) return []
  return metricKeys.value.map(k => {
    const def = ALL_METRICS.find(m => m.key === k); if (!def) return null
    let v, cls = ''
    if (k === 'w52_high') v = week52.value.high
    else if (k === 'w52_low') v = week52.value.low
    else v = o[k]

    if (k === 'turnover_amount') v = fmtAmt(v)
    else if (k === 'market_cap' || k === 'circ_cap') v = fmtAmt(v)
    else if (k === 'volume') v = v != null ? fmtVol(v) : '-'
    else if (k === 'total_shares') v = v != null ? (v / 1e8).toFixed(2) + '亿' : '-'
    else if (k === 'turnover_rate' || k === 'amplitude' || k === 'roe' || k === 'gross_margin') v = v != null ? Number(v).toFixed(2) + '%' : '-'
    else if (k === 'vol_ratio') v = v != null ? Number(v).toFixed(2) : '-'
    else v = v != null ? Number(v).toFixed(2) : '-'

    if (k === 'high' || k === 'limit_up' || k === 'w52_high') cls = 'pos'
    if (k === 'low' || k === 'limit_down' || k === 'w52_low') cls = 'neg'
    return { key: k, label: def.label, value: v, cls }
  }).filter(Boolean)
})

const fundMetrics = computed(() => {
  const o = overview.value; if (!o) return []
  return [
    { label: '市盈率PE(TTM)', value: o.pe_ttm?.toFixed(2) ?? '-', cls: o.pe_ttm == null ? '' : o.pe_ttm < 15 ? 'pos' : o.pe_ttm > 60 ? 'neg' : '', hint: o.pe_ttm == null ? '' : o.pe_ttm < 15 ? '低估' : o.pe_ttm > 60 ? '高估' : '合理' },
    { label: '市净率PB', value: o.pb?.toFixed(2) ?? '-', cls: o.pb == null ? '' : o.pb < 1 ? 'pos' : o.pb > 5 ? 'neg' : '', hint: o.pb == null ? '' : o.pb < 1 ? '破净' : '' },
    { label: 'ROE', value: o.roe != null ? o.roe + '%' : '-', cls: o.roe == null ? '' : o.roe > 15 ? 'pos' : o.roe > 0 ? '' : 'neg', hint: o.roe == null ? '' : o.roe > 20 ? '优秀' : o.roe > 10 ? '良好' : o.roe > 0 ? '一般' : '亏损' },
    { label: '毛利率', value: o.gross_margin != null ? o.gross_margin.toFixed(1) + '%' : '-' },
    { label: '总股本(亿)', value: o.total_shares ? (o.total_shares / 1e8).toFixed(2) : '-' },
    { label: '总市值', value: fmtAmt(o.market_cap) },
    { label: '流通市值', value: fmtAmt(o.circ_cap) },
  ]
})

// ── helpers ────────────────────────────────────────────────────
function fmtPrice(v) { return (v == null || v === 0) ? '-' : Number(v).toFixed(2) }
function fmtChg(v) { return v == null ? '-' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }
function fmtSigned(v) { return v == null ? '' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) }
function fmtAmt(v) { if (!v) return '-'; if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿'; if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'; if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'; return String(Math.round(v)) }
// 成交量单位为手；按手→万手/亿手折算
function fmtVol(v) { if (!v) return '-'; if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿手'; if (v >= 1e4) return (v / 1e4).toFixed(1) + '万手'; return Math.round(v) + '手' }
function chgClass(v) { return v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '' }

// 机构荐股 helpers
function fmtNum(v) { return (v == null || v === '') ? '-' : Number(v).toFixed(2) }
function pdfUrl(infoCode) { return `https://pdf.dfcfw.com/pdf/H3_${infoCode}_1.pdf` }
function ratingCls(r) {
  const s = String(r || '')
  if (/买入|增持|强烈推荐|推荐|跑赢|outperform|buy/i.test(s)) return 'buy'
  if (/卖出|减持|回避|跑输|underperform|sell/i.test(s)) return 'sell'
  return 'hold'
}
// 一致目标价较当前价的上涨空间(%)
function targetUpside(tp) {
  const cur = overview.value?.price ?? overview.value?.yesterday_close
  if (!cur || !tp) return null
  return Math.round((tp / cur - 1) * 1000) / 10
}

// ── init ───────────────────────────────────────────────────────
watch(() => props.symbol, sym => {
  if (!sym) return
  overview.value = null; fundamental.value = null; newsItems.value = []; bars.value = []; momentum.value = null
  onepager.value = null; onepagerError.value = ''; repSummary.value = null; reports.value = []
  profile.value = null
  expanded.value = null; reportText.value = {}
  loadOverview(); loadBars(); loadFundamental(); loadMomentum()
  loadProfile()        // 信息栏速览
  loadReports()        // 信息栏的机构荐股速览（也供机构荐股 Tab 复用）
  probeOnepager()      // 当天若已生成 AI 深度分析则即时可看
  if (infoTab.value === 'onepager') loadOnepager()
}, { immediate: true })
</script>

<style scoped>
.sad { display: flex; flex-direction: column; gap: 12px; }
.card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-xl); }
.up, .pos { color: var(--up); }
.down, .neg { color: var(--down); }

/* 今日首次买入信号提示条 */
.fresh-buy { padding: 11px 16px; display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: linear-gradient(90deg, rgba(220,38,38,.12), rgba(220,38,38,.03));
  border: 1px solid rgba(220,38,38,.35); }
.fb-badge { font-weight: 800; font-size: 14px; color: #dc2626; }
.fb-date { font-size: 12px; color: var(--text-3); }
.fb-levels { display: flex; gap: 14px; flex-wrap: wrap; margin-left: auto; }
.fb-levels em { font-style: normal; font-size: 13px; font-weight: 600; color: var(--text-2); }
.fb-levels em.up { color: #dc2626; }
.fb-levels em.down { color: var(--down); }
.fb-levels em i { font-style: normal; opacity: .8; }

/* 信息栏：行业/概念 + 核心竞争力 + 风险点 + 机构荐股 */
.info-card { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.ic-loading { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.ic-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.ic-chip { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--bg-elevated); color: var(--text-2); border: 1px solid var(--border); }
.ic-chip.ic-industry { background: rgba(37,99,235,.1); color: #2563eb; border-color: rgba(37,99,235,.3); font-weight: 600; }
.ic-chip.ic-top { background: rgba(124,58,237,.12); color: #7c3aed; border-color: rgba(124,58,237,.35); font-weight: 700; }
.ic-reason { font-size: 12px; line-height: 1.5; }
.ic-reason b { color: #7c3aed; }
.ic-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.ic-col { background: var(--bg-elevated); border-radius: var(--radius-md); padding: 10px 12px; }
.ic-col-title { font-size: 11px; font-weight: 700; letter-spacing: .04em; margin-bottom: 6px; }
.ic-strength .ic-col-title { color: var(--up); }
.ic-risk .ic-col-title { color: var(--down); }
.ic-col ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.ic-col li { position: relative; padding-left: 14px; font-size: 12.5px; line-height: 1.5; color: var(--text-1); }
.ic-col li::before { content: ''; position: absolute; left: 2px; top: 8px; width: 5px; height: 5px; border-radius: 50%; }
.ic-strength li::before { background: var(--up); }
.ic-risk li::before { background: var(--down); }
.ic-rep { border-top: 1px solid var(--border); padding-top: 10px; }
.ic-rep-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.ic-rep-body { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.ic-rep-tgt { font-size: 12px; color: var(--text-2); margin-left: auto; }
.ic-rep-tgt b { font-family: var(--font-mono); color: var(--text-1); font-size: 14px; }
.ic-rep-tgt em { font-style: normal; font-weight: 700; margin-left: 4px; }
@media (max-width: 720px) { .ic-cols { grid-template-columns: 1fr; } .ic-rep-tgt { margin-left: 0; flex-basis: 100%; } }

/* 动能买卖点快照 */
.mom-card { padding: 12px 16px; display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.mom-gauge { display: flex; align-items: center; gap: 10px; }
.mom-score { font-size: 30px; font-weight: 800; line-height: 1; min-width: 56px; text-align: center; color: var(--text-1); }
.mom-score.sc-strong { color: #2563eb; }
.mom-score.sc-weak { color: #f59e0b; }
.mom-score.sc-mid { color: var(--text-2, #64748b); }
.mom-meta { display: flex; flex-direction: column; gap: 4px; }
.mom-state { font-size: 13px; font-weight: 700; padding: 2px 10px; border-radius: 999px; align-self: flex-start; }
.st-buy { background: rgba(37,99,235,.12); color: #2563eb; }
.st-sell { background: rgba(245,158,11,.14); color: #d97706; }
.st-reduce { background: rgba(217,119,6,.12); color: #d97706; }
.st-hold { background: rgba(138,148,166,.14); color: var(--text-3); }
.mom-dir { font-size: 12px; }
.mom-levels { display: flex; gap: 18px; flex-wrap: wrap; }
.mlv { display: flex; flex-direction: column; gap: 2px; }
.mlv-lbl { font-size: 11px; color: var(--text-3); font-style: normal; }
.mlv-val { font-size: 15px; font-weight: 700; font-family: var(--font-mono); display: flex; align-items: baseline; gap: 4px; }
.mlv-val em { font-size: 11px; font-weight: 600; font-style: normal; opacity: .8; }
.mom-hint { font-size: 11px; margin-left: auto; }

/* 风险预警 + 目标价分析 */
.rt-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
@media (max-width: 720px) { .rt-row { grid-template-columns: 1fr; } }
.rt-card { padding: 12px 16px; }
.rt-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.rt-title { font-size: 14px; font-weight: 700; color: var(--text-1); }
.rt-level { font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 999px; }
.rl-低 { background: rgba(22,163,74,.12); color: var(--down); }
.rl-中 { background: rgba(245,158,11,.14); color: #d97706; }
.rl-高 { background: rgba(220,38,38,.12); color: var(--up); }
.risk-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.risk-item { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; line-height: 1.4; color: var(--text-2); }
.ri-dot { width: 7px; height: 7px; border-radius: 50%; margin-top: 5px; flex: none; }
.ri-dot.rl-低 { background: var(--down); } .ri-dot.rl-中 { background: #d97706; } .ri-dot.rl-高 { background: var(--up); }
.ri-msg { flex: 1; }
.rt-empty { font-size: 13px; padding: 6px 0; }
.rt-metrics { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 12px; }
.tgt-grid { display: flex; gap: 24px; flex-wrap: wrap; }
.tgt-block { display: flex; flex-direction: column; gap: 2px; }
.tgt-lbl { font-size: 12px; }
.tgt-val { font-size: 20px; font-weight: 800; font-family: var(--font-mono); color: var(--text-1); display: flex; align-items: baseline; gap: 6px; }
.tgt-val em { font-size: 13px; font-weight: 700; font-style: normal; }
.tgt-sub { font-size: 11px; }
.tgt-ratings { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.rating-chip { font-size: 11px; padding: 2px 8px; border-radius: 6px; background: var(--bg-subtle, #f1f5f9); color: var(--text-2); }
.tgt-recent { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.recent-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 10px; font-size: 12px; align-items: center; }
.rr-rating { color: #2563eb; } .rr-target { font-weight: 700; color: var(--text-1); } .rr-date { color: var(--text-3); }

/* 行情头 */
.quote-head { padding: 14px 18px; }
.qh-main { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
.qh-title { display: flex; align-items: baseline; gap: 8px; }
.qh-name { font-size: 20px; font-weight: 800; color: var(--text-1); }
.qh-code { font-size: 13px; color: var(--text-3); font-family: var(--font-mono); }
.qh-market { font-size: 11px; color: var(--text-3); }
.qh-price-row { display: flex; align-items: baseline; gap: 12px; }
.qh-price { font-size: 30px; font-weight: 800; font-family: var(--font-mono); }
.qh-chg { font-size: 15px; font-weight: 700; font-family: var(--font-mono); }
.qh-metrics { position: relative; display: flex; flex-wrap: wrap; gap: 8px 22px; margin-top: 12px; align-items: center; }
.qh-metric { display: flex; align-items: baseline; gap: 6px; font-size: 12px; }
.qm-lbl { font-style: normal; color: var(--text-3); }
.qm-val { font-weight: 700; color: var(--text-1); font-family: var(--font-mono); }
.qh-gear { margin-left: auto; background: var(--bg-elevated); border: 1px solid var(--border); color: var(--text-3); border-radius: var(--radius-md); width: 26px; height: 24px; cursor: pointer; }
.qh-gear:hover { color: var(--accent); }

/* 周期 + 指标工具条 */
.chart-toolbar { display: flex; align-items: center; gap: 10px; padding: 8px 12px; flex-wrap: wrap; }
.period-tabs { display: flex; gap: 2px; }
.ptab { padding: 5px 13px; font-size: 13px; color: var(--text-2); background: transparent; border: none; border-radius: var(--radius-sm); cursor: pointer; }
.ptab:hover { background: var(--bg-elevated); color: var(--text-1); }
.ptab.active { background: var(--accent); color: #fff; font-weight: 600; }
.tb-spacer { flex: 1; }
.ind-config { position: relative; }
.ind-btn-toggle { font-size: 12px; color: var(--text-2); background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 5px 12px; cursor: pointer; }
.ind-btn-toggle:hover { color: var(--text-1); border-color: var(--border-light); }

/* 浮层 */
.popover { position: absolute; top: calc(100% + 6px); right: 0; z-index: 30;
  background: var(--bg-elevated); border: 1px solid var(--border-light); border-radius: var(--radius-md);
  box-shadow: 0 10px 30px rgba(15,23,42,0.18); padding: 10px 12px; min-width: 150px; }
.metric-pop { right: 0; min-width: 280px; }
.pop-title { font-size: 11px; color: var(--text-3); font-weight: 700; margin-bottom: 8px; }
.pop-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }
.pop-chk { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-1); cursor: pointer; padding: 3px 0; }
.pop-chk input { accent-color: var(--accent); }
.ind-dot { width: 10px; height: 3px; border-radius: 2px; display: inline-block; }

/* 图表 */
.chart-card { padding: 8px 8px 4px; }
.chart-loading, .chart-empty { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 60px; color: var(--text-3); font-size: 13px; }

/* 信息 tab */
.info-tabs { display: flex; gap: 4px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 4px; width: fit-content; }
.itab { padding: 6px 18px; border-radius: calc(var(--radius-md) - 2px); font-size: 13px; color: var(--text-2); background: transparent; border: none; cursor: pointer; }
.itab.active { background: var(--accent); color: #fff; }
.itab:hover:not(.active) { background: var(--bg-elevated); color: var(--text-1); }
.info-pane { display: flex; flex-direction: column; gap: 12px; }

/* 基本面 */
.fund-metrics { display: flex; gap: 12px; flex-wrap: wrap; }
.fund-card { padding: 14px 18px; min-width: 110px; text-align: center; }
.fund-val { font-size: 20px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.fund-lbl { font-size: 11px; color: var(--text-3); margin-top: 3px; }
.fund-hint { font-size: 11px; color: var(--text-2); margin-top: 2px; }
.section-card { padding: 14px 16px; }
.section-title { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 10px; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { color: var(--text-3); font-weight: 600; text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); font-size: 11px; }
.data-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text-1); }
.data-table tr:last-child td { border-bottom: none; }
.td-ts { font-size: 12px; color: var(--text-3); font-family: var(--font-mono); }
.fw-600 { font-weight: 600; } .mono { font-family: var(--font-mono); }

/* 消息面 */
.news-list { overflow: hidden; }
.list-header { padding: 8px 14px 6px; border-bottom: 1px solid var(--border); font-size: 12px; }
.news-item { padding: 9px 14px; border-bottom: 1px solid var(--border); cursor: pointer; }
.news-item:last-child { border-bottom: none; }
.news-item:hover { background: var(--bg-hover); }
.ni-row { display: flex; align-items: flex-start; gap: 8px; }
.ni-title { flex: 1; font-size: 13px; color: var(--text-1); line-height: 1.4; }
.ni-time { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); white-space: nowrap; }
.ni-link { padding-left: 15px; margin-top: 4px; }
.ni-link a { font-size: 11px; color: var(--text-3); }
.sdot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
.sdot.positive { background: var(--up); } .sdot.negative { background: var(--down); } .sdot.neutral { background: var(--text-3); }

/* AI */
.ai-start { padding: 40px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 16px; }
.ai-result { padding: 20px; }
.ai-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ai-badge { font-size: 12px; font-weight: 700; color: #7c3aed; background: #8b5cf618; padding: 4px 10px; border-radius: 6px; }
.ai-body { font-size: 13px; line-height: 1.8; color: var(--text-1); }
.ai-body :deep(strong) { font-weight: 700; color: var(--accent); }
.ai-body :deep(h4) { font-size: 13px; font-weight: 700; margin: 10px 0 4px; }

.loading-card { display: flex; align-items: center; gap: 10px; padding: 24px; }
.empty-card { padding: 24px; text-align: center; }
.btn-sm { padding: 5px 14px; font-size: 12px; }

/* ── 移动端适配 ─────────────────────────────────────────── */
@media (max-width: 768px) {
  .sad { gap: 10px; }

  /* 行情头：价格略缩，指标网格两列 */
  .quote-head { padding: 12px 14px; }
  .qh-name { font-size: 18px; }
  .qh-price { font-size: 26px; }
  .qh-chg { font-size: 14px; }
  .qh-metrics {
    display: grid; grid-template-columns: repeat(2, 1fr);
    gap: 7px 14px; margin-top: 10px;
  }
  .qh-metric { justify-content: space-between; }
  .qh-gear { position: absolute; top: -34px; right: 0; margin: 0; }

  /* 动能卡：评分与点位上下堆叠，提示移到下方 */
  .mom-card { gap: 12px; padding: 12px 14px; }
  .mom-levels { gap: 12px; width: 100%; }
  .mlv { flex: 1 1 calc(50% - 6px); }
  .mom-hint { margin-left: 0; flex-basis: 100%; }

  /* 目标价：块换行 */
  .tgt-grid { gap: 14px; }
  .tgt-val { font-size: 18px; }
  .recent-row { grid-template-columns: 1fr auto auto; }
  .recent-row .rr-date { display: none; }

  /* 周期/指标工具条：横向滚动避免换行成多排 */
  .chart-toolbar { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch; gap: 6px; }
  .period-tabs { flex-shrink: 0; }
  .ptab { padding: 6px 11px; }
  .ind-config { flex-shrink: 0; }
  .ind-btn-toggle { white-space: nowrap; }

  /* 浮层不超出屏幕 */
  .popover { right: 0; left: auto; max-width: calc(100vw - 32px); }
  .metric-pop { min-width: 0; width: calc(100vw - 32px); }

  /* 信息 tab 占满宽度更易点 */
  .info-tabs { width: 100%; }
  .itab { flex: 1; text-align: center; padding: 9px 8px; }

  /* 基本面指标卡两列 */
  .fund-metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .fund-card { min-width: 0; padding: 12px; }

  /* 表格横向滚动，避免挤压换行 */
  .section-card { padding: 12px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .section-card .data-table { min-width: 460px; }
}

/* ── 机构荐股 ── */
.rep-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.rep-sub { font-size: 11px; }
.rep-toprating { font-size: 12px; font-weight: 700; padding: 2px 10px; border-radius: 6px; }
.rep-toprating.buy  { color: var(--up); background: rgba(220,38,38,0.14); }
.rep-toprating.sell { color: var(--down); background: rgba(22,163,74,0.14); }
.rep-toprating.hold { color: var(--text-2); background: var(--bg-elevated); }
.rating-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.rating-chip2 { font-size: 12px; color: var(--text-2); background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 2px 10px; }
.rating-chip2.buy  { color: var(--up); border-color: rgba(220,38,38,0.4); }
.rating-chip2.sell { color: var(--down); border-color: rgba(22,163,74,0.4); }
.rating-chip2 b { margin-left: 2px; }

.rep-targets { display: flex; flex-wrap: wrap; gap: 10px; }
.rt-item { background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 8px 14px; min-width: 80px; }
.rt-lbl { display: block; font-size: 10px; color: var(--text-3); margin-bottom: 4px; }
.rt-val { font-size: 16px; font-weight: 700; font-family: var(--font-mono, monospace); color: var(--text-1); }
.rt-avg { background: rgba(220,38,38,0.08); border: 1px solid rgba(220,38,38,0.22); }
.rt-up { font-size: 12px; font-weight: 600; margin-left: 6px; }
.rt-up.up { color: var(--up); }
.rt-up.down { color: var(--down); }

.consensus { display: flex; flex-wrap: wrap; gap: 8px; }
.cons-item { display: flex; align-items: center; gap: 8px; background: var(--bg-elevated); border-radius: var(--radius-sm); padding: 6px 14px; font-size: 12px; }
.cons-item .ck { color: var(--text-3); }
.cons-item .cv { color: var(--text-1); font-weight: 600; }
.cons-item .ck2 { color: var(--text-2); }

.rep-list { display: flex; flex-direction: column; }
.rep-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-top: 1px solid var(--border); text-decoration: none; font-size: 13px; cursor: pointer; }
.rep-row:first-child { border-top: none; }
.rep-row:hover { background: var(--bg-elevated); }
.rep-row.open .rep-title { color: var(--accent); }
.rep-caret { flex-shrink: 0; color: var(--text-3); font-size: 11px; width: 12px; }
.rep-body { padding: 4px 0 12px 22px; border-bottom: 1px dashed var(--border); }
.rep-body-loading { display: flex; align-items: center; gap: 8px; padding: 8px 0; font-size: 12px; }
.rep-body-empty { font-size: 12px; padding: 6px 0; }
.rep-text { white-space: pre-wrap; word-break: break-word; font-family: inherit; font-size: 12.5px; line-height: 1.7; color: var(--text-2); max-height: 420px; overflow-y: auto; margin: 0 0 8px; padding: 10px 12px; background: var(--bg-elevated); border-radius: var(--radius-sm); }
.rep-pdf-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.rep-pdf-link:hover { text-decoration: underline; }
.rep-rating { flex-shrink: 0; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 5px; color: var(--text-2); background: var(--bg-elevated); min-width: 40px; text-align: center; }
.rep-rating.buy  { color: var(--up); background: rgba(220,38,38,0.12); }
.rep-rating.sell { color: var(--down); background: rgba(22,163,74,0.12); }
.rep-title { flex: 1; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rep-org { color: var(--text-3); white-space: nowrap; }
.rep-tp { color: var(--accent); white-space: nowrap; font-weight: 600; }
.rep-date { color: var(--text-3); white-space: nowrap; font-size: 11px; }

/* ── AI 深度分析（公司一页纸）── */
.onepager-card { padding: 16px; min-height: 320px; }
.op-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
.op-sub { font-size: 12px; }
.op-spacer { flex: 1; }
.op-loading { display: flex; align-items: center; gap: 16px; padding: 56px 24px; }
.op-loading-text { display: flex; flex-direction: column; gap: 5px; }
.op-loading-text > div:first-child { font-size: 14px; font-weight: 600; }
.op-loading-text > div:last-child { font-size: 12px; }
.op-error { display: flex; align-items: center; gap: 14px; padding: 40px 24px; }
.op-empty { padding: 56px 24px; text-align: center; font-size: 13px; }
.btn-sm { padding: 4px 12px; font-size: 12px; }

/* Markdown 正文 */
.markdown-body { font-size: 13.5px; line-height: 1.7; color: var(--text-2); }
.markdown-body :deep(h1) { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 26px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.markdown-body :deep(h1:first-child) { margin-top: 0; }
.markdown-body :deep(h2) { font-size: 15px; font-weight: 700; color: var(--text-1); margin: 20px 0 10px; }
.markdown-body :deep(h3) { font-size: 14px; font-weight: 600; color: var(--accent); margin: 16px 0 8px; }
.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(strong) { color: var(--text-1); font-weight: 700; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 8px 0; padding-left: 22px; }
.markdown-body :deep(li) { margin: 4px 0; }
.markdown-body :deep(code) { font-family: var(--font-mono, monospace); font-size: 12px; background: var(--bg-base); padding: 1px 5px; border-radius: 4px; color: var(--text-1); }
.markdown-body :deep(pre) { background: var(--bg-base); border: 1px solid var(--border); border-radius: 8px; padding: 12px; overflow-x: auto; margin: 12px 0; }
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 12.5px; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid var(--border); padding: 7px 10px; text-align: left; }
.markdown-body :deep(th) { background: var(--bg-base); color: var(--text-1); font-weight: 600; }
.markdown-body :deep(td) { color: var(--text-2); }
.markdown-body :deep(tr:nth-child(even) td) { background: var(--bg-base); }
.markdown-body :deep(blockquote) { border-left: 3px solid var(--border-light); margin: 10px 0; padding: 4px 14px; color: var(--text-3); background: var(--bg-base); border-radius: 0 8px 8px 0; }
.markdown-body :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 18px 0; }
.markdown-body :deep(.mermaid-rendered) { display: flex; justify-content: center; margin: 16px 0; padding: 16px; background: #fff; border: 1px solid var(--border); border-radius: 8px; overflow-x: auto; }
.markdown-body :deep(.mermaid-rendered svg) { max-width: 100%; height: auto; }
</style>
