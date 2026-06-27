<template>
  <div class="ir-layout">
    <!-- ── 左侧：历史报告 ── -->
    <aside class="ir-history">
      <div class="hist-title">报告</div>
      <div v-if="history.length === 0" class="hist-empty">暂无报告</div>
      <div
        v-for="h in history"
        :key="h.slug"
        :class="{ 'hist-item': true, active: currentSlug === h.slug, 'hist-item--err': h.status === 'error' }"
        @click="loadReport(h.slug)"
      >
        <div class="hist-main">
          <div class="hist-kw">
            <span v-if="h.status === 'error'" class="hist-err-badge">⚠</span>
            {{ h.display_name || h.keyword }}
          </div>
          <div v-if="h.status === 'error'" class="hist-err-stage">
            {{ h.stage ? `失败于：${h.stage}` : '分析失败' }} · {{ fmtDate(h.updated_at) }}
          </div>
          <div v-else class="hist-meta">{{ fmtDate(h.updated_at || h.created_at) }} · {{ h.report_count }} 篇研报</div>
        </div>
      </div>
    </aside>

    <!-- ── 主区 ── -->
    <main class="ir-main">
      <!-- 标题区（纯展示：分析主题与触发由管理后台统一收口，此处只看报告） -->
      <div class="ir-hero">
        <div class="hero-text">
          <h2>产业链分析 · 研报精读</h2>
          <p class="hero-sub">汇聚行业研报 + 机构荐股数据库，AI 逐层拆解产业链构成与成本占比、整合机构评级共识并给出多只标的。<b>由后台每日定时生成</b>，新增/重跑主题请在管理后台操作。</p>
        </div>
        <!-- 后台分析中：显示详细进度 -->
        <div v-if="analyzing" class="hero-progress">
          <div class="hp-top">
            <i class="run-dot"></i>
            <span class="hp-stage">{{ stage }}</span>
            <span class="hp-pct">{{ prog?.progress || 0 }}%</span>
            <span class="hp-eta" v-if="prog?.eta_text">约 {{ prog.eta_text }}</span>
          </div>
          <div class="hp-bar-track">
            <div class="hp-bar-fill" :style="{ width: (prog?.progress || 0) + '%' }"></div>
          </div>
          <div class="hp-stats" v-if="prog?.report_count || prog?.read_total">
            <span v-if="prog?.report_count">📄 {{ prog.report_count }} 篇研报</span>
            <span v-if="prog?.n_blog"> · 📋 {{ prog.n_blog }} 篇纪要</span>
            <span v-if="prog?.pdf_total"> · ⬇️ {{ prog.pdf_done || 0 }}/{{ prog.pdf_total }} PDF</span>
            <span v-if="prog?.cached_count != null && prog.read_total"> · ⚡缓存 {{ prog.cached_count }}</span>
            <span v-if="prog?.map_total"> · 🔬 MAP {{ prog.map_done || 0 }}/{{ prog.map_total }}</span>
          </div>
        </div>
      </div>

      <!-- 错误 -->
      <div v-if="errorMsg" class="error-card">⚠️ {{ errorMsg }}</div>

      <!-- 报告看板（后台重跑时仍展示上一版报告，不被进度页打断） -->
      <div v-if="report" class="report-board">
        <div class="board-head">
          <div class="bh-info">
            <h3>{{ report.topic_name || report.keyword }} · 产业链深度分析</h3>
            <div v-if="report.keywords && report.keywords.length > 1" class="bh-kws">
              <span class="bh-kws-label">检索关键词</span>
              <span v-for="k in report.keywords" :key="k" class="bh-kw-chip">{{ k }}</span>
            </div>
            <div class="bh-meta">
              <span>更新 {{ fmtDate(report.updated_at) || report.generated_at || fmtDate(report.created_at) }}</span>
              <span v-if="report.analysis_round" class="round-tag">第 {{ report.analysis_round }} 次</span>
              <span class="bh-dot">·</span>
              <span>研报 {{ (report.reports || []).length }} 篇</span>
              <template v-if="blogArticles.length">
                <span class="bh-dot">·</span>
                <span>纪要 {{ blogArticles.length }} 篇</span>
              </template>
              <span class="bh-dot">·</span>
              <span class="bh-ai">AI精读 {{ report.facts_count || report.pdf_used || 0 }} 篇</span>
              <template v-if="report.data_range && report.data_range.from">
                <span class="bh-dot">·</span>
                <span class="bh-range">{{ report.data_range.from }} ~ {{ report.data_range.to }}</span>
              </template>
            </div>
          </div>
          <div class="board-ops">
            <button class="op-btn" @click="exportJson">导出 JSON</button>
          </div>
        </div>

        <!-- 重新分析时：报告看板顶部进度条（不打断已有报告展示） -->
        <div v-if="analyzing || prog?.status === 'error'" class="reboard-progress" :class="{ 'rbp--err': prog?.status === 'error' }">
          <div class="rbp-row">
            <i class="run-dot" :class="{ 'run-dot--err': prog?.status === 'error' }"></i>
            <span class="rbp-stage">{{ stage }}</span>
            <span class="rbp-pct">{{ prog?.progress || 0 }}%</span>
            <span class="rbp-eta" v-if="prog?.eta_text && prog?.status !== 'error'">约 {{ prog.eta_text }}</span>
            <span class="rbp-detail" v-if="prog?.report_count"> · 📄 {{ prog.report_count }} 篇</span>
            <span class="rbp-detail" v-if="prog?.n_blog"> · 📋 纪要 {{ prog.n_blog }}</span>
            <span class="rbp-detail" v-if="prog?.pdf_total"> · ⬇️ {{ prog.pdf_done || 0 }}/{{ prog.pdf_total }}</span>
            <span class="rbp-detail" v-if="prog?.cached_count != null && prog?.read_total"> · ⚡{{ prog.cached_count }}</span>
            <span class="rbp-detail" v-if="prog?.map_total"> · 🔬 {{ prog.map_done || 0 }}/{{ prog.map_total }}</span>
          </div>
          <div v-if="prog?.status === 'error'" class="rbp-err-msg">{{ prog?.error || '分析出错' }}</div>
          <div class="rbp-bar"><div class="rbp-fill" :style="{ width: (prog?.progress || 0) + '%' }" :class="{ 'rbp-fill--err': prog?.status === 'error' }"></div></div>
        </div>

        <div class="tab-bar">
          <template v-for="t in tabs" :key="t.id">
            <div v-if="t.sep" class="tab-sep"></div>
            <button v-else
              :class="{ active: activeTab === t.id }"
              @click="activeTab = t.id"
            >{{ t.label }}</button>
          </template>
        </div>

        <div class="tab-body">
          <!-- 瓶颈卡位（瓶颈理论核心：卡脖子环节排行 + 价值迁移 + 海外催化映射） -->
          <div v-if="activeTab === 'bottleneck'">
            <div class="decision-head">
              <h4>🎯 瓶颈卡位 · 卡脖子环节优先</h4>
              <span class="decision-asof">押产业链最卡脖子的上游核心环节，回避终端整机巨头</span>
            </div>

            <!-- 瓶颈环节排行（按卡脖子评分降序） -->
            <div class="panel" v-if="bottleneckRanking.length">
              <h4>🔒 瓶颈环节排行 · 卡脖子评分</h4>
              <p class="cost-hint">评分越高越卡脖子（国产化率低 / 集中度高 / 技术壁垒高 / 不可替代）。这是“押上游卡脖子环节”的核心抓手。</p>
              <div class="bn-list">
                <div class="bn-item" v-for="(b, i) in bottleneckRanking" :key="i">
                  <div class="bn-rank">{{ i + 1 }}</div>
                  <div class="bn-body">
                    <div class="bn-top">
                      <b class="bn-name">{{ b.name }}</b>
                      <span class="bn-score" :class="scoreClass(b.score)">卡脖子 {{ b.score ?? '-' }}</span>
                      <span class="bn-vshare" v-if="b.value_share">价值量 {{ b.value_share }}</span>
                    </div>
                    <div class="bn-bar"><div class="bn-bar-fill" :class="scoreClass(b.score)" :style="{ width: Math.max(0, Math.min(100, Number(b.score) || 0)) + '%' }"></div></div>
                    <div class="bn-reason" v-if="b.reason">{{ b.reason }}</div>
                    <div class="bn-leader" v-if="b.leader">🏆 龙头：{{ b.leader }}</div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty-tip">本次分析未生成瓶颈环节排行（研报样本不足或解析失败，可重新分析）。</div>

            <!-- 个股卡脖子评分榜（个股维度） -->
            <div class="panel" v-if="bottleneckStocks.length">
              <h4>🏅 个股卡脖子评分榜</h4>
              <p class="cost-hint">从研报筛出处于卡脖子上游核心环节的个股，按卡脖子评分排序。市值/PE/年涨幅取自实时行情，关注度=库内研报家数，预期利润增速取一致预期 EPS，缺数据留空。</p>
              <div class="bs-scroll">
                <table class="data-table bs-table">
                  <thead>
                    <tr>
                      <th>#</th><th>标的</th><th>瓶颈环节</th><th>卡脖子</th>
                      <th>市值(亿)</th><th>年涨幅</th><th>PE</th><th>估值判定</th>
                      <th>关注度</th><th>预期利润增速</th><th>上季度增速</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(s, i) in bottleneckStocks" :key="s.code || i">
                      <td class="bs-rank">{{ i + 1 }}</td>
                      <td>
                        <b>{{ s.name || qOf(s.code).name }}</b>
                        <span class="mono bs-code" v-if="s.code">{{ s.code }}</span>
                        <div class="bs-reason" v-if="s.reason">{{ s.reason }}</div>
                      </td>
                      <td>{{ s.segment || '-' }}</td>
                      <td><span class="bn-score" :class="scoreClass(s.score)">{{ s.score ?? '-' }}</span></td>
                      <td class="mono">{{ s.mcap_yi != null ? Math.round(s.mcap_yi) : '-' }}</td>
                      <td class="mono" :class="pctClass(s.year_change)">{{ fmtPct(s.year_change) }}</td>
                      <td class="mono">{{ s.pe_ttm != null && s.pe_ttm !== 0 ? s.pe_ttm : '-' }}</td>
                      <td><span v-if="s.valuation" class="bs-val" :class="valuationClass(s.valuation)">{{ s.valuation }}</span><span v-else>-</span></td>
                      <td class="mono">{{ s.attention != null ? s.attention : '-' }}</td>
                      <td class="mono" :class="pctClass(s.fwd_growth)">{{ fmtPct(s.fwd_growth) }}</td>
                      <td class="mono" :class="pctClass(s.prev_growth)">{{ fmtPct(s.prev_growth) }}</td>
                      <td><button v-if="s.code" class="op-btn xs" @click="addWatch(s.code, s.name || qOf(s.code).name)">+自选</button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <!-- 价值量迁移 -->
            <div class="panel value-mig" v-if="valueMigration && (valueMigration.trend || valueMigration.to)">
              <h4>🔀 价值量迁移 · 未来瓶颈在哪</h4>
              <div class="vm-flow" v-if="valueMigration.from || valueMigration.to">
                <span class="vm-node from">{{ valueMigration.from || '—' }}</span>
                <span class="vm-arrow">➜</span>
                <span class="vm-node to">{{ valueMigration.to || '—' }}</span>
              </div>
              <p class="para" v-if="valueMigration.trend">{{ valueMigration.trend }}</p>
              <div class="vm-benef" v-if="valueMigration.beneficiary">🎯 受益：{{ valueMigration.beneficiary }}</div>
            </div>

            <!-- 海外一级催化 → 国内卡位供应商映射 -->
            <div class="panel" v-if="overseasMapping.length">
              <h4>🌐 海外催化 → 国内卡位映射</h4>
              <p class="cost-hint">由海外龙头（英伟达 / 台积电等）的资本开支 / 订单 / 技术路线倒推国内最卡脖子的二阶上游供应商。</p>
              <div class="om-list">
                <div class="om-item" v-for="(m, i) in overseasMapping" :key="i">
                  <div class="om-head">
                    <span class="om-anchor">{{ m.overseas_anchor }}</span>
                    <span class="om-cert" :class="'conv-' + impKey(m.certainty)" v-if="m.certainty">确定性 {{ m.certainty }}</span>
                  </div>
                  <div class="om-trans" v-if="m.transmission">{{ m.transmission }}</div>
                  <div class="om-seg" v-if="m.domestic_segment">🔒 卡位环节：<b>{{ m.domestic_segment }}</b></div>
                  <div class="om-cat" v-if="m.catalyst">{{ m.catalyst }}</div>
                  <div class="om-stocks" v-if="(m.stocks || []).length">
                    <div class="om-stock" v-for="(s, si) in m.stocks" :key="si">
                      <b>{{ s.name || qOf(s.code).name }}</b>
                      <span class="mono om-code" v-if="s.code">{{ s.code }}</span>
                      <span class="mono om-price" v-if="qOf(s.code).price">¥{{ qOf(s.code).price }}</span>
                      <span class="om-role" v-if="s.role">{{ s.role }}</span>
                      <button v-if="s.code" class="op-btn xs" @click="addWatch(s.code, s.name || qOf(s.code).name)">+自选</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 明日操作决策 -->
          <div v-if="activeTab === 'decision'">
            <div class="decision-head">
              <h4>📌 明日操作建议</h4>
              <span class="decision-asof">
                基于 {{ report.facts_count || report.pdf_used || 0 }} 篇研报 · 更新于 {{ fmtDate(report.updated_at) || report.generated_at }}
              </span>
            </div>
            <p class="disclaimer">⚠️ 以下为基于研报与估值的 AI 辅助判断，非投资建议，决策与风险自负。</p>

            <div class="panel market-view" v-if="decision.market_view">
              <h4>🧭 产业短期看法</h4>
              <p class="para">{{ decision.market_view }}</p>
            </div>

            <div class="picks-banner" v-if="topPicks.length">
              <span class="pb-label">🥇 首选（{{ topPicks.length }} 只）</span>
              <div class="pb-list">
                <span class="pb-text" v-for="(tp, i) in topPicks" :key="i">
                  <b v-if="tp.name">{{ tp.name }}</b><span v-if="tp.code" class="mono"> {{ tp.code }}</span>
                  <span v-if="tp.chain_position" class="cp-tag" :class="'cp-' + chainPosKey(tp.chain_position)">{{ tp.chain_position }}</span>
                  <template v-if="tp.reason">{{ tp.name ? ' · ' : '' }}{{ tp.reason }}</template>
                </span>
              </div>
            </div>

            <div class="cand-grid" v-if="buyCandidates.length">
              <div class="cand-card" v-for="(c, i) in buyCandidates" :key="i"
                   :class="{ 'is-terminal': chainPosKey(c.chain_position) === 'terminal' }">
                <div class="cc-head">
                  <div class="cc-name">
                    <span class="cc-rank">#{{ i + 1 }}</span>
                    <b>{{ c.name }}</b><span class="mono cc-code">{{ c.code }}</span>
                  </div>
                  <span class="cc-action" :class="actionClass(c.action)">{{ c.action || '关注' }}</span>
                </div>
                <div class="cc-tags">
                  <span v-if="c.chain_position" class="cc-tag cp" :class="'cp-' + chainPosKey(c.chain_position)">{{ c.chain_position }}</span>
                  <span v-if="c.tier" class="cc-tag tier" :class="'tier-' + tierKey(c.tier)">{{ c.tier }}</span>
                  <span class="cc-tag conv" :class="'conv-' + impKey(c.conviction)">信心 {{ c.conviction || '-' }}</span>
                  <span class="cc-tag" v-if="c.horizon">{{ c.horizon }}</span>
                  <span class="cc-tag up" :class="upsideClass(c.upside)" v-if="c.upside">空间 {{ c.upside }}</span>
                </div>
                <div class="cc-prices">
                  <div><span>现价</span><b class="mono">{{ c.current ?? '-' }}</b></div>
                  <div><span>买入区间</span><b class="mono">{{ c.entry || '-' }}</b></div>
                  <div><span>目标价</span><b class="mono">{{ c.target ?? '-' }}</b></div>
                  <div><span>止损</span><b class="mono">{{ c.stop || '-' }}</b></div>
                </div>
                <div class="cc-row" v-if="c.catalyst"><span>催化</span><p>{{ c.catalyst }}</p></div>
                <div class="cc-row" v-if="c.logic"><span>逻辑</span><p>{{ c.logic }}</p></div>
                <div class="cc-row risk" v-if="c.risk"><span>风险</span><p>{{ c.risk }}</p></div>
                <button class="op-btn sm cc-add" @click="addWatch(c.code, c.name)">+ 自选</button>
              </div>
            </div>
            <div v-else class="empty-tip">本次分析未生成明确的操作建议（研报样本不足或解析失败，可重新分析）。</div>

            <div class="panel" v-if="(decision.watch || []).length">
              <h4>👀 次选关注</h4>
              <div class="chips">
                <span v-for="(w, i) in decision.watch" :key="i" class="kp-chip">{{ w }}</span>
              </div>
            </div>
            <div class="panel notes-panel" v-if="decision.notes">
              <h4>📝 组合与纪律</h4>
              <p class="para">{{ decision.notes }}</p>
            </div>
          </div>

          <!-- 总览 -->
          <div v-if="activeTab === 'overview'">

            <!-- 数据来源与分析过程 -->
            <div class="dsp-card">
              <div class="dsp-head">数据来源 &amp; 分析过程</div>

              <!-- 统计数字行 -->
              <div class="dsp-stats">
                <div class="dsp-stat">
                  <span class="dss-val">{{ (report.reports || []).length }}</span>
                  <span class="dss-lbl">机构研报</span>
                  <span class="dss-sub">{{ reportOrgCount }} 家机构</span>
                </div>
                <div class="dsp-stat" v-if="blogArticles.length">
                  <span class="dss-val">{{ blogArticles.length }}</span>
                  <span class="dss-lbl">调研纪要</span>
                  <span class="dss-sub">知识星球</span>
                </div>
                <div class="dsp-stat dsp-stat--ai">
                  <span class="dss-val">{{ report.facts_count || report.pdf_used || 0 }}</span>
                  <span class="dss-lbl">AI 精读</span>
                  <span class="dss-sub">MAP 事实抽取</span>
                </div>
                <div class="dsp-stat" v-if="(res.key_segments || []).length">
                  <span class="dss-val">{{ (res.key_segments || []).length }}</span>
                  <span class="dss-lbl">拆解环节</span>
                  <span class="dss-sub">产业链层级</span>
                </div>
              </div>

              <!-- 分析流程管道 -->
              <div class="dsp-pipe">
                <div class="pp-step">
                  <span class="pp-num">1</span>
                  <div class="pp-body">
                    <span class="pp-lbl">识别相关标的</span>
                    <span class="pp-val">{{ Object.keys(report.quotes || {}).length }} 只</span>
                  </div>
                </div>
                <span class="pp-arr">›</span>
                <div class="pp-step">
                  <span class="pp-num">2</span>
                  <div class="pp-body">
                    <span class="pp-lbl">收集机构研报</span>
                    <span class="pp-val">{{ (report.reports || []).length }} 篇</span>
                  </div>
                </div>
                <template v-if="blogArticles.length">
                  <span class="pp-arr">›</span>
                  <div class="pp-step">
                    <span class="pp-num">3</span>
                    <div class="pp-body">
                      <span class="pp-lbl">调研纪要</span>
                      <span class="pp-val">{{ blogArticles.length }} 篇</span>
                    </div>
                  </div>
                </template>
                <span class="pp-arr">›</span>
                <div class="pp-step pp-step--ai">
                  <span class="pp-num">{{ blogArticles.length ? 4 : 3 }}</span>
                  <div class="pp-body">
                    <span class="pp-lbl">AI 逐篇精读</span>
                    <span class="pp-val">{{ report.facts_count || report.pdf_used || 0 }} 篇</span>
                  </div>
                </div>
                <span class="pp-arr">›</span>
                <div class="pp-step pp-step--done">
                  <span class="pp-num">{{ blogArticles.length ? 5 : 4 }}</span>
                  <div class="pp-body">
                    <span class="pp-lbl">AI 汇总合成</span>
                    <span class="pp-val">✓ 已完成</span>
                  </div>
                </div>
              </div>

              <!-- 数据覆盖 + 精读率 -->
              <div class="dsp-footer">
                <span v-if="report.data_range && report.data_range.from">
                  数据覆盖 {{ report.data_range.from }} ~ {{ report.data_range.to }}
                </span>
                <span
                  v-if="(report.reports || []).length && (report.facts_count || report.pdf_used)"
                  class="dsp-ratio"
                >精读覆盖率 {{ Math.round(((report.facts_count || report.pdf_used) / (report.reports || []).length) * 100) }}%</span>
              </div>
            </div>

            <div class="panel">
              <h4>📋 产业全景</h4>
              <p class="para">{{ res.overview || '暂无' }}</p>
            </div>
            <div class="panel" v-if="res.market_size">
              <h4>📈 市场规模</h4>
              <p class="para">{{ res.market_size }}</p>
            </div>
            <div class="points-grid">
              <div class="point-card pc-leader" v-if="res.leader">
                <div class="pc-label">🏆 龙头股</div>
                <div class="pc-text">{{ res.leader }}</div>
              </div>
              <div class="point-card pc-bottleneck" v-if="res.bottleneck">
                <div class="pc-label">🔒 最大卡脖子</div>
                <div class="pc-text">{{ res.bottleneck }}</div>
              </div>
              <div class="point-card pc-irrep" v-if="res.irreplaceable">
                <div class="pc-label">💎 不可替代性最强</div>
                <div class="pc-text">{{ res.irreplaceable }}</div>
              </div>
              <div class="point-card pc-catchup" v-if="res.fastest_catchup">
                <div class="pc-label">🚀 追赶最快</div>
                <div class="pc-text">{{ res.fastest_catchup }}</div>
              </div>
              <div class="point-card pc-gap" v-if="res.leader_gap">
                <div class="pc-label">📏 与龙头差距</div>
                <div class="pc-text">{{ res.leader_gap }}</div>
              </div>
            </div>

            <div class="panel" v-if="(res.milestones || []).length">
              <h4>🗓 产业里程碑</h4>
              <div class="timeline">
                <div class="tl-item" v-for="(m, i) in res.milestones" :key="i">
                  <div class="tl-dot"></div>
                  <div class="tl-date">{{ m.date }}</div>
                  <div class="tl-event">{{ m.event }}</div>
                </div>
              </div>
            </div>

          </div>

          <!-- 近期动态（产业链最近的新增信息/边际变化） -->
          <div v-if="activeTab === 'recent'">
            <h4>🆕 近期新增信息 · 产业逻辑更新</h4>
            <p class="cost-hint">提炼自最近 1-3 个月研报中**新出现的产业逻辑与边际变化**（新催化 / 技术 / 供需 / 政策 / 订单产能 / 价格 / 竞争 / 预期），按时间由新到旧。</p>
            <div class="upd-list" v-if="recentUpdates.length">
              <div class="upd-item" v-for="(u, i) in recentUpdates" :key="i">
                <div class="upd-side">
                  <span class="upd-date mono">{{ u.date || '—' }}</span>
                  <span class="upd-cat" v-if="u.category">{{ u.category }}</span>
                </div>
                <div class="upd-body">
                  <div class="upd-title">{{ u.title }}</div>
                  <p class="upd-detail" v-if="u.detail">{{ u.detail }}</p>
                  <div class="upd-foot">
                    <span class="upd-impact" :class="impactClass(u.impact)" v-if="u.impact">📊 {{ u.impact }}</span>
                    <span class="upd-benef" v-if="u.beneficiary">🎯 受益：{{ u.beneficiary }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty-tip">近期研报中暂未提取到明确的新增产业逻辑/边际变化（可重新分析或等当日研报增量入库后再看）。</div>
          </div>

          <!-- 成本构成（分层树状卡片 + 逐层下钻 + 叶子挂多只个股）-->
          <div v-if="activeTab === 'cost'">
            <h4>💰 成本 / 价值构成 · 逐层拆解</h4>
            <template v-if="costBars.length">
              <p class="cost-hint">
                每个环节标注「占上层 X%」与「占整体 Y%」。点击卡片展开下一层，逐层下钻到最细环节；最细环节下方挂该环节的头部个股（可加自选）。
              </p>
              <!-- 顶层概览条（一眼看清大类占比） -->
              <div class="cost-overview">
                <div
                  v-for="c1 in costBars" :key="c1.name"
                  class="cov-seg"
                  :style="{ width: Math.max(c1.percent, 4) + '%', background: c1.color }"
                  :title="c1.name + ' ' + c1.percent + '%'"
                >
                  <span class="cov-name">{{ c1.name }}</span>
                  <span class="cov-pct">{{ c1.percent }}%</span>
                </div>
              </div>

              <!-- 分层树状卡片：每个顶层大类一张可展开卡片 -->
              <div class="cost-tree">
                <BomNode
                  v-for="c1 in costBars" :key="c1.name"
                  :node="c1"
                  :color="c1.color || '#6366f1'"
                  :depth="1"
                  :parent-share="100"
                  :stock-info="stockInfoMap"
                />
              </div>
            </template>
            <div v-else class="empty-tip">研报中未提取到明确的成本占比数据</div>

            <!-- 降本路径 -->
            <div class="panel" v-if="costDownPaths.length" style="margin-top:22px">
              <h4>📉 降本路径</h4>
              <table class="data-table">
                <thead><tr><th>降本抓手</th><th>机理/环节</th><th>预计降幅</th><th>兑现节奏</th><th>受益方</th></tr></thead>
                <tbody>
                  <tr v-for="(p, i) in costDownPaths" :key="i">
                    <td><b>{{ p.lever }}</b></td>
                    <td>{{ p.mechanism }}</td>
                    <td class="dn-mag">{{ p.magnitude || '-' }}</td>
                    <td>{{ p.horizon || '-' }}</td>
                    <td>{{ p.beneficiary || '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- 细分环节 -->
          <div v-if="activeTab === 'segments'">
            <h4>🔗 核心环节拆解</h4>
            <p class="cost-hint">按「卡脖子评分」从高到低排列，越靠前越是产业链的瓶颈核心环节。</p>
            <div class="seg-grid">
              <div class="seg-card" v-for="(s, i) in (res.key_segments || [])" :key="i"
                   :class="{ 'seg-bottleneck': Number(s.bottleneck_score) >= 70 }">
                <div class="seg-top">
                  <span class="seg-name">{{ s.name }}</span>
                  <span class="seg-badge" :class="'b-' + impKey(s.importance)">{{ s.importance }}</span>
                </div>
                <div class="seg-row" v-if="s.bottleneck_score != null && s.bottleneck_score !== ''">
                  <span>卡脖子评分</span><b class="seg-score" :class="scoreClass(s.bottleneck_score)">{{ s.bottleneck_score }}</b>
                </div>
                <div class="seg-row" v-if="s.leader"><span>龙头</span><b>{{ s.leader }}</b></div>
                <div class="seg-row" v-if="s.localization_rate"><span>国产化率</span><b>{{ s.localization_rate }}</b></div>
                <div class="seg-row" v-if="s.substitution_risk"><span>被替代风险</span><b :class="'risk-' + impKey(s.substitution_risk)">{{ s.substitution_risk }}</b></div>
                <p class="seg-desc">{{ s.description }}</p>
              </div>
            </div>
            <div v-if="!(res.key_segments || []).length" class="empty-tip">暂无环节数据</div>
          </div>

          <!-- 竞争格局（国内 + 海外排行榜） -->
          <div v-if="activeTab === 'landscape'">
            <h4>🏆 竞争格局 · 国内外排行</h4>
            <p class="para" v-if="landscape && landscape.summary" style="margin-bottom:16px">{{ landscape.summary }}</p>
            <div class="rank-grid" v-if="landscape">
              <div class="rank-col">
                <div class="rank-head">🌍 全球排名 · 市场份额（按上中下游）</div>
                <template v-for="grp in landscapeGlobal" :key="'gg'+grp.seg">
                  <div class="rank-seg-label">{{ grp.seg }}</div>
                  <div class="rank-row" v-for="(g, i) in grp.rows" :key="'g'+grp.seg+i">
                    <span class="rank-no">{{ i + 1 }}</span>
                    <div class="rank-body">
                      <div class="rank-name">{{ g.company }}<span v-if="g.country" class="rank-flag">{{ g.country }}</span></div>
                      <div class="share-line" v-if="g.share">
                        <div class="share-track"><div class="share-fill gl" :style="{ width: sharePct(g.share) + '%' }"></div></div>
                        <span class="share-val mono">{{ g.share }}</span>
                      </div>
                      <div class="rank-edge">{{ g.edge }}</div>
                    </div>
                  </div>
                </template>
                <div v-if="!landscapeGlobal.length" class="empty-tip">暂无全球数据</div>
              </div>
              <div class="rank-col">
                <div class="rank-head">🇨🇳 国内排名 · 市场份额（按上中下游）</div>
                <template v-for="grp in landscapeDomestic" :key="'dd'+grp.seg">
                  <div class="rank-seg-label">{{ grp.seg }}</div>
                  <div class="rank-row" v-for="(d, i) in grp.rows" :key="'d'+grp.seg+i">
                    <span class="rank-no dom">{{ i + 1 }}</span>
                    <div class="rank-body">
                      <div class="rank-name">{{ d.company }}<span v-if="d.global_share" class="rank-gshare">🌍 全球 {{ d.global_share }}</span></div>
                      <div class="share-line" v-if="d.share">
                        <div class="share-track"><div class="share-fill dom" :style="{ width: sharePct(d.share) + '%' }"></div></div>
                        <span class="share-val mono">{{ d.share }}</span>
                      </div>
                      <div class="rank-edge">{{ d.edge }}</div>
                    </div>
                  </div>
                </template>
                <div v-if="!landscapeDomestic.length" class="empty-tip">暂无国内数据</div>
              </div>
            </div>
            <div v-else class="empty-tip">研报中未提取到明确的竞争格局数据</div>
          </div>

          <!-- 产业链分层（上中下游 → 细分环节 → 标的） -->
          <div v-if="activeTab === 'chain'">
            <h4>🧬 上中下游标的拆解</h4>
            <div class="chain-wrap" v-if="supplyChain.length">
              <div class="chain-seg" v-for="(seg, si) in supplyChain" :key="si">
                <div class="chain-seg-head" :class="'cs-' + si">
                  <span class="cs-tag">{{ seg.segment }}</span>
                  <span class="cs-desc">{{ seg.desc }}</span>
                </div>
                <div class="chain-link" v-for="(lk, li) in (seg.links || [])" :key="li">
                  <div class="cl-name">{{ lk.name }}<span v-if="lk.note" class="cl-note">{{ lk.note }}</span></div>
                  <div class="cl-stocks">
                    <div class="cl-stock" v-for="(s, ci) in (lk.stocks || [])" :key="ci">
                      <div class="cls-main">
                        <b class="cls-name">{{ s.name || qOf(s.code).name }}</b>
                        <span class="cls-code mono" v-if="s.code">{{ s.code }}</span>
                        <span class="cls-price mono" v-if="qOf(s.code).price">¥{{ qOf(s.code).price }}</span>
                        <button v-if="s.code" class="op-btn xs" @click="addWatch(s.code, s.name || qOf(s.code).name)">+自选</button>
                      </div>
                      <div class="cls-role" v-if="s.role">{{ s.role }}</div>
                      <div class="cls-share" v-if="s.share || s.tier_share">
                        <span class="cls-share-item" v-if="s.share"><i>份额</i>{{ s.share }}</span>
                        <span class="cls-share-item tier" v-if="s.tier_share"><i>高/中低端</i>{{ s.tier_share }}</span>
                      </div>
                    </div>
                    <div v-if="!(lk.stocks || []).length" class="cls-empty">暂无标的</div>
                  </div>
                </div>
                <div v-if="!(seg.links || []).length" class="empty-tip">暂无该段数据</div>
              </div>
            </div>
            <div v-else class="empty-tip">研报中未提取到明确的上中下游拆解数据</div>
          </div>

          <!-- 链主链路（围绕链主拆整条链路上的供应商及份额） -->
          <div v-if="activeTab === 'chainmaster'">
            <h4>🔗 链主链路 · 供应商与份额</h4>
            <p class="cost-hint">以主导整条产业链需求与利润分配的「链主」（如光模块的英伟达、谷歌）为锚，沿其需求链路逐环节拆出供应商及对该链主的供货份额。</p>
            <div class="cm-wrap" v-if="chainMasters.length">
              <div class="cm-master" v-for="(m, mi) in chainMasters" :key="mi">
                <div class="cm-head">
                  <span class="cm-name">{{ m.name }}</span>
                  <span class="cm-country" v-if="m.country">{{ m.country }}</span>
                  <span class="cm-role" v-if="m.role">{{ m.role }}</span>
                </div>
                <p class="cm-demand" v-if="m.demand">{{ m.demand }}</p>
                <div class="cm-links">
                  <div class="cm-link" v-for="(lk, li) in (m.links || [])" :key="li">
                    <div class="cm-link-head">
                      <span class="cm-seg">{{ lk.segment }}</span>
                      <span class="cm-note" v-if="lk.note">{{ lk.note }}</span>
                    </div>
                    <div class="cm-suppliers">
                      <div class="cm-supplier" v-for="(s, si) in (lk.suppliers || [])" :key="si">
                        <div class="cms-main">
                          <b class="cms-name">{{ s.name || qOf(s.code).name }}</b>
                          <span class="cms-country" v-if="s.country">{{ s.country }}</span>
                          <span class="cms-code mono" v-if="s.code">{{ s.code }}</span>
                          <span class="cms-price mono" v-if="qOf(s.code).price">¥{{ qOf(s.code).price }}</span>
                          <button v-if="s.code" class="op-btn xs" @click="addWatch(s.code, s.name || qOf(s.code).name)">+自选</button>
                        </div>
                        <div class="cms-bottom">
                          <span class="cms-share" v-if="s.share"><i>供货份额</i>{{ s.share }}</span>
                          <span class="cms-role" v-if="s.role">{{ s.role }}</span>
                        </div>
                      </div>
                      <div v-if="!(lk.suppliers || []).length" class="cls-empty">暂无供应商</div>
                    </div>
                  </div>
                  <div v-if="!(m.links || []).length" class="empty-tip">暂无该链主的链路数据</div>
                </div>
              </div>
            </div>
            <div v-else class="empty-tip">研报中未提取到明确的链主链路数据</div>
          </div>

          <!-- 生产设备（制造所需专用设备 → 工序/厂商份额/卡脖子） -->
          <div v-if="activeTab === 'equipment'">
            <h4>🏭 生产设备 · 厂商份额与卡脖子</h4>
            <p class="cost-hint">制造该产业链产品所需的关键专用设备，按生产工序排列，给出设备厂商的全球/国内市场份额排名与国产化（卡脖子）逻辑。</p>
            <p class="para" v-if="productionEquipment && productionEquipment.summary" style="margin-bottom:16px">{{ productionEquipment.summary }}</p>
            <div class="eq-wrap" v-if="equipmentList.length">
              <div class="eq-card" v-for="(eq, ei) in equipmentList" :key="ei">
                <div class="eq-head">
                  <span class="eq-step">{{ ei + 1 }}</span>
                  <div class="eq-title">
                    <b class="eq-name">{{ eq.name }}</b>
                    <span class="eq-proc" v-if="eq.process">{{ eq.process }}</span>
                    <span class="eq-imp" :class="'imp-' + (eq.importance || '')" v-if="eq.importance">{{ eq.importance }}</span>
                  </div>
                  <span class="eq-score bn-score" :class="scoreClass(eq.bottleneck_score)" v-if="eq.bottleneck_score != null">卡脖子 {{ eq.bottleneck_score }}</span>
                </div>
                <div class="eq-func" v-if="eq.function">{{ eq.function }}</div>
                <div class="eq-meta">
                  <span class="eq-tag" v-if="eq.value_share"><i>设备投资占比</i>{{ eq.value_share }}</span>
                  <span class="eq-tag" v-if="eq.localization_rate"><i>国产化率</i>{{ eq.localization_rate }}</span>
                </div>
                <div class="eq-reason" v-if="eq.bottleneck_reason">⚠️ {{ eq.bottleneck_reason }}</div>
                <div class="eq-makers">
                  <div class="eq-maker-col">
                    <div class="eq-maker-head">🌍 全球厂商</div>
                    <div class="eq-maker-row" v-for="(g, gi) in ((eq.makers || {}).global || [])" :key="'g'+gi">
                      <span class="rank-no">{{ gi + 1 }}</span>
                      <div class="eq-maker-body">
                        <div class="eq-maker-name">{{ g.company }}<span v-if="g.country" class="rank-flag">{{ g.country }}</span></div>
                        <div class="share-line" v-if="g.share">
                          <div class="share-track"><div class="share-fill gl" :style="{ width: sharePct(g.share) + '%' }"></div></div>
                          <span class="share-val mono">{{ g.share }}</span>
                        </div>
                        <div class="rank-edge" v-if="g.edge">{{ g.edge }}</div>
                      </div>
                    </div>
                    <div v-if="!((eq.makers || {}).global || []).length" class="cls-empty">暂无</div>
                  </div>
                  <div class="eq-maker-col">
                    <div class="eq-maker-head">🇨🇳 国内厂商</div>
                    <div class="eq-maker-row" v-for="(d, di) in ((eq.makers || {}).domestic || [])" :key="'d'+di">
                      <span class="rank-no dom">{{ di + 1 }}</span>
                      <div class="eq-maker-body">
                        <div class="eq-maker-name">
                          {{ d.company || qOf(d.code).name }}
                          <span class="eq-maker-code mono" v-if="d.code">{{ d.code }}</span>
                          <span class="eq-maker-price mono" v-if="qOf(d.code).price">¥{{ qOf(d.code).price }}</span>
                          <button v-if="d.code" class="op-btn xs" @click="addWatch(d.code, d.company || qOf(d.code).name)">+自选</button>
                          <span v-if="d.global_share" class="rank-gshare">🌍 全球 {{ d.global_share }}</span>
                        </div>
                        <div class="share-line" v-if="d.share">
                          <div class="share-track"><div class="share-fill dom" :style="{ width: sharePct(d.share) + '%' }"></div></div>
                          <span class="share-val mono">{{ d.share }}</span>
                        </div>
                        <div class="rank-edge" v-if="d.edge">{{ d.edge }}</div>
                      </div>
                    </div>
                    <div v-if="!((eq.makers || {}).domestic || []).length" class="cls-empty">暂无国产厂商（依赖进口）</div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="empty-tip">研报中未提取到明确的生产设备数据</div>
          </div>

          <!-- 替代风险 -->
          <div v-if="activeTab === 'substitution'">
            <h4>⚠️ 赛道替代风险</h4>
            <table class="data-table" v-if="(res.substitution_risk || []).length">
              <thead><tr><th>模块</th><th>被替代概率</th><th>替代技术</th><th>时间窗口</th><th>投资影响</th></tr></thead>
              <tbody>
                <tr v-for="(r, i) in res.substitution_risk" :key="i">
                  <td>{{ r.module }}</td>
                  <td>{{ r.probability }}</td>
                  <td>{{ r.tech }}</td>
                  <td>{{ r.window }}</td>
                  <td>{{ r.impact }}</td>
                </tr>
              </tbody>
            </table>
            <div v-else class="empty-tip">暂无替代风险数据</div>
            <div class="panel" v-if="(res.risks || []).length" style="margin-top:20px">
              <h4>风险提示</h4>
              <div class="risk-item" v-for="(r, i) in res.risks" :key="i">⚠️ {{ r }}</div>
            </div>
          </div>

          <!-- 研报库 -->
          <div v-if="activeTab === 'reports'">
            <div class="reports-head">
              <h4>📄 研报库（{{ filteredReports.length }}<span v-if="filteredReports.length !== (report.reports || []).length"> / {{ (report.reports || []).length }}</span> 篇）</h4>
              <div class="rep-filters">
                <select v-model="repOrg" class="rep-sel">
                  <option value="">全部机构</option>
                  <option v-for="o in reportOrgs" :key="o.name" :value="o.name">{{ o.name }}（{{ o.count }}）</option>
                </select>
                <select v-model="repDays" class="rep-sel rep-sel-sm">
                  <option value="">全部时间</option>
                  <option value="7">近一周</option>
                  <option value="30">近一月</option>
                  <option value="90">近三月</option>
                  <option value="180">近半年</option>
                  <option value="365">近一年</option>
                </select>
                <button v-if="repOrg || repDays" class="op-btn xs rep-clear" @click="repOrg=''; repDays=''">清除</button>
              </div>
            </div>
            <div class="report-list">
              <div v-if="!filteredReports.length" class="empty-tip">没有符合筛选条件的研报。</div>
              <div class="report-item" v-for="(r, i) in filteredReports" :key="i">
                <div class="ri-left">
                  <div class="ri-title">
                    {{ r.title }}
                    <span v-if="isExtracted(r.infoCode)" class="read-badge">已精读</span>
                  </div>
                  <div class="ri-meta">{{ r.orgSName }} · {{ (r.publishDate || '').slice(0,10) }}<span v-if="r.stockName"> · {{ r.stockName }}</span></div>
                  <div v-if="openedText[r.infoCode]" class="ri-text">{{ openedText[r.infoCode] }}</div>
                </div>
                <div class="ri-ops">
                  <button v-if="isExtracted(r.infoCode)" class="op-btn sm" @click="toggleText(r.infoCode)">
                    {{ openedText[r.infoCode] ? '收起' : '查看正文' }}
                  </button>
                  <a v-if="r.infoCode" class="op-btn sm" :href="'https://pdf.dfcfw.com/pdf/H3_' + r.infoCode + '_1.pdf'" target="_blank" rel="noopener">PDF</a>
                </div>
              </div>
            </div>
          </div>

          <!-- 调研纪要（机构荐股/知识星球博客，与东财研报分开展示） -->
          <div v-if="activeTab === 'blog'">
            <div class="reports-head">
              <h4>📋 调研纪要（{{ blogArticles.length }} 篇）</h4>
              <span class="cost-hint" style="font-size:12px;color:#999">来自机构荐股数据库（知识星球调研纪要），已并入精读分析</span>
            </div>
            <div class="report-list">
              <div v-if="!blogArticles.length" class="empty-tip">本主题暂无命中的调研纪要。</div>
              <div class="report-item" v-for="(r, i) in blogArticles" :key="i">
                <div class="ri-left">
                  <div class="ri-title">{{ r.title || '(无标题)' }}</div>
                  <div class="ri-meta">{{ r.org }} · {{ r.date }}<span v-if="r.source && r.source !== '机构荐股'"> · {{ r.source }}</span></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 估值建议 -->
          <div v-if="activeTab === 'valuation'">
            <div class="panel" v-if="res.target_price">
              <h4>🎯 整体目标价 / 估值中枢</h4>
              <p class="para">{{ res.target_price }}</p>
            </div>
            <div class="panel" v-if="productTargets.length" style="margin-bottom:18px">
              <h4>📦 整机 / 产品目标价</h4>
              <table class="data-table">
                <thead><tr><th>产品</th><th>当前均价</th><th>价格趋势</th><th>目标/展望</th><th>依据</th></tr></thead>
                <tbody>
                  <tr v-for="(p, i) in productTargets" :key="i">
                    <td><b>{{ p.product }}</b></td>
                    <td class="mono">{{ p.current_price || '-' }}</td>
                    <td>{{ p.price_trend || '-' }}</td>
                    <td class="mono">{{ p.target_price || '-' }}</td>
                    <td>{{ p.note || '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="(res.target_prices || []).length">
              <h4>💲 重点标的目标价</h4>
              <table class="data-table">
                <thead><tr><th>公司</th><th>现价</th><th>目标价</th><th>空间</th></tr></thead>
                <tbody>
                  <tr v-for="(t, i) in res.target_prices" :key="i">
                    <td>{{ t.name }}</td>
                    <td class="mono">{{ t.current ?? '-' }}</td>
                    <td class="mono">{{ t.target ?? '-' }}</td>
                    <td class="mono" :class="upsideClass(t.upside)">{{ t.upside || '-' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="panel" v-if="res.valuation" style="margin-top:18px">
              <h4>📐 估值全景</h4>
              <p class="para">{{ res.valuation }}</p>
            </div>
            <div class="panel" v-if="res.leader_gap">
              <h4>📏 与龙头差距</h4>
              <p class="para">{{ res.leader_gap }}</p>
            </div>
            <div class="panel">
              <h4>💡 投资建议</h4>
              <p class="para">{{ res.summary || '暂无' }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 空态 -->
      <div v-if="!report && !errorMsg" class="empty-board">
        <!-- 首次分析时：完整进度面板 -->
        <template v-if="analyzing">
          <div class="ana-panel">
            <div class="ap-header">
              <i class="run-dot"></i>
              <span class="ap-title">产业链 AI 精读中</span>
              <span class="ap-pct-big">{{ prog?.progress || 0 }}%</span>
            </div>
            <div class="ap-stage-text">{{ stage }}</div>
            <div class="ap-bar-wrap">
              <div class="ap-bar"><div class="ap-fill" :style="{ width: (prog?.progress || 0) + '%' }"></div></div>
            </div>
            <div class="ap-steps">
              <div v-for="(s, i) in analysisSteps" :key="i" :class="['ap-step', stepState(s)]">
                <span class="aps-dot"></span>
                <span class="aps-label">{{ s.label }}</span>
                <span class="aps-detail">
                  <span v-if="stepState(s) === 'step-active'" class="aps-running">进行中</span>
                  <span v-if="stepState(s) === 'step-error'" class="aps-err">✗ 失败</span>
                  <span v-if="stepHint(s)" class="aps-count">{{ stepHint(s) }}</span>
                </span>
              </div>
            </div>
            <div class="ap-stats" v-if="prog?.report_count || prog?.read_total">
              <div class="ap-stat" v-if="prog?.report_count">
                <span class="ast-icon">📄</span>
                <div><div class="ast-val">{{ prog.report_count }}</div><div class="ast-lbl">研报总数</div></div>
              </div>
              <div class="ap-stat" v-if="prog?.pdf_total">
                <span class="ast-icon">⬇️</span>
                <div><div class="ast-val">{{ prog.pdf_done || 0 }}/{{ prog.pdf_total }}</div><div class="ast-lbl">PDF下载</div></div>
              </div>
              <div class="ap-stat ap-stat--hit" v-if="prog?.cached_count != null && prog.read_total">
                <span class="ast-icon">⚡</span>
                <div>
                  <div class="ast-val ast-val--hit">{{ prog.cached_count }}</div>
                  <div class="ast-lbl">缓存命中</div>
                </div>
              </div>
              <div class="ap-stat ap-stat--map" v-if="prog?.map_total">
                <span class="ast-icon">🔬</span>
                <div>
                  <div class="ast-val">{{ prog.map_done || 0 }}/{{ prog.map_total }}</div>
                  <div class="ast-lbl">MAP精读中</div>
                </div>
              </div>
              <div class="ap-stat" v-if="prog?.read_total">
                <span class="ast-icon">🤖</span>
                <div><div class="ast-val">{{ prog.read_done || 0 }}/{{ prog.read_total }}</div><div class="ast-lbl">已完成</div></div>
              </div>
              <div class="ap-stat" v-if="prog?.eta_text">
                <span class="ast-icon">⏱</span>
                <div><div class="ast-val">{{ prog.eta_text }}</div><div class="ast-lbl">预计剩余</div></div>
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="empty-icon">📊</div>
          <p v-if="history.length">从左侧选择一个主题，查看产业链研报精读报告</p>
          <p v-else>暂无产业链分析报告 · 请在管理后台添加并生成分析主题</p>
        </template>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'
import { research, startTracking } from '../stores/research'

const route = useRoute()
import BomNode from '../components/BomNode.vue'
import { useWatchlistStore } from '../stores/watchlist'

const wl = useWatchlistStore()
function addWatch(code, name) {
  if (code && !wl.isInWatchlist(code)) wl.addToWatchlist({ code, name })
}

const keyword = ref('')
const history = ref([])
const currentSlug = ref('')
const report = ref(null)
const activeTab = ref('overview')

const errorMsg = ref('')
const openedText = reactive({})

// 进度统一来自全局 store（按 currentSlug），离开页面再回来仍能恢复
const prog = computed(() => research.progress[currentSlug.value] || null)
const analyzing = computed(() => prog.value?.status === 'running')
const stage = computed(() => prog.value?.stage || '初始化…')

// 当前正在跟踪的任务完成时，自动载入看板
watch(() => prog.value?.status, async (st) => {
  if (st === 'done' && currentSlug.value && !report.value) {
    await loadReport(currentSlug.value)
    loadHistory()
  } else if (st === 'error') {
    errorMsg.value = '分析失败：' + (prog.value?.error || '未知错误')
  }
})

// 任何后台分析完成（不止当前 slug、即便正在看别的报告）都刷新左侧「生成记录」，
// 否则新生成的记录要等到下次进页面/刷新才出现 → 看起来像「漏了」。
watch(() => research.toast, (t) => {
  if (t && t.type === 'done') loadHistory()
})

const stockInfoMap = computed(() => ({ ...(report.value?.quotes || {}), ...(report.value?.stock_info || {}) }))

// 新增能力的数据派生
const costDownPaths = computed(() => res.value.cost_down_paths || [])
const productTargets = computed(() => res.value.product_targets || [])
const landscape = computed(() => res.value.competitive_landscape || null)
// 竞争格局按上中下游分组（新版后端返回 {上游,中游,下游} 对象；兼容旧版扁平数组→归到「综合」）
function groupBySeg(side) {
  if (!side) return []
  if (Array.isArray(side)) return side.length ? [{ seg: '综合', rows: side }] : []
  const order = ['上游', '中游', '下游']
  const out = []
  order.forEach(seg => {
    const rows = side[seg]
    if (Array.isArray(rows) && rows.length) out.push({ seg, rows })
  })
  // 容错：模型若给了非标准键，也一并展示
  Object.keys(side).forEach(k => {
    if (!order.includes(k) && Array.isArray(side[k]) && side[k].length) out.push({ seg: k, rows: side[k] })
  })
  return out
}
const landscapeGlobal = computed(() => groupBySeg(landscape.value?.global))
const landscapeDomestic = computed(() => groupBySeg(landscape.value?.domestic))
const supplyChain = computed(() => res.value.supply_chain || [])
const chainMasters = computed(() => res.value.chain_masters || [])
const productionEquipment = computed(() => res.value.production_equipment || null)
const equipmentList = computed(() => productionEquipment.value?.equipment_list || [])
const recentUpdates = computed(() => res.value.recent_updates || [])
// 瓶颈理论视角派生数据
const bottleneckRanking = computed(() => res.value.bottleneck_ranking || [])
const bottleneckStocks = computed(() => res.value.bottleneck_stocks || [])
const valueMigration = computed(() => res.value.value_migration || null)
const overseasMapping = computed(() => res.value.overseas_mapping || [])
function qOf(code) { return stockInfoMap.value[code] || {} }

// 个股评分榜：百分比格式化(+/-，缺值显 -)、涨跌色阶、估值判定色
function fmtPct(v) {
  if (v == null || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return '-'
  return (n > 0 ? '+' : '') + n.toFixed(1) + '%'
}
function pctClass(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return ''
  return Number(v) >= 0 ? 'up-red' : 'down-green'
}
function valuationClass(v) {
  const s = String(v || '')
  if (s.includes('低估')) return 'val-low'
  if (s.includes('高估')) return 'val-high'
  if (s.includes('亏损')) return 'val-loss'
  return 'val-fair'
}

const analysisSteps = [
  { id: 'seed',     label: '识别核心标的', minPct: 0,  maxPct: 19 },
  { id: 'quote',    label: '获取行情数据', minPct: 19, maxPct: 31 },
  { id: 'reports',  label: '收集机构研报', minPct: 31, maxPct: 44 },
  { id: 'download', label: '下载研报 PDF', minPct: 44, maxPct: 59 },
  { id: 'blog',     label: '收集调研纪要', minPct: 59, maxPct: 60 },
  { id: 'map',      label: 'AI 逐篇精读', minPct: 60, maxPct: 84 },
  { id: 'reduce',   label: 'AI 汇总合成', minPct: 84, maxPct: 95 },
  { id: 'match',    label: '匹配个股标的', minPct: 95, maxPct: 100 },
]
function stepState(step) {
  const pct = prog.value?.progress || 0
  if (prog.value?.status === 'error' && pct >= step.minPct && pct < step.maxPct) return 'step-error'
  if (pct >= step.maxPct) return 'step-done'
  if (pct >= step.minPct) return 'step-active'
  return 'step-pending'
}
function stepHint(step) {
  const pct = prog.value?.progress || 0
  if (pct < step.minPct) return ''
  const p = prog.value || {}
  switch (step.id) {
    case 'reports':  return p.report_count ? `${p.report_count} 篇` : ''
    case 'download': return p.pdf_total ? `${p.pdf_done || 0}/${p.pdf_total} PDF` : ''
    case 'blog':     return p.n_blog != null ? `${p.n_blog} 篇纪要` : ''
    case 'map':      return p.read_total
      ? `缓存 ${p.cached_count ?? '—'} · MAP ${p.map_done ?? 0}/${p.map_total ?? 0}`
      : ''
    default: return ''
  }
}

// 卡脖子评分 → 高/中/低色阶
function scoreClass(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  if (n >= 70) return 'sc-high'
  if (n >= 40) return 'sc-mid'
  return 'sc-low'
}
// 产业链卡位 → 样式 key（瓶颈卡位 / 整机终端 / 泛受益）
function chainPosKey(p) {
  if (!p) return ''
  if (p.includes('瓶颈') || p.includes('卡位')) return 'bottleneck'
  if (p.includes('终端') || p.includes('整机')) return 'terminal'
  return 'general'
}
// 从市占率文本解析出用于进度条的百分比（取首个数字，区间如「约15-20%」取上界）
function sharePct(s) {
  if (s == null) return 0
  const nums = String(s).match(/\d+(?:\.\d+)?/g)
  if (!nums || !nums.length) return 0
  const v = Math.max(...nums.map(Number))
  return Math.max(0, Math.min(100, v))
}
function upsideClass(u) {
  if (!u) return ''
  const s = String(u)
  if (s.includes('-')) return 'risk-high'
  if (s.includes('+') || parseFloat(s) > 0) return 'risk-low'
  return ''
}
// 近期动态影响方向 → 颜色（看多红 / 看空绿 / 中性灰，A 股惯例）
function impactClass(v) {
  if (!v) return ''
  const s = String(v)
  if (s.includes('看多') || s.includes('利好') || s.includes('正面')) return 'imp-bull'
  if (s.includes('看空') || s.includes('利空') || s.includes('负面')) return 'imp-bear'
  return 'imp-neutral'
}

const reportOrgCount = computed(() => {
  const orgs = new Set((report.value?.reports || []).map(r => r.orgSName || r.org).filter(Boolean))
  return orgs.size
})

const tabs = [
  // 核心决策
  { id: 'overview',     label: '总览' },
  { id: 'bottleneck',   label: '瓶颈卡位' },
  { id: 'decision',     label: '明日决策' },
  { id: 'recent',       label: '近期动态' },
  // 深度分析
  { id: '__sep1', sep: true },
  { id: 'cost',         label: '成本构成' },
  { id: 'segments',     label: '细分环节' },
  { id: 'landscape',    label: '竞争格局' },
  { id: 'chain',        label: '产业链分层' },
  { id: 'chainmaster',  label: '链主链路' },
  { id: 'equipment',    label: '生产设备' },
  { id: 'substitution', label: '替代风险' },
  // 原始数据
  { id: '__sep2', sep: true },
  { id: 'reports',      label: '研报库' },
  { id: 'blog',         label: '调研纪要' },
  { id: 'valuation',    label: '估值建议' },
]

const res = computed(() => report.value?.result || {})
const decision = computed(() => res.value?.decision || {})

// ── 研报库筛选：机构 + 时间范围 两个下拉（行业研报普遍无个股名，故用时间而非标的）──
const repOrg = ref('')
const repDays = ref('')   // '' = 全部；否则近 N 天
const reportOrgs = computed(() => {
  const m = new Map()
  ;(report.value?.reports || []).forEach(r => {
    const v = (r.orgSName || '').trim()
    if (v) m.set(v, (m.get(v) || 0) + 1)
  })
  return [...m.entries()].map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
})
const filteredReports = computed(() => {
  let cutoff = ''
  if (repDays.value) {
    const d = new Date(); d.setDate(d.getDate() - Number(repDays.value))
    cutoff = d.toISOString().slice(0, 10)
  }
  return (report.value?.reports || []).filter(r =>
    (!repOrg.value || (r.orgSName || '') === repOrg.value) &&
    (!cutoff || (r.publishDate || '').slice(0, 10) >= cutoff))
})
const blogArticles = computed(() => report.value?.blog_articles || [])
// 首选：优先用新版多首选 top_picks，回退老版单 top_pick 字符串
const topPicks = computed(() => {
  const arr = decision.value?.top_picks
  if (Array.isArray(arr) && arr.length) return arr
  const one = decision.value?.top_pick
  return one ? [{ reason: one }] : []
})
const buyCandidates = computed(() => {
  const list = decision.value?.buy_candidates
  if (!Array.isArray(list)) return []
  // 优先用后端给的推荐优先级 priority；缺失则回退按信心(高>中>低)排
  const hasPriority = list.some(c => Number.isFinite(Number(c?.priority)))
  if (hasPriority) {
    return [...list].sort((a, b) => (Number(a?.priority) || 99) - (Number(b?.priority) || 99))
  }
  const rank = { '高': 0, '中': 1, '低': 2 }
  return [...list].sort((a, b) => (rank[a.conviction] ?? 3) - (rank[b.conviction] ?? 3))
})
// tier → 样式 key（龙头/中军/弹性/后排）
function tierKey(t) {
  if (!t) return 'other'
  if (t.includes('龙头')) return 'leader'
  if (t.includes('中军')) return 'mid'
  if (t.includes('弹性')) return 'elastic'
  if (t.includes('后排') || t.includes('二线')) return 'back'
  return 'other'
}
function actionClass(a) {
  if (!a) return ''
  if (a.includes('买')) return 'act-buy'
  if (a.includes('回避') || a.includes('卖')) return 'act-avoid'
  return 'act-watch'
}
const costBars = computed(() => {
  const bom = res.value.bom
  return Array.isArray(bom) ? bom.filter(b => b && b.name && b.percent != null) : []
})

function impKey(v) {
  if (!v) return ''
  if (v.includes('高')) return 'high'
  if (v.includes('中')) return 'mid'
  if (v.includes('低')) return 'low'
  return ''
}
function isExtracted(code) {
  return code && (report.value?.extracted_codes || []).includes(code)
}
function fmtDate(s) {
  if (!s) return ''
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }).slice(0, 16) } catch { return s }
}

async function loadHistory() {
  try {
    const { data } = await axios.get('/api/research/saved-reports')
    history.value = data.reports || []
  } catch (e) { /* ignore */ }
}

async function loadReport(slug) {
  const histItem = history.value.find(h => h.slug === slug)
  if (histItem?.status === 'error') {
    currentSlug.value = slug
    report.value = null
    const where = histItem.stage ? `（${histItem.stage}阶段）` : ''
    errorMsg.value = `分析失败${where}：${histItem.error || '未知错误'}`
    return
  }
  try {
    const { data } = await axios.get(`/api/research/analysis/${slug}`)
    if (data.data) {
      report.value = data.data
      currentSlug.value = slug
      activeTab.value = 'overview'
      repOrg.value = ''; repDays.value = ''
      Object.keys(openedText).forEach(k => delete openedText[k])
      errorMsg.value = ''
    }
  } catch (e) { errorMsg.value = '加载报告失败' }
}

async function toggleText(code) {
  if (openedText[code]) { delete openedText[code]; return }
  try {
    const { data } = await axios.get(`/api/research/report-text/${code}`)
    openedText[code] = data.text ? data.text.slice(0, 4000) : '（正文不可用）'
  } catch { openedText[code] = '（正文加载失败）' }
}

function exportJson() {
  if (!report.value) return
  const blob = new Blob([JSON.stringify(report.value, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${report.value.keyword || 'report'}_产业链分析.json`
  a.click()
  URL.revokeObjectURL(a.href)
}

async function loadDefaultReport() {
  // 默认主题（光模块）：直接打开后台每天生成的最新报告；若后台正在跑则展示进度
  try {
    const { data } = await axios.get('/api/research/daily-keywords')
    const first = (data.keywords || [])[0]
    if (!first) return
    keyword.value = first.keyword
    currentSlug.value = first.slug
    const { data: rep } = await axios.get(`/api/research/analysis/${first.slug}`)
    if (rep.data) {
      report.value = rep.data
      activeTab.value = 'overview'
      repOrg.value = ''; repDays.value = ''
    } else if (rep.status === 'running') {
      // 后台首跑尚未完成：跟踪进度，完成后自动载入
      startTracking(first.slug, first.keyword)
    } else if (rep.status === 'not_found') {
      // 从未生成过（或被中断后清掉）：显示提示引导管理员触发
      errorMsg.value = `「${first.keyword}」尚无可用报告（后台分析尚未完成或被中断），请在管理后台 → 产业链分析触发一次运行。`
    }
  } catch (e) { /* 无报告时静默，展示空看板 */ }
}

onMounted(async () => {
  await loadHistory()
  // 从完成提醒「查看」进入：直接打开该报告（store 或 query.slug，新标签页走 query）
  const wantSlug = research.openSlug || route.query.slug
  if (wantSlug) {
    const slug = wantSlug
    research.openSlug = null
    currentSlug.value = slug
    keyword.value = research.progress[slug]?.keyword || ''
    await loadReport(slug)
    return
  }
  await loadDefaultReport()
})
</script>

<style scoped>
.ir-layout { display: flex; height: 100%; gap: 0; }

/* 历史栏 */
.ir-history {
  width: 240px; flex-shrink: 0; border-right: 1px solid var(--border);
  background: var(--bg-surface); padding: 16px 12px; overflow-y: auto;
}
.new-btn {
  width: 100%; padding: 10px; border: 1px dashed var(--border); border-radius: 8px;
  background: transparent; color: var(--accent); font-weight: 600; cursor: pointer; margin-bottom: 16px;
}
.new-btn:hover { background: var(--bg-hover); }
.hist-title { font-size: 11px; color: var(--text-3); letter-spacing: .05em; margin-bottom: 8px; text-transform: uppercase; }
.hist-empty { font-size: 13px; color: var(--text-3); padding: 12px 4px; }
.hist-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px; border-radius: 8px; cursor: pointer; margin-bottom: 4px;
}
.hist-item:hover { background: var(--bg-hover); }
.hist-item.active { background: rgba(59,130,246,0.1); }
.hist-item--err { border-left: 3px solid rgba(239,68,68,.5); padding-left: 8px; }
.hist-err-badge { color: #ef4444; font-size: 11px; margin-right: 3px; }
.hist-err-stage { font-size: 11px; color: #ef4444; margin-top: 2px; opacity: .85; }
.hist-kw { font-weight: 600; font-size: 14px; }
.hist-meta { font-size: 11px; color: var(--text-3); margin-top: 3px; }
.hist-actions { display: flex; gap: 2px; opacity: 0; transition: .15s; }
.hist-item:hover .hist-actions { opacity: 1; }
.hist-actions button { background: none; border: none; cursor: pointer; font-size: 12px; padding: 2px 4px; color: var(--text-3); }
.hist-actions button:hover { color: var(--text-1); }

/* 主区 */
.ir-main { flex: 1; overflow-y: auto; padding: 24px 28px; }

/* 纯展示标题区（无输入框）。主题选择统一走左侧报告列表，不再重复一套 chips */
.ir-hero {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid var(--border);
}
.hero-text h2 { margin: 0 0 6px; font-size: 22px; }
.hero-sub { color: var(--text-3); font-size: 13px; line-height: 1.7; margin: 0; max-width: 760px; }
.hero-sub b { color: var(--text-2); font-weight: 600; }

/* 后台分析中：仅一行极简徽标，进度条本身只在后台/全局完成提醒里展示 */
.hero-running {
  flex-shrink: 0; display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 14px; font-size: 12px; white-space: nowrap;
  background: rgba(59,130,246,.1); color: var(--accent); border: 1px solid rgba(59,130,246,.25);
}
.run-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: run-pulse 1.1s ease-in-out infinite; }
.run-dot--err { background: #ef4444; animation: none; }
@keyframes run-pulse { 0%,100% { opacity: .35; } 50% { opacity: 1; } }

.error-card { background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.3); color: #dc2626; border-radius: 10px; padding: 16px; margin-bottom: 20px; }

/* 看板 */
.report-board { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.board-head { display: flex; justify-content: space-between; align-items: flex-start; padding: 20px 24px; border-bottom: 1px solid var(--border); background: var(--bg-elevated); }
.board-head h3 { margin: 0; font-size: 18px; }
.round-tag { display: inline-block; margin: 0 4px; padding: 1px 7px; border-radius: 6px; background: var(--accent); color: #fff; font-size: 11px; }
.board-ops { display: flex; gap: 8px; }

/* 明日决策 */
.decision-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.decision-head h4 { margin: 0; font-size: 17px; }
.decision-asof { font-size: 12px; color: var(--text-3); }
.disclaimer { margin: 8px 0 16px; padding: 8px 12px; border-radius: 8px; background: rgba(245,158,11,.1); color: #d97706; font-size: 12px; }
.market-view { margin-bottom: 16px; }
.picks-banner { display: flex; align-items: flex-start; gap: 12px; padding: 12px 16px; border-radius: 10px; margin-bottom: 16px;
  background: linear-gradient(90deg, rgba(22,163,74,.14), rgba(22,163,74,0)); border: 1px solid rgba(22,163,74,.3); }
.pb-label { font-weight: 700; color: #16a34a; white-space: nowrap; padding-top: 1px; }
.pb-text { font-size: 14px; }
.cand-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.cand-card { position: relative; border: 1px solid var(--border); border-radius: 12px; padding: 16px; background: var(--bg-elevated); }
.cc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.cc-name b { font-size: 16px; }
.cc-code { margin-left: 8px; color: var(--text-3); font-size: 12px; }
.cc-action { padding: 3px 10px; border-radius: 7px; font-size: 12px; font-weight: 700; }
.act-buy { background: rgba(220,38,38,.16); color: #dc2626; }
.act-watch { background: var(--accent-dim); color: var(--accent); }
.act-avoid { background: var(--bg-hover); color: var(--text-3); }
.cc-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.cc-tag { padding: 2px 9px; border-radius: 6px; background: var(--bg-hover); font-size: 12px; color: var(--text-2); }
.cc-tag.conv-high { background: rgba(220,38,38,.14); color: #dc2626; }
.cc-tag.conv-mid { background: rgba(245,158,11,.14); color: #d97706; }
.cc-tag.conv-low { background: var(--bg-hover); color: var(--text-3); }
.cc-rank { display: inline-block; min-width: 22px; margin-right: 6px; font-weight: 800; font-size: 13px; color: var(--accent); }
.cc-tag.tier { font-weight: 700; }
.cc-tag.tier-leader { background: rgba(220,38,38,.16); color: #dc2626; }
.cc-tag.tier-mid { background: rgba(37,99,235,.14); color: #2563eb; }
.cc-tag.tier-elastic { background: rgba(217,119,6,.16); color: #d97706; }
.cc-tag.tier-back { background: var(--bg-hover); color: var(--text-2); }
.cc-tag.tier-other { background: var(--bg-hover); color: var(--text-3); }
.cc-prices { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; padding: 12px 0; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.cc-prices > div { display: flex; justify-content: space-between; font-size: 13px; }
.cc-prices span { color: var(--text-3); }
.cc-row { display: flex; gap: 8px; margin-top: 10px; font-size: 13px; line-height: 1.5; }
.cc-row > span { flex: 0 0 36px; color: var(--text-3); }
.cc-row > p { margin: 0; color: var(--text-1); }
.cc-row.risk > p { color: #d97706; }
.cc-add { margin-top: 12px; }
.notes-panel { margin-top: 16px; }
.op-btn { padding: 7px 14px; border: 1px solid var(--border); border-radius: 8px; background: transparent; color: var(--text-1); cursor: pointer; font-size: 13px; text-decoration: none; display: inline-block; }
.op-btn:hover { border-color: var(--accent); color: var(--accent); }
.op-btn.sm { padding: 4px 10px; font-size: 12px; }

.tab-bar { display: flex; gap: 6px; padding: 12px 24px; border-bottom: 1px solid var(--border); overflow-x: auto; }
.tab-bar button { background: transparent; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; color: var(--text-2); white-space: nowrap; font-size: 14px; }
.tab-bar button.active { background: var(--accent); color: #fff; }
.tab-body { padding: 24px; }
.tab-body h4 { margin: 0 0 16px; font-size: 16px; }


.panel { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 18px; }
.panel h4 { margin: 0 0 12px; }
.para { line-height: 1.8; font-size: 14px; color: var(--text-1); margin: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.kp-chip { padding: 5px 12px; border-radius: 8px; background: var(--bg-hover); font-size: 13px; }

.cost-hint { font-size: 12px; color: var(--text-3); margin: -6px 0 16px; line-height: 1.6; }

/* 新版成本构成：顶层概览条 + 分层树 */
.cost-overview { display: flex; width: 100%; height: 56px; border-radius: 10px; overflow: hidden; gap: 2px; margin-bottom: 20px; }
.cov-seg { display: flex; flex-direction: column; align-items: center; justify-content: center; color: #fff; min-width: 40px; overflow: hidden; padding: 0 4px; }
.cov-name { font-size: 12px; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; max-width: 100%; text-shadow: 0 1px 2px rgba(0,0,0,.3); }
.cov-pct { font-size: 13px; font-weight: 700; font-family: var(--font-mono); text-shadow: 0 1px 2px rgba(0,0,0,.3); }
.cost-tree { display: flex; flex-direction: column; gap: 8px; }

/* 机构荐股表 */
.inst-table .inst-name { display: flex; align-items: center; }
.inst-table .inst-name b { font-size: 14px; }
.inst-code { font-size: 11px; color: var(--text-3); }
.inst-rating { display: inline-block; padding: 2px 9px; border-radius: 6px; background: rgba(220,38,38,.14); color: #dc2626; font-size: 12px; font-weight: 600; }
.inst-bull { font-size: 13px; }
.inst-bull b { color: #dc2626; font-size: 15px; }
.inst-slash { color: var(--text-3); margin: 0 2px; }
.inst-bar { height: 5px; background: var(--bg-1, rgba(255,255,255,.06)); border-radius: 3px; overflow: hidden; margin-top: 4px; max-width: 90px; }
.inst-bar-fill { height: 100%; background: #dc2626; border-radius: 3px; }
.inst-orgs { font-size: 10px; color: var(--text-3); margin-left: 5px; }
.inst-range { font-size: 12px; color: var(--text-3); }
/* 机构荐股·推荐逻辑行 */
.inst-table tr.has-logic > td { border-bottom: none; }
.inst-logic-row > td { padding: 4px 13px 12px; border-bottom: 1px solid var(--border); font-size: 12px; line-height: 1.6; color: var(--text-2); }
.inst-logic-tag { display: inline-block; margin-right: 8px; padding: 1px 8px; border-radius: 5px; background: rgba(99,102,241,.12); color: var(--accent); font-weight: 600; white-space: nowrap; vertical-align: top; }
.inst-orgcount { font-size: 12px; color: var(--text-2); white-space: nowrap; }
.inst-orgcount b { font-size: 15px; color: var(--accent); margin-right: 2px; }
/* 核心竞争力 3 句 */
.inst-compet { display: flex; align-items: flex-start; }
.inst-compet-list { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; }
.inst-compet-list li { line-height: 1.6; }
/* 调研纪要链接 */
.inst-refs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
.inst-refs-tag { display: inline-block; padding: 1px 8px; border-radius: 5px; background: rgba(22,163,74,.12); color: #16a34a; font-weight: 600; white-space: nowrap; }
.inst-ref-link { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-elevated); color: var(--text-2); font-size: 11px; text-decoration: none; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.inst-ref-link:hover { border-color: var(--accent); color: var(--accent); }
.inst-ref-date { color: var(--text-3); font-family: var(--font-mono); }

/* 近期动态 */
.upd-list { display: flex; flex-direction: column; gap: 12px; }
.upd-item { display: flex; gap: 14px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 12px; background: var(--bg-elevated); }
.upd-side { flex: 0 0 96px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
.upd-date { font-size: 13px; font-weight: 700; color: var(--accent); }
.upd-cat { font-size: 11px; padding: 2px 8px; border-radius: 6px; background: var(--bg-hover); color: var(--text-2); }
.upd-body { flex: 1; min-width: 0; }
.upd-title { font-size: 14px; font-weight: 600; color: var(--text-1); line-height: 1.5; }
.upd-detail { margin: 6px 0 0; font-size: 13px; line-height: 1.7; color: var(--text-2); }
.upd-foot { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.upd-impact, .upd-benef { font-size: 12px; padding: 3px 10px; border-radius: 7px; line-height: 1.5; }
.upd-impact.imp-bull { background: rgba(220,38,38,.12); color: #dc2626; }
.upd-impact.imp-bear { background: rgba(22,163,74,.12); color: #16a34a; }
.upd-impact.imp-neutral { background: var(--bg-hover); color: var(--text-2); }
.upd-benef { background: rgba(99,102,241,.1); color: var(--accent); }
@media (max-width: 768px) {
  .upd-item { flex-direction: column; gap: 8px; }
  .upd-side { flex-direction: row; align-items: center; }
}

/* 多首选 */
.pb-list { display: flex; flex-direction: column; gap: 4px; }
.pb-list .pb-text { font-size: 13px; line-height: 1.5; }
.cost-area { display: flex; flex-direction: column; gap: 8px; }
.bom-l1 { display: flex; flex-direction: column; gap: 6px; }
.cost-bar-item { display: grid; grid-template-columns: 180px 1fr 56px; gap: 12px; align-items: center; }
.cost-bar-item.l1 { cursor: pointer; }
.cost-bar-item.l1 .cost-label { font-weight: 600; }
.bom-children { display: flex; flex-direction: column; gap: 6px; margin: 4px 0 8px; padding-left: 14px; border-left: 2px solid var(--border); }
.bom-l2 { display: flex; flex-direction: column; gap: 5px; }
.cost-bar-item.l2 .cost-label { font-size: 13px; color: var(--text-2); }
.cost-bar-item.l2 .cost-track { height: 20px; }
.cost-bar-item.l3 .cost-label { font-size: 12px; color: var(--text-3); }
.cost-bar-item.l3 .cost-track { height: 15px; }
.cost-label { text-align: right; font-weight: 500; font-size: 14px; }
.caret { color: var(--text-3); margin-right: 4px; font-size: 11px; }
.cost-track { height: 26px; background: var(--bg-elevated); border-radius: 6px; overflow: hidden; }
.cost-fill { height: 100%; transition: width .6s ease; border-radius: 6px; }
.cost-val { font-weight: 600; font-family: var(--font-mono); }

/* 头部个股推荐 */
.rec-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.rec-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.rec-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.rec-name { font-weight: 600; font-size: 15px; }
.rec-code { font-size: 12px; color: var(--text-3); margin-left: 8px; }
.add-wl { padding: 4px 11px; border: 1px solid var(--accent); border-radius: 7px; background: transparent; color: var(--accent); font-size: 12px; cursor: pointer; white-space: nowrap; }
.add-wl:hover { background: var(--accent); color: #fff; }
.add-wl.added { border-color: #16a34a; color: #16a34a; background: rgba(22,163,74,.1); cursor: default; }
.rec-metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; margin-bottom: 10px; }
.rm { text-align: center; }
.rm span { display: block; font-size: 10px; color: var(--text-3); margin-bottom: 2px; }
.rm b { font-size: 13px; }
.up { color: #dc2626; }
.down { color: #16a34a; }
.rec-reason { font-size: 12px; line-height: 1.6; color: var(--text-2); border-top: 1px dashed var(--border); padding-top: 8px; }

/* 产业要点卡片 */
.points-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-bottom: 18px; }
/* 类别用标签前色点标识（替代左条纹） */
.point-card { padding: 14px 16px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-elevated); }
.pc-label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); margin-bottom: 7px; font-weight: 600; }
.pc-label::before { content: ''; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--pc-color, var(--accent)); }
.pc-text { font-size: 13px; line-height: 1.6; color: var(--text-1); }
.pc-leader { --pc-color: #d97706; }
.pc-bottleneck { --pc-color: #dc2626; }
.pc-irrep { --pc-color: #7c3aed; }
.pc-catchup { --pc-color: #16a34a; }
.pc-gap { --pc-color: #2563eb; }

/* 里程碑时间线 */
.timeline { display: flex; flex-direction: column; gap: 2px; }
.tl-item { display: grid; grid-template-columns: 90px 1fr; gap: 14px; padding: 8px 0 8px 16px; position: relative; border-left: 2px solid var(--border); }
.tl-dot { position: absolute; left: -6px; top: 14px; width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }
.tl-date { font-family: var(--font-mono); font-weight: 600; font-size: 13px; color: var(--accent); }
.tl-event { font-size: 13px; line-height: 1.6; color: var(--text-1); }

.seg-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
.seg-card { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.seg-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.seg-name { font-weight: 600; font-size: 15px; }
.seg-badge { font-size: 11px; padding: 3px 9px; border-radius: 8px; font-weight: 600; }
.b-high { background: rgba(220,38,38,.15); color: #dc2626; }
.b-mid { background: rgba(245,158,11,.15); color: #d97706; }
.b-low { background: rgba(100,130,160,.15); color: #64748b; }
.seg-row { display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; color: var(--text-3); }
.seg-row b { color: var(--text-1); }
.risk-high { color: #dc2626 !important; }
.risk-mid { color: #d97706 !important; }
.risk-low { color: #16a34a !important; }
.seg-desc { font-size: 13px; line-height: 1.6; color: var(--text-2); margin: 10px 0 0; }

.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; background: var(--bg-elevated); padding: 11px 13px; color: var(--text-3); font-weight: 600; border-bottom: 2px solid var(--border); }
.data-table td { padding: 11px 13px; border-bottom: 1px solid var(--border); }
.mono { font-family: var(--font-mono); }

.risk-item { padding: 11px; background: rgba(239,68,68,.05); border: 1px solid rgba(239,68,68,.2); border-radius: 8px; margin-bottom: 8px; font-size: 14px; }

/* 研报库筛选条 */
.reports-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.reports-head h4 { margin: 0; }
.rep-filters { display: flex; align-items: center; gap: 8px; }
.rep-sel {
  max-width: 220px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg-elevated); color: var(--text-1, var(--text-2)); font-size: 13px; cursor: pointer;
}
.rep-sel:focus { outline: none; border-color: var(--accent); }
.rep-sel-sm { max-width: 130px; }
.rep-clear { align-self: center; }

.report-list { display: flex; flex-direction: column; gap: 10px; }
.report-item { display: flex; justify-content: space-between; gap: 12px; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: var(--bg-elevated); }
.ri-title { font-weight: 500; font-size: 14px; }
.ri-meta { color: var(--text-3); font-size: 12px; margin-top: 5px; }
.ri-text { margin-top: 10px; padding: 10px; background: var(--bg-surface); border-radius: 8px; font-size: 12px; line-height: 1.7; color: var(--text-2); white-space: pre-wrap; max-height: 260px; overflow-y: auto; }
.ri-ops { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; flex-shrink: 0; }
.read-badge { font-size: 10px; padding: 2px 7px; border-radius: 6px; background: rgba(22,163,74,.15); color: #16a34a; margin-left: 8px; font-weight: 600; }

.empty-tip { color: var(--text-3); font-size: 14px; padding: 30px 0; text-align: center; }

.op-btn.xs { padding: 2px 8px; font-size: 11px; }
.dn-mag { color: #16a34a; font-weight: 600; }

/* 竞争格局排行榜 */
.rank-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.rank-col { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
.rank-head { font-size: 14px; font-weight: 700; color: var(--text-1); margin-bottom: 12px; }
.rank-row { display: flex; align-items: flex-start; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.rank-row:last-child { border-bottom: none; }
.rank-no { flex: 0 0 24px; height: 24px; border-radius: 6px; background: var(--accent-dim); color: var(--accent); font-weight: 700; font-size: 13px; display: flex; align-items: center; justify-content: center; }
.rank-no.dom { background: rgba(240,64,96,.15); color: #f04060; }
.rank-body { flex: 1; min-width: 0; }
.rank-name { font-size: 14px; font-weight: 600; color: var(--text-1); display: flex; align-items: center; gap: 8px; }
.rank-flag { font-size: 11px; padding: 1px 7px; border-radius: 5px; background: var(--bg-1, rgba(255,255,255,.06)); color: var(--text-3); font-weight: 500; }
/* 国内榜额外标注的全球市场份额徽标 */
.rank-gshare { font-size: 11px; padding: 1px 8px; border-radius: 5px; background: var(--accent-dim); color: var(--accent); font-weight: 600; white-space: nowrap; }
.rank-edge { font-size: 12px; color: var(--text-3); margin-top: 3px; line-height: 1.5; }
.rank-share { flex: 0 0 auto; font-size: 13px; font-weight: 700; color: var(--accent); font-family: ui-monospace, monospace; }
/* 市占率进度条 */
.share-line { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
.share-track { flex: 1; min-width: 0; height: 7px; background: var(--bg-1, rgba(255,255,255,.06)); border-radius: 4px; overflow: hidden; }
.share-fill { height: 100%; border-radius: 4px; transition: width .5s ease; }
.share-fill.gl { background: var(--accent); }
.share-fill.dom { background: #f04060; }
.share-val { flex: 0 0 auto; font-size: 12px; font-weight: 700; color: var(--text-1); }

/* 上中下游分层 */
.chain-wrap { display: flex; flex-direction: column; gap: 18px; }
.chain-seg { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
/* 上中下游段头：用色点标识替代左条纹 */
.chain-seg-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.chain-seg-head::before { content: ''; width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; background: #6366f1; }
.chain-seg-head.cs-0::before { background: #6366f1; }
.chain-seg-head.cs-1::before { background: #06d6c8; }
.chain-seg-head.cs-2::before { background: #f59e0b; }
.cs-tag { font-size: 15px; font-weight: 700; color: var(--text-1); }
.cs-desc { font-size: 12px; color: var(--text-3); }
.chain-link { padding: 12px 16px; border-top: 1px solid var(--border); }
.cl-name { font-size: 13px; font-weight: 600; color: var(--text-1); margin-bottom: 8px; }
.cl-note { font-size: 11px; color: var(--text-3); font-weight: 400; margin-left: 8px; }
.cl-stocks { display: flex; flex-wrap: wrap; gap: 8px; }
.cl-stock { flex: 1 1 240px; min-width: 220px; background: var(--bg-1, rgba(255,255,255,.03)); border: 1px solid var(--border); border-radius: 9px; padding: 8px 11px; }
.cls-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cls-name { font-size: 13px; color: var(--text-1); }
.cls-code { font-size: 11px; color: var(--text-3); }
.cls-price { font-size: 12px; color: var(--accent); font-weight: 600; }
.cls-role { font-size: 11px; color: var(--text-3); margin-top: 4px; line-height: 1.5; }
.cls-share { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; }
.cls-share-item { font-size: 11px; color: var(--text-2); background: var(--bg-hover); border-radius: 5px; padding: 1px 7px; line-height: 1.6; }
.cls-share-item i { font-style: normal; color: var(--text-3); margin-right: 4px; }
.cls-share-item.tier { background: rgba(37,99,235,.1); color: #2563eb; }
.cls-share-item.tier i { color: #2563eb; opacity: .7; }
.cls-empty { font-size: 12px; color: var(--text-3); }

/* ── 链主链路 ──────────────────────────────────────────── */
.cm-wrap { display: flex; flex-direction: column; gap: 18px; }
.cm-master { border: 1px solid var(--border); border-radius: 12px; overflow: hidden; background: var(--bg-surface); }
.cm-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 13px 16px; background: var(--bg-elevated); border-bottom: 1px solid var(--border); }
.cm-name { font-size: 16px; font-weight: 800; color: var(--text-1); }
.cm-country { font-size: 11px; color: var(--text-3); background: var(--bg-hover); border-radius: 5px; padding: 1px 7px; }
.cm-role { font-size: 12px; color: var(--text-2); }
.cm-demand { font-size: 12px; color: var(--text-3); line-height: 1.6; padding: 10px 16px 0; margin: 0; }
.cm-links { padding: 6px 16px 14px; }
.cm-link { padding: 12px 0; border-top: 1px solid var(--border); }
.cm-link:first-child { border-top: none; }
.cm-link-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.cm-seg { font-size: 13px; font-weight: 700; color: var(--accent); }
.cm-note { font-size: 11px; color: var(--text-3); }
.cm-suppliers { display: flex; flex-wrap: wrap; gap: 8px; }
.cm-supplier { flex: 1 1 240px; min-width: 220px; background: var(--bg-1, rgba(255,255,255,.03)); border: 1px solid var(--border); border-radius: 9px; padding: 8px 11px; }
.cms-main { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cms-name { font-size: 13px; color: var(--text-1); }
.cms-country { font-size: 10px; color: var(--text-3); background: var(--bg-hover); border-radius: 4px; padding: 0 5px; }
.cms-code { font-size: 11px; color: var(--text-3); }
.cms-price { font-size: 12px; color: var(--accent); font-weight: 600; }
.cms-bottom { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 5px; }
.cms-share { font-size: 11px; color: #dc2626; font-weight: 600; background: rgba(220,38,38,.1); border-radius: 5px; padding: 1px 7px; }
.cms-share i { font-style: normal; color: #dc2626; opacity: .7; margin-right: 4px; font-weight: 400; }
.cms-role { font-size: 11px; color: var(--text-3); line-height: 1.5; }

/* ── 生产设备 ─────────────────────────────────────────── */
.eq-wrap { display: flex; flex-direction: column; gap: 16px; }
.eq-card { border: 1px solid var(--border); border-radius: 12px; background: var(--bg-surface); padding: 14px 16px; }
.eq-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.eq-step { width: 22px; height: 22px; flex-shrink: 0; border-radius: 50%; background: var(--accent); color: #fff; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.eq-title { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; flex: 1; }
.eq-name { font-size: 15px; font-weight: 800; color: var(--text-1); }
.eq-proc { font-size: 11px; color: var(--accent); background: var(--bg-hover); border-radius: 5px; padding: 1px 7px; }
.eq-imp { font-size: 11px; color: var(--text-3); }
.eq-imp.imp-高 { color: #dc2626; font-weight: 700; }
.eq-score { margin-left: auto; }
.eq-func { font-size: 12px; color: var(--text-2); line-height: 1.6; margin-top: 8px; }
.eq-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.eq-tag { font-size: 11px; color: var(--text-2); background: var(--bg-hover); border-radius: 5px; padding: 2px 8px; }
.eq-tag i { font-style: normal; color: var(--text-3); margin-right: 5px; }
.eq-reason { font-size: 12px; color: #dc2626; line-height: 1.6; margin-top: 8px; background: rgba(220,38,38,.08); border-radius: 6px; padding: 6px 10px; }
.eq-makers { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 12px; }
.eq-maker-col { min-width: 0; }
.eq-maker-head { font-size: 12px; font-weight: 700; color: var(--text-2); margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.eq-maker-row { display: flex; gap: 8px; padding: 7px 0; }
.eq-maker-row .rank-no { flex-shrink: 0; }
.eq-maker-body { flex: 1; min-width: 0; }
.eq-maker-name { font-size: 13px; color: var(--text-1); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.eq-maker-code { font-size: 11px; color: var(--text-3); }
.eq-maker-price { font-size: 12px; color: var(--accent); font-weight: 600; }

/* ── 移动端适配 ─────────────────────────────────────────── */
@media (max-width: 768px) {
  /* 双栏 → 纵向：历史栏变顶部横向滚动条 */
  .ir-layout { flex-direction: column; height: auto; }
  .ir-history {
    width: 100%; flex-shrink: 0; border-right: none;
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
    padding: 10px 12px; overflow-x: auto; -webkit-overflow-scrolling: touch;
  }
  .new-btn { width: auto; margin-bottom: 0; padding: 8px 14px; white-space: nowrap; flex-shrink: 0; }
  .hist-title { display: none; }
  .hist-item { flex-shrink: 0; margin-bottom: 0; padding: 6px 10px; max-width: 180px; }
  .hist-actions { opacity: 1; }

  .ir-main { padding: 14px 12px; }
  .hero-text h2 { font-size: 19px; }

  /* tab 栏横向滚动 */
  .tab-bar { padding: 10px 12px; }

  /* 固定列网格全部折叠 */
  .rec-grid, .seg-grid, .points-grid, .cand-grid { grid-template-columns: 1fr; }
  .rec-metrics { grid-template-columns: repeat(3, 1fr); }
  .cc-prices { grid-template-columns: 1fr 1fr; }
  .rank-grid { grid-template-columns: 1fr; gap: 12px; }
  .cl-stock { flex: 1 1 100%; min-width: 0; }
  .eq-makers { grid-template-columns: 1fr; gap: 10px; }

  /* 成本条：标签换行到上方 */
  .cost-bar-item, .sub-break .cost-bar-item { grid-template-columns: 1fr; gap: 4px; }

  /* 时间线缩进收紧 */
  .tl-item { grid-template-columns: 70px 1fr; gap: 10px; }

  /* 表格横向滚动（table 转 block 撑开内容宽度） */
  .ir-main .data-table {
    display: block; overflow-x: auto; -webkit-overflow-scrolling: touch;
    white-space: nowrap;
  }

  .board-head { flex-direction: column; gap: 10px; padding: 16px; }
}

/* ── 瓶颈卡位视角（卡脖子排行 / 价值迁移 / 海外映射 / 卡位标签）── */
.sc-high { color: #dc2626; }
.sc-mid  { color: #d97706; }
.sc-low  { color: #16a34a; }

/* 个股卡脖子评分榜 */
.bs-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.bs-table { min-width: 760px; }
.bs-table th, .bs-table td { white-space: nowrap; }
.bs-rank { font-weight: 700; color: #1f2937; }
.bs-code { margin-left: 6px; font-size: 12px; color: #8a93a6; }
.bs-reason { font-size: 12px; color: #6b7280; line-height: 1.4; white-space: normal; max-width: 240px; margin-top: 2px; }
.bs-val { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 10px; border: 1px solid transparent; }
.val-low  { color: #16a34a; background: #effaf1; border-color: #c6ecd0; }
.val-fair { color: #d97706; background: #fff6e8; border-color: #f3dcb0; }
.val-high { color: #dc2626; background: #fff0f0; border-color: #f5c2c2; }
.val-loss { color: #6b7280; background: #f3f4f6; border-color: #e5e7eb; }
.up-red { color: #dc2626; }
.down-green { color: #16a34a; }
/* 竞争格局上中下游分组标签 */
.rank-seg-label { margin: 12px 0 4px; font-size: 13px; font-weight: 700; color: #4b5563;
  padding-left: 8px; border-left: 3px solid #6366f1; }

.bn-list { display: flex; flex-direction: column; gap: 10px; }
.bn-item { display: flex; gap: 12px; align-items: flex-start;
  padding: 12px 14px; border: 1px solid #eceef3; border-radius: 10px; background: #fbfcfe; }
.bn-rank { flex: 0 0 26px; width: 26px; height: 26px; border-radius: 50%;
  background: #1f2937; color: #fff; font-weight: 700; font-size: 13px;
  display: flex; align-items: center; justify-content: center; }
.bn-body { flex: 1; min-width: 0; }
.bn-top { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.bn-name { font-size: 15px; }
.bn-score { font-size: 12px; font-weight: 700; padding: 1px 8px; border-radius: 10px;
  background: #fff0f0; border: 1px solid #fadcdc; }
.bn-score.sc-high { background: #fff0f0; border-color: #f5c2c2; }
.bn-score.sc-mid  { background: #fff6e8; border-color: #f3dcb0; }
.bn-score.sc-low  { background: #effaf1; border-color: #c6ecd0; }
.bn-vshare { font-size: 12px; color: #6b7280; }
.bn-bar { height: 6px; border-radius: 4px; background: #eef0f4; margin: 7px 0 6px; overflow: hidden; }
.bn-bar-fill { height: 100%; border-radius: 4px; background: #dc2626; }
.bn-bar-fill.sc-mid { background: #d97706; }
.bn-bar-fill.sc-low { background: #16a34a; }
.bn-reason { font-size: 13px; color: #374151; line-height: 1.5; }
.bn-leader { font-size: 12.5px; color: #6b7280; margin-top: 3px; }

.value-mig .vm-flow { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.vm-node { padding: 6px 14px; border-radius: 8px; font-weight: 600; font-size: 14px; }
.vm-node.from { background: #f1f3f7; color: #6b7280; }
.vm-node.to { background: #fff0f0; color: #dc2626; border: 1px solid #f5c2c2; }
.vm-arrow { color: #9ca3af; font-size: 18px; }
.vm-benef { margin-top: 8px; font-size: 13px; color: #b45309; font-weight: 600; }

.om-list { display: flex; flex-direction: column; gap: 12px; }
.om-item { padding: 12px 14px; border: 1px solid #eceef3; border-radius: 10px; background: #fbfcfe; }
.om-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
.om-anchor { font-weight: 700; font-size: 14px; color: #1d4ed8; }
.om-cert { font-size: 12px; padding: 1px 8px; border-radius: 10px; background: #eef2ff; color: #4f46e5; }
.om-trans { font-size: 13px; color: #374151; margin-bottom: 4px; }
.om-seg { font-size: 13px; margin-bottom: 4px; }
.om-cat { font-size: 12.5px; color: #6b7280; margin-bottom: 6px; }
.om-stocks { display: flex; flex-direction: column; gap: 6px; }
.om-stock { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 6px 10px; background: #fff; border: 1px solid #eef0f4; border-radius: 8px; }
.om-code { color: #6b7280; font-size: 12px; }
.om-price { color: #dc2626; font-size: 12px; }
.om-role { font-size: 12px; color: #6b7280; }

/* 产业链卡位标签 */
.cp-tag, .cc-tag.cp { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 9px; }
.cp-bottleneck { background: #fff0f0; color: #dc2626; border: 1px solid #f5c2c2; }
.cp-terminal { background: #f1f3f7; color: #94a3b8; border: 1px solid #e2e6ec; }
.cp-general { background: #eef6ff; color: #2563eb; border: 1px solid #d4e6fb; }
.cp-tag { margin: 0 4px; }

/* 终端整机标的：决策卡片整体降权（灰化） */
.cand-card.is-terminal { opacity: 0.72; background: #fafbfc; }
.cand-card.is-terminal::after { content: '终端·非首选'; position: absolute; top: 8px; right: 10px;
  font-size: 10px; color: #94a3b8; background: #f1f3f7; padding: 1px 6px; border-radius: 8px; }
.cand-card { position: relative; }

/* 瓶颈环节高亮（细分环节卡片） */
.seg-card.seg-bottleneck { border-color: #f5c2c2; box-shadow: 0 0 0 1px #f9dada inset; }
.seg-score { font-weight: 700; }

/* ── 分析进度 UI ──────────────────────────────────────────────── */

/* 英雄区紧凑进度框（有/无报告时均显示） */
.hero-progress {
  flex-shrink: 0; min-width: 260px; max-width: 360px;
  background: var(--bg-elevated); border: 1px solid rgba(59,130,246,.3);
  border-radius: 12px; padding: 12px 16px;
}
.hp-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.hp-stage { flex: 1; font-size: 12px; font-weight: 600; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.hp-pct { font-weight: 700; color: var(--accent); font-family: var(--font-mono); font-size: 13px; flex-shrink: 0; }
.hp-eta { font-size: 11px; color: var(--text-3); white-space: nowrap; flex-shrink: 0; }
.hp-bar-track { height: 5px; background: var(--bg-hover); border-radius: 4px; overflow: hidden; margin-bottom: 8px; }
.hp-bar-fill { height: 100%; background: var(--accent); border-radius: 4px; transition: width 0.8s ease; }
.hp-stats { font-size: 11px; color: var(--text-3); line-height: 1.8; }

/* 报告看板顶部重跑进度条 */
.reboard-progress {
  padding: 9px 24px; background: rgba(59,130,246,.05);
  border-bottom: 1px solid rgba(59,130,246,.18);
}
.rbp-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.rbp-stage { font-size: 12px; font-weight: 600; color: var(--accent); }
.rbp-pct { font-size: 12px; font-family: var(--font-mono); color: var(--accent); font-weight: 700; }
.rbp-eta { font-size: 11px; color: var(--text-3); }
.rbp-detail { font-size: 11px; color: var(--text-3); }
.rbp-bar { height: 4px; background: var(--bg-hover); border-radius: 3px; overflow: hidden; }
.rbp-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.8s ease; }
.rbp-fill--err { background: #ef4444; }
.rbp--err .rbp-stage { color: #ef4444; }
.rbp--err .rbp-pct { color: #ef4444; }
.rbp-err-msg { font-size: 11px; color: #ef4444; margin-bottom: 5px; word-break: break-all; opacity: .9; }

/* 首次分析时的完整进度面板（空态） */
.empty-board { text-align: center; padding: 60px 0 80px; color: var(--text-3); }
.empty-icon { font-size: 56px; margin-bottom: 16px; }
.ana-panel {
  max-width: 540px; margin: 0 auto; text-align: left;
  background: var(--bg-elevated); border: 1px solid rgba(59,130,246,.22);
  border-radius: 16px; padding: 26px 26px 22px;
  box-shadow: 0 4px 24px rgba(59,130,246,.07);
}
.ap-header { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.ap-title { flex: 1; font-size: 15px; font-weight: 700; color: var(--text-1); }
.ap-pct-big { font-size: 22px; font-weight: 800; color: var(--accent); font-family: var(--font-mono); }
.ap-stage-text { font-size: 12px; color: var(--text-3); margin-bottom: 14px; min-height: 18px; }
.ap-bar-wrap { margin-bottom: 20px; }
.ap-bar { height: 8px; background: var(--bg-hover); border-radius: 6px; overflow: hidden; }
.ap-fill {
  height: 100%; border-radius: 6px;
  background: linear-gradient(90deg, var(--accent) 0%, #06d6c8 100%);
  transition: width 0.8s ease;
}
/* 步骤列表 */
.ap-steps { display: flex; flex-direction: column; gap: 5px; margin-bottom: 20px; }
.ap-step { display: flex; align-items: center; gap: 10px; font-size: 13px; padding: 1px 0; }
.aps-dot {
  width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid var(--border); background: transparent;
  transition: background 0.3s, border-color 0.3s;
}
.aps-label { color: var(--text-3); transition: color 0.3s; }
.aps-detail { margin-left: auto; display: flex; align-items: center; gap: 6px; }
.aps-running { font-size: 11px; color: var(--accent); font-weight: 600; }
.aps-count { font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.aps-err { font-size: 11px; color: #ef4444; font-weight: 600; }
.ap-step.step-done .aps-dot { background: var(--accent); border-color: var(--accent); }
.ap-step.step-done .aps-label { color: var(--text-2); }
.ap-step.step-done .aps-count { color: var(--text-2); }
.ap-step.step-active .aps-dot {
  background: var(--accent); border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(59,130,246,.2);
  animation: aps-pulse 1.3s ease-in-out infinite;
}
.ap-step.step-active .aps-label { color: var(--text-1); font-weight: 600; }
.ap-step.step-error .aps-dot { background: #ef4444; border-color: #ef4444; }
.ap-step.step-error .aps-label { color: #ef4444; }
@keyframes aps-pulse {
  0%,100% { box-shadow: 0 0 0 3px rgba(59,130,246,.15); }
  50%      { box-shadow: 0 0 0 6px rgba(59,130,246,.32); }
}
/* 统计数字格 */
.ap-stats {
  display: flex; gap: 18px; flex-wrap: wrap;
  padding-top: 16px; border-top: 1px solid var(--border);
}
.ap-stat { display: flex; align-items: center; gap: 10px; }
.ap-stat--hit { background: rgba(34,217,122,.07); border-radius: 6px; padding: 4px 8px; }
.ap-stat--map { background: rgba(99,102,241,.08); border-radius: 6px; padding: 4px 8px; }
.ast-icon { font-size: 20px; line-height: 1; }
.ast-val { font-size: 15px; font-weight: 700; color: var(--text-1); font-family: var(--font-mono); }
.ast-val--hit { color: #22d97a; }
.ast-lbl { font-size: 11px; color: var(--text-3); margin-top: 1px; }

@media (max-width: 768px) {
  .hero-progress { min-width: 0; max-width: 100%; margin-top: 8px; }
  .ana-panel { padding: 18px 14px; }
  .ap-stats { gap: 12px; }
}

/* ── Tab 分组分隔线 ──────────────────────────── */
.tab-sep { width: 1px; background: var(--border); margin: 6px 4px; flex-shrink: 0; align-self: stretch; }

/* ── Board head 元数据行 ─────────────────────── */
.bh-info { flex: 1; min-width: 0; }
.bh-meta {
  display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
  font-size: 12px; color: var(--text-3); margin-top: 5px; line-height: 1.8;
}
.bh-dot { color: var(--border); }
.bh-ai  { color: #16a34a; font-weight: 600; }
.bh-kws { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.bh-kws-label { font-size: 11px; color: var(--text-3); }
.bh-kw-chip { font-size: 11px; color: var(--text-2); background: var(--bg-hover); border: 1px solid var(--border); border-radius: 10px; padding: 1px 9px; }
.bh-range { font-family: var(--font-mono); }

/* ── 数据来源 & 分析过程卡 ───────────────────── */
.dsp-card {
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 20px; margin-bottom: 20px;
}
.dsp-head {
  font-size: 11px; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .06em; margin-bottom: 14px;
}

/* 统计数字行 */
.dsp-stats {
  display: flex; border: 1px solid var(--border); border-radius: 10px;
  overflow: hidden; margin-bottom: 18px;
}
.dsp-stat {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  padding: 12px 8px; gap: 3px; border-right: 1px solid var(--border); min-width: 0;
}
.dsp-stat:last-child { border-right: none; }
.dsp-stat--ai { background: rgba(22,163,74,.05); }
.dss-val { font-size: 22px; font-weight: 700; color: var(--text-1); font-family: var(--font-mono); line-height: 1.2; }
.dsp-stat--ai .dss-val { color: #16a34a; }
.dss-lbl { font-size: 12px; color: var(--text-2); font-weight: 600; text-align: center; }
.dss-sub { font-size: 10px; color: var(--text-3); text-align: center; }

/* 分析流程管道 */
.dsp-pipe {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-bottom: 12px;
}
.pp-step {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 11px; border: 1px solid var(--border);
  border-radius: 9px; background: var(--bg-surface);
}
.pp-step--ai   { border-color: rgba(22,163,74,.3);  background: rgba(22,163,74,.04); }
.pp-step--done { border-color: rgba(59,130,246,.3); background: rgba(59,130,246,.04); }
.pp-num {
  width: 20px; height: 20px; border-radius: 50%;
  background: var(--bg-hover); color: var(--text-3);
  font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.pp-step--ai   .pp-num { background: rgba(22,163,74,.15);  color: #16a34a; }
.pp-step--done .pp-num { background: rgba(59,130,246,.15); color: var(--accent); }
.pp-body { display: flex; flex-direction: column; gap: 1px; }
.pp-lbl { font-size: 12px; color: var(--text-2); font-weight: 600; white-space: nowrap; }
.pp-val { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); white-space: nowrap; }
.pp-step--ai   .pp-val { color: #16a34a; font-weight: 600; }
.pp-step--done .pp-val { color: var(--accent); font-weight: 600; }
.pp-arr { color: var(--text-3); font-size: 16px; flex-shrink: 0; }

/* 底部覆盖率行 */
.dsp-footer {
  display: flex; gap: 14px; flex-wrap: wrap;
  font-size: 12px; color: var(--text-3); margin-top: 4px;
}
.dsp-ratio { color: #16a34a; font-weight: 600; }

/* Mobile */
@media (max-width: 768px) {
  .dsp-stats { flex-wrap: wrap; }
  .dsp-stat  { flex: 1 1 calc(33% - 2px); min-width: 0; }
  .dsp-pipe  { gap: 4px; }
  .pp-step   { padding: 6px 8px; }
  .pp-lbl    { font-size: 11px; }
}
</style>
