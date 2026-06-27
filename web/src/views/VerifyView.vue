<template>
  <div class="vfy-wrap">

    <!-- ── Header (global controls) ─────────────────────────────────────── -->
    <div class="vfy-header card">
      <div class="hd-row hd-row-top">
        <div class="hd-title-group">
          <div class="hd-title">推荐验证</div>
          <div class="view-tabs">
            <button
              v-for="t in VIEW_TABS" :key="t.key"
              :class="['view-tab', { active: activeTab === t.key }]"
              @click="activeTab = t.key"
            >{{ t.label }}</button>
          </div>
        </div>
        <div class="hd-right">
          <span v-if="verifyMsg" :class="['vmsg', verifyMsg.type]">{{ verifyMsg.text }}</span>
          <label class="force-label">
            <input type="checkbox" v-model="forceVerify" class="force-cb" />
            <span>强制重验</span>
          </label>
          <button class="btn-verify" @click="triggerVerify" :disabled="verifying">
            {{ verifying ? '验证中…' : '验证选定区间' }}
          </button>
        </div>
      </div>
      <div class="hd-row hd-row-filters">
        <div class="strat-tabs">
          <button
            v-for="t in PICK_STRATEGIES" :key="t.key"
            :class="['strat-tab', { active: filterPickStrategy === t.key }]"
            @click="selectPickStrategy(t.key)"
          >{{ t.label }}</button>
        </div>
        <div class="date-range">
          <input type="date" v-model="trackFrom" @change="load" class="date-in" />
          <span class="date-sep">至</span>
          <input type="date" v-model="trackTo"   @change="load" class="date-in" />
        </div>
        <!-- 明细 Tab 专属筛选 -->
        <template v-if="activeTab === 'records'">
          <select v-model="filterVerified" @change="load" class="filter-sel">
            <option :value="null">全部状态</option>
            <option :value="false">待验证</option>
            <option :value="true">已验证</option>
          </select>
          <select v-model="filterOutcome" class="filter-sel">
            <option value="">全部结果</option>
            <option value="hit_target">达目标</option>
            <option value="hit_stop">触止损</option>
            <option value="positive">正收益</option>
            <option value="negative">负收益</option>
            <option value="open">进行中</option>
          </select>
          <div class="search-wrap">
            <svg class="search-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input v-model="searchQuery" class="search-in" placeholder="股票名 / 代码" />
            <button v-if="searchQuery" class="search-clear" @click="searchQuery = ''">×</button>
          </div>
        </template>
      </div>
    </div>

    <!-- ════════════ TAB 1 · 收益概览 ════════════ -->
    <div v-if="activeTab === 'overview'" class="tab-content">
      <div v-if="loading" class="tbl-loading card">加载中…</div>
      <template v-else-if="settledTotal > 0">
        <!-- 结论横幅：AI 荐股到底赚不赚钱 -->
        <div :class="['verdict', 'vd-' + verdict.tone]">
          <div class="vd-icon">{{ verdict.icon }}</div>
          <div class="vd-text">
            <div class="vd-headline">{{ verdict.headline }}</div>
            <div class="vd-sub">{{ verdict.sub }}</div>
          </div>
          <div class="vd-hero">
            <span class="vd-hero-val">{{ fmtSigned(avgChange) }}</span>
            <span class="vd-hero-lbl">每笔平均收益（等额组合）</span>
          </div>
        </div>

        <!-- 核心指标 tiles -->
        <div class="kpi-grid">
          <div class="kpi card">
            <span class="kpi-val" :class="winClass(winRate)">{{ winRate != null ? winRate + '%' : '-' }}</span>
            <span class="kpi-lbl">胜率（正/正+负）</span>
            <span class="kpi-sub">{{ stats.win ?? 0 }} 胜 · {{ stats.loss ?? 0 }} 负<span v-if="stats.neutral"> · {{ stats.neutral }} 平</span></span>
          </div>
          <div class="kpi card">
            <span class="kpi-val" :class="upDn(avgPos)">{{ avgPos != null ? '+' + avgPos + '%' : '-' }}</span>
            <span class="kpi-lbl">盈利笔均收益</span>
            <span class="kpi-sub">亏损笔均 <b :class="upDn(avgNeg)">{{ avgNeg != null ? avgNeg + '%' : '-' }}</b></span>
          </div>
          <div class="kpi card">
            <span class="kpi-val" :class="upDn(excessAvg)">{{ fmtSigned(excessAvg) }}</span>
            <span class="kpi-lbl">超额收益（vs 沪深300）</span>
            <span class="kpi-sub">基准同期 <b :class="upDn(benchAvg)">{{ fmtSigned(benchAvg) }}</b></span>
          </div>
          <div class="kpi card">
            <span class="kpi-val" :class="winClass(beatPct)">{{ beatPct != null ? beatPct + '%' : '-' }}</span>
            <span class="kpi-lbl">跑赢基准占比</span>
            <span class="kpi-sub">共 {{ settledTotal }} 笔已结算</span>
          </div>
        </div>

        <!-- 多窗口回测：荐股后持有 1/3/5/30 日的胜率与平均涨幅 -->
        <div class="bt-card card">
          <div class="bt-head">
            <span class="bt-title">多窗口回测</span>
            <span class="bt-note">买入价开仓、持有 N 个交易日后按收盘退出（无止盈止损）</span>
          </div>
          <div class="bt-grid">
            <div class="bt-cell" v-for="c in backtestCards" :key="c.h">
              <div class="bt-cell-head">
                <span class="bt-cell-label">{{ c.label }}</span>
                <span class="bt-cell-sub">{{ c.sub }} · {{ c.total }} 笔</span>
              </div>
              <div class="bt-metrics">
                <div class="bt-metric">
                  <span class="bt-val" :class="winClass(c.win_rate)">{{ c.win_rate != null ? c.win_rate + '%' : '-' }}</span>
                  <span class="bt-lbl">胜率</span>
                </div>
                <div class="bt-metric">
                  <span class="bt-val" :class="upDn(c.avg_change)">{{ fmtSigned(c.avg_change) }}</span>
                  <span class="bt-lbl">平均涨幅</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 累计收益曲线（每笔等额收益累加，按买入日排序） -->
        <div class="curve-card card" v-if="equityCurve.length >= 2">
          <div class="cc-head">
            <span class="cc-title">累计收益曲线</span>
            <span class="cc-note">每笔等额、收益累加（%）· 共 {{ equityCurve.length }} 笔已结算</span>
            <span class="cc-final" :class="upDn(equityLast)">{{ fmtSigned(equityLast) }}</span>
          </div>
          <svg class="cc-svg" viewBox="0 0 100 38" preserveAspectRatio="none">
            <line class="cc-zero" :x1="0" :y1="eq.zeroY" :x2="100" :y2="eq.zeroY" />
            <polyline class="cc-area" :points="eq.areaPoints" :class="equityLast >= 0 ? 'area-up' : 'area-dn'" />
            <polyline class="cc-line" :points="eq.linePoints" :class="equityLast >= 0 ? 'line-up' : 'line-dn'" />
          </svg>
          <div class="cc-axis">
            <span>{{ equityCurve[0].date }}</span>
            <span>{{ equityCurve[equityCurve.length - 1].date }}</span>
          </div>
        </div>

        <!-- 持仓构成 -->
        <div class="comp-card card">
          <div class="comp-title">持仓构成（区间内全部荐股）</div>
          <div class="formula-row">
            <div class="fm-item">
              <span class="fm-val">{{ predictions.length }}</span>
              <span class="fm-lbl">全部</span>
            </div>
            <span class="fm-eq">=</span>
            <div class="fm-item fm-pending">
              <span class="fm-val">{{ oPending }}</span>
              <span class="fm-lbl">进行中</span>
            </div>
            <span class="fm-op">+</span>
            <div class="fm-item fm-profit">
              <span class="fm-val">{{ oProfit }}</span>
              <span class="fm-lbl">正收益</span>
            </div>
            <span class="fm-op">+</span>
            <div class="fm-item fm-loss">
              <span class="fm-val">{{ oNeg }}</span>
              <span class="fm-lbl">负收益</span>
            </div>
            <span class="fm-op">+</span>
            <div class="fm-item">
              <span class="fm-val">{{ oNeutral }}</span>
              <span class="fm-lbl">持平</span>
            </div>
          </div>
        </div>

        <!-- 分荐股策略对比：哪种 AI 荐股更准 -->
        <div class="pick-strat-section" v-if="byPickStrategy.length">
          <div class="ps-card card" v-for="ps in byPickStrategy" :key="ps.key"
               :class="{ active: filterPickStrategy === ps.key }"
               @click="selectPickStrategy(filterPickStrategy === ps.key ? '' : ps.key)">
            <div class="ps-head">
              <span class="ps-name">{{ ps.label }}</span>
              <span class="ps-total">{{ ps.total }} 个已结算</span>
            </div>
            <div class="ps-body">
              <div class="ps-wr" :class="winClass(ps.win_rate)">
                <span class="ps-wr-val">{{ ps.win_rate != null ? ps.win_rate + '%' : '-' }}</span>
                <span class="ps-wr-lbl">胜率</span>
              </div>
              <div class="ps-stat">
                <div class="ps-line"><span class="ps-up">{{ ps.win }}</span> 胜 / <span class="ps-dn">{{ ps.loss }}</span> 负<span v-if="ps.neutral"> / {{ ps.neutral }} 平</span></div>
                <div class="ps-line" :class="(ps.avg_change||0) >= 0 ? 'ps-up' : 'ps-dn'">均涨跌 {{ fmtPct(ps.avg_change) }}</div>
              </div>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="tbl-empty card">
        <p>暂无已结算样本</p>
        <p class="sub">AI 每日精选后自动生成预测记录；满 {{ verifyWindowHint }} 个交易日或触及止盈止损后结算</p>
      </div>
    </div>

    <!-- ════════════ TAB 2 · 持仓明细 ════════════ -->
    <div v-else-if="activeTab === 'records'" class="tab-content">
      <div class="stats-section" v-if="predTotal > 0">
        <div class="formula-row">
          <div class="fm-item fm-profit">
            <span class="fm-val">{{ fProfitCount }}</span>
            <span class="fm-lbl">正收益</span>
            <span class="fm-sub" v-if="fAvgPosPct != null">均+{{ fAvgPosPct }}%</span>
          </div>
          <span class="fm-eq">=</span>
          <div class="fm-item fm-hit">
            <span class="fm-val">{{ fHitTarget }}</span>
            <span class="fm-lbl">达目标</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item">
            <span class="fm-val">{{ fProfitCount - fHitTarget }}</span>
            <span class="fm-lbl">未达目标</span>
          </div>
          <div class="fm-divider"></div>
          <div class="fm-item fm-loss">
            <span class="fm-val">{{ fNegCount }}</span>
            <span class="fm-lbl">负收益</span>
            <span class="fm-sub" v-if="fAvgNegPct != null">均{{ fAvgNegPct }}%</span>
          </div>
          <span class="fm-eq">=</span>
          <div class="fm-item fm-stp">
            <span class="fm-val">{{ fHitStop }}</span>
            <span class="fm-lbl">触止损</span>
          </div>
          <span class="fm-op">+</span>
          <div class="fm-item">
            <span class="fm-val">{{ fNegCount - fHitStop }}</span>
            <span class="fm-lbl">未触止损</span>
          </div>
          <div class="fm-divider"></div>
          <div class="fm-item fm-accent">
            <span class="fm-val">{{ fAccuracy != null ? fAccuracy + '%' : '-' }}</span>
            <span class="fm-lbl">胜率</span>
          </div>
        </div>
      </div>

      <div class="table-card card">
        <div v-if="loading" class="tbl-loading">加载中…</div>
        <table v-else-if="sortedPredictions.length" class="pred-tbl">
          <thead>
            <tr>
              <th class="sortable" @click="toggleSort('date')">
                日期 <span class="sort-icon">{{ sortIcon('date') }}</span>
              </th>
              <th>股票</th>
              <th>类型</th>
              <th class="sortable" @click="toggleSort('buy_price')">
                建议价 <span class="sort-icon">{{ sortIcon('buy_price') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('entry_price')">
                开盘价 <span class="sort-icon">{{ sortIcon('entry_price') }}</span>
              </th>
              <th>止损</th>
              <th>目标</th>
              <th class="sortable" @click="toggleSort('actual_close')">
                现价 <span class="sort-icon">{{ sortIcon('actual_close') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('change_pct')">
                涨跌 <span class="sort-icon">{{ sortIcon('change_pct') }}</span>
              </th>
              <th class="sortable" @click="toggleSort('confidence')">
                置信度 <span class="sort-icon">{{ sortIcon('confidence') }}</span>
              </th>
              <th>风险</th>
              <th>结果</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in sortedPredictions" :key="p.id" class="pred-row" @click="openDetail(p)">
              <td class="td-date">{{ p.date }}</td>
              <td class="td-stock">
                <b>{{ p.name }}</b>
                <span class="td-code">{{ p.code }}</span>
              </td>
              <td>
                <span :class="['ps-badge', 'ps-' + (p.pick_strategy || 'momentum')]">{{ pickStratLabel(p.pick_strategy) }}</span>
              </td>
              <td class="td-mono td-dim">{{ p.buy_price ?? '-' }}</td>
              <td class="td-mono">
                <span v-if="p.entry_price" class="entry-price">{{ p.entry_price }}</span>
                <span v-else class="td-dim">-</span>
              </td>
              <td class="td-stop">
                {{ p.stop_price ?? '-' }}
                <span v-if="p.stop_pct" class="pct-sub pct-loss">(-{{ p.stop_pct.toFixed(1) }}%)</span>
              </td>
              <td class="td-tgt">
                {{ p.target_price ?? '-' }}
                <span v-if="p.target_pct" class="pct-sub pct-profit">(+{{ p.target_pct.toFixed(1) }}%)</span>
              </td>
              <td class="td-mono">
                <template v-if="p.actual_close">
                  <span :class="(changePct(p) ?? 0) >= 0 ? 'td-up' : 'td-dn'">{{ p.actual_close }}</span>
                </template>
                <span v-else class="td-dim">-</span>
              </td>
              <td class="td-mono">
                <template v-if="changePct(p) !== null">
                  <span :class="['pct-chip', (changePct(p) ?? 0) >= 0 ? 'chip-up' : 'chip-dn']">
                    {{ (changePct(p) ?? 0) >= 0 ? '+' : '' }}{{ changePct(p) }}%
                  </span>
                </template>
                <span v-else class="td-dim">-</span>
              </td>
              <td>
                <div class="conf-row">
                  <div class="conf-bar"><div class="conf-fill" :style="{ width: (p.confidence||0)+'%' }"></div></div>
                  <span class="conf-num">{{ p.confidence ?? '-' }}</span>
                </div>
              </td>
              <td><span :class="['risk-badge', 'r-' + (p.risk_level||'中')]">{{ p.risk_level ?? '-' }}</span></td>
              <td>
                <span :class="['out-badge', 'o-' + (p.outcome||'open')]">{{ outLabel(p.outcome) }}</span>
              </td>
              <td class="td-action">
                <span class="detail-link">详情 →</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-else-if="predictions.length && !sortedPredictions.length" class="tbl-empty">
          <p>没有匹配的记录</p>
          <p class="sub">调整搜索条件或清除筛选</p>
        </div>
        <div v-else class="tbl-empty">
          <p>暂无预测记录</p>
          <p class="sub">AI 每日精选后自动生成预测记录</p>
        </div>
      </div>
    </div>

    <!-- ════════════ TAB 3 · 维度分析 ════════════ -->
    <div v-else class="tab-content">
      <div v-if="loading" class="tbl-loading card">加载中…</div>
      <template v-else-if="settledList.length">
        <!-- ① 资金曲线 + 风控指标 -->
        <div class="curve-card card" v-if="portfolio">
          <div class="cc-head">
            <span class="cc-title">资金曲线 <span class="bd-note">(逐笔等额复利, 初始本金=1)</span></span>
            <span class="cc-note">{{ portfolio.n }} 笔已结算</span>
            <span class="cc-final" :class="upDn(portfolio.totalRet)">{{ fmtSigned(portfolio.totalRet) }}</span>
          </div>
          <svg class="cc-svg" viewBox="0 0 100 38" preserveAspectRatio="none" v-if="portfolio.curve.length >= 2">
            <line class="cc-zero" :x1="0" :y1="pf.baseY" :x2="100" :y2="pf.baseY" />
            <polyline class="cc-area" :points="pf.areaPoints" :class="portfolio.totalRet >= 0 ? 'area-up' : 'area-dn'" />
            <polyline class="cc-line" :points="pf.linePoints" :class="portfolio.totalRet >= 0 ? 'line-up' : 'line-dn'" />
          </svg>
          <div class="rk-grid">
            <div class="rk-cell"><span class="rkc-val" :class="upDn(portfolio.totalRet)">{{ fmtSigned(portfolio.totalRet) }}</span><span class="rkc-lbl">累计收益</span></div>
            <div class="rk-cell"><span class="rkc-val dn">-{{ portfolio.maxDD }}%</span><span class="rkc-lbl">最大回撤</span></div>
            <div class="rk-cell"><span class="rkc-val" :class="upDn(portfolio.annual)">{{ fmtSigned(portfolio.annual) }}</span><span class="rkc-lbl">年化收益</span></div>
            <div class="rk-cell"><span class="rkc-val">{{ portfolio.sharpe ?? '-' }}</span><span class="rkc-lbl">夏普(按笔)</span></div>
          </div>
        </div>

        <!-- 关键交易指标 -->
        <div class="kpi-grid">
          <div class="kpi card">
            <span class="kpi-val" :class="upDn(advStats.expectancy)">{{ fmtSigned(advStats.expectancy) }}</span>
            <span class="kpi-lbl">期望收益 / 笔</span>
            <span class="kpi-sub">{{ advStats.n }} 笔已结算</span>
          </div>
          <div class="kpi card">
            <span class="kpi-val" :class="advStats.profitFactor >= 1 ? 'up' : 'dn'">{{ advStats.profitFactor === null ? '-' : advStats.profitFactor === Infinity ? '∞' : advStats.profitFactor }}</span>
            <span class="kpi-lbl">盈亏比（总盈利/总亏损）</span>
            <span class="kpi-sub">&gt;1 即整体盈利</span>
          </div>
          <div class="kpi card">
            <span class="kpi-val up">+{{ advStats.maxWin }}%</span>
            <span class="kpi-lbl">最大单笔盈利</span>
          </div>
          <div class="kpi card">
            <span class="kpi-val dn">{{ advStats.maxLoss }}%</span>
            <span class="kpi-lbl">最大单笔亏损</span>
          </div>
          <div class="kpi card">
            <span class="kpi-val">{{ advStats.avgHold != null ? advStats.avgHold + ' 天' : '-' }}</span>
            <span class="kpi-lbl">平均持仓交易日</span>
          </div>
        </div>

        <!-- ② 止盈止损有效性 + ④ 持仓窗口敏感性 -->
        <div class="analysis-grid">
          <div class="bd-card card" v-if="efficacy">
            <div class="bd-title">止盈止损有效性 <span class="bd-note">(按规则 vs 硬扛到窗口末)</span></div>
            <div class="eff-summary">
              <div class="eff-col">
                <span class="eff-val" :class="upDn(efficacy.ruled_avg)">{{ fmtSigned(efficacy.ruled_avg) }}</span>
                <span class="eff-lbl">按规则 · 笔均</span>
              </div>
              <span class="eff-vs">vs</span>
              <div class="eff-col">
                <span class="eff-val" :class="upDn(efficacy.held_avg)">{{ fmtSigned(efficacy.held_avg) }}</span>
                <span class="eff-lbl">硬扛到期 · 笔均</span>
              </div>
            </div>
            <div class="eff-rows">
              <div class="eff-row" v-if="efficacy.stop.n">
                <span class="eff-tag dn">止损 {{ efficacy.stop.n }} 笔</span>
                <span class="eff-mid">救命 <b class="up">{{ efficacy.stop.saved }}</b> · 误杀 <b class="dn">{{ efficacy.stop.mistaken }}</b></span>
                <span class="eff-extra">扛到期均 {{ fmtSigned(efficacy.stop.avg_if_held) }}</span>
              </div>
              <div class="eff-row" v-if="efficacy.target.n">
                <span class="eff-tag up">止盈 {{ efficacy.target.n }} 笔</span>
                <span class="eff-mid">锁定 {{ fmtSigned(efficacy.target.avg_locked) }} · 最高可达 {{ fmtSigned(efficacy.target.avg_mfe) }}</span>
                <span class="eff-extra" v-if="efficacy.target.left_on_table != null">少赚约 {{ efficacy.target.left_on_table }}%</span>
              </div>
              <div class="eff-hint">救命=止损后若硬扛反而更差；误杀=止损后其实能涨回。</div>
            </div>
          </div>

          <div class="bd-card card" v-if="byHorizon.length">
            <div class="bd-title">多窗口回测明细 <span class="bd-note">(买入持有 N 日, 无止盈止损)</span></div>
            <div class="bd-row bd-head">
              <span class="bd-name">持有</span><span class="bd-n">样本</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均收益</span>
            </div>
            <div class="bd-row" v-for="h in byHorizon" :key="h.horizon">
              <span class="bd-name">{{ h.horizon }} 个交易日</span>
              <span class="bd-n">{{ h.total }}</span>
              <span class="bd-wr" :class="winClass(h.win_rate)">{{ h.win_rate != null ? h.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="upDn(h.avg_change)">{{ fmtSigned(h.avg_change) }}</span>
            </div>
          </div>
        </div>

        <div class="analysis-grid">
          <!-- 收益分布直方图 -->
          <div class="bd-card card">
            <div class="bd-title">收益分布 <span class="bd-note">(已结算 {{ settledList.length }} 笔)</span></div>
            <div class="hist">
              <div class="hist-col" v-for="b in histBuckets" :key="b.key">
                <span class="hist-cnt">{{ b.count || '' }}</span>
                <div class="hist-bar-wrap">
                  <div class="hist-bar" :class="'hb-' + b.tone" :style="{ height: (b.count / histMax * 100) + '%' }"></div>
                </div>
                <span class="hist-lbl">{{ b.label }}</span>
              </div>
            </div>
          </div>

          <!-- 按月表现 -->
          <div class="bd-card card">
            <div class="bd-title">按月表现 <span class="bd-note">(胜率 / 笔均收益)</span></div>
            <div class="bd-row bd-head">
              <span class="bd-name">月份</span><span class="bd-n">笔数</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均收益</span>
            </div>
            <div class="bd-row" v-for="m in monthlyStats" :key="m.month">
              <span class="bd-name">{{ m.month }}</span>
              <span class="bd-n">{{ m.total }}</span>
              <span class="bd-wr" :class="winClass(m.win_rate)">{{ m.win_rate != null ? m.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="upDn(m.avg)">{{ fmtSigned(m.avg) }}</span>
            </div>
          </div>
        </div>

        <!-- 表现最佳 / 最差 -->
        <div class="analysis-grid">
          <div class="bd-card card">
            <div class="bd-title">表现最佳 Top5</div>
            <div class="rank-row" v-for="p in topWinners" :key="p.id" @click="openDetail(p)">
              <span class="rk-name"><b>{{ p.name }}</b><span class="td-code">{{ p.code }}</span></span>
              <span class="rk-date">{{ p.date }}</span>
              <span class="rk-ret up">+{{ p.actual_change_pct.toFixed(1) }}%</span>
            </div>
          </div>
          <div class="bd-card card">
            <div class="bd-title">表现最差 Top5</div>
            <div class="rank-row" v-for="p in topLosers" :key="p.id" @click="openDetail(p)">
              <span class="rk-name"><b>{{ p.name }}</b><span class="td-code">{{ p.code }}</span></span>
              <span class="rk-date">{{ p.date }}</span>
              <span class="rk-ret dn">{{ p.actual_change_pct.toFixed(1) }}%</span>
            </div>
          </div>
        </div>

        <div class="breakdown-grid" v-if="bySector.length || byStrategy.length || byConfidence.length || byRisk.length">
          <!-- ③ 行业/板块维度胜率 -->
          <div class="bd-card card" v-if="bySector.length">
            <div class="bd-title">行业胜率 <span class="bd-note">(AI 擅长哪些板块)</span></div>
            <div class="bd-row bd-head">
              <span class="bd-name">行业</span><span class="bd-n">样本</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均涨跌</span>
            </div>
            <div class="bd-row" v-for="s in bySector" :key="s.sector">
              <span class="bd-name" :title="s.sector">{{ s.sector }}</span>
              <span class="bd-n">{{ s.total }}</span>
              <span class="bd-wr" :class="winClass(s.win_rate)">{{ s.win_rate != null ? s.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="(s.avg_change||0) >= 0 ? 'up' : 'dn'">{{ fmtPct(s.avg_change) }}</span>
            </div>
          </div>

          <div class="bd-card card" v-if="byStrategy.length">
            <div class="bd-title">命中策略胜率 <span class="bd-note">(命中样本≥2)</span></div>
            <div class="bd-row bd-head">
              <span class="bd-name">策略</span><span class="bd-n">样本</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均涨跌</span>
            </div>
            <div class="bd-row" v-for="s in byStrategy" :key="s.strategy">
              <span class="bd-name" :title="s.strategy">{{ s.strategy }}</span>
              <span class="bd-n">{{ s.total }}</span>
              <span class="bd-wr" :class="winClass(s.win_rate)">{{ s.win_rate != null ? s.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="(s.avg_change||0) >= 0 ? 'up' : 'dn'">{{ fmtPct(s.avg_change) }}</span>
            </div>
          </div>

          <div class="bd-card card" v-if="byConfidence.length">
            <div class="bd-title">置信度分桶 <span class="bd-note">(置信度越高是否越准)</span></div>
            <div class="bd-row bd-head">
              <span class="bd-name">置信度</span><span class="bd-n">样本</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均涨跌</span>
            </div>
            <div class="bd-row" v-for="c in byConfidence" :key="c.bucket">
              <span class="bd-name">{{ c.bucket }}</span>
              <span class="bd-n">{{ c.total }}</span>
              <span class="bd-wr" :class="winClass(c.win_rate)">{{ c.win_rate != null ? c.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="(c.avg_change||0) >= 0 ? 'up' : 'dn'">{{ fmtPct(c.avg_change) }}</span>
            </div>
          </div>

          <div class="bd-card card" v-if="byRisk.length">
            <div class="bd-title">风险等级</div>
            <div class="bd-row bd-head">
              <span class="bd-name">风险</span><span class="bd-n">样本</span>
              <span class="bd-wr">胜率</span><span class="bd-avg">均涨跌</span>
            </div>
            <div class="bd-row" v-for="r in byRisk" :key="r.risk">
              <span class="bd-name">{{ r.risk }}</span>
              <span class="bd-n">{{ r.total }}</span>
              <span class="bd-wr" :class="winClass(r.win_rate)">{{ r.win_rate != null ? r.win_rate + '%' : '-' }}</span>
              <span class="bd-avg" :class="(r.avg_change||0) >= 0 ? 'up' : 'dn'">{{ fmtPct(r.avg_change) }}</span>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="tbl-empty card">
        <p>暂无可分析的已结算样本</p>
        <p class="sub">样本结算后这里会按命中策略 / 置信度 / 风险拆分胜率</p>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()

// ── 视图 Tab（概览/明细/分析）──────────────────────────────────────────
const VIEW_TABS = [
  { key: 'overview', label: '收益概览' },
  { key: 'records',  label: '持仓明细' },
  { key: 'analysis', label: '维度分析' },
]
const activeTab = ref('overview')

// ── AI Picks State ─────────────────────────────────────────────────────────────
const predictions    = ref([])
const stats          = ref({})
const allStats       = ref({})   // 不随策略筛选收窄的全量统计（供分策略对比卡片）
const predTotal      = ref(0)
const loading        = ref(false)
const verifying      = ref(false)
const verifyMsg      = ref(null)
const forceVerify    = ref(false)
const filterVerified = ref(null)
const filterOutcome  = ref('')
const searchQuery    = ref('')
const verifyWindowHint = 20      // QF_VERIFY_WINDOW 默认值，仅用于空态文案提示

// 荐股策略筛选：区分动能买点 / 普林格KST周期，判断哪种荐股更准
const PICK_STRATEGIES = [
  { key: '',         label: '全部' },
  { key: 'momentum', label: '动能买点' },
  { key: 'pring',    label: '普林格KST' },
]
const filterPickStrategy = ref('')
const PICK_STRAT_CN = { momentum: '动能买点', pring: '普林格KST周期' }
function pickStratLabel(s) { return PICK_STRAT_CN[s] || PICK_STRAT_CN.momentum }
function selectPickStrategy(key) {
  if (filterPickStrategy.value === key) return
  filterPickStrategy.value = key
  load()
}

const today     = new Date()
const thirtyAgo = new Date(today); thirtyAgo.setDate(thirtyAgo.getDate() - 30)
const future    = new Date(today); future.setDate(future.getDate() + 30)
const trackFrom = ref(thirtyAgo.toISOString().slice(0, 10))
const trackTo   = ref(future.toISOString().slice(0, 10))

const sortKey = ref('date')
const sortDir = ref('desc')

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = key === 'date' ? 'desc' : 'desc'
  }
}

function sortIcon(key) {
  if (sortKey.value !== key) return '⇅'
  return sortDir.value === 'asc' ? '↑' : '↓'
}

async function load() {
  loading.value = true
  try {
    const params = { limit: 300, date_from: trackFrom.value, date_to: trackTo.value }
    if (filterVerified.value !== null) params.verified = filterVerified.value
    if (filterPickStrategy.value) params.pick_strategy = filterPickStrategy.value
    // 分策略对比卡片始终用「全部」口径（不随当前筛选收窄），其余统计随筛选
    const statsParams = { date_from: trackFrom.value, date_to: trackTo.value }
    if (filterPickStrategy.value) statsParams.pick_strategy = filterPickStrategy.value
    const [pr, sr, allStatsRes] = await Promise.all([
      axios.get('/api/predictions/', { params }),
      axios.get('/api/predictions/stats', { params: statsParams }),
      axios.get('/api/predictions/stats', { params: { date_from: trackFrom.value, date_to: trackTo.value } }),
    ])
    allStats.value = allStatsRes.data
    predictions.value = pr.data.predictions
    predTotal.value   = pr.data.total
    stats.value       = sr.data
  } finally {
    loading.value = false
  }
}

let pollTimer = null
function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

async function triggerVerify() {
  verifying.value = true; verifyMsg.value = null
  try {
    const res = await axios.post('/api/predictions/verify', {
      date_from: trackFrom.value,
      date_to: trackTo.value,
      force: forceVerify.value,
    })
    verifyMsg.value = { type: 'ok', text: res.data.message }
    // 轮询真实进度（后台落 DB，跨 worker 可见），完成后刷新——不再 setTimeout 猜。
    stopPoll()
    pollTimer = setInterval(async () => {
      try {
        const st = (await axios.get('/api/predictions/verify/status')).data || {}
        if (st.total > 0) verifyMsg.value = { type: 'ok', text: `验证中… ${st.done}/${st.total}` }
        if (!st.running) {
          stopPoll()
          await load()
          verifyMsg.value = { type: 'ok', text: `已结算 ${st.settled ?? ''} 条` }
          setTimeout(() => { verifyMsg.value = null }, 2500)
        }
      } catch { stopPoll() }
    }, 1500)
  } catch (e) {
    verifyMsg.value = { type: 'err', text: e.response?.data?.detail || '验证失败' }
  } finally {
    verifying.value = false
  }
}

const filteredPredictions = computed(() => {
  let list = predictions.value
  if (filterOutcome.value) {
    if (filterOutcome.value === 'open') {
      list = list.filter(p => !['hit_target', 'hit_stop', 'positive', 'negative'].includes(p.outcome))
    } else {
      list = list.filter(p => p.outcome === filterOutcome.value)
    }
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(p =>
      (p.name || '').toLowerCase().includes(q) ||
      (p.code || '').includes(q)
    )
  }
  return list
})

const numericKeys = new Set(['buy_price', 'entry_price', 'actual_close', 'confidence', 'change_pct'])

const sortedPredictions = computed(() => {
  const list = [...filteredPredictions.value]
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  const isNumeric = numericKeys.has(key)

  list.sort((a, b) => {
    let va, vb
    if (key === 'change_pct') {
      va = parseFloat(changePct(a)) || -9999
      vb = parseFloat(changePct(b)) || -9999
    } else if (isNumeric) {
      va = parseFloat(a[key]) || -9999
      vb = parseFloat(b[key]) || -9999
    } else {
      va = a[key] ?? ''
      vb = b[key] ?? ''
    }
    if (va < vb) return -1 * dir
    if (va > vb) return 1 * dir
    return 0
  })
  return list
})

// ── 明细 Tab：跟随搜索/结果筛选的逐项计数 ──────────────────────────────
const fProfitCount  = computed(() => filteredPredictions.value.filter(p => ['hit_target', 'positive'].includes(p.outcome)).length)
const fNegCount     = computed(() => filteredPredictions.value.filter(p => ['hit_stop', 'negative'].includes(p.outcome)).length)
const fHitTarget    = computed(() => filteredPredictions.value.filter(p => p.outcome === 'hit_target').length)
const fHitStop      = computed(() => filteredPredictions.value.filter(p => p.outcome === 'hit_stop').length)

const fAccuracy = computed(() => {
  const win = fProfitCount.value, loss = fNegCount.value
  const decisive = win + loss
  if (!decisive) return null
  return (win / decisive * 100).toFixed(1)
})

const fAvgPosPct = computed(() => {
  const vals = filteredPredictions.value
    .filter(p => p.actual_change_pct != null && p.actual_change_pct > 0)
    .map(p => p.actual_change_pct)
  if (!vals.length) return null
  return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2)
})

const fAvgNegPct = computed(() => {
  const vals = filteredPredictions.value
    .filter(p => p.actual_change_pct != null && p.actual_change_pct < 0)
    .map(p => p.actual_change_pct)
  if (!vals.length) return null
  return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(2)
})

// ── 概览 Tab：核心结论（全样本口径，取后端 /stats，不随搜索收窄）─────────
const settledTotal = computed(() => stats.value?.total ?? 0)
const winRate    = computed(() => stats.value?.accuracy_pct ?? null)
const avgChange  = computed(() => stats.value?.avg_change_pct ?? null)
const avgPos     = computed(() => stats.value?.avg_positive_pct ?? null)
const avgNeg     = computed(() => stats.value?.avg_negative_pct ?? null)
const benchAvg   = computed(() => stats.value?.benchmark_avg_pct ?? null)
const excessAvg  = computed(() => stats.value?.excess_avg_pct ?? null)
const beatPct    = computed(() => stats.value?.beat_benchmark_pct ?? null)
const byPickStrategy = computed(() => allStats.value?.by_pick_strategy || [])
const byStrategy = computed(() => (stats.value?.by_strategy || []).filter(s => s.total >= 2).slice(0, 8))
const byConfidence = computed(() => stats.value?.by_confidence || [])
const byRisk     = computed(() => stats.value?.by_risk || [])

// ── 维度分析 Tab：基于已结算样本的前端深度分析 ────────────────────────
const settledList = computed(() =>
  predictions.value.filter(p => p.verified && p.actual_change_pct != null)
)

const advStats = computed(() => {
  const list = settledList.value
  if (!list.length) return { profitFactor: null, avgHold: null, maxWin: 0, maxLoss: 0, expectancy: 0, n: 0 }
  const rets = list.map(p => p.actual_change_pct)
  const sumPos = rets.filter(r => r > 0).reduce((a, b) => a + b, 0)
  const sumNeg = Math.abs(rets.filter(r => r < 0).reduce((a, b) => a + b, 0))
  const profitFactor = sumNeg > 0 ? +(sumPos / sumNeg).toFixed(2) : (sumPos > 0 ? Infinity : 0)
  const holds = list.map(p => p.hold_days).filter(d => d != null)
  const avgHold = holds.length ? +(holds.reduce((a, b) => a + b, 0) / holds.length).toFixed(1) : null
  return {
    profitFactor, avgHold,
    maxWin: +Math.max(...rets).toFixed(2),
    maxLoss: +Math.min(...rets).toFixed(2),
    expectancy: +(rets.reduce((a, b) => a + b, 0) / rets.length).toFixed(2),
    n: list.length,
  }
})

// 收益分布直方图：按收益区间分桶（bin 为左闭右开）
const histBuckets = computed(() => {
  const defs = [
    { key: 'a', label: '≤-10', min: -Infinity, max: -10, tone: 'dn' },
    { key: 'b', label: '-10~-5', min: -10, max: -5, tone: 'dn' },
    { key: 'c', label: '-5~0', min: -5, max: 0, tone: 'dn' },
    { key: 'd', label: '0~5', min: 0, max: 5, tone: 'up' },
    { key: 'e', label: '5~10', min: 5, max: 10, tone: 'up' },
    { key: 'f', label: '10~20', min: 10, max: 20, tone: 'up' },
    { key: 'g', label: '>20', min: 20, max: Infinity, tone: 'up' },
  ]
  const buckets = defs.map(d => ({ ...d, count: 0 }))
  for (const p of settledList.value) {
    const r = p.actual_change_pct
    for (const b of buckets) {
      if (r >= b.min && (r < b.max || b.max === Infinity)) { b.count++; break }
    }
  }
  return buckets
})
const histMax = computed(() => Math.max(1, ...histBuckets.value.map(b => b.count)))

// 按月表现：胜率 + 笔均收益（最新月在前）
const monthlyStats = computed(() => {
  const map = {}
  for (const p of settledList.value) {
    const m = (p.date || '').slice(0, 7)
    if (!m) continue
    ;(map[m] ||= []).push(p)
  }
  return Object.entries(map)
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([month, rows]) => {
      const rets = rows.map(p => p.actual_change_pct)
      const win = rows.filter(p => ['hit_target', 'positive'].includes(p.outcome)).length
      const loss = rows.filter(p => ['hit_stop', 'negative'].includes(p.outcome)).length
      const dec = win + loss
      return {
        month, total: rows.length,
        win_rate: dec ? +(win / dec * 100).toFixed(1) : null,
        avg: +(rets.reduce((a, b) => a + b, 0) / rets.length).toFixed(2),
      }
    })
})

const topWinners = computed(() =>
  [...settledList.value].sort((a, b) => b.actual_change_pct - a.actual_change_pct).slice(0, 5)
)
const topLosers = computed(() =>
  [...settledList.value].sort((a, b) => a.actual_change_pct - b.actual_change_pct).slice(0, 5)
)

// ① 资金曲线（按买入日逐笔等额复利）+ 风控指标（最大回撤/年化/夏普）
const portfolio = computed(() => {
  const list = [...settledList.value].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  if (!list.length) return null
  let cap = 1, peak = 1, maxDD = 0
  const curve = []
  for (const p of list) {
    cap *= (1 + p.actual_change_pct / 100)
    peak = Math.max(peak, cap)
    maxDD = Math.max(maxDD, (peak - cap) / peak)
    curve.push({ date: p.date, cap })
  }
  const rets = list.map(p => p.actual_change_pct)
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length)
  const d0 = new Date(list[0].date), d1 = new Date(list[list.length - 1].date)
  const days = Math.max(1, (d1 - d0) / 86400000)
  return {
    curve, n: list.length,
    totalRet: +((cap - 1) * 100).toFixed(2),
    maxDD: +(maxDD * 100).toFixed(2),
    annual: +((Math.pow(cap, 365 / days) - 1) * 100).toFixed(2),
    sharpe: sd > 0 ? +(mean / sd).toFixed(2) : null,
  }
})

const pf = computed(() => {
  const c = portfolio.value
  if (!c || c.curve.length < 2) return { linePoints: '', areaPoints: '', baseY: 19 }
  const caps = c.curve.map(p => p.cap).concat([1])
  const min = Math.min(...caps), max = Math.max(...caps)
  const span = (max - min) || 1
  const H = 38, pad = 3
  const y = v => H - pad - ((v - min) / span) * (H - pad * 2)
  const x = i => (i / (c.curve.length - 1)) * 100
  const line = c.curve.map((p, i) => `${x(i).toFixed(2)},${y(p.cap).toFixed(2)}`).join(' ')
  const area = `0,${y(1).toFixed(2)} ${line} 100,${y(1).toFixed(2)}`
  return { linePoints: line, areaPoints: area, baseY: +y(1).toFixed(2) }
})

// ② 止盈止损有效性 ③ 行业维度 ④ 持仓窗口敏感性（均取后端 /stats，全样本口径）
const efficacy  = computed(() => stats.value?.efficacy || null)
const bySector  = computed(() => (stats.value?.by_sector || []).filter(s => s.total >= 1).slice(0, 10))
const byHorizon = computed(() => stats.value?.by_horizon || [])

// 多窗口回测：固定 1/3/5/30 日窗口，顺序与标签稳定（缺数据的窗口仍占位）
const BACKTEST_WINDOWS = [
  { h: 1,  label: '昨日',  sub: '持有 1 日' },
  { h: 3,  label: '3 日',  sub: '持有 3 日' },
  { h: 5,  label: '5 日',  sub: '持有 5 日' },
  { h: 30, label: '30 日', sub: '持有 30 日' },
]
const backtestCards = computed(() => {
  const map = {}
  for (const r of (stats.value?.by_horizon || [])) map[r.horizon] = r
  return BACKTEST_WINDOWS.map(w => {
    const r = map[w.h]
    return {
      ...w,
      total: r?.total ?? 0,
      win_rate: r?.win_rate ?? null,
      avg_change: r?.avg_change ?? null,
    }
  })
})

// 持仓构成（区间内全部荐股，按 pick_strategy/日期筛选；不受搜索/结果筛选影响）
const oPending  = computed(() => predictions.value.filter(p => !p.verified).length)
const oProfit   = computed(() => predictions.value.filter(p => ['hit_target', 'positive'].includes(p.outcome)).length)
const oNeg      = computed(() => predictions.value.filter(p => ['hit_stop', 'negative'].includes(p.outcome)).length)
const oNeutral  = computed(() => predictions.value.filter(p => p.outcome === 'neutral').length)

// 结论横幅：直接回答「AI 荐股到底赚不赚钱」
const verdict = computed(() => {
  const a = avgChange.value
  const beat = beatPct.value
  if (a == null) return { tone: 'neutral', icon: '—', headline: '样本不足', sub: '结算后给出收益结论' }
  const beatTxt = beat != null ? `，约 ${beat}% 的荐股跑赢沪深300` : ''
  if (a > 0.5) {
    return { tone: 'good', icon: '📈',
      headline: `AI 荐股整体盈利：每笔平均 ${fmtSigned(a)}`,
      sub: `胜率 ${winRate.value ?? '-'}%${beatTxt}` }
  }
  if (a < -0.5) {
    return { tone: 'bad', icon: '📉',
      headline: `AI 荐股整体亏损：每笔平均 ${fmtSigned(a)}`,
      sub: `胜率 ${winRate.value ?? '-'}%${beatTxt}` }
  }
  return { tone: 'neutral', icon: '➖',
    headline: `AI 荐股基本持平：每笔平均 ${fmtSigned(a)}`,
    sub: `胜率 ${winRate.value ?? '-'}%${beatTxt}` }
})

// 累计收益曲线：已结算荐股按买入日升序，逐笔等额收益累加
const equityCurve = computed(() => {
  const pts = predictions.value
    .filter(p => p.verified && p.actual_change_pct != null)
    .map(p => ({ date: p.date, v: p.actual_change_pct }))
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  let cum = 0
  return pts.map(p => { cum += p.v; return { date: p.date, cum: +cum.toFixed(2) } })
})
const equityLast = computed(() => equityCurve.value.length ? equityCurve.value[equityCurve.value.length - 1].cum : 0)

const eq = computed(() => {
  const c = equityCurve.value
  if (c.length < 2) return { linePoints: '', areaPoints: '', zeroY: 19 }
  const vals = c.map(p => p.cum).concat([0])
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = (max - min) || 1
  const H = 38, pad = 3
  const y = v => H - pad - ((v - min) / span) * (H - pad * 2)
  const x = i => (i / (c.length - 1)) * 100
  const line = c.map((p, i) => `${x(i).toFixed(2)},${y(p.cum).toFixed(2)}`).join(' ')
  const area = `0,${y(0).toFixed(2)} ${line} 100,${y(0).toFixed(2)}`
  return { linePoints: line, areaPoints: area, zeroY: +y(0).toFixed(2) }
})

function openDetail(p) {
  sessionStorage.setItem('verifyPred', JSON.stringify(p))
  // 新标签页打开：sessionStorage 不一定跨标签复制，关键字段同时带到 query 兜底
  const query = {
    id: p.id ?? '', code: p.code ?? '', name: p.name ?? '', date: p.date ?? '',
    buy: p.buy_price ?? '', target: p.target_price ?? '', stop: p.stop_price ?? '',
    target_pct: p.target_pct ?? '', stop_pct: p.stop_pct ?? '',
    confidence: p.confidence ?? '', risk: p.risk_level ?? '', outcome: p.outcome ?? '',
  }
  window.open(router.resolve({ path: '/verify-detail', query }).href, '_blank')
}

function outLabel(o) {
  return { hit_target:'达目标', hit_stop:'触止损', positive:'正收益', negative:'负收益', neutral:'持平', open:'待验证' }[o] || '待验证'
}

function fmtPct(v) {
  if (v == null) return '-'
  return (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%'
}
function fmtSigned(v) {
  if (v == null) return '-'
  return (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%'
}
function winClass(wr) {
  if (wr == null) return ''
  return wr >= 60 ? 'wr-good' : wr >= 45 ? 'wr-mid' : 'wr-bad'
}
function upDn(v) {
  if (v == null) return ''
  return v >= 0 ? 'up' : 'dn'
}

function changePct(p) {
  // 已结算的以后端 actual_change_pct 为唯一真相（路径锁定收益）；未结算的现算。
  if (p.actual_change_pct != null) return Number(p.actual_change_pct).toFixed(1)
  const basis = p.entry_price || p.buy_price
  if (!p.actual_close || !basis || basis <= 0) return null
  return ((p.actual_close - basis) / basis * 100).toFixed(1)
}

onMounted(() => { load() })
onUnmounted(() => { stopPoll() })
</script>

<style scoped>
.vfy-wrap { padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; }

.tab-content { display: flex; flex-direction: column; gap: 10px; animation: fadeIn 0.25s ease; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Header */
.vfy-header { padding: 10px 14px 8px; display: flex; flex-direction: column; gap: 8px; }
.hd-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.hd-row-top { justify-content: space-between; }
.hd-row-filters { flex-wrap: wrap; }
.hd-right { display: flex; align-items: center; gap: 8px; }
.hd-title { font-size: 13px; font-weight: 700; color: var(--text-1); letter-spacing: 0.03em; }
.hd-title-group { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }

/* 视图主 Tab（概览/明细/分析）—— 较大、下划线风格 */
.view-tabs { display: inline-flex; gap: 4px; }
.view-tab { border: none; background: transparent; color: var(--text-3); font-size: 13px; font-weight: 600; padding: 4px 4px 6px; cursor: pointer; position: relative; transition: color 0.15s; }
.view-tab:hover { color: var(--text-1); }
.view-tab.active { color: var(--accent); }
.view-tab.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: var(--accent); border-radius: 2px; }

/* 荐股策略 Tab（数据筛选）—— 小号 segmented */
.strat-tabs { display: inline-flex; gap: 2px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 2px; }
.strat-tab { border: none; background: transparent; color: var(--text-3); font-size: 11px; font-weight: 500; padding: 4px 11px; border-radius: calc(var(--radius-md) - 2px); cursor: pointer; transition: all 0.15s; white-space: nowrap; }
.strat-tab:hover { color: var(--text-1); }
.strat-tab.active { background: var(--accent); color: #fff; }

/* ── 概览：结论横幅 ───────────────────────────────────────── */
.verdict { display: flex; align-items: center; gap: 16px; padding: 16px 20px; border-radius: var(--radius-md); border: 1px solid var(--border); }
.vd-good    { background: linear-gradient(90deg, rgba(220,38,38,0.10), rgba(220,38,38,0.02)); border-color: rgba(220,38,38,0.35); }
.vd-bad     { background: linear-gradient(90deg, rgba(22,163,74,0.10), rgba(22,163,74,0.02)); border-color: rgba(22,163,74,0.35); }
.vd-neutral { background: var(--bg-elevated); }
.vd-icon { font-size: 30px; line-height: 1; }
.vd-text { flex: 1; min-width: 0; }
.vd-headline { font-size: 16px; font-weight: 800; color: var(--text-1); letter-spacing: 0.01em; }
.vd-sub { font-size: 12px; color: var(--text-3); margin-top: 4px; }
.vd-hero { display: flex; flex-direction: column; align-items: flex-end; text-align: right; }
.vd-hero-val { font-size: 30px; font-weight: 800; font-family: var(--font-mono); line-height: 1; }
.vd-good .vd-hero-val { color: #dc2626; }
.vd-bad  .vd-hero-val { color: #16a34a; }
.vd-neutral .vd-hero-val { color: var(--text-1); }
.vd-hero-lbl { font-size: 10px; color: var(--text-3); margin-top: 4px; }

/* ── 概览：核心指标 tiles ─────────────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.kpi { padding: 12px 14px; display: flex; flex-direction: column; gap: 3px; }
.kpi-val { font-size: 24px; font-weight: 800; font-family: var(--font-mono); line-height: 1.1; color: var(--text-1); }
.kpi-lbl { font-size: 11px; color: var(--text-2); }
.kpi-sub { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); margin-top: 1px; }
.kpi-val.up, .kpi-sub b.up { color: #dc2626; }
.kpi-val.dn, .kpi-sub b.dn { color: #16a34a; }
.kpi-val.wr-good { color: #dc2626; }
.kpi-val.wr-mid  { color: #b45309; }
.kpi-val.wr-bad  { color: #16a34a; }

/* ── 概览：多窗口回测 ─────────────────────────────────────── */
.bt-card { padding: 12px 14px; }
.bt-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; }
.bt-title { font-size: 12px; font-weight: 700; color: var(--text-1); }
.bt-note { font-size: 10px; color: var(--text-3); }
.bt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
.bt-cell { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; background: var(--bg-1); }
.bt-cell-head { display: flex; flex-direction: column; gap: 1px; margin-bottom: 8px; }
.bt-cell-label { font-size: 13px; font-weight: 800; color: var(--text-1); }
.bt-cell-sub { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); }
.bt-metrics { display: flex; gap: 14px; }
.bt-metric { display: flex; flex-direction: column; gap: 1px; }
.bt-val { font-size: 20px; font-weight: 800; font-family: var(--font-mono); line-height: 1.1; color: var(--text-1); }
.bt-val.up { color: #dc2626; }
.bt-val.dn { color: #16a34a; }
.bt-val.wr-good { color: #dc2626; }
.bt-val.wr-mid  { color: #b45309; }
.bt-val.wr-bad  { color: #16a34a; }
.bt-lbl { font-size: 10px; color: var(--text-2); }

/* ── 概览：累计收益曲线 ───────────────────────────────────── */
.curve-card { padding: 12px 14px; }
.cc-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.cc-title { font-size: 12px; font-weight: 700; color: var(--text-1); }
.cc-note { font-size: 10px; color: var(--text-3); flex: 1; }
.cc-final { font-size: 16px; font-weight: 800; font-family: var(--font-mono); }
.cc-final.up { color: #dc2626; }
.cc-final.dn { color: #16a34a; }
.cc-svg { width: 100%; height: 110px; display: block; }
.cc-zero { stroke: var(--border); stroke-width: 0.4; stroke-dasharray: 1.5 1.5; vector-effect: non-scaling-stroke; }
.cc-line { fill: none; stroke-width: 1.4; vector-effect: non-scaling-stroke; }
.cc-line.line-up { stroke: #dc2626; }
.cc-line.line-dn { stroke: #16a34a; }
.cc-area { stroke: none; opacity: 0.10; }
.cc-area.area-up { fill: #dc2626; }
.cc-area.area-dn { fill: #16a34a; }
.cc-axis { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-3); font-family: var(--font-mono); margin-top: 4px; }

/* ── 概览：持仓构成 ───────────────────────────────────────── */
.comp-card { padding: 10px 14px; }
.comp-title { font-size: 12px; font-weight: 700; color: var(--text-1); margin-bottom: 8px; }

/* 分荐股策略对比卡片 */
.pick-strat-section { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.ps-card { padding: 12px 14px; cursor: pointer; transition: border-color 0.15s, background 0.15s; }
.ps-card:hover { border-color: var(--accent); }
.ps-card.active { border-color: var(--accent); background: var(--accent-dim); }
.ps-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px; }
.ps-name { font-size: 13px; font-weight: 700; color: var(--text-1); }
.ps-total { font-size: 10px; color: var(--text-3); }
.ps-body { display: flex; align-items: center; gap: 14px; }
.ps-wr { display: flex; flex-direction: column; align-items: center; min-width: 56px; }
.ps-wr-val { font-size: 24px; font-weight: 800; font-family: var(--font-mono); line-height: 1; }
.ps-wr-lbl { font-size: 9px; color: var(--text-3); margin-top: 2px; letter-spacing: 0.04em; }
.ps-stat { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--text-2); font-family: var(--font-mono); }
.ps-line { white-space: nowrap; }
.ps-up { color: #dc2626; font-weight: 600; }
.ps-dn { color: #16a34a; font-weight: 600; }
.ps-wr.wr-good .ps-wr-val { color: #dc2626; }
.ps-wr.wr-mid  .ps-wr-val { color: #b45309; }
.ps-wr.wr-bad  .ps-wr-val { color: #16a34a; }

/* 行内荐股类型徽标 */
.ps-badge { font-size: 10px; padding: 2px 7px; border-radius: 8px; font-weight: 600; white-space: nowrap; }
.ps-momentum { background: rgba(37,99,235,0.12); color: #2563eb; }
.ps-pring { background: rgba(8,145,178,0.12); color: #0891b2; }

.date-in  { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 4px 7px; font-size: 11px; }
.date-sep { font-size: 11px; color: var(--text-3); }
.filter-sel { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 4px 7px; font-size: 11px; }

.force-label { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--text-3); cursor: pointer; user-select: none; }
.force-cb { width: 12px; height: 12px; accent-color: var(--accent); cursor: pointer; }

.vmsg { font-size: 12px; padding: 4px 10px; border-radius: 6px; }
.vmsg.ok  { background: #14532d33; color: #16a34a; }
.vmsg.err { background: #7f1d1d33; color: #dc2626; }

.btn-verify { background: var(--accent); color: #fff; border: none; border-radius: var(--radius-sm); padding: 5px 13px; font-size: 11px; font-weight: 600; cursor: pointer; transition: opacity 0.15s; letter-spacing: 0.02em; }
.btn-verify:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-verify:hover:not(:disabled) { opacity: 0.85; }

/* Stats — formula rows */
.stats-section { display: flex; flex-direction: column; gap: 4px; }
.formula-row {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 6px 12px;
}
.comp-card .formula-row { background: transparent; border: none; padding: 0; }
.fm-item { display: flex; flex-direction: column; align-items: center; min-width: 48px; padding: 2px 6px; }
.fm-val { font-size: 16px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1.2; }
.fm-lbl { font-size: 9px; color: var(--text-3); letter-spacing: 0.04em; margin-top: 1px; }
.fm-sub { font-size: 9px; font-family: var(--font-mono); color: var(--text-3); }
.fm-eq, .fm-op { font-size: 14px; font-weight: 600; color: var(--text-3); font-family: var(--font-mono); }
.fm-divider { width: 1px; height: 28px; background: var(--border-light); margin: 0 6px; flex-shrink: 0; }
.fm-pending .fm-val { color: #b45309; }
.fm-profit .fm-val  { color: #dc2626; }
.fm-loss .fm-val    { color: #16a34a; }
.fm-hit .fm-val     { color: #dc2626; }
.fm-stp .fm-val     { color: #16a34a; }
.fm-accent .fm-val  { color: var(--accent); }

/* Grouped breakdowns */
.breakdown-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
.bd-card { padding: 10px 12px; }
.bd-title { font-size: 12px; font-weight: 700; color: var(--text-1); margin-bottom: 6px; }
.bd-note  { font-size: 10px; font-weight: 400; color: var(--text-3); }
.bd-row {
  display: grid; grid-template-columns: 1fr 36px 52px 64px; gap: 4px;
  align-items: center; padding: 3px 0; font-size: 12px;
}
.bd-head { color: var(--text-3); font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); padding-bottom: 4px; margin-bottom: 2px; }
.bd-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-2); }
.bd-n    { text-align: right; font-family: var(--font-mono); color: var(--text-3); }
.bd-wr   { text-align: right; font-family: var(--font-mono); font-weight: 700; }
.bd-avg  { text-align: right; font-family: var(--font-mono); }
.bd-row .up { color: #dc2626; }
.bd-row .dn { color: #16a34a; }
.wr-good { color: #dc2626; }
.wr-mid  { color: #b45309; }
.wr-bad  { color: #16a34a; }

/* 维度分析：两列网格 */
.analysis-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }

/* 资金曲线风控指标行 */
.rk-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--border); }
.rk-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.rkc-val { font-size: 17px; font-weight: 800; font-family: var(--font-mono); color: var(--text-1); }
.rkc-val.up { color: #dc2626; }
.rkc-val.dn { color: #16a34a; }
.rkc-lbl { font-size: 10px; color: var(--text-3); }

/* 止盈止损有效性 */
.eff-summary { display: flex; align-items: center; justify-content: center; gap: 18px; padding: 8px 0 12px; }
.eff-col { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.eff-val { font-size: 22px; font-weight: 800; font-family: var(--font-mono); }
.eff-val.up { color: #dc2626; }
.eff-val.dn { color: #16a34a; }
.eff-lbl { font-size: 10px; color: var(--text-3); }
.eff-vs { font-size: 12px; color: var(--text-3); font-weight: 600; }
.eff-rows { display: flex; flex-direction: column; gap: 6px; }
.eff-row { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); flex-wrap: wrap; }
.eff-tag { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 8px; white-space: nowrap; }
.eff-tag.up { background: #ef444422; color: #dc2626; }
.eff-tag.dn { background: #22c55e22; color: #16a34a; }
.eff-mid { flex: 1; }
.eff-mid b.up { color: #dc2626; }
.eff-mid b.dn { color: #16a34a; }
.eff-extra { font-family: var(--font-mono); color: var(--text-3); font-size: 11px; white-space: nowrap; }
.eff-hint { font-size: 10px; color: var(--text-3); margin-top: 2px; line-height: 1.4; }

/* 收益分布直方图 */
.hist { display: flex; align-items: flex-end; gap: 6px; height: 130px; padding-top: 6px; }
.hist-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
.hist-cnt { font-size: 10px; font-family: var(--font-mono); color: var(--text-2); height: 14px; }
.hist-bar-wrap { flex: 1; width: 100%; display: flex; align-items: flex-end; justify-content: center; }
.hist-bar { width: 70%; min-height: 2px; border-radius: 3px 3px 0 0; transition: height 0.3s ease; }
.hist-bar.hb-up { background: #dc2626; }
.hist-bar.hb-dn { background: #16a34a; }
.hist-lbl { font-size: 9px; color: var(--text-3); font-family: var(--font-mono); margin-top: 4px; white-space: nowrap; }

/* 最佳 / 最差排行 */
.rank-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.1s; }
.rank-row:last-child { border-bottom: none; }
.rank-row:hover { background: var(--bg-hover); }
.rk-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text-1); }
.rk-name b { font-weight: 700; }
.rk-date { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); white-space: nowrap; }
.rk-ret { font-size: 13px; font-weight: 700; font-family: var(--font-mono); min-width: 56px; text-align: right; }
.rk-ret.up { color: #dc2626; }
.rk-ret.dn { color: #16a34a; }

/* Table card */
.table-card { overflow: visible; padding: 0; }
.pred-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.pred-tbl th {
  background: var(--bg-elevated); color: var(--text-3); font-weight: 600; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.06em; padding: 7px 8px; text-align: left;
  border-bottom: 1px solid var(--border); white-space: nowrap;
}
.pred-tbl td { padding: 6px 8px; border-bottom: 1px solid var(--border); color: var(--text-1); overflow: visible; }
.pred-tbl tr:last-child td { border-bottom: none; }
.pred-row { cursor: pointer; transition: background 0.1s; }
.pred-row:hover { background: var(--bg-hover); }

.sortable { cursor: pointer; user-select: none; transition: color 0.12s; }
.sortable:hover { color: var(--accent); }
.sort-icon { font-size: 10px; opacity: 0.6; margin-left: 2px; }

.td-date { font-size: 11px; color: var(--text-3); white-space: nowrap; font-family: var(--font-mono); }
.td-stock b { font-weight: 700; }
.td-code { font-size: 11px; color: var(--text-3); margin-left: 5px; font-family: var(--font-mono); }
.td-mono { font-family: var(--font-mono); }
.td-stop { color: #16a34a; font-family: var(--font-mono); white-space: nowrap; }
.td-tgt  { color: #dc2626; font-family: var(--font-mono); white-space: nowrap; }
.td-up { color: #dc2626; font-weight: 600; font-family: var(--font-mono); }
.td-dn { color: #16a34a; font-weight: 600; font-family: var(--font-mono); }
.td-dim { color: var(--text-3); font-family: var(--font-mono); }
.pct-sub { font-size: 10px; opacity: 0.75; font-family: var(--font-mono); margin-left: 2px; }
.pct-profit { color: #dc2626; }
.pct-loss   { color: #16a34a; }

.entry-price { color: var(--cyan); font-family: var(--font-mono); font-weight: 600; }

.search-wrap {
  position: relative; display: flex; align-items: center;
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: 0 7px; gap: 4px;
  min-width: 150px;
}
.search-icon { color: var(--text-3); flex-shrink: 0; }
.search-in {
  background: none; border: none; outline: none;
  color: var(--text-1); font-size: 11px; padding: 4px 0;
  width: 120px;
}
.search-in::placeholder { color: var(--text-3); }
.search-clear {
  background: none; border: none; color: var(--text-3); cursor: pointer;
  font-size: 13px; line-height: 1; padding: 0; flex-shrink: 0;
}
.search-clear:hover { color: var(--text-1); }

.pct-chip { display: inline-block; font-size: 10px; padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-weight: 600; }
.pct-chip.chip-up { background: #ef444422; color: #dc2626; }
.pct-chip.chip-dn { background: #22c55e22; color: #16a34a; }

.conf-row { display: flex; align-items: center; gap: 6px; }
.conf-bar { flex: 1; height: 4px; background: var(--border); border-radius: 2px; min-width: 40px; }
.conf-fill { height: 100%; background: var(--accent); border-radius: 2px; }
.conf-num { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); min-width: 20px; text-align: right; }

.risk-badge { padding: 2px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.r-低 { background: #14532d33; color: #16a34a; }
.r-中 { background: #78350f33; color: #b45309; }
.r-高 { background: #7f1d1d33; color: #dc2626; }

.out-badge { padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.o-hit_target { background: #ef444422; color: #dc2626; }
.o-positive   { background: #ef444418; color: #dc2626; }
.o-hit_stop   { background: #22c55e22; color: #16a34a; }
.o-negative   { background: #22c55e18; color: #16a34a; }
.o-neutral    { background: var(--bg-elevated); color: var(--text-2); }
.o-open       { background: var(--bg-elevated); color: var(--text-3); }

.tbl-loading, .tbl-empty { padding: 40px; text-align: center; color: var(--text-3); }
.tbl-empty .sub { font-size: 12px; margin-top: 6px; }

.td-action { text-align: right; }
.detail-link {
  font-size: 11px; color: var(--accent); cursor: pointer;
  opacity: 0.7; white-space: nowrap; transition: opacity 0.12s;
}
.pred-row:hover .detail-link { opacity: 1; }

@media (max-width: 768px) {
  /* 预测表列多，整表横向滚动 */
  .table-card { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .pred-tbl { min-width: 700px; }
  .verdict { flex-wrap: wrap; }
  .vd-hero { align-items: flex-start; text-align: left; }
}
@media (max-width: 600px) {
  .vfy-wrap { padding: 12px; }
}
</style>
