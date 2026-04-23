<template>
  <div class="screener-view">

    <!-- ── Tab bar ── -->
    <div class="view-tabs">
      <button :class="['view-tab', mode === 'strategy' ? 'active' : '']" @click="mode = 'strategy'">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>
          <rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>
        </svg>
        策略选股
      </button>
      <button :class="['view-tab', mode === 'custom' ? 'active' : '']" @click="mode = 'custom'">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="14" y2="12"/><line x1="4" y1="18" x2="17" y2="18"/>
        </svg>
        自定义因子
      </button>
      <button :class="['view-tab', mode === 'summary' ? 'active' : '']" @click="mode = 'summary'">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
        </svg>
        汇总推荐
      </button>
    </div>

    <!-- ════════════ STRATEGY MODE ════════════ -->
    <div v-if="mode === 'strategy'" class="strategy-mode">
      <div class="strategy-header">
        <div>
          <div class="strategy-title">量化选股策略库</div>
          <div class="strategy-subtitle">共 {{ screeningStrategies.length }} 个策略，覆盖动量、价值、成长、反转等全市场风格</div>
        </div>
        <div class="cat-pills">
          <button
            v-for="cat in stratCategories" :key="cat.key"
            :class="['cat-pill', activeCat === cat.key ? 'active' : '']"
            :style="activeCat === cat.key ? { borderColor: cat.color, color: cat.color, background: cat.color + '18' } : {}"
            @click="activeCat = activeCat === cat.key ? 'all' : cat.key"
          >
            <span class="cat-pill-dot" v-if="cat.key !== 'all'" :style="{ background: cat.color }"></span>
            {{ cat.label }}
            <span class="cat-pill-count">{{ cat.count }}</span>
          </button>
          <button class="cat-pill ai-pill" @click="showAIModal = true">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9 12l2 2 4-4"/></svg>
            AI 生成策略
          </button>
        </div>
      </div>

      <!-- Grouped strategy sections -->
      <template v-if="activeCat === 'all'">
        <div v-for="group in stratGroups" :key="group.key" class="strat-group">
          <div class="strat-group-hd">
            <span class="strat-group-dot" :style="{ background: group.color }"></span>
            <span class="strat-group-label">{{ group.label }}</span>
            <span class="strat-group-count">{{ group.strategies.length }} 个策略</span>
          </div>
          <div class="strat-grid">
            <div
              v-for="s in group.strategies" :key="s.key"
              :class="['strat-card', activeStratKey === s.key ? 'selected' : '']"
              :style="{ '--sc': s.category_color }"
            >
              <div class="strat-card-top">
                <div class="strat-id-badge">{{ s.id }}</div>
                <span class="strat-risk-badge" :class="'risk-' + riskClass(s.risk)">{{ s.risk }}</span>
              </div>
              <div class="strat-name">{{ s.display_name }}</div>
              <div class="strat-rationale">{{ s.rationale || s.description?.slice(0, 60) }}</div>
              <div class="strat-meta">
                <span class="strat-meta-item">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  {{ s.holding_period }}
                </span>
                <span class="strat-meta-item strat-suitable-short">{{ s.suitable?.split('、')[0] }}</span>
              </div>
              <div v-if="stratResults[s.key]" class="strat-hit-bar">
                <span class="strat-hit-count">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  命中 {{ stratResults[s.key].stocks?.length }} 只
                </span>
                <button class="btn-view-stocks" @click="openStocksModal(s.key)">查看 ▸</button>
              </div>
              <div class="strat-actions">
                <button
                  class="strat-run-btn"
                  :class="{ running: runningKey === s.key }"
                  @click="runStrategy(s.key)"
                  :disabled="!!runningKey"
                >
                  <span v-if="runningKey === s.key" class="spinner spinner-sm"></span>
                  <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  {{ runningKey === s.key ? '筛选中...' : stratResults[s.key] ? '重新运行' : '运行' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- Single category filtered view -->
      <template v-else>
        <div class="strat-grid">
          <div
            v-for="s in filteredStrategies" :key="s.key"
            :class="['strat-card', activeStratKey === s.key ? 'selected' : '']"
            :style="{ '--sc': s.category_color }"
          >
            <div class="strat-card-top">
              <div class="strat-id-badge">{{ s.id }}</div>
              <span class="strat-risk-badge" :class="'risk-' + riskClass(s.risk)">{{ s.risk }}</span>
            </div>
            <div class="strat-name">{{ s.display_name }}</div>
            <div class="strat-rationale">{{ s.rationale || s.description?.slice(0, 60) }}</div>
            <div class="strat-meta">
              <span class="strat-meta-item">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                {{ s.holding_period }}
              </span>
              <span class="strat-meta-item strat-suitable-short">{{ s.suitable?.split('、')[0] }}</span>
            </div>
            <div v-if="stratResults[s.key]" class="strat-hit-bar">
              <span class="strat-hit-count">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                命中 {{ stratResults[s.key].stocks?.length }} 只
              </span>
              <button class="btn-view-stocks" @click="openStocksModal(s.key)">查看 ▸</button>
            </div>
            <div class="strat-actions">
              <button
                class="strat-run-btn"
                :class="{ running: runningKey === s.key }"
                @click="runStrategy(s.key)"
                :disabled="!!runningKey"
              >
                <span v-if="runningKey === s.key" class="spinner spinner-sm"></span>
                <svg v-else width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                {{ runningKey === s.key ? '筛选中...' : stratResults[s.key] ? '重新运行' : '运行' }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <div v-if="error" class="error-box">{{ error }}</div>
    </div>

    <!-- ════════════ CUSTOM MODE ════════════ -->
    <div v-if="mode === 'custom'" class="custom-mode">
      <div class="layout">
        <!-- Left config -->
        <div class="config-panel card">
          <div class="panel-section">
            <div class="panel-title">过滤条件</div>
            <div class="form-row">
              <div class="field"><label class="form-label">最低价格</label><input class="input" type="number" v-model.number="form.min_price" /></div>
              <div class="field"><label class="form-label">最高价格</label><input class="input" type="number" v-model.number="form.max_price" placeholder="不限" /></div>
            </div>
            <div class="form-row">
              <div class="field"><label class="form-label">PE 下限</label><input class="input" type="number" v-model.number="form.min_pe" placeholder="不限" /></div>
              <div class="field"><label class="form-label">PE 上限</label><input class="input" type="number" v-model.number="form.max_pe" /></div>
            </div>
            <div class="form-row">
              <div class="field"><label class="form-label">PB 下限</label><input class="input" type="number" v-model.number="form.min_pb" placeholder="不限" /></div>
              <div class="field"><label class="form-label">PB 上限</label><input class="input" type="number" v-model.number="form.max_pb" placeholder="不限" /></div>
            </div>
            <div class="form-row">
              <div class="field"><label class="form-label">最小市值(亿)</label><input class="input" type="number" v-model.number="form.min_market_cap" placeholder="不限" /></div>
              <div class="field"><label class="form-label">最大市值(亿)</label><input class="input" type="number" v-model.number="form.max_market_cap" placeholder="不限" /></div>
            </div>
            <div class="form-row">
              <div class="field">
                <label class="form-label">交易所</label>
                <select class="select-base" v-model="form.exchange">
                  <option value="">全市场</option>
                  <option value="SSE">上交所</option>
                  <option value="SZSE">深交所</option>
                  <option value="BSE">北交所</option>
                </select>
              </div>
              <div class="field">
                <label class="form-label">返回数量</label>
                <select class="select-base" v-model.number="form.top_n">
                  <option :value="20">Top 20</option>
                  <option :value="50">Top 50</option>
                  <option :value="100">Top 100</option>
                </select>
              </div>
            </div>
          </div>

          <div class="panel-section">
            <div class="panel-title">因子权重</div>
            <div class="factor-hint text-3">权重0=禁用，合计自动归一化</div>
            <div v-for="f in factors" :key="f.name" class="factor-row">
              <div class="factor-hd">
                <span class="factor-label">{{ f.label }}</span>
                <div class="factor-right">
                  <span class="factor-src text-3">{{ f.data_source }}</span>
                  <span class="factor-wt">{{ form.factor_weights[f.name] || 0 }}</span>
                </div>
              </div>
              <input
                type="range" min="0" max="10" step="1"
                :value="form.factor_weights[f.name] || 0"
                @input="form.factor_weights[f.name] = +$event.target.value"
                class="weight-slider"
              />
              <div class="factor-desc">{{ f.description }}</div>
            </div>
          </div>

          <div class="panel-section">
            <div class="panel-title">快捷预设</div>
            <div class="preset-row">
              <button v-for="p in presets" :key="p.key" class="preset-btn" @click="applyPreset(p.key)">{{ p.label }}</button>
            </div>
          </div>

          <button class="btn-primary run-btn" @click="runCustom" :disabled="customLoading">
            <span v-if="customLoading" class="spinner spinner-sm"></span>
            {{ customLoading ? '筛选中...' : '▶ 运行选股' }}
          </button>
        </div>

        <!-- Right results -->
        <div class="result-area">
          <div v-if="!customResult && !customLoading" class="empty-state card">
            <div class="empty-icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
            </div>
            <p>配置因子权重后点击"运行选股"</p>
            <p class="empty-hint">全市场 ~5800 只 A 股实时评分</p>
          </div>

          <div v-if="customLoading" class="loading-row card" style="padding:40px;justify-content:center;gap:12px">
            <span class="spinner"></span>
            <span class="text-2">正在从东方财富拉取全市场数据并评分...</span>
          </div>

          <template v-if="customResult && !customLoading">
            <div class="result-stats-row">
              <div class="r-stat"><div class="r-stat-label">全市场</div><div class="r-stat-val">{{ customResult.total_universe?.toLocaleString() }}</div></div>
              <div class="r-stat"><div class="r-stat-label">过滤后</div><div class="r-stat-val">{{ customResult.total_after_filter?.toLocaleString() }}</div></div>
              <div class="r-stat"><div class="r-stat-label">返回</div><div class="r-stat-val">{{ customResult.stocks?.length }}</div></div>
              <div class="r-stat"><div class="r-stat-label">耗时</div><div class="r-stat-val">{{ customResult.run_time_ms }}ms</div></div>
            </div>
            <div v-if="customResult.sector_distribution?.length" class="sector-row">
              <div v-for="s in customResult.sector_distribution" :key="s.name" class="sector-chip">
                <span>{{ s.name }}</span><span class="sector-n">{{ s.count }}</span>
              </div>
            </div>
            <!-- Inline stock table for custom mode -->
            <div class="table-card card">
              <div class="modal-table-wrap" style="max-height:600px">
                <table class="data-table modal-table">
                  <thead>
                    <tr>
                      <th @click="cSort('rank')" class="sortable">#</th>
                      <th @click="cSort('code')" class="sortable">代码</th>
                      <th @click="cSort('name')" class="sortable">名称</th>
                      <th @click="cSort('price')" class="sortable">现价</th>
                      <th @click="cSort('change_pct')" class="sortable">涨跌%</th>
                      <th @click="cSort('pe')" class="sortable">PE</th>
                      <th @click="cSort('pb')" class="sortable">PB</th>
                      <th @click="cSort('market_cap')" class="sortable">市值(亿)</th>
                      <th @click="cSort('score_pct')" class="sortable">评分%</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="s in customSortedStocks" :key="s.code" class="stock-row" @click="openStockDetail(s)">
                      <td class="text-3">{{ s.rank }}</td>
                      <td><span class="mono accent">{{ s.code }}</span></td>
                      <td class="stock-name">{{ s.name }}</td>
                      <td class="mono">{{ s.price?.toFixed(2) ?? '—' }}</td>
                      <td :class="(s.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                        {{ s.change_pct != null ? ((s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(2) + '%') : '—' }}
                      </td>
                      <td class="mono">{{ s.pe != null ? s.pe.toFixed(1) : '—' }}</td>
                      <td class="mono">{{ s.pb != null ? s.pb.toFixed(2) : '—' }}</td>
                      <td class="mono">{{ s.market_cap != null ? (s.market_cap / 1e8).toFixed(0) : '—' }}</td>
                      <td>
                        <div class="score-cell">
                          <div class="score-bar-bg"><div class="score-bar-fill" :style="{ width: (s.score_pct || 0) + '%', background: 'var(--accent)' }"></div></div>
                          <span class="score-num" style="color:var(--accent)">{{ s.score_pct?.toFixed(1) }}</span>
                        </div>
                      </td>
                      <td><button class="detail-btn" @click.stop="openStockDetail(s)">详情</button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </template>

          <div v-if="customError" class="error-box">{{ customError }}</div>
        </div>
      </div>
    </div>

    <!-- ════════════ SUMMARY MODE ════════════ -->
    <div v-if="mode === 'summary'" class="summary-mode">
      <div class="summary-header">
        <div>
          <div class="strategy-title">汇总推荐</div>
          <div class="strategy-subtitle">以股票为单位，聚合所有策略命中结果，命中策略越多信号越强</div>
        </div>
        <div class="summary-actions">
          <span v-if="summaryCacheInfo" class="text-3" style="font-size:11px">
            缓存 {{ summaryCacheInfo.age_minutes }}分钟前 · {{ summaryCacheInfo.strategy_count }}个策略
          </span>
          <span v-else class="text-3" style="font-size:11px">已运行 {{ Object.keys(stratResults).length }} 个策略</span>
          <button class="btn-ghost btn-sm" @click="runAllStrategies(false)" :disabled="summaryLoading">
            <span v-if="summaryLoading" class="spinner spinner-sm"></span>
            {{ summaryLoading ? '运行中...' : '加载缓存' }}
          </button>
          <button class="btn-primary btn-sm" @click="runAllStrategies(true)" :disabled="summaryLoading">
            <span v-if="summaryLoading" class="spinner spinner-sm"></span>
            {{ summaryLoading ? '运行中...' : '重新运行全部' }}
          </button>
        </div>
      </div>

      <div v-if="summaryLoading" class="card" style="padding:40px;display:flex;align-items:center;justify-content:center;gap:12px">
        <span class="spinner"></span>
        <span class="text-2">正在运行所有策略并缓存结果，请稍候（约30-60秒）...</span>
      </div>

      <div v-if="!summaryStocks.length && !summaryLoading" class="empty-state card">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
          </svg>
        </div>
        <p>点击「加载缓存」获取上次结果，或「重新运行全部」重新筛选</p>
        <p class="empty-hint">缓存保存24小时，重新运行约需30-60秒</p>
      </div>

      <div v-if="summaryStocks.length" class="table-card card">
        <div class="summary-stats">
          <span class="text-3" style="font-size:12px">共 {{ summaryStocks.length }} 只股票，涉及 {{ Object.keys(stratResults).length }} 个策略</span>
          <div class="summary-search-wrap">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="modal-search" v-model="summaryQuery" placeholder="搜索代码/名称..." style="width:160px" />
          </div>
        </div>
        <div class="modal-table-wrap" style="max-height:600px">
          <table class="data-table modal-table">
            <thead>
              <tr>
                <th>#</th>
                <th>代码</th>
                <th>名称</th>
                <th>现价</th>
                <th>涨跌%</th>
                <th>PE</th>
                <th>PB</th>
                <th>市值(亿)</th>
                <th>命中策略</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(s, idx) in filteredSummaryStocks" :key="s.code" class="stock-row" @click="openStockDetail(s)">
                <td class="text-3">{{ idx + 1 }}</td>
                <td><span class="mono accent">{{ s.code }}</span></td>
                <td class="stock-name">{{ s.name }}</td>
                <td class="mono">{{ s.price?.toFixed(2) ?? '—' }}</td>
                <td :class="(s.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                  {{ s.change_pct != null ? ((s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(2) + '%') : '—' }}
                </td>
                <td class="mono">{{ s.pe != null ? s.pe.toFixed(1) : '—' }}</td>
                <td class="mono">{{ s.pb != null ? s.pb.toFixed(2) : '—' }}</td>
                <td class="mono">{{ s.market_cap != null ? (s.market_cap / 1e8).toFixed(0) : '—' }}</td>
                <td>
                  <div class="strategy-tags">
                    <span v-for="tag in s.strategies" :key="tag.key"
                      class="strat-tag"
                      :style="{ background: tag.color + '20', color: tag.color, borderColor: tag.color + '40' }">
                      {{ tag.id }}
                    </span>
                  </div>
                </td>
                <td><button class="detail-btn" @click.stop="openStockDetail(s)">详情</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ════════════ AI Generate Modal ════════════ -->
    <Teleport to="body">
      <div v-if="showAIModal" class="modal-overlay" @click.self="showAIModal = false">
        <div class="modal ai-modal">
          <div class="modal-header">
            <div class="modal-header-left">
              <div class="modal-title">AI 生成选股策略</div>
              <div class="modal-sub text-3">描述你想要的股票特征，AI 将生成对应的因子配置</div>
            </div>
            <button class="modal-close" @click="showAIModal = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <div class="ai-modal-body">
            <div class="field">
              <label class="form-label">用自然语言描述选股条件</label>
              <textarea class="ai-textarea" v-model="aiDescription" placeholder="例如：寻找低PE、高ROE的价值成长股，市值在50-500亿之间，主板优先" rows="4"></textarea>
            </div>

            <div class="ai-examples">
              <span class="text-3" style="font-size:11px">快捷示例：</span>
              <button v-for="ex in aiExamples" :key="ex" class="ai-example-btn" @click="aiDescription = ex">{{ ex }}</button>
            </div>

            <div class="ai-actions">
              <button class="btn-primary" @click="generateAI" :disabled="aiLoading || !aiDescription">
                <span v-if="aiLoading" class="spinner spinner-sm"></span>
                {{ aiLoading ? 'AI 生成中...' : '✨ 生成策略配置' }}
              </button>
            </div>

            <div v-if="aiError" class="error-box" style="margin-top:12px">{{ aiError }}</div>

            <!-- AI result -->
            <div v-if="aiResult" class="ai-result">
              <div class="ai-result-title">生成结果</div>
              <div class="ai-config-preview">
                <div v-if="aiResult.config.min_price || aiResult.config.max_price" class="config-item">
                  <span class="config-key">价格范围</span>
                  <span class="config-val">{{ aiResult.config.min_price ?? '—' }} ~ {{ aiResult.config.max_price ?? '不限' }}</span>
                </div>
                <div v-if="aiResult.config.min_pe != null || aiResult.config.max_pe != null" class="config-item">
                  <span class="config-key">PE</span>
                  <span class="config-val">{{ aiResult.config.min_pe ?? '—' }} ~ {{ aiResult.config.max_pe ?? '不限' }}</span>
                </div>
                <div v-if="aiResult.config.min_pb != null || aiResult.config.max_pb != null" class="config-item">
                  <span class="config-key">PB</span>
                  <span class="config-val">{{ aiResult.config.min_pb ?? '—' }} ~ {{ aiResult.config.max_pb ?? '不限' }}</span>
                </div>
                <div v-if="aiResult.config.min_market_cap || aiResult.config.max_market_cap" class="config-item">
                  <span class="config-key">市值(亿)</span>
                  <span class="config-val">{{ aiResult.config.min_market_cap ?? '—' }} ~ {{ aiResult.config.max_market_cap ?? '不限' }}</span>
                </div>
                <div v-if="aiResult.config.exchange" class="config-item">
                  <span class="config-key">交易所</span>
                  <span class="config-val">{{ aiResult.config.exchange }}</span>
                </div>
                <div class="config-item">
                  <span class="config-key">返回数量</span>
                  <span class="config-val">Top {{ aiResult.config.top_n || 50 }}</span>
                </div>
                <div v-if="aiResult.config.factor_weights" class="config-item config-weights">
                  <span class="config-key">因子权重</span>
                  <div class="weight-tags">
                    <span v-for="(v, k) in aiResult.config.factor_weights" :key="k"
                      v-if="v > 0"
                      class="weight-tag">{{ k }}: {{ v }}</span>
                  </div>
                </div>
              </div>
              <div class="ai-result-actions">
                <button class="btn-ghost" @click="showAIModal = false">取消</button>
                <button class="btn-primary" @click="applyAIConfig">应用到自定义模式并运行 →</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ════════════ Stocks Modal ════════════ -->
    <Teleport to="body">
      <div v-if="modal.open" class="modal-overlay" @click.self="closeModal">
        <div class="modal" :style="{ '--mc': modal.color }">

          <!-- Modal header -->
          <div class="modal-header">
            <div class="modal-header-left">
              <span class="modal-id">{{ modal.stratId }}</span>
              <div>
                <div class="modal-title">{{ modal.stratName }}</div>
                <div class="modal-sub text-3">命中 {{ modal.stocks.length }} 只股票 · {{ modal.rationale }}</div>
              </div>
            </div>
            <div class="modal-header-right">
              <div class="modal-search-wrap">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                <input class="modal-search" v-model="modal.query" placeholder="搜索代码/名称..." />
              </div>
              <button class="modal-close" @click="closeModal">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>

          <!-- Stats bar inside modal -->
          <div class="modal-stats">
            <div class="m-stat"><span class="m-stat-l">命中数量</span><span class="m-stat-v">{{ modal.stocks.length }}</span></div>
            <div class="m-stat" v-if="modal.meta.total_universe"><span class="m-stat-l">全市场</span><span class="m-stat-v">{{ modal.meta.total_universe?.toLocaleString() }}</span></div>
            <div class="m-stat" v-if="modal.meta.total_after_filter"><span class="m-stat-l">过滤后</span><span class="m-stat-v">{{ modal.meta.total_after_filter?.toLocaleString() }}</span></div>
            <div class="m-stat" v-if="modal.meta.run_time_ms"><span class="m-stat-l">耗时</span><span class="m-stat-v">{{ modal.meta.run_time_ms }}ms</span></div>
            <div class="m-stat"><span class="m-stat-l">因子</span><span class="m-stat-v m-fac">{{ (modal.meta.factors_used || []).join(' · ') }}</span></div>
            <router-link
              v-if="modal.stocks.length"
              :to="{ path: '/backtest', query: { symbols: modal.stocks.slice(0,10).map(s=>s.code).join(',') } }"
              class="btn-to-backtest"
              @click="closeModal"
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3h6l1 9H8L9 3z"/><path d="M6.1 15a3 3 0 0 0 2.19 5h7.42a3 3 0 0 0 2.19-5L15 12H9L6.1 15z"/></svg>
              批量回测（前{{ Math.min(modal.stocks.length,10) }}只）
            </router-link>
          </div>

          <!-- Board distribution chips -->
          <div v-if="modal.meta.sector_distribution?.length" class="modal-sectors">
            <div v-for="s in modal.meta.sector_distribution" :key="s.name" class="sector-chip">
              <span>{{ s.name }}</span><span class="sector-n">{{ s.count }}</span>
            </div>
          </div>

          <!-- Stock table -->
          <div class="modal-table-wrap">
            <table class="data-table modal-table">
              <thead>
                <tr>
                  <th @click="mSort('rank')" class="sortable"># <span class="sort-arrow">{{ mSortKey === 'rank' ? (mSortAsc ? '↑' : '↓') : '' }}</span></th>
                  <th @click="mSort('code')" class="sortable">代码</th>
                  <th @click="mSort('name')" class="sortable">名称</th>
                  <th @click="mSort('price')" class="sortable">现价</th>
                  <th @click="mSort('change_pct')" class="sortable">涨跌%</th>
                  <th @click="mSort('pe')" class="sortable">PE</th>
                  <th @click="mSort('pb')" class="sortable">PB</th>
                  <th @click="mSort('market_cap')" class="sortable">市值(亿)</th>
                  <th @click="mSort('score_pct')" class="sortable">评分%</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="s in modalSortedStocks" :key="s.code"
                  :class="['stock-row', selectedStock?.code === s.code ? 'row-selected' : '']"
                  @click="selectedStock = selectedStock?.code === s.code ? null : s"
                >
                  <td class="text-3">{{ s.rank }}</td>
                  <td><span class="mono accent">{{ s.code }}</span></td>
                  <td class="stock-name">{{ s.name }}</td>
                  <td class="mono">{{ s.price?.toFixed(2) ?? '—' }}</td>
                  <td :class="(s.change_pct ?? 0) >= 0 ? 'pos' : 'neg'">
                    {{ s.change_pct != null ? ((s.change_pct >= 0 ? '+' : '') + s.change_pct.toFixed(2) + '%') : '—' }}
                  </td>
                  <td class="mono">{{ s.pe != null ? s.pe.toFixed(1) : '—' }}</td>
                  <td class="mono">{{ s.pb != null ? s.pb.toFixed(2) : '—' }}</td>
                  <td class="mono">{{ s.market_cap != null ? (s.market_cap / 1e8).toFixed(0) : '—' }}</td>
                  <td>
                    <div class="score-cell">
                      <div class="score-bar-bg">
                        <div class="score-bar-fill" :style="{ width: (s.score_pct || 0) + '%', background: modal.color }"></div>
                      </div>
                      <span class="score-num" :style="{ color: modal.color }">{{ s.score_pct?.toFixed(1) }}</span>
                    </div>
                  </td>
                  <td>
                    <button class="detail-btn" @click.stop="openStockDetail(s)">详情</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ════════════ Stock Detail Drawer ════════════ -->
    <Teleport to="body">
      <div v-if="stockDetail" class="drawer-overlay" @click.self="stockDetail = null">
        <div class="stock-drawer">
          <div class="stock-drawer-header">
            <div class="stock-drawer-title-row">
              <span class="mono accent" style="font-size:16px;font-weight:700">{{ stockDetail.code }}</span>
              <span class="stock-drawer-name">{{ stockDetail.name }}</span>
              <span :class="['chg-badge', (stockDetail.change_pct ?? 0) >= 0 ? 'chg-up' : 'chg-down']">
                {{ stockDetail.change_pct != null ? ((stockDetail.change_pct >= 0 ? '+' : '') + stockDetail.change_pct.toFixed(2) + '%') : '—' }}
              </span>
            </div>
            <button class="modal-close" @click="stockDetail = null">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
          </div>

          <div class="stock-drawer-body">
            <!-- Price hero -->
            <div class="price-hero">
              <div class="price-val mono">¥{{ stockDetail.price?.toFixed(2) ?? '—' }}</div>
              <div class="price-label">现价</div>
            </div>

            <!-- Key metrics grid -->
            <div class="detail-grid">
              <div class="detail-cell">
                <div class="detail-cell-label">PE（市盈率）</div>
                <div class="detail-cell-val mono">{{ stockDetail.pe?.toFixed(2) ?? '—' }}</div>
              </div>
              <div class="detail-cell">
                <div class="detail-cell-label">PB（市净率）</div>
                <div class="detail-cell-val mono">{{ stockDetail.pb?.toFixed(2) ?? '—' }}</div>
              </div>
              <div class="detail-cell">
                <div class="detail-cell-label">总市值</div>
                <div class="detail-cell-val mono">{{ stockDetail.market_cap != null ? (stockDetail.market_cap / 1e8).toFixed(2) + ' 亿' : '—' }}</div>
              </div>
              <div class="detail-cell">
                <div class="detail-cell-label">流通市值</div>
                <div class="detail-cell-val mono">{{ stockDetail.circulating_cap != null ? (stockDetail.circulating_cap / 1e8).toFixed(2) + ' 亿' : '—' }}</div>
              </div>
              <div class="detail-cell">
                <div class="detail-cell-label">换手率</div>
                <div class="detail-cell-val mono">{{ stockDetail.turnover_rate?.toFixed(2) ?? '—' }}%</div>
              </div>
              <div class="detail-cell" v-if="stockDetail.roe != null">
                <div class="detail-cell-label">ROE</div>
                <div class="detail-cell-val mono">{{ stockDetail.roe?.toFixed(2) }}%</div>
              </div>
              <div class="detail-cell" v-if="stockDetail.industry">
                <div class="detail-cell-label">行业</div>
                <div class="detail-cell-val">{{ stockDetail.industry }}</div>
              </div>
              <div class="detail-cell">
                <div class="detail-cell-label">综合评分</div>
                <div class="detail-cell-val mono" style="color:var(--accent)">{{ stockDetail.score_pct?.toFixed(1) }}%</div>
              </div>
            </div>

            <!-- Factor scores if available -->
            <div v-if="stockFactorKeys(stockDetail).length" class="factor-scores-section">
              <div class="factor-scores-title">因子得分</div>
              <div class="factor-scores-grid">
                <div v-for="key in stockFactorKeys(stockDetail)" :key="key" class="factor-score-item">
                  <div class="fs-label">{{ factorLabel(key) }}</div>
                  <div class="fs-bar-wrap">
                    <div class="fs-bar-bg">
                      <div class="fs-bar-fill" :style="{ width: Math.min(Math.max((stockDetail[key] + 3) / 6 * 100, 0), 100) + '%' }"></div>
                    </div>
                    <span class="fs-val mono">{{ stockDetail[key]?.toFixed(2) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Quick actions -->
            <div class="drawer-actions">
              <router-link :to="{ path: '/backtest', query: { symbol: stockDetail.code } }" class="btn-ghost" @click="stockDetail = null">去回测</router-link>
              <router-link :to="{ path: '/live', query: { symbol: stockDetail.code } }" class="btn-primary" @click="stockDetail = null">启动模拟 ▶</router-link>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import axios from 'axios'

// ── A tiny inline component used only in custom mode ──────────────────────────
// (Avoids runtime-compiler dependency — all logic is in the parent template)
// Stock detail is opened via openStockDetail()

// ── State ─────────────────────────────────────────────────────────────────────
const mode             = ref('strategy')
const factors          = ref([])
const screeningStrategies = ref([])

// Strategy mode
const activeCat        = ref('all')
const runningKey       = ref('')
const stratResults     = ref({})   // key → full API response
const error            = ref('')

// Custom mode
const customLoading    = ref(false)
const customResult     = ref(null)
const customError      = ref('')
const cSortKey         = ref('rank')
const cSortAsc         = ref(true)

// Stocks modal
const modal = ref({
  open: false, stratKey: '', stratId: '', stratName: '', rationale: '', color: 'var(--accent)',
  stocks: [], meta: {}, query: '',
})
const mSortKey   = ref('rank')
const mSortAsc   = ref(true)
const selectedStock = ref(null)

// Stock detail drawer
const stockDetail = ref(null)

// Summary mode
const summaryQuery   = ref('')
const summaryLoading = ref(false)
const summaryCacheInfo = ref(null)  // {saved_at, age_minutes, strategy_count}

// AI modal
const showAIModal    = ref(false)
const aiDescription  = ref('')
const aiLoading      = ref(false)
const aiError        = ref('')
const aiResult       = ref(null)
const aiExamples = [
  '低PE高ROE的价值成长股，市值50-500亿',
  '近期强势上涨、换手率高的动量股',
  '小市值、低估值的潜力股',
  '大蓝筹，高股息，稳健型',
]

// Custom form
const form = ref({
  min_price: 2.0, max_price: null, min_pe: null, max_pe: 200,
  min_pb: null, max_pb: null, min_market_cap: null, max_market_cap: null,
  exchange: '', top_n: 50,
  factor_weights: {
    value: 3, pb: 1, graham: 0, value_composite: 0,
    momentum: 2, size: 1, large_cap: 0, liquidity: 1, quality: 0, float_ratio: 0,
  },
})

const presets = [
  { key: 'value',    label: '价值型',   weights: { value: 5, pb: 3, graham: 2, momentum: 0, size: 0, large_cap: 1, liquidity: 1, quality: 1, value_composite: 0, float_ratio: 0 } },
  { key: 'momentum', label: '动量型',   weights: { momentum: 7, liquidity: 4, size: 2, value: 1, pb: 0, quality: 0, large_cap: 0, graham: 0, value_composite: 0, float_ratio: 1 } },
  { key: 'quality',  label: '质量成长', weights: { quality: 6, value: 3, pb: 2, momentum: 2, value_composite: 2, size: 0, large_cap: 0, graham: 0, liquidity: 1, float_ratio: 0 } },
  { key: 'smallcap', label: '小市值',  weights: { size: 7, momentum: 3, liquidity: 2, value: 1, pb: 0, quality: 0, large_cap: 0, graham: 0, value_composite: 0, float_ratio: 0 } },
  { key: 'bluechip', label: '蓝筹',    weights: { large_cap: 4, value: 4, pb: 3, float_ratio: 2, quality: 2, momentum: 0, size: 0, graham: 1, value_composite: 0, liquidity: 1 } },
  { key: 'balanced', label: '均衡',    weights: { value_composite: 4, quality: 3, momentum: 3, liquidity: 2, size: 1, large_cap: 0, graham: 0, value: 2, pb: 1, float_ratio: 1 } },
]

// ── Computed ──────────────────────────────────────────────────────────────────
const stratCategories = computed(() => {
  const cats = { all: { key: 'all', label: '全部', color: 'var(--text-2)', count: screeningStrategies.value.length } }
  for (const s of screeningStrategies.value) {
    if (!s.category) continue
    if (!cats[s.category]) cats[s.category] = { key: s.category, label: s.category_label, color: s.category_color, count: 0 }
    cats[s.category].count++
  }
  return Object.values(cats)
})

const customSortedStocks = computed(() => {
  if (!customResult.value?.stocks?.length) return []
  const arr = [...customResult.value.stocks]
  arr.sort((a, b) => {
    const av = a[cSortKey.value] ?? (cSortAsc.value ? Infinity : -Infinity)
    const bv = b[cSortKey.value] ?? (cSortAsc.value ? Infinity : -Infinity)
    return cSortAsc.value ? av - bv : bv - av
  })
  return arr
})

const filteredStrategies = computed(() =>
  activeCat.value === 'all'
    ? screeningStrategies.value
    : screeningStrategies.value.filter(s => s.category === activeCat.value)
)

// Grouped view: strategies organized by category, sorted by category_order
const stratGroups = computed(() => {
  const groupMap = {}
  for (const s of screeningStrategies.value) {
    const cat = s.category || 'other'
    if (!groupMap[cat]) {
      groupMap[cat] = {
        key: cat,
        label: s.category_label || cat,
        color: s.category_color || '#718096',
        order: s.category_order ?? 99,
        strategies: [],
      }
    }
    groupMap[cat].strategies.push(s)
  }
  return Object.values(groupMap).sort((a, b) => a.order - b.order)
})

const riskClass = (risk) => {
  if (!risk) return 'mid'
  if (risk.includes('低')) return 'low'
  if (risk.includes('高')) return 'high'
  return 'mid'
}

// Summary: aggregate all strategy results by stock code
const summaryStocks = computed(() => {
  const map = {}  // code → {stock data, strategies: [{key, id, color}]}
  for (const [key, res] of Object.entries(stratResults.value)) {
    const strat = screeningStrategies.value.find(s => s.key === key)
    for (const stock of (res.stocks || [])) {
      if (!map[stock.code]) {
        map[stock.code] = { ...stock, strategies: [] }
      }
      map[stock.code].strategies.push({
        key,
        id: strat?.id || key,
        name: strat?.display_name || key,
        color: strat?.category_color || 'var(--accent)',
      })
    }
  }
  return Object.values(map).sort((a, b) => b.strategies.length - a.strategies.length)
})

const filteredSummaryStocks = computed(() => {
  const q = summaryQuery.value.trim().toLowerCase()
  if (!q) return summaryStocks.value
  return summaryStocks.value.filter(s =>
    s.code?.toLowerCase().includes(q) || s.name?.toLowerCase().includes(q)
  )
})

const activeStratKey = ref('')

const modalFilteredStocks = computed(() => {
  const q = modal.value.query.trim().toLowerCase()
  if (!q) return modal.value.stocks
  return modal.value.stocks.filter(s =>
    s.code?.toLowerCase().includes(q) || s.name?.toLowerCase().includes(q)
  )
})

const modalSortedStocks = computed(() => {
  const arr = [...modalFilteredStocks.value]
  arr.sort((a, b) => {
    const av = a[mSortKey.value] ?? (mSortAsc.value ? Infinity : -Infinity)
    const bv = b[mSortKey.value] ?? (mSortAsc.value ? Infinity : -Infinity)
    return mSortAsc.value ? av - bv : bv - av
  })
  return arr
})

// ── Actions ───────────────────────────────────────────────────────────────────
async function runStrategy(key) {
  runningKey.value = key
  error.value = ''
  try {
    const res = await axios.post(`/api/screener/run-strategy/${key}`)
    stratResults.value = { ...stratResults.value, [key]: res.data }
    // Auto-open the modal after running
    openStocksModal(key)
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  }
  runningKey.value = ''
}

function openStocksModal(key) {
  const res = stratResults.value[key]
  if (!res) return
  const strat = screeningStrategies.value.find(s => s.key === key)
  modal.value = {
    open: true, stratKey: key,
    stratId: strat?.id || '',
    stratName: strat?.display_name || key,
    rationale: strat?.rationale || '',
    color: strat?.category_color || 'var(--accent)',
    stocks: res.stocks || [],
    meta: { total_universe: res.total_universe, total_after_filter: res.total_after_filter, run_time_ms: res.run_time_ms, factors_used: res.factors_used, sector_distribution: res.sector_distribution },
    query: '',
  }
  mSortKey.value = 'rank'
  mSortAsc.value = true
  selectedStock.value = null
  document.body.style.overflow = 'hidden'
}

function closeModal() {
  modal.value.open = false
  document.body.style.overflow = ''
}

function openStockDetail(s) {
  stockDetail.value = s
  document.body.style.overflow = 'hidden'
}

function mSort(key) {
  if (mSortKey.value === key) mSortAsc.value = !mSortAsc.value
  else { mSortKey.value = key; mSortAsc.value = key === 'rank' }
}

function cSort(key) {
  if (cSortKey.value === key) cSortAsc.value = !cSortAsc.value
  else { cSortKey.value = key; cSortAsc.value = key === 'rank' }
}

function applyPreset(key) {
  const p = presets.find(x => x.key === key)
  if (p) form.value.factor_weights = { ...p.weights }
}

async function runCustom() {
  customLoading.value = true
  customError.value = ''
  customResult.value = null
  try {
    const payload = {
      ...form.value,
      exchange: form.value.exchange || null,
      max_price: form.value.max_price || null,
      min_pe: form.value.min_pe || null,
      min_pb: form.value.min_pb || null,
      max_pb: form.value.max_pb || null,
      min_market_cap: form.value.min_market_cap || null,
      max_market_cap: form.value.max_market_cap || null,
    }
    const res = await axios.post('/api/screener/run', payload)
    customResult.value = res.data
  } catch (e) {
    customError.value = e.response?.data?.detail || e.message
  }
  customLoading.value = false
}

async function loadSummaryCache() {
  summaryLoading.value = true
  try {
    const res = await axios.get('/api/screener/summary')
    if (res.data.results && Object.keys(res.data.results).length > 0) {
      // Merge cached results into stratResults
      for (const [key, result] of Object.entries(res.data.results)) {
        stratResults.value = { ...stratResults.value, [key]: result }
      }
      summaryCacheInfo.value = res.data.info
    }
  } catch {}
  summaryLoading.value = false
}

async function runAllStrategies(force = false) {
  summaryLoading.value = true
  error.value = ''
  try {
    const res = await axios.post(`/api/screener/summary/run?force=${force}`)
    if (res.data.results) {
      for (const [key, result] of Object.entries(res.data.results)) {
        stratResults.value = { ...stratResults.value, [key]: result }
      }
      summaryCacheInfo.value = res.data.info
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message
  }
  summaryLoading.value = false
}

async function generateAI() {
  aiLoading.value = true; aiError.value = ''; aiResult.value = null
  try {
    const res = await axios.post('/api/screener/ai-generate', { description: aiDescription.value })
    aiResult.value = res.data
  } catch (e) {
    aiError.value = e.response?.data?.detail || e.message
  }
  aiLoading.value = false
}

function applyAIConfig() {
  if (!aiResult.value?.config) return
  const c = aiResult.value.config
  if (c.min_price != null) form.value.min_price = c.min_price
  if (c.max_price != null) form.value.max_price = c.max_price
  if (c.min_pe != null) form.value.min_pe = c.min_pe
  if (c.max_pe != null) form.value.max_pe = c.max_pe
  if (c.min_pb != null) form.value.min_pb = c.min_pb
  if (c.max_pb != null) form.value.max_pb = c.max_pb
  if (c.min_market_cap != null) form.value.min_market_cap = c.min_market_cap
  if (c.max_market_cap != null) form.value.max_market_cap = c.max_market_cap
  if (c.exchange) form.value.exchange = c.exchange
  if (c.top_n) form.value.top_n = c.top_n
  if (c.factor_weights) form.value.factor_weights = { ...form.value.factor_weights, ...c.factor_weights }
  showAIModal.value = false
  mode.value = 'custom'
  runCustom()
}

// Factor helpers for detail drawer
const factorLabelMap = computed(() => {
  const m = {}
  for (const f of factors.value) m[`factor_${f.name}`] = f.label
  return m
})
function stockFactorKeys(s) {
  return Object.keys(s || {}).filter(k => k.startsWith('factor_'))
}
function factorLabel(key) {
  return factorLabelMap.value[key] || key.replace('factor_', '')
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    if (stockDetail.value) { stockDetail.value = null }
    else if (modal.value.open) { closeModal() }
  }
}

// Auto-load cache when switching to summary tab
watch(mode, (m) => {
  if (m === 'summary' && !summaryStocks.value.length && !summaryLoading.value) {
    loadSummaryCache()
  }
})

onMounted(async () => {
  try { const r = await axios.get('/api/screener/factors'); factors.value = r.data } catch {}
  try { const r = await axios.get('/api/screener/strategies'); screeningStrategies.value = r.data } catch {}
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.body.style.overflow = ''
})
</script>

<style scoped>
.screener-view { padding: 24px; display: flex; flex-direction: column; gap: 20px; }

/* Tabs */
.view-tabs { display: flex; gap: 3px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 3px; align-self: flex-start; }
.view-tab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; border-radius: calc(var(--radius-md) - 2px); background: transparent; border: none; color: var(--text-3); font-size: 13px; cursor: pointer; transition: all 0.15s; }
.view-tab:hover { color: var(--text-1); }
.view-tab.active { background: var(--bg-elevated); color: var(--text-1); box-shadow: 0 1px 3px rgba(0,0,0,0.3); }

/* Strategy mode */
.strategy-mode { display: flex; flex-direction: column; gap: 16px; }
.strategy-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.strategy-title { font-size: 16px; font-weight: 700; }
.strategy-subtitle { font-size: 12px; color: var(--text-3); margin-top: 3px; }

.cat-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.cat-pill { display: flex; align-items: center; gap: 5px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-3); border-radius: 20px; padding: 4px 12px; font-size: 12px; cursor: pointer; transition: all 0.12s; }
.cat-pill:hover:not(.active) { color: var(--text-1); }
.cat-pill-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.cat-pill-count { font-size: 10px; opacity: 0.7; background: rgba(255,255,255,0.08); border-radius: 10px; padding: 0 5px; }

/* Strategy groups */
.strat-group { margin-bottom: 28px; }
.strat-group-hd { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.strat-group-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.strat-group-label { font-size: 14px; font-weight: 600; color: var(--text-1); }
.strat-group-count { font-size: 12px; color: var(--text-3); margin-left: auto; }

.strat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }

/* Risk badge */
.strat-risk-badge { font-size: 10px; padding: 2px 7px; border-radius: 10px; font-weight: 500; }
.strat-risk-badge.risk-low  { background: rgba(16,185,129,0.15); color: #10b981; }
.strat-risk-badge.risk-mid  { background: rgba(245,158,11,0.15); color: #f59e0b; }
.strat-risk-badge.risk-high { background: rgba(239,68,68,0.15);  color: #ef4444; }
.strat-suitable-short { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.strat-card {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-top: 3px solid var(--sc, var(--accent));
  border-radius: var(--radius-lg); padding: 16px;
  display: flex; flex-direction: column; gap: 9px;
  transition: box-shadow 0.15s;
}
.strat-card.selected { box-shadow: 0 0 0 2px var(--sc, var(--accent))44; }

.strat-card-top { display: flex; align-items: center; justify-content: space-between; }
.strat-id-badge { font-family: var(--font-mono); font-size: 10px; font-weight: 700; color: var(--sc, var(--accent)); letter-spacing: 0.05em; }
.strat-cat-badge { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 3px; }
.strat-name { font-size: 14px; font-weight: 700; color: var(--text-1); }
.strat-rationale { font-size: 12px; color: var(--text-2); line-height: 1.5; }
.strat-meta { display: flex; flex-wrap: wrap; gap: 10px; }
.strat-meta-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: var(--text-3); }
.strat-suitable { font-size: 11px; color: var(--text-3); }

.strat-hit-bar {
  display: flex; align-items: center; justify-content: space-between;
  background: color-mix(in srgb, var(--sc, var(--accent)) 8%, var(--bg-base));
  border: 1px solid color-mix(in srgb, var(--sc, var(--accent)) 25%, transparent);
  border-radius: var(--radius-sm); padding: 7px 10px;
}
.strat-hit-count { display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--sc, var(--accent)); font-weight: 600; }
.btn-view-stocks {
  font-size: 11px; font-weight: 600;
  background: color-mix(in srgb, var(--sc, var(--accent)) 18%, transparent);
  border: 1px solid color-mix(in srgb, var(--sc, var(--accent)) 40%, transparent);
  color: var(--sc, var(--accent));
  border-radius: var(--radius-sm); padding: 3px 10px; cursor: pointer;
  transition: background 0.12s;
}
.btn-view-stocks:hover { background: color-mix(in srgb, var(--sc, var(--accent)) 28%, transparent); }

.strat-actions { margin-top: auto; padding-top: 4px; }
.strat-run-btn {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  width: 100%; padding: 7px;
  background: color-mix(in srgb, var(--sc, var(--accent)) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--sc, var(--accent)) 35%, transparent);
  color: var(--sc, var(--accent));
  border-radius: var(--radius-sm); font-size: 12px; font-weight: 600; cursor: pointer;
  transition: background 0.12s;
}
.strat-run-btn:hover:not(:disabled) { background: color-mix(in srgb, var(--sc, var(--accent)) 20%, transparent); }
.strat-run-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Custom mode */
.custom-mode {}
.layout { display: grid; grid-template-columns: 300px 1fr; gap: 16px; align-items: start; }
.config-panel { padding: 16px; }
.panel-section { margin-bottom: 18px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
.panel-section:last-of-type { border-bottom: none; margin-bottom: 0; }
.panel-title { font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 12px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.field { margin-bottom: 10px; }
.factor-hint { font-size: 11px; margin-bottom: 10px; }
.factor-row { margin-bottom: 12px; }
.factor-hd { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.factor-label { font-size: 12px; color: var(--text-1); font-weight: 500; }
.factor-right { display: flex; align-items: center; gap: 8px; }
.factor-src { font-size: 10px; }
.factor-wt { font-size: 12px; color: var(--accent); font-weight: 700; min-width: 14px; text-align: right; }
.weight-slider { width: 100%; accent-color: var(--accent); cursor: pointer; }
.factor-desc { font-size: 10px; color: var(--text-3); margin-top: 2px; line-height: 1.4; }
.preset-row { display: flex; gap: 5px; flex-wrap: wrap; }
.preset-btn { background: var(--bg-elevated); border: 1px solid var(--border); color: var(--text-2); border-radius: var(--radius-sm); padding: 4px 10px; font-size: 11px; cursor: pointer; transition: all 0.12s; }
.preset-btn:hover { background: var(--bg-hover); color: var(--text-1); border-color: var(--accent); }
.run-btn { width: 100%; justify-content: center; padding: 10px; font-size: 14px; }
.result-area { display: flex; flex-direction: column; gap: 12px; }
.table-card { overflow: hidden; }

/* Shared stats row */
.result-stats-row { display: flex; gap: 10px; flex-wrap: wrap; }
.r-stat { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 9px 14px; }
.r-stat-label { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 3px; }
.r-stat-val { font-size: 15px; font-weight: 700; font-family: var(--font-mono); }
.r-stat-val.fac { font-size: 11px; color: var(--text-2); font-family: var(--font-body); max-width: 200px; }
.sector-row { display: flex; gap: 6px; flex-wrap: wrap; }
.sector-chip { display: flex; align-items: center; gap: 6px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: 20px; padding: 3px 10px; font-size: 11px; color: var(--text-2); }
.sector-n { color: var(--accent); font-weight: 600; }

/* Loading */
.loading-row { display: flex; align-items: center; gap: 10px; }

/* ── Modal ── */
.modal-overlay { position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.7); backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; padding: 24px; }
.modal {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-top: 3px solid var(--mc, var(--accent));
  border-radius: var(--radius-lg);
  width: min(900px, 100%); max-height: 85vh;
  display: flex; flex-direction: column;
  animation: fadeUp 0.2s ease;
}
@keyframes fadeUp { from { transform: translateY(20px); opacity: 0; } to { transform: none; opacity: 1; } }

.modal-header {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  padding: 18px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.modal-header-left { display: flex; align-items: center; gap: 14px; }
.modal-id { font-family: var(--font-mono); font-size: 11px; font-weight: 700; color: var(--mc, var(--accent)); background: color-mix(in srgb, var(--mc, var(--accent)) 15%, transparent); padding: 4px 8px; border-radius: 4px; flex-shrink: 0; }
.modal-title { font-size: 16px; font-weight: 700; }
.modal-sub { font-size: 11px; margin-top: 2px; }
.modal-header-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.modal-search-wrap { display: flex; align-items: center; gap: 6px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0 10px; }
.modal-search-wrap:focus-within { border-color: var(--accent); }
.modal-search { background: transparent; border: none; outline: none; color: var(--text-1); font-size: 12px; padding: 6px 0; width: 150px; font-family: var(--font-body); }
.modal-search::placeholder { color: var(--text-3); }
.modal-close { display: flex; align-items: center; justify-content: center; width: 30px; height: 30px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); cursor: pointer; transition: all 0.12s; }
.modal-close:hover { border-color: var(--danger); color: var(--danger); }

.modal-stats { display: flex; gap: 0; border-bottom: 1px solid var(--border); flex-shrink: 0; align-items: center; }
.m-stat { padding: 10px 16px; border-right: 1px solid var(--border); }
.m-stat:last-child { border-right: none; }
.m-stat-l { display: block; font-size: 10px; color: var(--text-3); text-transform: uppercase; margin-bottom: 2px; }
.m-stat-v { font-size: 14px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); }
.m-stat-v.m-fac { font-size: 11px; font-family: var(--font-body); color: var(--text-2); }
.btn-to-backtest { display: flex; align-items: center; gap: 5px; margin-left: auto; margin-right: 12px; padding: 5px 12px; border-radius: var(--radius-sm); border: 1px solid var(--accent); color: var(--accent); background: var(--accent-dim); font-size: 11px; font-weight: 500; cursor: pointer; text-decoration: none; white-space: nowrap; }
.btn-to-backtest:hover { background: color-mix(in srgb, var(--accent) 20%, transparent); }

.modal-sectors { display: flex; gap: 6px; flex-wrap: wrap; padding: 10px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0; }

.modal-table-wrap { flex: 1; overflow-y: auto; }
.modal-table { width: 100%; }
.modal-table th { position: sticky; top: 0; background: var(--bg-base); z-index: 1; }
.modal-table .sortable { cursor: pointer; user-select: none; }
.modal-table .sortable:hover { color: var(--accent); }
.sort-arrow { color: var(--accent); font-size: 10px; }
.stock-row { cursor: pointer; transition: background 0.1s; }
.stock-row:hover td { background: rgba(255,255,255,0.03); }
.stock-row.row-selected td { background: color-mix(in srgb, var(--mc, var(--accent)) 8%, transparent); }
.stock-name { max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.score-cell { display: flex; align-items: center; gap: 6px; min-width: 80px; }
.score-bar-bg { flex: 1; height: 5px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; }
.score-bar-fill { height: 100%; border-radius: 3px; opacity: 0.85; transition: width 0.3s; }
.score-num { font-size: 11px; font-family: var(--font-mono); min-width: 32px; text-align: right; }
.detail-btn { font-size: 10px; padding: 2px 8px; background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-3); cursor: pointer; white-space: nowrap; transition: all 0.12s; }
.detail-btn:hover { border-color: var(--accent); color: var(--accent); }

/* ── Stock detail drawer ── */
.drawer-overlay { position: fixed; inset: 0; z-index: 1100; background: rgba(0,0,0,0.55); backdrop-filter: blur(2px); display: flex; justify-content: flex-end; }
.stock-drawer {
  width: 380px; max-width: 95vw; height: 100%;
  background: var(--bg-surface); border-left: 1px solid var(--border);
  display: flex; flex-direction: column;
  animation: slideIn 0.2s ease;
}
@keyframes slideIn { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }

.stock-drawer-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 18px 20px; border-bottom: 1px solid var(--border);
}
.stock-drawer-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.stock-drawer-name { font-size: 16px; font-weight: 700; color: var(--text-1); }
.chg-badge { font-size: 12px; font-weight: 700; padding: 2px 8px; border-radius: 4px; }
.chg-up { background: rgba(239,68,68,0.12); color: #f87171; }
.chg-down { background: rgba(34,197,94,0.12); color: #4ade80; }

.stock-drawer-body { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 20px; }

.price-hero { text-align: center; padding: 12px 0; }
.price-val { font-size: 32px; font-weight: 800; color: var(--text-1); }
.price-label { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--border); border-radius: var(--radius-md); overflow: hidden; }
.detail-cell { background: var(--bg-base); padding: 12px 14px; }
.detail-cell-label { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; }
.detail-cell-val { font-size: 16px; font-weight: 700; color: var(--text-1); }

.factor-scores-section {}
.factor-scores-title { font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px; }
.factor-scores-grid { display: flex; flex-direction: column; gap: 8px; }
.factor-score-item {}
.fs-label { font-size: 11px; color: var(--text-2); margin-bottom: 4px; }
.fs-bar-wrap { display: flex; align-items: center; gap: 8px; }
.fs-bar-bg { flex: 1; height: 5px; background: var(--bg-elevated); border-radius: 3px; overflow: hidden; }
.fs-bar-fill { height: 100%; background: var(--accent); border-radius: 3px; opacity: 0.8; transition: width 0.3s; }
.fs-val { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); min-width: 36px; text-align: right; }

.drawer-actions { display: flex; gap: 10px; justify-content: flex-end; padding-top: 8px; border-top: 1px solid var(--border); margin-top: auto; }
.drawer-actions .btn-primary { text-decoration: none; padding: 8px 14px; }
.drawer-actions .btn-ghost { text-decoration: none; padding: 8px 14px; }

/* ── Summary mode ── */
.summary-mode { display: flex; flex-direction: column; gap: 16px; }
.summary-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.summary-actions { display: flex; align-items: center; gap: 10px; }
.btn-sm { padding: 5px 12px; font-size: 12px; }

.summary-stats { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap; gap: 8px; }
.summary-search-wrap { display: flex; align-items: center; gap: 6px; }

.strategy-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.strat-tag { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; border: 1px solid; font-family: var(--font-mono); }

/* ── AI modal ── */
.ai-pill {
  background: linear-gradient(135deg, #3b82f620, #8b5cf620) !important;
  border-color: #8b5cf660 !important;
  color: #a78bfa !important;
  display: flex; align-items: center; gap: 4px;
}
.ai-pill:hover { background: linear-gradient(135deg, #3b82f630, #8b5cf630) !important; }

.ai-modal { max-width: 560px; width: 100%; }
.ai-modal-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }

.ai-textarea {
  width: 100%; padding: 10px 12px; font-size: 13px;
  background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md);
  color: var(--text-1); resize: vertical; font-family: inherit; line-height: 1.5;
  box-sizing: border-box;
}
.ai-textarea:focus { outline: none; border-color: var(--accent); }

.ai-examples { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.ai-example-btn {
  font-size: 11px; padding: 3px 10px; background: var(--bg-elevated);
  border: 1px solid var(--border); border-radius: 20px; color: var(--text-2);
  cursor: pointer; transition: all 0.12s;
}
.ai-example-btn:hover { border-color: var(--accent); color: var(--accent); }
.ai-actions { display: flex; justify-content: flex-end; }

.ai-result { border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
.ai-result-title { font-size: 12px; font-weight: 600; color: var(--text-2); padding: 10px 14px; background: var(--bg-elevated); border-bottom: 1px solid var(--border); }
.ai-config-preview { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; }
.config-item { display: flex; align-items: flex-start; gap: 12px; font-size: 13px; }
.config-key { font-weight: 600; color: var(--text-3); min-width: 80px; font-size: 12px; padding-top: 1px; }
.config-val { color: var(--text-1); }
.config-weights .config-val { flex: 1; }
.weight-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.weight-tag { font-size: 11px; padding: 2px 8px; background: var(--accent-dim); color: var(--accent); border-radius: 4px; font-family: var(--font-mono); }
.ai-result-actions { display: flex; gap: 10px; justify-content: flex-end; padding: 12px 14px; border-top: 1px solid var(--border); }

@media (max-width: 768px) {
  .layout { grid-template-columns: 1fr; }
  .stock-drawer { width: 100%; max-width: 100%; position: fixed; inset: auto 0 0 0; height: 85vh; border-left: none; border-top: 1px solid var(--border); border-radius: var(--radius-xl) var(--radius-xl) 0 0; }
  .drawer-overlay { align-items: flex-end; }
}
</style>
