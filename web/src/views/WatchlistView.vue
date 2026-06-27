<template>
  <div class="watchlist-page">

    <!-- ── 指数条（卡片式 + 实时刷新）──────────────────────────── -->
    <div v-if="indices.length" class="index-bar">
      <div class="index-bar-head">
        <span class="ib-title">大盘指数</span>
        <span class="ib-live"><i class="live-dot"></i>实时 · {{ idxUpdated || '--:--:--' }}</span>
      </div>
      <div v-if="cnIndices.length" class="index-row">
        <span class="region-tag">沪深</span>
        <div v-for="idx in cnIndices" :key="idx.code"
          :class="['index-chip', idxCls(idx), { flash: idxFlash.has(idx.code), clickable: idx.chart_code }]"
          @click="openIndexChart(idx)"
          :title="idx.chart_code ? '点击查看走势曲线' : ''">
          <span class="idx-name">{{ idx.name }}<svg v-if="idx.chart_code" class="idx-chart-ic" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/></svg></span>
          <span class="idx-price">{{ idx.price != null ? idx.price.toFixed(2) : '--' }}</span>
          <span class="idx-delta">
            <span class="idx-chg">{{ fmtIdxChg(idx.change) }}</span>
            <span class="idx-pct">{{ fmtIdxPct(idx.change_pct) }}</span>
          </span>
        </div>
      </div>
      <div v-if="globalIndices.length" class="index-row">
        <span class="region-tag">全球</span>
        <div v-for="idx in globalIndices" :key="idx.code"
          :class="['index-chip', idxCls(idx), { flash: idxFlash.has(idx.code), clickable: idx.chart_code }]"
          @click="openIndexChart(idx)"
          :title="idx.chart_code ? '点击查看走势曲线' : ''">
          <span class="idx-name">{{ idx.name }}<svg v-if="idx.chart_code" class="idx-chart-ic" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/></svg></span>
          <span class="idx-price">{{ idx.price != null ? idx.price.toFixed(2) : '--' }}</span>
          <span class="idx-delta">
            <span class="idx-chg">{{ fmtIdxChg(idx.change) }}</span>
            <span class="idx-pct">{{ fmtIdxPct(idx.change_pct) }}</span>
          </span>
        </div>
      </div>
    </div>

    <!-- 指数走势详情弹窗 -->
    <IndexChartModal v-if="openedIndex" :index="openedIndex" @close="openedIndex = null" />

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="hub-tabs">
      <button :class="['hub-tab', tab === 'watchlist' ? 'active' : '']" @click="switchTab('watchlist')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        自选股
        <span v-if="watchlist.length" class="hub-tab-count">{{ watchlist.length }}</span>
      </button>
      <button :class="['hub-tab', tab === 'news' ? 'active' : '']" @click="switchTab('news')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/></svg>
        异动·资讯
        <span v-if="newsUnseen" class="hub-tab-count">{{ newsUnseen > 99 ? '99+' : newsUnseen }}</span>
      </button>
      <button :class="['hub-tab', tab === 'all' ? 'active' : '']" @click="switchTab('all')">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        搜索股票
      </button>
      <div class="tab-spacer"></div>
      <span v-if="tab === 'watchlist' && lastUpdated" class="updated-hint">{{ lastUpdated }} 更新</span>
      <!-- 预警铃铛 -->
      <div class="alert-bell-wrap" @click.stop>
        <button class="btn-bell" :class="{ active: alertBell }" @click="toggleAlertBell" title="预警通知">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
          <span v-if="unreadAlerts" class="bell-badge">{{ unreadAlerts > 99 ? '99+' : unreadAlerts }}</span>
        </button>
        <div v-if="alertBell" class="bell-pop">
          <div class="bell-head">
            <span class="bell-title">预警通知</span>
            <button class="bell-check" @click="checkAlertsNow">立即检查</button>
          </div>
          <div v-if="!alertNotifs.length" class="bell-empty">暂无预警触发<br /><span class="text-3">右键自选股可设置到价/涨跌幅预警</span></div>
          <div v-else class="bell-list">
            <div v-for="n in alertNotifs" :key="n.id" :class="['bell-item', { unread: !n.read }]">
              <div class="bell-msg">{{ n.message }}</div>
              <div class="bell-time">{{ n.triggered_at?.replace('T', ' ').slice(5, 16) }}</div>
            </div>
          </div>
        </div>
      </div>
      <button class="btn-refresh" @click="refreshData" :disabled="isLoading">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: isLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <!-- ════════════ TAB: 自选股 ════════════ -->
    <template v-if="tab === 'watchlist'">
      <div v-if="watchlistLoading && !watchlist.length" class="panel" style="padding: 8px;">
        <div class="skeleton-row" v-for="i in 6" :key="i">
          <span class="skeleton w-md"></span><span class="skeleton"></span><span class="skeleton w-md"></span><span class="skeleton w-sm"></span>
        </div>
      </div>

      <div v-else-if="watchlist.length === 0" class="panel">
        <div class="empty-state">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" stroke-width="1.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
          <p>还没有自选股</p>
          <p class="text-3">从「全部股票」添加，或在下方搜索快速加入</p>
          <button class="empty-cta" @click="switchTab('all')">去添加自选 →</button>
        </div>
      </div>

      <template v-else>
        <!-- ── 汇总条 ─────────────────────────────────────────── -->
        <div class="summary-bar">
          <div class="sum-item">
            <span class="sum-val">{{ watchlist.length }}</span>
            <span class="sum-lbl">自选</span>
          </div>
          <div class="sum-sep"></div>
          <div class="sum-item">
            <span class="sum-val up">{{ summary.up }}</span>
            <span class="sum-lbl">上涨</span>
          </div>
          <div class="sum-item">
            <span class="sum-val down">{{ summary.down }}</span>
            <span class="sum-lbl">下跌</span>
          </div>
          <div class="sum-item">
            <span class="sum-val">{{ summary.flat }}</span>
            <span class="sum-lbl">平盘</span>
          </div>
          <div class="sum-sep"></div>
          <div class="sum-item">
            <span :class="['sum-val', summary.avg > 0 ? 'up' : summary.avg < 0 ? 'down' : '']">
              {{ summary.avg > 0 ? '+' : '' }}{{ summary.avg.toFixed(2) }}%
            </span>
            <span class="sum-lbl">平均涨幅</span>
          </div>
          <template v-if="holdingSummary.count">
            <div class="sum-sep"></div>
            <div class="sum-item">
              <span class="sum-val">{{ fmtAmt(holdingSummary.marketVal) }}</span>
              <span class="sum-lbl">持仓市值</span>
            </div>
            <div class="sum-item">
              <span :class="['sum-val', holdingSummary.profit > 0 ? 'up' : holdingSummary.profit < 0 ? 'down' : '']">
                {{ holdingSummary.profit >= 0 ? '+' : '-' }}{{ fmtAmt0(holdingSummary.profit) }}
              </span>
              <span class="sum-lbl">浮动盈亏 ({{ holdingSummary.profitPct >= 0 ? '+' : '' }}{{ holdingSummary.profitPct.toFixed(2) }}%)</span>
            </div>
          </template>
        </div>

        <div class="panel">
          <!-- ── 工具栏 ─────────────────────────────────────────── -->
          <div class="wl-toolbar">
            <div class="wl-search">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input v-model="wlSearch" class="wl-search-input" placeholder="筛选自选股..." />
              <button v-if="wlSearch" class="wl-search-clear" @click="wlSearch = ''">×</button>
            </div>

            <div class="toolbar-spacer"></div>

            <div class="sort-chips">
              <button v-for="s in sortOpts" :key="s.key"
                :class="['sort-chip', sortKey === s.key ? 'active' : '']"
                @click="toggleSort(s.key)">
                {{ s.label }}<template v-if="sortKey === s.key && s.key !== 'manual'">{{ sortAsc ? ' ↑' : ' ↓' }}</template>
              </button>
            </div>

            <div class="view-toggle">
              <button :class="['vt-btn', view === 'card' ? 'active' : '']" @click="setView('card')" title="卡片视图">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
              </button>
              <button :class="['vt-btn', view === 'list' ? 'active' : '']" @click="setView('list')" title="列表视图">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
              </button>
            </div>

            <div v-if="view === 'list'" class="col-config" @click.stop>
              <button class="select-toggle" @click="colPicker = !colPicker">列 ({{ shownCols.length }}) ▾</button>
              <div v-if="colPicker" class="col-pop">
                <div class="col-pop-head">
                  <span class="col-pop-title">显示列</span>
                  <button class="col-reset" @click="resetCols">重置</button>
                </div>
                <div v-for="g in COL_GROUPS" :key="g" class="col-group">
                  <div class="col-group-title">{{ g }}</div>
                  <div class="col-group-items">
                    <label v-for="c in colsByGroup(g)" :key="c.key" class="col-chk">
                      <input type="checkbox" :checked="colKeys.includes(c.key)" @change="toggleCol(c.key)" />
                      {{ c.label }}
                    </label>
                  </div>
                </div>
              </div>
            </div>

            <button class="ai-diag-btn" @click="runAiDiagnose" :disabled="aiDiagLoading" title="AI 综合诊断(评分+点评，结果缓存6h)">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: aiDiagLoading }"><path d="M12 2a7 7 0 0 0-4 12.7V17a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-2.3A7 7 0 0 0 12 2z"/><line x1="9" y1="21" x2="15" y2="21"/></svg>
              {{ aiDiagLoading ? '诊断中…' : 'AI诊断' }}
            </button>
            <button class="ai-group-btn" @click="openAiGroupModal" :disabled="aiGroupLoading" title="AI 智能分组 & 标色（分析量价/资金/技术位，自动归类）">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: aiGroupLoading }"><circle cx="9" cy="7" r="4"/><circle cx="17" cy="17" r="4"/><path d="M2 21v-2a4 4 0 0 1 4-4h4"/><path d="M19 9l2 2-2 2"/><path d="M21 11h-4"/></svg>
              {{ aiGroupLoading ? '分析中…' : 'AI分组' }}
            </button>

            <button :class="['select-toggle', selectMode ? 'active' : '']" @click="toggleSelectMode">
              {{ selectMode ? '完成' : '多选' }}
            </button>
          </div>

          <!-- 分组（标签）切换条 + 颜色筛选 -->
          <div class="group-bar" :class="{ 'has-content': watchlistStore.tags.length || anyColored }">
            <template v-if="watchlistStore.tags.length">
              <button :class="['group-chip', tagFilter === '' && !colorFilter ? 'active' : '']"
                @click="tagFilter = ''; colorFilter = ''">
                全部 <span class="group-count">{{ watchlist.length }}</span>
              </button>
              <span class="group-chip-wrap" v-for="t in watchlistStore.tags" :key="t.tag">
                <button :class="['group-chip', tagFilter === t.tag ? 'active' : '']"
                  @click="tagFilter = tagFilter === t.tag ? '' : t.tag; colorFilter = ''">
                  {{ t.tag }} <span class="group-count">{{ t.count }}</span>
                </button>
                <button class="group-del" @click.stop="deleteGroup(t.tag)" title="删除该分组（从所有股票移除此标签）">×</button>
              </span>
              <span class="group-divider" v-if="anyColored"></span>
            </template>
            <!-- 颜色快速筛选 -->
            <template v-if="anyColored">
              <span class="group-color-label">颜色</span>
              <button v-for="c in usedColors" :key="c.hex"
                :class="['color-filter-dot', { active: colorFilter === c.hex }]"
                :style="{ background: c.hex }"
                :title="c.name + '（' + c.count + '只）'"
                @click="colorFilter = colorFilter === c.hex ? '' : c.hex; tagFilter = ''">
                <span v-if="colorFilter === c.hex" class="cfd-check">✓</span>
              </button>
              <button v-if="colorFilter" class="group-chip active color-clear" @click="colorFilter = ''">× 清除</button>
            </template>
          </div>

          <div v-if="!canDrag && sortKey === 'manual'" class="drag-hint">
            清除筛选/搜索后可拖拽排序
          </div>
          <div v-else-if="canDrag && view === 'card'" class="drag-hint">拖动卡片可调整顺序</div>

          <div v-if="displayList.length === 0" class="panel-empty">没有匹配的自选股</div>

          <!-- ── 卡片视图 ───────────────────────────────────────── -->
          <div v-else-if="view === 'card'" class="card-grid">
            <div v-for="stock in displayList" :key="stock.code"
              :class="['wl-card', { selected: isSelected(stock.code), dragging: draggingCode === stock.code }]"
              :style="rowColorStyle(stock)"
              :draggable="canDrag"
              @dragstart="onDragStart(stock.code, $event)"
              @dragover.prevent="onDragOver(stock.code)"
              @dragend="onDragEnd"
              @drop="onDrop(stock.code)"
              @contextmenu.prevent.stop="openCtxMenu(stock, $event)"
              @click="onCardClick(stock)">
              <label v-if="selectMode" class="card-check" @click.stop>
                <input type="checkbox" :checked="isSelected(stock.code)" @change="toggleSelect(stock.code)" />
              </label>
              <button v-else class="card-x" @click.stop="removeWithUndo(stock)" title="移除自选">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
              <div class="wl-top">
                <span class="wl-name">
                  <i v-if="colorOf(stock)" class="wl-color-dot" :style="{ background: colorOf(stock) }"></i>
                  {{ stock.name }}
                  <span v-if="alertCodes.has(stock.code)" class="wl-alert-flag" title="已设预警">🔔</span>
                </span>
                <span :class="['market-badge', 'market-' + marketOf(stock.code)]" v-if="marketOf(stock.code) !== 'a'">{{ marketLabel(stock.code) }}</span>
                <span class="wl-code">{{ stock.code }}</span>
              </div>
              <div class="wl-price-row">
                <span :class="['wl-price', getPriceClass(stock.code)]">{{ getCurrentPrice(stock.code) }}</span>
                <span :class="['wl-badge', getPriceClass(stock.code)]">{{ getChangePercent(stock.code) }}</span>
              </div>
              <div class="wl-spark" v-if="getChartData(stock.code).length > 0">
                <StockMiniChart :data="getChartData(stock.code)" :width="240" :height="40" :color="getStockColor(stock.code)" :pre-close="getStockPre(stock.code)" />
              </div>
              <div class="wl-meta">
                <span v-for="m in stockMetrics(stock.code)" :key="m.label" class="wl-metric">
                  <i class="wm-label">{{ m.label }}</i><b :class="['wm-val', m.cls]">{{ m.val }}</b>
                </span>
              </div>
              <div v-if="hasHolding(stock.code) && holdingPnl(stock.code)" class="wl-holding">
                <span class="wh-lbl">持仓</span>
                <span :class="['wh-pnl', holdingPnl(stock.code).profit >= 0 ? 'up' : 'down']">
                  {{ holdingPnl(stock.code).profit >= 0 ? '+' : '-' }}{{ fmtAmt0(holdingPnl(stock.code).profit) }}
                  ({{ holdingPnl(stock.code).profitPct >= 0 ? '+' : '' }}{{ holdingPnl(stock.code).profitPct.toFixed(2) }}%)
                </span>
              </div>
              <div v-if="aiDiag[stock.code]" class="wl-ai" :title="aiDiag[stock.code].comment">
                <span class="wl-ai-tag">AI</span>
                <span :class="['wl-ai-score', aiDiag[stock.code].score >= 60 ? 'up' : aiDiag[stock.code].score < 40 ? 'down' : '']">{{ aiDiag[stock.code].score }}</span>
                <span :class="['wl-ai-rating', ratingCls(aiDiag[stock.code].rating)]">{{ aiDiag[stock.code].rating }}</span>
                <span class="wl-ai-comment">{{ aiDiag[stock.code].comment }}</span>
              </div>
              <div v-if="stock.reports?.count" class="wl-research">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                研报 {{ stock.reports.count }}
                <span class="wr-date">{{ stock.reports.latest_date }}</span>
              </div>
              <div class="wl-tags" @click.stop>
                <span v-for="t in (stock.tags || [])" :key="t" class="wl-tag">
                  {{ t }}<i class="tag-x" @click="removeTag(stock, t)">×</i>
                </span>
                <input v-if="tagEditCode === stock.code" class="tag-input"
                  v-model="tagInput" @keyup.enter="addTag(stock)" @blur="addTag(stock)" placeholder="标签名" />
                <button v-else class="tag-add" @click="startTagEdit(stock.code)">＋标签</button>
              </div>
            </div>
          </div>

          <!-- ── 列表视图（可配置列）─────────────────────────────── -->
          <div v-else class="wl-list">
            <div class="wl-list-head wl-flexrow">
              <label v-if="selectMode" class="lc-sel"></label>
              <span :class="['lc-name', 'lc-sortable', { sorted: sortKey === 'name' }]" @click="sortByCol('name')">名称{{ sortArrow('name') }}</span>
              <span class="lc-spark">走势</span>
              <span v-for="c in shownCols" :key="c.key"
                :class="['lc-num', 'lc-sortable', { sorted: sortKey === c.key }]"
                @click="sortByCol(c.key)">{{ c.label }}{{ sortArrow(c.key) }}</span>
              <span class="lc-act"></span>
            </div>
            <div v-for="stock in displayList" :key="stock.code"
              :class="['wl-row', 'wl-flexrow', { selected: isSelected(stock.code), dragging: draggingCode === stock.code }]"
              :style="rowColorStyle(stock)"
              :draggable="canDrag"
              @dragstart="onDragStart(stock.code, $event)"
              @dragover.prevent="onDragOver(stock.code)"
              @dragend="onDragEnd"
              @drop="onDrop(stock.code)"
              @contextmenu.prevent.stop="openCtxMenu(stock, $event)"
              @click="onCardClick(stock)">
              <label v-if="selectMode" class="lc-sel" @click.stop>
                <input type="checkbox" :checked="isSelected(stock.code)" @change="toggleSelect(stock.code)" />
              </label>
              <span class="lc-name">
                <i v-if="colorOf(stock)" class="wl-color-dot" :style="{ background: colorOf(stock) }"></i>
                <span class="lr-name">{{ stock.name }}</span>
                <span v-if="alertCodes.has(stock.code)" class="wl-alert-flag" title="已设预警">🔔</span>
                <span :class="['market-badge', 'market-' + marketOf(stock.code)]" v-if="marketOf(stock.code) !== 'a'">{{ marketLabel(stock.code) }}</span>
                <span class="lr-code">{{ stock.code }}</span>
              </span>
              <span class="lc-spark">
                <StockMiniChart v-if="getChartData(stock.code).length > 0"
                  :data="getChartData(stock.code)" :width="88" :height="24" :color="getStockColor(stock.code)" :pre-close="getStockPre(stock.code)" />
                <span v-else class="text-3">—</span>
              </span>
              <span v-for="c in shownCols" :key="c.key" class="lc-num">
                <span v-if="c.badge" :class="['wl-badge', getPriceClass(stock.code)]" :style="pctHeatStyle(stock.code)">{{ getChangePercent(stock.code) }}</span>
                <span v-else :class="colCls(c, stock.code)">{{ colValue(c, stock.code) }}</span>
              </span>
              <span class="lc-act" @click.stop>
                <button class="row-x" @click="removeWithUndo(stock)" title="移除自选">×</button>
              </span>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- ════════════ TAB: 异动·资讯 ════════════ -->
    <template v-if="tab === 'news'">
      <div class="panel">
        <div class="wl-toolbar">
          <div class="news-filter">
            <button v-for="f in NEWS_FILTERS" :key="f.key"
              :class="['filter-chip', newsFilter === f.key ? 'active' : '']"
              @click="newsFilter = f.key">{{ f.label }}</button>
          </div>
          <div class="toolbar-spacer"></div>
          <span v-if="newsUpdated" class="updated-hint">{{ newsUpdated }} 更新</span>
          <button class="select-toggle" @click="loadWatchlistNews(true)" :disabled="newsLoading">
            {{ newsLoading ? '加载中…' : '刷新' }}
          </button>
        </div>

        <div v-if="newsLoading && !newsFeed.length" class="panel-loading">
          <span class="spinner spinner-sm"></span> 正在聚合自选股资讯…
        </div>
        <div v-else-if="!watchlist.length" class="panel-empty">先添加自选股，这里会汇总它们的新闻与公告</div>
        <div v-else-if="!filteredNews.length" class="panel-empty">暂无{{ newsFilterLabel }}动态</div>

        <div v-else class="news-feed">
          <a v-for="n in filteredNews" :key="n.id || (n.wl_code + n.title)"
            class="news-item" :href="n.url || 'javascript:void(0)'"
            :target="n.url ? '_blank' : ''" rel="noopener">
            <div class="news-stock" @click.prevent.stop="goToDetail(n.wl_code)">
              <i v-if="codeColor(n.wl_code)" class="wl-color-dot" :style="{ background: codeColor(n.wl_code) }"></i>
              <span class="ns-name">{{ codeName(n.wl_code) }}</span>
              <span class="ns-code">{{ n.symbol || n.wl_code }}</span>
            </div>
            <div class="news-main">
              <div class="news-title">
                <span :class="['news-dot', n.sentiment]"></span>
                <span :class="['news-type-tag', n.type === 'announcement' ? 'ann' : '']">{{ n.type === 'announcement' ? '公告' : (n.category || '新闻') }}</span>
                {{ n.title }}
              </div>
              <div v-if="n.content" class="news-digest">{{ n.content }}</div>
              <div class="news-foot">
                <span class="news-src">{{ n.source }}</span>
                <span class="news-time">{{ n.date }} {{ n.time }}</span>
              </div>
            </div>
          </a>
        </div>
      </div>
    </template>

    <!-- ════════════ TAB: 搜索股票 ════════════ -->
    <template v-if="tab === 'all'">
      <!-- 搜索栏 -->
      <div class="panel">
        <div class="search-row">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <input v-model="searchQuery" @input="handleSearch" class="search-input"
            placeholder="搜索股票：代码 / 名称 / 拼音缩写（如 GZMT → 贵州茅台）· A股·ETF·港股·美股·指数" />
          <button v-if="searchQuery" class="wl-search-clear" @click="clearSearch">×</button>
        </div>
        <div v-if="!searchQuery.trim()" class="filter-chips">
          <button :class="['filter-chip', filterType === 'all' ? 'active' : '']" @click="setFilter('all')">全部</button>
          <button :class="['filter-chip', filterType === 'gainers' ? 'active' : '']" @click="setFilter('gainers')">涨幅榜</button>
          <button :class="['filter-chip', filterType === 'losers' ? 'active' : '']" @click="setFilter('losers')">跌幅榜</button>
        </div>
      </div>

      <!-- ── 搜索结果（统一：代码/名称/拼音缩写，全市场，可直接加自选）── -->
      <template v-if="searchQuery.trim()">
        <div class="panel">
          <div class="panel-title">
            搜索结果
            <span class="panel-hint">代码 · 名称 · 拼音缩写 · 全市场</span>
            <span v-if="searchBusy" class="spinner spinner-sm" style="margin-left:6px"></span>
          </div>
          <div v-if="!searchResults.length && !searchBusy" class="panel-empty">
            未找到「{{ searchQuery }}」，换个代码 / 名称 / 拼音缩写试试
          </div>
          <div v-else class="card-grid">
            <div v-for="stock in searchResults" :key="stock.code" class="wl-card" @click="goToDetail(stock.code)">
              <div class="wl-top">
                <span class="wl-name">{{ stock.name }}</span>
                <span v-if="marketOf(stock.code) !== 'a'" :class="['market-badge', 'market-' + marketOf(stock.code)]">{{ marketLabel(stock.code) }}</span>
                <span class="wl-code">{{ stock.code }}</span>
              </div>
              <div v-if="stock.price != null" class="wl-price-row">
                <span :class="['wl-price', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">{{ stock.price.toFixed(2) }}</span>
                <span :class="['wl-badge', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                  {{ stock.change_pct != null ? ((stock.change_pct > 0 ? '+' : '') + stock.change_pct.toFixed(2) + '%') : '--' }}
                </span>
              </div>
              <div class="wl-card-foot" style="margin-top:8px">
                <span class="text-3" style="font-size:11px">{{ stock.exchange || stock.market || '—' }}</span>
                <button v-if="!isInWatchlist(stock.code)" class="wl-add" @click.stop="addSearchResult(stock)">＋ 自选</button>
                <span v-else class="wl-added">✓ 已自选</span>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ── 浏览全部 A股（无搜索时）── -->
      <template v-else>
        <div v-if="allStocksLoading && allStocks.length === 0" class="panel"><div class="panel-loading"><span class="spinner spinner-sm"></span> {{ allWarming ? '行情首次加载中，请稍候…' : '加载全部股票...' }}</div></div>

        <div v-else-if="allStocks.length === 0" class="panel">
          <div class="panel-empty">{{ allWarming ? '行情快照正在生成，稍后自动出现' : '未找到匹配的股票' }}</div>
        </div>

        <div v-else class="panel">
          <div class="panel-title">
            A股列表 ({{ allTotal }}){{ allUpdated ? ' · ' + allUpdated + ' 更新' : '' }}
          </div>
          <div class="card-grid">
            <div v-for="stock in allStocks" :key="stock.code" class="wl-card" @click="goToDetail(stock.code)">
              <div class="wl-top">
                <span class="wl-name">{{ stock.name }}</span>
                <span class="wl-code">{{ stock.code }}</span>
              </div>
              <div class="wl-price-row">
                <span :class="['wl-price', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                  {{ stock.price != null ? stock.price.toFixed(2) : '--' }}
                </span>
                <span :class="['wl-badge', (stock.change_pct ?? 0) >= 0 ? 'up' : 'down']">
                  {{ stock.change_pct != null ? ((stock.change_pct > 0 ? '+' : '') + stock.change_pct.toFixed(2) + '%') : '--' }}
                </span>
              </div>
              <div class="wl-card-foot">
                <span v-if="stock.exchange" class="exchange-tag">{{ stock.exchange }}</span>
                <span v-else class="text-3" style="font-size:11px">—</span>
                <button v-if="!isInWatchlist(stock.code)" class="wl-add" @click.stop="addToWatchlist(stock)">＋ 自选</button>
                <span v-else class="wl-added">✓ 已自选</span>
              </div>
            </div>
          </div>

          <!-- 分页 -->
          <div v-if="allTotalPages > 1" class="pagination">
            <button class="page-btn" @click="gotoPage(currentPage - 1)" :disabled="currentPage === 1">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
            </button>
            <span class="page-info">{{ currentPage }} / {{ allTotalPages }}</span>
            <button class="page-btn" @click="gotoPage(currentPage + 1)" :disabled="currentPage >= allTotalPages">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
            </button>
          </div>
        </div>
      </template>
    </template>

    <!-- ── 多选操作条 ─────────────────────────────────────────── -->
    <transition name="bar-slide">
      <div v-if="selectMode && selectedCodes.size > 0" class="batch-bar">
        <span class="batch-count">已选 {{ selectedCodes.size }} 只</span>
        <button class="batch-btn" @click="selectAll">{{ allSelected ? '取消全选' : '全选' }}</button>
        <button class="batch-btn" @click="compareSelected" :disabled="selectedCodes.size < 2" title="选中 2~6 只进行对比">个股对比</button>
        <div class="batch-spacer"></div>
        <!-- 批量标色 -->
        <div class="batch-colors">
          <span class="batch-label">标色</span>
          <button v-for="c in COLOR_PALETTE" :key="c.hex" class="batch-swatch"
            :style="{ background: c.hex }" :title="c.name"
            @click="batchSetColor(c.hex)"></button>
          <button class="batch-swatch clear" title="清除颜色" @click="batchSetColor('')">×</button>
        </div>
        <div class="batch-tag">
          <input v-model="batchTagInput" class="batch-tag-input" placeholder="打标签..." @keyup.enter="applyBatchTag" />
          <button class="batch-btn" @click="applyBatchTag" :disabled="!batchTagInput.trim()">添加</button>
        </div>
        <button class="batch-btn danger" @click="batchRemoveSelected">移除</button>
      </div>
    </transition>

    <!-- ── 撤销 toast ─────────────────────────────────────────── -->
    <transition name="toast-fade">
      <div v-if="undoToast" class="undo-toast">
        <span>已移除 {{ undoToast.items.length }} 只自选</span>
        <button class="undo-btn" @click="undoRemoval">撤销</button>
        <button class="undo-close" @click="undoToast = null">×</button>
      </div>
    </transition>

    <!-- ── 右键菜单（同花顺式）─────────────────────────────────── -->
    <div v-if="ctxMenu && ctxStock" class="ctx-menu" :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }" @click.stop>
      <div class="ctx-title">{{ ctxMenu.name }} <span class="ctx-code">{{ ctxMenu.code }}</span></div>
      <!-- 标色 -->
      <div class="ctx-section">
        <div class="ctx-label">标记颜色</div>
        <div class="ctx-colors">
          <button v-for="c in COLOR_PALETTE" :key="c.hex" class="ctx-swatch"
            :class="{ active: colorOf(ctxStock) === c.hex }"
            :style="{ background: c.hex }" :title="c.name"
            @click="applyColor(ctxMenu.code, c.hex)"></button>
          <button class="ctx-swatch clear" title="清除" @click="applyColor(ctxMenu.code, '')">×</button>
        </div>
      </div>
      <div class="ctx-divider"></div>
      <!-- 加入分组（标签即分组）-->
      <div class="ctx-section">
        <div class="ctx-label-row">
          <span class="ctx-label">加入分组</span>
          <button v-if="ctxStock?.tags?.length" class="ctx-clear-groups" @click="clearAllGroups">清除所有</button>
        </div>
        <div class="ctx-groups">
          <button v-for="t in watchlistStore.tags" :key="t.tag"
            :class="['ctx-grp', { active: ctxHasTag(t.tag) }]" @click="toggleGroup(t.tag)">
            {{ t.tag }}
          </button>
        </div>
        <input v-model="ctxTagInput" class="ctx-grp-input" placeholder="新建分组并加入…" @keyup.enter="addCtxGroup" />
      </div>
      <div class="ctx-divider"></div>
      <button class="ctx-item" @click="openHoldingModal(ctxStock)">
        💰 {{ hasHolding(ctxMenu.code) ? '编辑持仓' : '录入持仓' }}
      </button>
      <button class="ctx-item" @click="openAlertModal(ctxStock)">
        🔔 设置预警<span v-if="alertCodes.has(ctxMenu.code)" class="ctx-tag">已设</span>
      </button>
      <button class="ctx-item" @click="goToDetail(ctxMenu.code); closeCtxMenu()">📈 个股详情</button>
      <div class="ctx-divider"></div>
      <button class="ctx-item danger" @click="removeWithUndo(ctxStock); closeCtxMenu()">✕ 移出自选</button>
    </div>

    <!-- ── 持仓录入弹窗 ───────────────────────────────────────── -->
    <div v-if="holdingModal" class="modal-mask" @click.self="holdingModal = null">
      <div class="modal-card">
        <div class="modal-head">
          <span>{{ holdingModal.name }} · 持仓</span>
          <button class="modal-x" @click="holdingModal = null">×</button>
        </div>
        <div class="modal-body">
          <label class="modal-field">
            <span>成本价 (元)</span>
            <input v-model="holdingModal.cost" type="number" step="0.01" placeholder="如 18.50" />
          </label>
          <label class="modal-field">
            <span>持股数 (股)</span>
            <input v-model="holdingModal.shares" type="number" step="100" placeholder="如 1000" />
          </label>
          <p class="modal-hint">两项都填才计入盈亏；留空保存即清除持仓。</p>
        </div>
        <div class="modal-foot">
          <button v-if="hasHolding(holdingModal.code)" class="modal-btn ghost" @click="clearHolding">清除</button>
          <div class="modal-foot-spacer"></div>
          <button class="modal-btn" @click="holdingModal = null">取消</button>
          <button class="modal-btn primary" @click="saveHolding">保存</button>
        </div>
      </div>
    </div>

    <!-- ── 预警设置弹窗 ───────────────────────────────────────── -->
    <div v-if="alertModal" class="modal-mask" @click.self="alertModal = null">
      <div class="modal-card">
        <div class="modal-head">
          <span>{{ alertModal.name }} · 预警</span>
          <button class="modal-x" @click="alertModal = null">×</button>
        </div>
        <div class="modal-body">
          <div class="alert-form">
            <select v-model="alertModal.type" class="alert-type" @change="onAlertTypeChange">
              <option v-for="t in ALERT_TYPES" :key="t.key" :value="t.key">{{ t.label }}</option>
            </select>
            <input v-if="!curAlertType.noTarget" v-model="alertModal.target" type="number" step="0.01"
              class="alert-target" :placeholder="curAlertType.ph || '数值'" @keyup.enter="createAlert" />
            <span v-if="curAlertType.unit" class="alert-unit">{{ curAlertType.unit }}</span>
            <button class="modal-btn primary" @click="createAlert">添加</button>
          </div>
          <div class="alert-rules">
            <div v-if="alertModal.loading" class="alert-empty">加载中...</div>
            <div v-else-if="!alertModal.rules.length" class="alert-empty">尚无预警规则</div>
            <div v-else v-for="r in alertModal.rules" :key="r.id" class="alert-rule">
              <span class="ar-desc">{{ alertTypeLabel(r.type) }} <b v-if="!alertNoTarget(r.type)">{{ r.target }}</b></span>
              <span :class="['ar-state', r.enabled ? 'on' : 'off']">{{ r.enabled ? '启用' : '停用' }}</span>
              <button class="ar-del" @click="deleteAlert(r.id)">删除</button>
            </div>
          </div>
          <p class="modal-hint">盘中每分钟后台自动检查命中即推送；可在「通知设置」配置 Telegram/企业微信/邮件渠道。</p>
        </div>
      </div>
    </div>

    <!-- ── AI 分组弹窗 ────────────────────────────────────────── -->
    <div v-if="aiGroupModal" class="modal-mask" @click.self="aiGroupModal = false">
      <div class="modal-card ai-group-modal">
        <div class="modal-head">
          <span>AI 智能分组 & 标色</span>
          <button class="modal-x" @click="aiGroupModal = false">×</button>
        </div>

        <!-- 加载中 -->
        <div v-if="aiGroupLoading" class="ag-loading">
          <span class="spinner spinner-sm"></span>
          <span>AI 正在分析 {{ watchlist.length }} 只自选股的量价/资金/技术位…</span>
        </div>

        <!-- 错误 -->
        <div v-else-if="aiGroupError" class="ag-error">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          {{ aiGroupError }}
          <button class="modal-btn" style="margin-top:10px" @click="runAiGroup(true)">重试</button>
        </div>

        <!-- 结果：按分组展示，可勾选/修改 -->
        <template v-else-if="aiGroupSuggestions.length">
          <div class="ag-meta">
            AI 建议将自选股分为 <b>{{ aiGroupNames.length }}</b> 个组，颜色已按强弱标记。逐行调整后点击「应用」。
            <button class="ag-rerun" @click="runAiGroup(true)">重新分析</button>
          </div>
          <div class="ag-body">
            <!-- 按分组聚合展示 -->
            <div v-for="grp in aiGroupNames" :key="grp" class="ag-group">
              <div class="ag-group-head">
                <span class="ag-group-name">{{ grp }}</span>
                <span class="ag-group-count">{{ aiGroupSuggestions.filter(s => s.group === grp).length }} 只</span>
              </div>
              <div v-for="s in aiGroupSuggestions.filter(x => x.group === grp)" :key="s.code" class="ag-row">
                <label class="ag-check">
                  <input type="checkbox" v-model="s.selected" />
                </label>
                <span class="ag-name">{{ s.name }}</span>
                <span class="ag-code mono">{{ s.code }}</span>
                <!-- 颜色选择 -->
                <div class="ag-colors">
                  <button v-for="c in COLOR_PALETTE" :key="c.hex" class="ag-swatch"
                    :class="{ active: s.color === c.hex }"
                    :style="{ background: c.hex }" :title="c.name"
                    @click="s.color = s.color === c.hex ? '' : c.hex"></button>
                  <button class="ag-swatch clear" title="不标色" @click="s.color = ''">×</button>
                </div>
                <!-- 分组输入 -->
                <input class="ag-grp-input" v-model="s.group" placeholder="分组名" />
                <span class="ag-reason">{{ s.reason }}</span>
              </div>
            </div>
          </div>
          <div class="modal-foot">
            <label class="ag-sel-all">
              <input type="checkbox" :checked="aiGroupAllSelected" @change="toggleAiGroupAll" />
              全选 ({{ aiGroupSuggestions.filter(s=>s.selected).length }}/{{ aiGroupSuggestions.length }})
            </label>
            <div class="modal-foot-spacer"></div>
            <button class="modal-btn" @click="aiGroupModal = false">取消</button>
            <button class="modal-btn primary" @click="applyAiGroup"
              :disabled="!aiGroupSuggestions.some(s => s.selected)">
              应用选中 ({{ aiGroupSuggestions.filter(s=>s.selected).length }})
            </button>
          </div>
        </template>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useWatchlistStore } from '../stores/watchlist'
import StockMiniChart from '../components/StockMiniChart.vue'
import IndexChartModal from '../components/IndexChartModal.vue'

const router = useRouter()
const watchlistStore = useWatchlistStore()

// ── 持久化偏好 ────────────────────────────────────────────────────────────
const LS = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : v } catch { return d } },
  set(k, v) { try { localStorage.setItem(k, v) } catch { /* ignore */ } },
}

const tab = ref('watchlist')
const filterType = ref('all')
const searchQuery = ref('')
const sortKey = ref(LS.get('wl_sort', 'manual'))
const sortAsc = ref(LS.get('wl_sort_asc', '0') === '1')
const view = ref(LS.get('wl_view', 'list'))
const currentPage = ref(1)
const pageSize = 50
const tagFilter = ref('')
const colorFilter = ref('')
const tagEditCode = ref('')
const tagInput = ref('')
const wlSearch = ref('')

const watchlistLoading = ref(false)
const allStocksLoading = ref(false)
const allStocks = ref([])            // 当前页(服务端分页)
const allTotal = ref(0)
const allTotalPages = ref(0)
const allUpdated = ref('')
const allWarming = ref(false)
const lastUpdated = ref('')
const isLoading = computed(() => watchlistLoading.value || allStocksLoading.value)

// 跨市场搜索（港股/美股/ETF/指数）
const globalSearchResults = ref([])
const globalSearchLoading = ref(false)

// 多选 / 拖拽 / 撤销
const selectMode = ref(false)
const selectedCodes = ref(new Set())
const batchTagInput = ref('')
const draggingCode = ref(null)
const undoToast = ref(null)
let undoTimer = null
let _alertTimer = null
let _ffTimer = null

const sortOpts = [
  { key: 'manual', label: '自定义' },
  { key: 'change_pct', label: '涨跌幅' },
  { key: 'price', label: '价格' },
  { key: 'turnover_rate', label: '换手' },
  { key: 'vol_ratio', label: '量比' },
  { key: 'turnover', label: '成交额' },
  { key: 'market_cap', label: '市值' },
  { key: 'main_net', label: '主力净流入' },
  { key: 'name', label: '名称' },
]

// ── 列表视图可配置列 ──────────────────────────────────────────────────────
// 涨跌着色辅助：相对昨收/现价判断红涨绿跌（开高低这类价格列用得到）
const upDownVs = (v, base) => (v == null || base == null) ? '' : (v >= base ? 'up' : v < base ? 'down' : '')
const fmtP2 = v => v != null ? Number(v).toFixed(2) : '--'

// group 用于列选择面板分组；cls 返回 'up'/'down' 给数值着色
const ALL_COLS = [
  // 行情
  { key: 'price',         label: '现价',   group: '行情', fmt: d => fmtP2(d.price), cls: d => d.change_pct >= 0 ? 'up' : 'down' },
  { key: 'change_pct',    label: '涨跌幅', group: '行情', badge: true },
  { key: 'change',        label: '涨跌额', group: '行情', fmt: d => d.change != null ? (d.change >= 0 ? '+' : '') + Number(d.change).toFixed(2) : '--', cls: d => d.change >= 0 ? 'up' : d.change < 0 ? 'down' : '' },
  { key: 'open',          label: '今开',   group: '行情', fmt: d => fmtP2(d.open),  cls: d => upDownVs(d.open, d.pre_close) },
  { key: 'high',          label: '最高',   group: '行情', fmt: d => fmtP2(d.high),  cls: d => upDownVs(d.high, d.pre_close) },
  { key: 'low',           label: '最低',   group: '行情', fmt: d => fmtP2(d.low),   cls: d => upDownVs(d.low, d.pre_close) },
  { key: 'pre_close',     label: '昨收',   group: '行情', fmt: d => fmtP2(d.pre_close) },
  { key: 'amplitude',     label: '振幅',   group: '行情', fmt: d => fmtPct(d.amplitude) },
  // 量能
  { key: 'turnover_rate', label: '换手',   group: '量能', fmt: d => fmtPct(d.turnover_rate) },
  { key: 'vol_ratio',     label: '量比',   group: '量能', fmt: d => fmtP2(d.vol_ratio), cls: d => d.vol_ratio != null ? (d.vol_ratio >= 1 ? 'up' : 'down') : '' },
  { key: 'turnover',      label: '成交额', group: '量能', fmt: d => fmtAmt(d.turnover) },
  // 估值
  { key: 'pe',            label: 'PE',     group: '估值', fmt: d => d.pe != null ? Number(d.pe).toFixed(1) : '--' },
  { key: 'pb',            label: 'PB',     group: '估值', fmt: d => fmtP2(d.pb) },
  { key: 'market_cap',    label: '总市值', group: '估值', fmt: d => fmtAmt(d.market_cap) },
  { key: 'float_market_cap', label: '流通市值', group: '估值', fmt: d => fmtAmt(d.float_market_cap) },
  // 涨跌停
  { key: 'limit_up',      label: '涨停',   group: '涨跌停', fmt: d => fmtP2(d.limit_up),   cls: () => 'up' },
  { key: 'limit_down',    label: '跌停',   group: '涨跌停', fmt: d => fmtP2(d.limit_down), cls: () => 'down' },
  // 资金流（主力=超大单+大单；东财 push2，盘中 60s 缓存）
  { key: 'main_net',  label: '主力净流入', group: '资金', fmt: d => fmtSignedAmt(d.main_net), cls: d => signCls(d.main_net) },
  { key: 'main_pct',  label: '主力净占比', group: '资金', optional: true, fmt: d => fmtSignedPct(d.main_pct), cls: d => signCls(d.main_pct) },
  { key: 'super_net', label: '超大单净额', group: '资金', optional: true, fmt: d => fmtSignedAmt(d.super_net), cls: d => signCls(d.super_net) },
  { key: 'big_net',   label: '大单净额',   group: '资金', optional: true, fmt: d => fmtSignedAmt(d.big_net), cls: d => signCls(d.big_net) },
  // AI 诊断（来自 aiDiag map，在 colValue/colCls 里特殊处理；按需触发，默认隐藏）
  { key: 'ai_score',   label: 'AI评分', group: 'AI诊断', ai: true, optional: true },
  { key: 'ai_rating',  label: 'AI评级', group: 'AI诊断', ai: true, optional: true },
  { key: 'ai_comment', label: 'AI点评', group: 'AI诊断', ai: true, optional: true },
  // 持仓（数据来自自选项本身的成本/股数，非实时行情；在 colValue/colCls 里特殊处理）
  { key: 'cost',       label: '成本',  group: '持仓', holding: true },
  { key: 'shares',     label: '持股',  group: '持仓', holding: true },
  { key: 'market_val', label: '持仓市值', group: '持仓', holding: true },
  { key: 'profit',     label: '浮动盈亏', group: '持仓', holding: true },
  { key: 'profit_pct', label: '盈亏%',  group: '持仓', holding: true },
]
// 列分组（供列选择面板按组展示）
const COL_GROUPS = [...new Set(ALL_COLS.map(c => c.group))]
const colsByGroup = g => ALL_COLS.filter(c => c.group === g)

// 默认列：行情全量展示；持仓列(无持仓全是 '--')与可选资金列默认隐藏，需要的人手动开
const DEFAULT_COLS = ALL_COLS.filter(c => !c.holding && !c.optional).map(c => c.key).join(',')
const WL_COLS_VER = 5   // bump：把老用户默认列刷成含「主力净流入」的新默认
if (Number(LS.get('wl_cols_ver', '0')) < WL_COLS_VER) {
  LS.set('wl_cols', DEFAULT_COLS)
  LS.set('wl_cols_ver', String(WL_COLS_VER))
}
const colKeys = ref(LS.get('wl_cols', DEFAULT_COLS).split(',').filter(Boolean))
const colPicker = ref(false)
// 按 ALL_COLS 的声明顺序展示（而非用户勾选顺序），保持表头稳定
const shownCols = computed(() => ALL_COLS.filter(c => colKeys.value.includes(c.key)))
function toggleCol(k) {
  colKeys.value = colKeys.value.includes(k) ? colKeys.value.filter(x => x !== k) : [...colKeys.value, k]
  LS.set('wl_cols', colKeys.value.join(','))
}
function resetCols() { colKeys.value = DEFAULT_COLS.split(','); LS.set('wl_cols', DEFAULT_COLS) }
function colValue(c, code) {
  if (c.ai) {
    const a = aiDiag.value[code]
    if (!a) return '—'
    if (c.key === 'ai_score') return a.score != null ? a.score : '—'
    if (c.key === 'ai_rating') return a.rating || '—'
    if (c.key === 'ai_comment') return a.comment || '—'
    return '—'
  }
  if (c.holding) {
    const h = holdingPnl(code)
    if (!h) return '--'
    if (c.key === 'cost') return fmtP2(h.cost)
    if (c.key === 'shares') return fmtShares(h.shares)
    if (c.key === 'market_val') return fmtAmt(h.marketVal)
    if (c.key === 'profit') return (h.profit >= 0 ? '+' : '') + fmtAmt0(h.profit)
    if (c.key === 'profit_pct') return (h.profitPct >= 0 ? '+' : '') + h.profitPct.toFixed(2) + '%'
    return '--'
  }
  const d = realtimeData.value[code] || {}
  return c.fmt ? c.fmt(d) : '--'
}
function colCls(c, code) {
  if (c.ai) {
    const a = aiDiag.value[code]
    if (!a) return ''
    if (c.key === 'ai_score') return a.score == null ? '' : a.score >= 60 ? 'up' : a.score < 40 ? 'down' : ''
    if (c.key === 'ai_rating') return ratingCls(a.rating)
    return ''
  }
  if (c.holding) {
    if (c.key !== 'profit' && c.key !== 'profit_pct') return ''
    const h = holdingPnl(code)
    if (!h) return ''
    return h.profit > 0 ? 'up' : h.profit < 0 ? 'down' : ''
  }
  const d = realtimeData.value[code] || {}
  return c.cls ? c.cls(d) : ''
}

const watchlist = computed(() => watchlistStore.watchlist)
const realtimeData = computed(() => watchlistStore.realtimeData)
const aiDiag = computed(() => watchlistStore.aiDiag)
const aiDiagLoading = computed(() => watchlistStore.aiDiagLoading)
// AI 评级红/绿/中性着色
function ratingCls(r) { return r === '看多' ? 'up' : r === '看空' ? 'down' : '' }
const miniChartData = computed(() => watchlistStore.miniChartData)
const miniChartPre = computed(() => watchlistStore.miniChartPre)
const indices = computed(() => watchlistStore.indices)
// 按地区分行：A股(code 纯数字) / 全球(code 含字母, 如 DJI/N225)
const cnIndices = computed(() => indices.value.filter(i => !/\D/.test(i.code)))
const globalIndices = computed(() => indices.value.filter(i => /\D/.test(i.code)))

// ── 指数实时刷新 ──────────────────────────────────────────────────────────
const idxUpdated = ref('')          // 最近一次指数刷新时间
const idxFlash = ref(new Set())     // 本轮价格有变动、需高亮闪烁的指数 code
let _idxTimer = null
const IDX_REFRESH_MS = 5000

async function refreshIndices() {
  // 记录刷新前各指数现价，刷新后对比出有变动的，触发高亮
  const prev = {}
  for (const i of indices.value) prev[i.code] = i.price
  await watchlistStore.fetchShIndex()
  const changed = new Set()
  for (const i of indices.value) {
    if (prev[i.code] != null && i.price != null && i.price !== prev[i.code]) changed.add(i.code)
  }
  if (changed.size) {
    idxFlash.value = changed
    setTimeout(() => { idxFlash.value = new Set() }, 800)
  }
  idxUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function startIndexAutoRefresh() {
  stopIndexAutoRefresh()
  _idxTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    refreshIndices()
  }, IDX_REFRESH_MS)
}
function stopIndexAutoRefresh() {
  if (_idxTimer) { clearInterval(_idxTimer); _idxTimer = null }
}

// 点开指数详情（曲线/历史走势）；仅对有 chart_code 的指数可点
const openedIndex = ref(null)
function openIndexChart(idx) {
  if (!idx.chart_code) return
  openedIndex.value = idx
}

function fmtIdxChg(v) {
  if (v == null) return '--'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(2)
}
function fmtIdxPct(v) {
  if (v == null) return '--'
  return (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%'
}

// ── 汇总统计 ──────────────────────────────────────────────────────────────
const summary = computed(() => {
  let up = 0, down = 0, flat = 0, sum = 0, n = 0
  for (const s of watchlist.value) {
    const pct = realtimeData.value[s.code]?.change_pct
    if (pct == null) { flat++; continue }
    if (pct > 0) up++; else if (pct < 0) down++; else flat++
    sum += pct; n++
  }
  return { up, down, flat, avg: n ? sum / n : 0 }
})


// ── 自选股展示列表（筛选 + 排序）───────────────────────────────────────────
const displayList = computed(() => {
  let list = [...watchlist.value]
  if (tagFilter.value) list = list.filter(s => (s.tags || []).includes(tagFilter.value))
  if (colorFilter.value) list = list.filter(s => (s.color || '') === colorFilter.value)
  if (wlSearch.value.trim()) {
    const q = wlSearch.value.trim().toLowerCase()
    list = list.filter(s => s.name.toLowerCase().includes(q) || s.code.toLowerCase().includes(q))
  }

  if (sortKey.value === 'name') {
    list.sort((a, b) => sortAsc.value ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name))
  } else if (sortKey.value !== 'manual') {
    // 任意数值字段排序（支持顶部 chip 与列表表头点击）
    const k = sortKey.value
    list.sort((a, b) => {
      const av = realtimeData.value[a.code]?.[k]
      const bv = realtimeData.value[b.code]?.[k]
      const an = av == null ? -Infinity : Number(av)
      const bn = bv == null ? -Infinity : Number(bv)
      return sortAsc.value ? an - bn : bn - an
    })
  }
  // manual: 保持 store 顺序（已持久化）
  return list
})

// 仅在自定义排序且无筛选/搜索时允许拖拽
const canDrag = computed(() =>
  sortKey.value === 'manual' && !tagFilter.value && !colorFilter.value && !wlSearch.value.trim() && !selectMode.value)

// ── tab / 筛选 / 排序 ─────────────────────────────────────────────────────
function switchTab(t) {
  tab.value = t
  if (t === 'all' && allStocks.value.length === 0) { currentPage.value = 1; loadAllStocks() }
  if (t === 'news') {
    loadWatchlistNews().then(() => {
      // 进过资讯页即标记当前条数为已读，清角标
      newsSeenCount.value = newsFeed.value.length
      LS.set('wl_news_seen', String(newsSeenCount.value))
    })
  }
}

function setFilter(f) { filterType.value = f; currentPage.value = 1; loadAllStocks() }

function gotoPage(p) {
  if (p < 1 || (allTotalPages.value && p > allTotalPages.value)) return
  currentPage.value = p
  loadAllStocks()
}

function toggleSort(key) {
  if (key === 'manual') { sortKey.value = 'manual' }
  else if (sortKey.value === key) { sortAsc.value = !sortAsc.value }
  else { sortKey.value = key; sortAsc.value = false }
  LS.set('wl_sort', sortKey.value)
  LS.set('wl_sort_asc', sortAsc.value ? '1' : '0')
}

function setView(v) { view.value = v; LS.set('wl_view', v) }

// 列表表头点击排序：name 用名称排序，其余按字段；再次点同列切升/降
function sortByCol(key) {
  if (key === 'name') { toggleSort('name'); return }
  toggleSort(key)
}
function sortArrow(key) {
  if (sortKey.value !== key) return ''
  return sortAsc.value ? ' ↑' : ' ↓'
}

// ── 市场类型辅助 ───────────────────────────────────────────────────────────
function marketOf(code) {
  const cu = (code || '').toUpperCase()
  if (cu.startsWith('HK')) return 'hk'
  if (cu.startsWith('US')) return 'us'
  if (cu.startsWith('KR')) return 'kr'
  if (cu.startsWith('JP')) return 'jp'
  if (/^(5|1)\d{5}$/.test(cu)) return 'etf'
  if (/^(000|399)\d{3}$/.test(cu)) return 'idx'
  return 'a'
}
function marketLabel(code) {
  const m = marketOf(code)
  return { hk: '港股', us: '美股', kr: '韩股', jp: '日股', etf: 'ETF', idx: '指数', a: '' }[m] || ''
}

// 跨市场搜索
let _globalTimer = null
async function fetchGlobalSearch(q) {
  q = (q || '').trim()
  if (!q) { globalSearchResults.value = []; return }
  globalSearchLoading.value = true
  try {
    const { data } = await axios.get('/api/market/search-global', { params: { q, limit: 20 } })
    globalSearchResults.value = data.items || []
  } catch {
    globalSearchResults.value = []
  } finally {
    globalSearchLoading.value = false
  }
}

// 添加搜索结果到自选（A股/ETF/港股/美股/指数通用）
async function addSearchResult(stock) {
  const ok = await watchlistStore.addToWatchlist({ code: stock.code, name: stock.name })
  if (ok) watchlistStore.loadWatchlist()
}

// 统一搜索结果：smartbox(拼音/全市场，已补 A股现价) 优先，本地 A股 LIKE 兜底补充
const searchResults = computed(() => {
  if (!searchQuery.value.trim()) return []
  const seen = new Set()
  const out = []
  for (const s of globalSearchResults.value) {
    if (!s.code || seen.has(s.code)) continue
    seen.add(s.code); out.push(s)
  }
  for (const s of allStocks.value) {
    if (!s.code || seen.has(s.code)) continue
    seen.add(s.code); out.push({ ...s, market: 'A股' })
  }
  return out
})
const searchBusy = computed(() => globalSearchLoading.value || allStocksLoading.value)

function clearSearch() {
  searchQuery.value = ''
  globalSearchResults.value = []
  if (_searchTimer) clearTimeout(_searchTimer)
  if (_globalTimer) clearTimeout(_globalTimer)
  currentPage.value = 1
  loadAllStocks()   // 还原为全部 A股浏览列表
}

// 「搜索股票」：300ms 防抖后走本地 A股 查询 + smartbox 跨市场/拼音搜索
let _searchTimer = null
function handleSearch() {
  if (_searchTimer) clearTimeout(_searchTimer)
  if (_globalTimer) clearTimeout(_globalTimer)
  const q = searchQuery.value
  _searchTimer = setTimeout(() => { currentPage.value = 1; loadAllStocks() }, 300)
  _globalTimer = setTimeout(() => fetchGlobalSearch(q), 400)
  // 搜索清空时也清空跨市场结果
  if (!q.trim()) globalSearchResults.value = []
}

// ── 拖拽排序 ──────────────────────────────────────────────────────────────
function onDragStart(code, e) {
  if (!canDrag.value) return
  draggingCode.value = code
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
function onDragOver(code) {
  if (!canDrag.value || draggingCode.value == null || draggingCode.value === code) return
  const codes = displayList.value.map(s => s.code)
  const from = codes.indexOf(draggingCode.value)
  const to = codes.indexOf(code)
  if (from < 0 || to < 0) return
  codes.splice(to, 0, codes.splice(from, 1)[0])
  watchlistStore.reorderWatchlist(codes)
}
function onDrop() { draggingCode.value = null }
function onDragEnd() { draggingCode.value = null }

// ── 多选批量 ──────────────────────────────────────────────────────────────
function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) selectedCodes.value = new Set()
}
function isSelected(code) { return selectedCodes.value.has(code) }
function toggleSelect(code) {
  const s = new Set(selectedCodes.value)
  s.has(code) ? s.delete(code) : s.add(code)
  selectedCodes.value = s
}
const allSelected = computed(() =>
  displayList.value.length > 0 && displayList.value.every(s => selectedCodes.value.has(s.code)))
function selectAll() {
  if (allSelected.value) { selectedCodes.value = new Set() }
  else { selectedCodes.value = new Set(displayList.value.map(s => s.code)) }
}
async function applyBatchTag() {
  const t = batchTagInput.value.trim()
  if (!t || !selectedCodes.value.size) return
  for (const code of selectedCodes.value) {
    const item = watchlist.value.find(s => s.code === code)
    const cur = item?.tags || []
    if (!cur.includes(t)) await watchlistStore.setTags(code, [...cur, t])
  }
  batchTagInput.value = ''
}
// 选中多只 → 跳转个股对比页（带代码与名称，对比页自动开跑）
function compareSelected() {
  const codes = [...selectedCodes.value]
  if (codes.length < 2) return
  if (codes.length > 6) { alert('个股对比最多 6 只'); return }
  const names = codes.map(c => watchlist.value.find(s => s.code === c)?.name || c)
  window.open(router.resolve({
    path: '/stock-compare',
    query: { symbols: codes.join(','), names: names.join(',') },
  }).href, '_blank')
}

function batchRemoveSelected() {
  const codes = [...selectedCodes.value]
  if (!codes.length) return
  const snapshot = watchlist.value.filter(s => codes.includes(s.code)).map(s => ({ ...s }))
  const order = watchlist.value.map(s => s.code)
  watchlistStore.batchRemove(codes)
  selectedCodes.value = new Set()
  showUndoToast(snapshot, order)
}

// ── 撤销 toast ────────────────────────────────────────────────────────────
function showUndoToast(items, order) {
  if (undoTimer) clearTimeout(undoTimer)
  undoToast.value = { items, order }
  undoTimer = setTimeout(() => { undoToast.value = null }, 6000)
}
async function undoRemoval() {
  const snap = undoToast.value
  undoToast.value = null
  if (undoTimer) clearTimeout(undoTimer)
  if (!snap) return
  for (const it of snap.items) {
    await watchlistStore.addToWatchlist({ code: it.code, name: it.name })
    if (it.tags?.length) await watchlistStore.setTags(it.code, it.tags)
  }
  watchlistStore.reorderWatchlist(snap.order)
  watchlistStore.fetchAllMiniChartData()
}

// ── 数据加载（服务端分页 + 搜索）─────────────────────────────────────────────
let _warmTimer = null
async function loadAllStocks() {
  allStocksLoading.value = true
  // 涨/跌幅榜按涨跌幅排序，否则按代码
  const sort_by = filterType.value === 'gainers' || filterType.value === 'losers' ? 'change_pct' : 'code'
  const order = filterType.value === 'gainers' ? 'desc' : filterType.value === 'losers' ? 'asc' : 'asc'
  try {
    const { data } = await axios.get('/api/market/all-stocks', {
      params: {
        page: currentPage.value, page_size: pageSize, sort_by, order,
        filter_type: filterType.value === 'all' ? undefined : filterType.value,
        search: searchQuery.value.trim() || undefined,
      },
    })
    allStocks.value = data.stocks || []
    allTotal.value = data.total || 0
    allTotalPages.value = data.total_pages || 0
    allWarming.value = !!data.warming
    allUpdated.value = data.updated_at
      ? new Date(data.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      : ''
    // 冷启动：快照生成中，稍后自动重试一次
    if (allWarming.value) {
      if (_warmTimer) clearTimeout(_warmTimer)
      _warmTimer = setTimeout(() => { if (tab.value === 'all') loadAllStocks() }, 4000)
    }
  } catch (error) {
    console.error('Failed to load all stocks:', error)
    allStocks.value = []
    allTotal.value = 0
    allTotalPages.value = 0
  } finally {
    allStocksLoading.value = false
  }
}

async function refreshData() {
  if (tab.value === 'all') await loadAllStocks()
  await loadWatchlistData(true)
}

async function loadWatchlistData(forceCharts = false) {
  watchlistLoading.value = true
  try {
    // 先确保自选列表已加载完成（store 初始化是 fire-and-forget，进页面时可能还没回来）
    await watchlistStore.refreshAll()
    lastUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    if (watchlist.value.length === 0) return   // 加载完仍为空才跳过
    // 迷你图后台并发加载（默认只补缺失的）
    watchlistStore.fetchAllMiniChartData(forceCharts)
    // 主力资金流后台拉取（push2 间歇失败不阻塞主行情）
    watchlistStore.fetchFundFlow()
  } finally {
    watchlistLoading.value = false
  }
}

// AI 诊断：触发批量诊断，并自动开启 AI 列(列表视图)，让结果可见
async function runAiDiagnose() {
  if (!watchlist.value.length) return
  for (const k of ['ai_score', 'ai_rating', 'ai_comment']) {
    if (!colKeys.value.includes(k)) colKeys.value = [...colKeys.value, k]
  }
  LS.set('wl_cols', colKeys.value.join(','))
  if (view.value !== 'list') setView('list')
  await watchlistStore.fetchAiDiagnose(false)
}

// ── AI 一键分组 & 标色 ────────────────────────────────────────────────────────
const aiGroupModal = ref(false)
const aiGroupLoading = ref(false)
const aiGroupError = ref('')
const aiGroupSuggestions = ref([])   // [{code, name, group, color, reason, selected}]
const aiGroupNames = computed(() => {
  const seen = new Set()
  return aiGroupSuggestions.value.map(s => s.group).filter(g => g && !seen.has(g) && seen.add(g))
})
const aiGroupAllSelected = computed(() =>
  aiGroupSuggestions.value.length > 0 && aiGroupSuggestions.value.every(s => s.selected))
function toggleAiGroupAll() {
  const val = !aiGroupAllSelected.value
  aiGroupSuggestions.value.forEach(s => { s.selected = val })
}

async function openAiGroupModal() {
  aiGroupModal.value = true
  if (!aiGroupSuggestions.value.length) await runAiGroup(false)
}

async function runAiGroup(force = false) {
  if (!watchlist.value.length) return
  aiGroupLoading.value = true
  aiGroupError.value = ''
  try {
    const codes = watchlist.value.map(s => s.code)
    const { data } = await axios.post('/api/watchlist/ai-group', { codes, force })
    const suggestions = []
    for (const s of watchlist.value) {
      const r = data.data?.[s.code] || {}
      suggestions.push({
        code: s.code,
        name: s.name,
        group: r.group || '其他',
        color: r.color || '',
        reason: r.reason || '',
        selected: true,
      })
    }
    // 按分组聚合排序
    const order = {}
    suggestions.forEach(s => { if (!(s.group in order)) order[s.group] = Object.keys(order).length })
    suggestions.sort((a, b) => order[a.group] - order[b.group])
    aiGroupSuggestions.value = suggestions
  } catch (e) {
    aiGroupError.value = e.response?.data?.detail || e.message || 'AI 分析失败，请重试'
  } finally {
    aiGroupLoading.value = false
  }
}

async function applyAiGroup() {
  const selected = aiGroupSuggestions.value.filter(s => s.selected)
  if (!selected.length) return
  // 并发应用（setTags + setColor），限制并发 5
  const sem = 5
  for (let i = 0; i < selected.length; i += sem) {
    await Promise.all(selected.slice(i, i + sem).map(async s => {
      const item = watchlist.value.find(x => x.code === s.code)
      // 合并分组：保留现有标签，追加 AI 建议的分组（如没有）
      const cur = item?.tags || []
      const next = cur.includes(s.group) ? cur : [...cur.filter(t => t), s.group].filter(Boolean)
      if (s.group) await watchlistStore.setTags(s.code, next)
      if (s.color !== undefined) await watchlistStore.setColor(s.code, s.color)
    }))
  }
  aiGroupModal.value = false
}

function isInWatchlist(code) { return watchlistStore.isInWatchlist(code) }
function addToWatchlist(stock) { watchlistStore.addToWatchlist({ code: stock.code, name: stock.name }) }

function removeWithUndo(stock) {
  const snapshot = [{ ...stock }]
  const order = watchlist.value.map(s => s.code)
  watchlistStore.removeFromWatchlist(stock.code)
  showUndoToast(snapshot, order)
}

function onCardClick(stock) {
  if (selectMode.value) { toggleSelect(stock.code); return }
  goToDetail(stock.code)
}
function goToDetail(code) { window.open(router.resolve(`/stock/${code}`).href, '_blank') }

// ── 行情取值 ──────────────────────────────────────────────────────────────
function getCurrentPrice(code) {
  const d = realtimeData.value[code]
  return d && d.price != null ? d.price.toFixed(2) : '--'
}
function getChangePercent(code) {
  const d = realtimeData.value[code]
  if (d && d.change_pct != null) {
    const pct = parseFloat(d.change_pct)
    return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'
  }
  return '--'
}
function getPriceClass(code) {
  const d = realtimeData.value[code]
  if (!d || d.change_pct == null) return ''
  return d.change_pct >= 0 ? 'up' : 'down'
}
function getStockColor(code) {
  const d = realtimeData.value[code]
  if (!d || d.change_pct == null) return null
  return d.change_pct >= 0 ? 'red' : 'green'
}
// 涨跌幅热力背景：幅度越大底色越深(±10% 封顶)，红涨绿跌，一眼看强弱
function pctHeatStyle(code) {
  const d = realtimeData.value[code]
  const p = d?.change_pct
  if (p == null || p === 0) return {}
  const intensity = Math.min(Math.abs(p) / 10, 1)        // 0~1
  const alpha = (0.08 + intensity * 0.34).toFixed(3)      // 0.08~0.42
  const rgb = p > 0 ? '220,38,38' : '22,163,74'           // --up / --down
  return { background: `rgba(${rgb},${alpha})`, color: p > 0 ? 'var(--up)' : 'var(--down)' }
}
function getChartData(code) { return miniChartData.value[code] || [] }
// 分时图基准价：优先分时接口给的昨收，回退实时行情的 pre_close
function getStockPre(code) {
  return miniChartPre.value[code] ?? realtimeData.value[code]?.pre_close ?? null
}
function idxCls(idx) {
  if (idx.change_pct == null) return ''
  return idx.change_pct >= 0 ? 'up' : 'down'
}

// 同花顺式丰富指标（卡片底部网格）
function stockMetrics(code) {
  const d = realtimeData.value[code] || {}
  return [
    { label: '量比', val: fmtNum(d.vol_ratio) },
    { label: '振幅', val: fmtPct(d.amplitude) },
    { label: '换手', val: fmtPct(d.turnover_rate) },
    { label: '主力', val: fmtSignedAmt(d.main_net), cls: signCls(d.main_net) },
    { label: '市值', val: fmtAmt(d.market_cap) },
    { label: '额', val: fmtAmt(d.turnover) },
  ]
}

// ── 格式化 ────────────────────────────────────────────────────────────────
function fmtNum(v) { return v != null ? Number(v).toFixed(1) : '--' }
function fmtPct(v) { return v != null ? Number(v).toFixed(2) + '%' : '--' }
function fmtAmt(v) {
  if (!v) return '--'
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿'
  if (v >= 1e8) return (v / 1e8).toFixed(1) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return String(Math.round(v))
}
// 盈亏金额：保留符号、绝对值走带单位的金额格式
function fmtAmt0(v) { return fmtAmt(Math.abs(v)) }
// 带符号资金净额(主力/超大单等，单位元)：+/- 前缀 + 亿/万
function fmtSignedAmt(v) {
  if (v == null) return '--'
  return (v >= 0 ? '+' : '-') + fmtAmt(Math.abs(v))
}
function fmtSignedPct(v) { return v == null ? '--' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' }
function signCls(v) { return v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '' }
function fmtShares(v) {
  if (v == null) return '--'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万股'
  return Math.round(v) + '股'
}

// ── 持仓盈亏 ──────────────────────────────────────────────────────────────
// 单只持仓盈亏：需成本价 + 股数 + 现价齐全才计算
function holdingPnl(code) {
  const s = watchlist.value.find(x => x.code === code)
  const price = realtimeData.value[code]?.price
  if (!s || s.cost_price == null || s.shares == null || price == null) return null
  const cost = Number(s.cost_price), shares = Number(s.shares)
  const costVal = cost * shares
  const marketVal = price * shares
  const profit = marketVal - costVal
  return { cost, shares, price, costVal, marketVal, profit, profitPct: costVal ? profit / costVal * 100 : 0 }
}
function hasHolding(code) {
  const s = watchlist.value.find(x => x.code === code)
  return !!(s && s.cost_price != null && s.shares != null)
}
// 持仓汇总：总市值 / 总成本 / 浮动盈亏（仅统计有持仓的）
const holdingSummary = computed(() => {
  let mv = 0, cv = 0, n = 0
  for (const s of watchlist.value) {
    const h = holdingPnl(s.code)
    if (!h) continue
    mv += h.marketVal; cv += h.costVal; n++
  }
  const profit = mv - cv
  return { count: n, marketVal: mv, costVal: cv, profit, profitPct: cv ? profit / cv * 100 : 0 }
})

// ── 标签编辑 ──────────────────────────────────────────────────────────────
function startTagEdit(code) { tagEditCode.value = code; tagInput.value = '' }
async function addTag(stock) {
  const t = tagInput.value.trim()
  tagInput.value = ''
  tagEditCode.value = ''
  if (!t) return
  const cur = stock.tags || []
  if (cur.includes(t)) return
  await watchlistStore.setTags(stock.code, [...cur, t])
}
async function removeTag(stock, t) {
  await watchlistStore.setTags(stock.code, (stock.tags || []).filter(x => x !== t))
}

// 全局点击关闭浮层（列选择/右键菜单/铃铛）
function closeOverlays() { colPicker.value = false; closeCtxMenu(); alertBell.value = false }

// ── 标色（单只 + 批量 + 筛选）────────────────────────────────────────────
// 预设色板：红/橙/黄/绿/蓝/紫/灰，覆盖常见「重点/止盈/观察」语义
const COLOR_PALETTE = [
  { hex: '#ef4444', name: '红' },
  { hex: '#f97316', name: '橙' },
  { hex: '#eab308', name: '黄' },
  { hex: '#22c55e', name: '绿' },
  { hex: '#3b82f6', name: '蓝' },
  { hex: '#a855f7', name: '紫' },
  { hex: '#94a3b8', name: '灰' },
]
function colorOf(stock) { return stock?.color || '' }
function rowColorStyle(stock) {
  const c = colorOf(stock)
  return c ? { borderLeft: `3px solid ${c}` } : {}
}
async function applyColor(code, hex) {
  await watchlistStore.setColor(code, hex || '')
  closeCtxMenu()
}
// 批量标色
async function batchSetColor(hex) {
  for (const code of selectedCodes.value) {
    await watchlistStore.setColor(code, hex || '')
  }
}
// 颜色筛选辅助：统计自选股中已使用的颜色 + 数量
const anyColored = computed(() => watchlist.value.some(s => s.color))
const usedColors = computed(() => {
  const map = {}
  for (const s of watchlist.value) {
    if (!s.color) continue
    map[s.color] = (map[s.color] || 0) + 1
  }
  return COLOR_PALETTE
    .filter(c => map[c.hex])
    .map(c => ({ ...c, count: map[c.hex] }))
})

// ── 右键菜单（同花顺式：标色/分组/持仓/预警/移除）─────────────────────────
const ctxMenu = ref(null)   // { code, name, x, y }
function openCtxMenu(stock, e) {
  if (selectMode.value) return
  const pad = 8, w = 220, h = 320
  const x = Math.min(e.clientX, window.innerWidth - w - pad)
  const y = Math.min(e.clientY, window.innerHeight - h - pad)
  ctxMenu.value = { code: stock.code, name: stock.name, x: Math.max(pad, x), y: Math.max(pad, y) }
}
function closeCtxMenu() { ctxMenu.value = null }
const ctxStock = computed(() =>
  ctxMenu.value ? watchlist.value.find(s => s.code === ctxMenu.value.code) : null)

// 右键菜单内「加入分组」：复用标签体系（标签即分组，与顶部分组条联动）
const ctxTagInput = ref('')
function ctxHasTag(tag) { return (ctxStock.value?.tags || []).includes(tag) }
async function toggleGroup(tag) {
  const s = ctxStock.value
  if (!s || !tag) return
  const cur = s.tags || []
  const next = cur.includes(tag) ? cur.filter(x => x !== tag) : [...cur, tag]
  await watchlistStore.setTags(s.code, next)
}
async function addCtxGroup() {
  const t = ctxTagInput.value.trim()
  ctxTagInput.value = ''
  if (!t || ctxHasTag(t)) return
  await toggleGroup(t)
}
// 从右键菜单一键清除该股所有分组
async function clearAllGroups() {
  const s = ctxStock.value
  if (!s || !s.tags?.length) return
  await watchlistStore.setTags(s.code, [])
}
// group-bar 删除整个分组：从所有持有该标签的股票中移除
async function deleteGroup(tag) {
  if (!tag) return
  const stocks = watchlist.value.filter(s => (s.tags || []).includes(tag))
  for (const s of stocks) {
    await watchlistStore.setTags(s.code, (s.tags || []).filter(t => t !== tag))
  }
  if (tagFilter.value === tag) tagFilter.value = ''
}

// ── 持仓录入弹窗 ──────────────────────────────────────────────────────────
const holdingModal = ref(null)   // { code, name, cost, shares }
function openHoldingModal(stock) {
  closeCtxMenu()
  holdingModal.value = {
    code: stock.code, name: stock.name,
    cost: stock.cost_price ?? '', shares: stock.shares ?? '',
  }
}
async function saveHolding() {
  const m = holdingModal.value
  if (!m) return
  const cost = m.cost === '' ? null : Number(m.cost)
  const shares = m.shares === '' ? null : Number(m.shares)
  await watchlistStore.setHolding(m.code, cost, shares)
  holdingModal.value = null
}
async function clearHolding() {
  const m = holdingModal.value
  if (!m) return
  await watchlistStore.setHolding(m.code, null, null)
  holdingModal.value = null
}

// ── 预警弹窗（复用后端 /api/alerts 引擎）─────────────────────────────────
const ALERT_TYPES = [
  // 基础
  { key: 'price_above',  label: '价格突破 ≥', unit: '元', ph: '如 18.50' },
  { key: 'price_below',  label: '价格跌破 ≤', unit: '元', ph: '如 15.00' },
  { key: 'change_above', label: '涨幅超过 ≥', unit: '%', ph: '如 5' },
  { key: 'change_below', label: '跌幅超过 ≥', unit: '%', ph: '如 5' },
  // 智能盯盘
  { key: 'rapid_rise',     label: '⚡快速拉升 ≥(5分钟)', unit: '%', ph: '如 3' },
  { key: 'rapid_fall',     label: '⚡快速跳水 ≥(5分钟)', unit: '%', ph: '如 3' },
  { key: 'vol_ratio_above',label: '📊量比放大 ≥',       unit: '倍', ph: '如 2' },
  { key: 'limit_up',       label: '🔴封涨停',           unit: '', ph: '无需填值', noTarget: true },
  { key: 'limit_down',     label: '🟢触及跌停',         unit: '', ph: '无需填值', noTarget: true },
  { key: 'new_high',       label: '📈创N日新高',        unit: '日', ph: '如 20', def: 20 },
  { key: 'new_low',        label: '📉创N日新低',        unit: '日', ph: '如 20', def: 20 },
  { key: 'ma_above',       label: '↗上穿N日均线',       unit: '日', ph: '如 20', def: 20 },
  { key: 'ma_below',       label: '↘跌破N日均线',       unit: '日', ph: '如 20', def: 20 },
]
const curAlertType = computed(() => ALERT_TYPES.find(t => t.key === alertModal.value?.type) || ALERT_TYPES[0])
const alertModal = ref(null)     // { code, name, type, target, rules:[] }
async function openAlertModal(stock) {
  closeCtxMenu()
  alertModal.value = { code: stock.code, name: stock.name, type: 'price_above', target: '', rules: [], loading: true }
  await loadAlertRules(stock.code)
  if (alertModal.value) alertModal.value.loading = false
}
async function loadAlertRules(code) {
  try {
    const { data } = await axios.get('/api/alerts/')
    if (alertModal.value) alertModal.value.rules = (data || []).filter(r => r.code === code)
  } catch (e) { console.error('load alerts failed', e) }
}
async function createAlert() {
  const m = alertModal.value
  if (!m) return
  const meta = ALERT_TYPES.find(t => t.key === m.type) || {}
  // 封板/跌停类无需阈值；其余必须是合法数值
  const target = meta.noTarget ? 0 : Number(m.target)
  if (!meta.noTarget && (m.target === '' || isNaN(target))) return
  try {
    await axios.post('/api/alerts/', {
      code: m.code, name: m.name, type: m.type, target,
    })
    m.target = ''
    await loadAlertRules(m.code)
    await loadAllAlertRules()
  } catch (e) { console.error('create alert failed', e) }
}
async function deleteAlert(ruleId) {
  try {
    await axios.delete(`/api/alerts/${ruleId}`)
    if (alertModal.value) await loadAlertRules(alertModal.value.code)
    await loadAllAlertRules()
  } catch (e) { console.error('delete alert failed', e) }
}
// 切换预警类型时，带默认阈值(如新高新低/均线缺省 20 日)的自动填上
function onAlertTypeChange() {
  const meta = ALERT_TYPES.find(t => t.key === alertModal.value?.type)
  if (meta && meta.def != null && !alertModal.value.target) alertModal.value.target = meta.def
}
function alertTypeLabel(t) { return (ALERT_TYPES.find(x => x.key === t) || {}).label || t }
function alertNoTarget(t) { return !!(ALERT_TYPES.find(x => x.key === t) || {}).noTarget }
const alertCodes = computed(() => new Set(allAlertRules.value.map(r => r.code)))
const allAlertRules = ref([])
async function loadAllAlertRules() {
  try { const { data } = await axios.get('/api/alerts/'); allAlertRules.value = data || [] }
  catch { allAlertRules.value = [] }
}

// ── 预警触发通知（铃铛）───────────────────────────────────────────────────
const alertNotifs = ref([])
const alertBell = ref(false)
const unreadAlerts = computed(() => alertNotifs.value.filter(n => !n.read).length)
async function loadAlertNotifs() {
  try {
    const { data } = await axios.get('/api/alerts/notifications', { params: { limit: 30 } })
    alertNotifs.value = data.notifications || []
  } catch { /* ignore */ }
}
async function checkAlertsNow() {
  try { await axios.post('/api/alerts/check'); await loadAlertNotifs(); await loadAllAlertRules() }
  catch (e) { console.error('check alerts failed', e) }
}
async function markAlertsRead() {
  try { await axios.post('/api/alerts/notifications/read'); alertNotifs.value.forEach(n => n.read = true) }
  catch { /* ignore */ }
}
function toggleAlertBell() {
  alertBell.value = !alertBell.value
  if (alertBell.value && unreadAlerts.value) markAlertsRead()
}

// ── 异动·资讯流 ────────────────────────────────────────────────────────────
const NEWS_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'news', label: '新闻' },
  { key: 'announcement', label: '公告' },
  { key: 'positive', label: '利好' },
  { key: 'negative', label: '利空' },
]
const newsFeed = ref([])
const newsLoading = ref(false)
const newsUpdated = ref('')
const newsFilter = ref('all')
const newsSeenCount = ref(Number(LS.get('wl_news_seen', '0')))   // 已读过的最新条数(角标用)
const newsUnseen = computed(() => Math.max(0, newsFeed.value.length - newsSeenCount.value))
const newsFilterLabel = computed(() => (NEWS_FILTERS.find(f => f.key === newsFilter.value) || {}).label || '')
const filteredNews = computed(() => {
  const f = newsFilter.value
  if (f === 'all') return newsFeed.value
  if (f === 'announcement') return newsFeed.value.filter(n => n.type === 'announcement')
  if (f === 'news') return newsFeed.value.filter(n => n.type !== 'announcement')
  return newsFeed.value.filter(n => n.sentiment === f)   // positive / negative
})
function codeName(code) { return watchlist.value.find(s => s.code === code)?.name || code }
function codeColor(code) { return watchlist.value.find(s => s.code === code)?.color || '' }

async function loadWatchlistNews(force = false) {
  if (!watchlist.value.length) return
  if (newsLoading.value) return
  if (!force && newsFeed.value.length) return   // 已有则不重复拉
  newsLoading.value = true
  try {
    const codes = watchlist.value.map(s => s.code)
    const { data } = await axios.post('/api/news/watchlist', { codes, per_code: 5, limit: 80 })
    newsFeed.value = data.items || []
    newsUpdated.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch (e) {
    console.error('Failed to load watchlist news:', e)
  } finally {
    newsLoading.value = false
  }
}

onMounted(async () => {
  await loadWatchlistData()
  await refreshIndices()            // 立即拉一次并记录更新时间
  startIndexAutoRefresh()           // 指数独立高频轮询(5s)
  watchlistStore.startAutoRefresh(15000)
  window.addEventListener('click', closeOverlays)
  // 预警：规则与触发通知，进页面拉一次 + 每 60s 刷新铃铛
  loadAllAlertRules()
  loadAlertNotifs()
  _alertTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    loadAlertNotifs()
  }, 60000)
  // 资金流每 60s 刷新一次(后端 60s 缓存，盘后基本不变)
  _ffTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    if (tab.value === 'watchlist' && watchlist.value.length) watchlistStore.fetchFundFlow()
  }, 60000)
  // 后台预拉自选资讯(让 Tab 角标在首屏可用；不标记已读)
  if (watchlist.value.length) loadWatchlistNews()
})

onBeforeUnmount(() => {
  watchlistStore.stopAutoRefresh()
  stopIndexAutoRefresh()
  if (undoTimer) clearTimeout(undoTimer)
  if (_searchTimer) clearTimeout(_searchTimer)
  if (_warmTimer) clearTimeout(_warmTimer)
  if (_alertTimer) clearInterval(_alertTimer)
  if (_ffTimer) clearInterval(_ffTimer)
  window.removeEventListener('click', closeOverlays)
})

watch(tab, (newTab) => {
  if (newTab === 'watchlist') loadWatchlistData()
})
</script>

<style scoped>
.watchlist-page {
  padding: 20px 24px 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ── 指数条（卡片式）─────────────────────────────────────── */
.index-bar {
  display: flex;
  flex-direction: column;
  gap: 9px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 11px 14px;
}
.index-bar-head { display: flex; align-items: center; justify-content: space-between; }
.ib-title { font-size: 12px; font-weight: 700; color: var(--text-2); letter-spacing: .5px; }
.ib-live {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--text-3); font-family: var(--font-mono);
}
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #22c55e; box-shadow: 0 0 0 0 rgba(34,197,94,.6);
  animation: live-pulse 1.8s ease-out infinite;
}
@keyframes live-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(34,197,94,.55); }
  70%  { box-shadow: 0 0 0 6px rgba(34,197,94,0); }
  100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
}
.index-row { display: flex; align-items: stretch; flex-wrap: wrap; gap: 8px; }
.region-tag {
  align-self: center; flex-shrink: 0; width: 30px;
  font-size: 11px; color: var(--text-3); font-weight: 600; letter-spacing: 1px;
}
.index-chip {
  flex: 0 0 auto; min-width: 122px;
  display: flex; flex-direction: column; gap: 1px;
  padding: 7px 12px 7px 13px; position: relative; overflow: hidden;
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-md);
  transition: border-color .2s, background .25s;
}
.index-chip::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--text-3); opacity: .5;
}
.index-chip.up    { border-color: rgba(239,68,68,.32); }
.index-chip.down  { border-color: rgba(34,197,94,.32); }
.index-chip.up::before   { background: var(--up); opacity: 1; }
.index-chip.down::before { background: var(--down); opacity: 1; }
.idx-name { font-size: 11px; color: var(--text-3); white-space: nowrap; display: flex; align-items: center; gap: 4px; }
.idx-chart-ic { color: var(--text-3); opacity: 0; transition: opacity .15s; }
.index-chip.clickable { cursor: pointer; }
.index-chip.clickable:hover { border-color: var(--accent); background: var(--bg-surface); }
.index-chip.clickable:hover .idx-chart-ic { opacity: .7; }
.idx-price { font-size: 17px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1.15; }
.index-chip.up   .idx-price { color: var(--up); }
.index-chip.down .idx-price { color: var(--down); }
.idx-delta { display: flex; align-items: baseline; gap: 7px; font-size: 11px; font-weight: 600; font-family: var(--font-mono); color: var(--text-3); }
.index-chip.up   .idx-delta { color: var(--up); }
.index-chip.down .idx-delta { color: var(--down); }
/* 数值变动高亮闪烁 */
@keyframes idx-flash {
  0%   { background: var(--accent-dim); }
  100% { background: var(--bg-elevated); }
}
.index-chip.flash { animation: idx-flash .8s ease-out; }

/* ── Tab bar ─────────────────────────────────────────────── */
.hub-tabs {
  display: flex;
  align-items: center;
  gap: 3px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 3px;
}
.hub-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px;
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 13px;
  border-radius: calc(var(--radius-md) - 2px);
  cursor: pointer;
  transition: all 0.15s;
}
.hub-tab:hover { color: var(--text-1); }
.hub-tab.active {
  background: var(--bg-elevated);
  color: var(--text-1);
  box-shadow: 0 1px 3px rgba(15,23,42,0.12);
}
.hub-tab-count {
  font-size: 11px; font-family: var(--font-mono);
  background: var(--accent-dim); color: var(--accent);
  border-radius: 8px; padding: 0 6px; line-height: 16px;
}
.tab-spacer { flex: 1; }
.updated-hint { font-size: 11px; color: var(--text-3); margin-right: 10px; font-family: var(--font-mono); }
.btn-refresh {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-2);
  font-size: 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.15s;
}
.btn-refresh:hover:not(:disabled) { color: var(--text-1); border-color: var(--border-light); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-refresh .spin { animation: wl-spin 0.9s linear infinite; }
@keyframes wl-spin { to { transform: rotate(360deg); } }

/* ── 汇总条 ─────────────────────────────────────────────── */
.summary-bar {
  display: flex;
  align-items: center;
  gap: 22px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 12px 20px;
}
.sum-item { display: flex; flex-direction: column; gap: 2px; }
.sum-val { font-size: 19px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1.1; }
.sum-val.up { color: var(--up); }
.sum-val.down { color: var(--down); }
.sum-lbl { font-size: 11px; color: var(--text-3); }
.sum-sep { width: 1px; height: 28px; background: var(--border); }

/* ── Panel (card container) ──────────────────────────────── */
.panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 16px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 12px;
}
.panel-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px;
  color: var(--text-2);
  font-size: 13px;
}
.panel-empty {
  text-align: center;
  padding: 48px 20px;
  color: var(--text-3);
  font-size: 14px;
}

.empty-state { text-align: center; padding: 40px 20px; }
.empty-state svg { margin-bottom: 16px; }
.empty-state p { margin: 0 0 4px; color: var(--text-2); }
.empty-cta {
  margin-top: 14px; font-size: 13px; color: #fff;
  background: var(--accent); border: none; border-radius: var(--radius-md);
  padding: 8px 18px; cursor: pointer; transition: background 0.15s;
}
.empty-cta:hover { background: var(--accent-hover); }

/* ── 工具栏 ─────────────────────────────────────────────── */
.wl-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.toolbar-spacer { flex: 1; }
.wl-search {
  display: flex; align-items: center; gap: 7px;
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 6px 10px; min-width: 180px;
}
.wl-search svg { color: var(--text-3); flex-shrink: 0; }
.wl-search-input {
  flex: 1; background: none; border: none; color: var(--text-1);
  font-size: 13px; outline: none; min-width: 0;
}
.wl-search-input::placeholder { color: var(--text-3); }
.wl-search-clear { background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 15px; line-height: 1; }
.wl-search-clear:hover { color: var(--text-1); }

.view-toggle { display: flex; gap: 2px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 2px; }
.vt-btn {
  display: flex; align-items: center; justify-content: center;
  width: 30px; height: 26px; border: none; background: transparent;
  color: var(--text-3); border-radius: calc(var(--radius-md) - 3px); cursor: pointer; transition: all 0.15s;
}
.vt-btn:hover { color: var(--text-1); }
.vt-btn.active { background: var(--bg-elevated); color: var(--accent); }

.select-toggle {
  font-size: 12px; color: var(--text-2);
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 6px 14px; cursor: pointer; transition: all 0.15s;
}
.select-toggle:hover { color: var(--text-1); border-color: var(--border-light); }
.select-toggle.active { background: var(--accent); border-color: var(--accent); color: #fff; }

.drag-hint { font-size: 11px; color: var(--text-3); margin-bottom: 10px; }

.search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--bg-1);
  border-radius: 6px;
  margin-bottom: 8px;
}
.search-row svg { color: var(--text-3); flex-shrink: 0; }
.search-input {
  flex: 1; background: none; border: none; color: var(--text-1);
  font-size: 13px; outline: none;
}
.search-input::placeholder { color: var(--text-3); }

.filter-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-chip, .sort-chip {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.filter-chip:hover, .sort-chip:hover { border-color: var(--text-3); color: var(--text-2); }
.filter-chip.active, .sort-chip.active { background: var(--accent); border-color: var(--accent); color: white; }
.sort-chips { display: flex; gap: 4px; }

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 16px 0 8px;
}
.page-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
}
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.page-info { font-size: 13px; color: var(--text-3); font-family: 'JetBrains Mono', monospace; }

.exchange-tag {
  font-size: 10px;
  color: var(--accent);
  background: rgba(230, 57, 70, 0.15);
  padding: 1px 4px;
  border-radius: 3px;
}

/* ── 市场类型标签 ─────────────────────────────────────── */
.market-badge {
  font-size: 9.5px; font-weight: 600; padding: 1px 5px; border-radius: 3px;
  flex-shrink: 0; letter-spacing: 0.2px;
}
.market-hk  { color: #c97c00; background: rgba(201,124,0,0.14); }
.market-us  { color: #1d6ac8; background: rgba(29,106,200,0.14); }
.market-kr  { color: #8c44c4; background: rgba(140,68,196,0.14); }
.market-jp  { color: #c44444; background: rgba(196,68,68,0.14);  }
.market-etf { color: #22897c; background: rgba(34,137,124,0.14); }
.market-idx { color: #7c6e22; background: rgba(124,110,34,0.14); }

/* ── 其他市场搜索结果标题 ─────────────────────────────── */
.panel-hint { font-size: 11px; color: var(--text-3); font-weight: 400; margin-left: 6px; }

/* ── 卡片网格 ───────────────────────────────────────────── */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.wl-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px 13px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: transform 0.16s, border-color 0.16s, box-shadow 0.16s, opacity 0.16s;
}
.wl-card:hover {
  transform: translateY(-2px);
  border-color: var(--border-glow);
  box-shadow: var(--accent-glow);
}
.wl-card.selected { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent) inset; }
.wl-card.dragging { opacity: 0.4; }
.wl-card[draggable="true"] { cursor: grab; }

.card-x {
  position: absolute;
  top: 8px; right: 8px;
  width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  border: none; background: transparent;
  color: var(--text-3); border-radius: 5px;
  cursor: pointer; opacity: 0;
  transition: all 0.15s;
}
.wl-card:hover .card-x { opacity: 1; }
.card-x:hover { background: rgba(239,68,68,0.15); color: var(--down); }
.card-check { position: absolute; top: 8px; right: 8px; cursor: pointer; }
.card-check input, .lc-sel input { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }

.wl-top { display: flex; align-items: baseline; gap: 8px; padding-right: 22px; }
.wl-name {
  font-size: 15px; font-weight: 700; color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.wl-code { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); flex-shrink: 0; }

.wl-price-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wl-price { font-size: 22px; font-weight: 700; font-family: var(--font-mono); color: var(--text-1); line-height: 1; }
.wl-price.up { color: var(--up); }
.wl-price.down { color: var(--down); }
.wl-badge { font-size: 13px; font-weight: 700; font-family: var(--font-mono); padding: 3px 8px; border-radius: 6px; flex-shrink: 0; }
.wl-badge.up { color: var(--up); background: rgba(239,68,68,0.14); }
.wl-badge.down { color: var(--down); background: rgba(34,197,94,0.14); }

.wl-spark { height: 40px; overflow: hidden; margin: 0 -2px; }

.wl-meta {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 4px 10px; font-size: 11px; font-family: var(--font-mono);
}
.wl-metric { display: flex; align-items: baseline; justify-content: space-between; gap: 4px; min-width: 0; }
.wm-label { font-style: normal; color: var(--text-3); flex-shrink: 0; }
.wm-val { font-weight: 600; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wl-research { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--accent); }
.wl-research svg { flex-shrink: 0; opacity: 0.85; }
.wl-research .wr-date { color: var(--text-3); font-family: var(--font-mono); margin-left: auto; }

.wl-tags { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.wl-tag {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 11px; color: var(--accent);
  background: var(--accent-dim); border: 1px solid var(--border-light);
  border-radius: 10px; padding: 1px 8px;
}
.tag-x { font-style: normal; cursor: pointer; opacity: 0.55; }
.tag-x:hover { opacity: 1; color: var(--down); }
.tag-add {
  font-size: 11px; color: var(--text-3);
  background: transparent; border: 1px dashed var(--border-light);
  border-radius: 10px; padding: 1px 8px; cursor: pointer; transition: all 0.15s;
}
.tag-add:hover { color: var(--accent); border-color: var(--accent); }
.tag-input {
  width: 72px; font-size: 11px; color: var(--text-1);
  background: var(--bg-base); border: 1px solid var(--accent);
  border-radius: 10px; padding: 1px 8px; outline: none;
}

.wl-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; }
.wl-add { font-size: 12px; color: #fff; background: var(--accent); border: none; border-radius: 6px; padding: 4px 12px; cursor: pointer; transition: background 0.15s; }
.wl-add:hover { background: var(--accent-hover); }
.wl-added { font-size: 11px; color: var(--accent); }

/* ── 分组切换条 + 颜色筛选 ──────────────────────────────── */
.group-bar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-bottom: 12px;
  min-height: 34px;
}
.group-bar.has-content {
  border-bottom: 1px solid var(--border); padding-bottom: 2px;
}
.group-chip {
  font-size: 13px; color: var(--text-3);
  background: transparent; border: none;
  border-bottom: 2px solid transparent;
  padding: 6px 12px 8px; cursor: pointer; transition: all 0.15s;
  margin-bottom: -1px; white-space: nowrap;
}
.group-chip:hover { color: var(--text-1); }
.group-chip.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
.group-count { opacity: 0.6; font-size: 11px; font-family: var(--font-mono); }
/* 每个分组 chip 外包装，用于显示删除按钮 */
.group-chip-wrap {
  position: relative; display: inline-flex; align-items: center;
}
.group-chip-wrap .group-chip { padding-right: 22px; }
.group-del {
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%) translateY(-1px);
  width: 14px; height: 14px; border: none; background: transparent;
  color: var(--text-3); font-size: 13px; line-height: 1;
  cursor: pointer; opacity: 0; transition: opacity .12s, color .12s;
  display: flex; align-items: center; justify-content: center; padding: 0;
}
.group-chip-wrap:hover .group-del { opacity: 1; }
.group-del:hover { color: var(--down); }
/* 分隔线 */
.group-divider { width: 1px; height: 18px; background: var(--border); margin: 0 6px; flex-shrink: 0; }
/* 颜色标签 */
.group-color-label { font-size: 11px; color: var(--text-3); padding: 0 4px; flex-shrink: 0; }
/* 颜色快速筛选圆点 */
.color-filter-dot {
  width: 18px; height: 18px; border-radius: 50%; border: 2px solid transparent;
  cursor: pointer; padding: 0; flex-shrink: 0; position: relative;
  transition: transform .12s, border-color .12s;
  display: flex; align-items: center; justify-content: center;
}
.color-filter-dot:hover { transform: scale(1.18); }
.color-filter-dot.active { border-color: var(--text-1); box-shadow: 0 0 0 2px var(--bg-surface) inset; }
.cfd-check { font-size: 9px; color: #fff; font-weight: 700; text-shadow: 0 0 3px rgba(0,0,0,.6); }
.color-clear { padding: 3px 8px 5px; font-size: 11px; }

/* ── 列表视图（flex，列可配置）───────────────────────────── */
/* 列多时整表横向滚动，名称列吸附左侧，数值列不被挤压 */
.wl-list { display: flex; flex-direction: column; overflow-x: auto; }
.wl-flexrow { display: flex; align-items: center; gap: 12px; min-width: max-content; }
.wl-list-head {
  padding: 0 10px 7px 0;
  font-size: 11px; color: var(--text-3);
  border-bottom: 1px solid var(--border);
  user-select: none;
}
.lc-sortable { cursor: pointer; transition: color 0.12s; white-space: nowrap; }
.lc-sortable:hover { color: var(--text-1); }
.lc-sortable.sorted { color: var(--accent); }
.wl-row {
  padding: 6px 10px 6px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.12s, opacity 0.16s;
}
.wl-row:hover { background: var(--bg-elevated); }
.wl-row.selected { background: var(--accent-dim); }
.wl-row.dragging { opacity: 0.4; }
.wl-row[draggable="true"] { cursor: grab; }
.lc-sel { display: flex; align-items: center; width: 18px; flex-shrink: 0; }
/* 名称列吸附左侧：横向滚动看后面列时名称始终可见 */
.lc-name {
  display: flex; flex-direction: column; gap: 0; line-height: 1.25;
  width: 126px; flex: 0 0 126px;
  position: sticky; left: 0; z-index: 2;
  background: var(--bg-surface); padding: 0 8px 0 10px;
}
.wl-row:hover .lc-name { background: var(--bg-elevated); }
.wl-row.selected .lc-name { background: var(--accent-dim); }
.wl-list-head .lc-name { background: var(--bg-surface); }
.lr-name { font-size: 13px; font-weight: 600; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lr-code { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); }
.lc-num {
  width: 72px; flex-shrink: 0; text-align: right;
  font-size: 13px; font-family: var(--font-mono); color: var(--text-1);
}
.lc-num .up { color: var(--up); } .lc-num .down { color: var(--down); }
.wl-list-head .lc-num { font-family: inherit; }
.lc-spark { width: 96px; flex-shrink: 0; display: flex; align-items: center; justify-content: flex-start; height: 24px; }
.wl-list-head .lc-spark { justify-content: flex-start; }
.lc-act { width: 32px; flex-shrink: 0; display: flex; justify-content: center; }
.row-x {
  width: 22px; height: 22px; border: none; background: transparent;
  color: var(--text-3); border-radius: 5px; cursor: pointer; font-size: 16px; line-height: 1;
}
.row-x:hover { background: rgba(239,68,68,0.15); color: var(--down); }

/* 列配置浮层（按指标分组） */
.col-config { position: relative; }
.col-pop {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 30;
  background: var(--bg-elevated); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); box-shadow: 0 10px 30px rgba(15,23,42,0.18);
  padding: 10px 12px; min-width: 230px; max-width: 280px;
}
.col-pop-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.col-pop-title { font-size: 11px; color: var(--text-3); font-weight: 700; }
.col-reset {
  font-size: 11px; color: var(--accent); background: transparent; border: none;
  cursor: pointer; padding: 1px 4px; border-radius: 4px;
}
.col-reset:hover { background: var(--accent-dim); }
.col-group + .col-group { margin-top: 7px; padding-top: 7px; border-top: 1px solid var(--border); }
.col-group-title { font-size: 10px; color: var(--text-3); font-weight: 700; letter-spacing: .5px; margin-bottom: 4px; }
.col-group-items { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 12px; }
.col-chk { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-1); cursor: pointer; }
.col-chk input { accent-color: var(--accent); }

/* ── 多选操作条 ─────────────────────────────────────────── */
.batch-bar {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
  display: flex; align-items: center; gap: 12px;
  background: var(--bg-elevated); border: 1px solid var(--border-light);
  border-radius: var(--radius-xl); padding: 10px 16px;
  box-shadow: 0 8px 30px rgba(15,23,42,0.12); z-index: 50;
}
.batch-count { font-size: 13px; color: var(--text-1); font-weight: 600; }
.batch-spacer { width: 8px; }
/* 批量标色 */
.batch-colors { display: flex; align-items: center; gap: 5px; }
.batch-label { font-size: 11px; color: var(--text-3); white-space: nowrap; }
.batch-swatch {
  width: 18px; height: 18px; border-radius: 4px; border: 2px solid transparent;
  cursor: pointer; padding: 0; flex-shrink: 0; transition: transform .1s;
}
.batch-swatch:hover { transform: scale(1.14); }
.batch-swatch.clear {
  background: var(--bg-base); border: 1px dashed var(--border-light);
  color: var(--text-3); font-size: 12px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
}
.batch-tag { display: flex; align-items: center; gap: 6px; }
.batch-tag-input {
  width: 110px; font-size: 12px; color: var(--text-1);
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 5px 10px; outline: none;
}
.batch-tag-input:focus { border-color: var(--accent); }
.batch-btn {
  font-size: 12px; color: var(--text-2);
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 5px 12px; cursor: pointer; transition: all 0.15s;
}
.batch-btn:hover:not(:disabled) { color: var(--text-1); border-color: var(--border-light); }
.batch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.batch-btn.danger { color: var(--down); border-color: rgba(239,68,68,0.4); }
.batch-btn.danger:hover { background: rgba(239,68,68,0.12); }

.bar-slide-enter-active, .bar-slide-leave-active { transition: all 0.22s ease; }
.bar-slide-enter-from, .bar-slide-leave-to { opacity: 0; transform: translate(-50%, 14px); }

/* ── 撤销 toast ─────────────────────────────────────────── */
.undo-toast {
  position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
  display: flex; align-items: center; gap: 14px;
  background: var(--bg-elevated); border: 1px solid var(--border-light);
  border-radius: var(--radius-xl); padding: 11px 16px;
  box-shadow: 0 8px 30px rgba(15,23,42,0.12); z-index: 51;
  font-size: 13px; color: var(--text-1);
}
.undo-btn { font-size: 13px; color: var(--accent); background: none; border: none; cursor: pointer; font-weight: 600; }
.undo-btn:hover { text-decoration: underline; }
.undo-close { background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 16px; line-height: 1; }
.undo-close:hover { color: var(--text-1); }

.toast-fade-enter-active, .toast-fade-leave-active { transition: all 0.22s ease; }
.toast-fade-enter-from, .toast-fade-leave-to { opacity: 0; transform: translate(-50%, 14px); }

/* ── 移动端适配 ─────────────────────────────────────────── */
@media (max-width: 768px) {
  .watchlist-page { padding: 12px 12px 16px; gap: 10px; }

  /* 指数条：窄屏卡片横向滚动，避免挤压 */
  .index-bar { padding: 10px 12px; gap: 8px; }
  .index-row {
    flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch;
    gap: 8px; padding-bottom: 2px;
  }
  .region-tag { align-self: center; }
  .index-chip { min-width: 108px; padding: 6px 10px 6px 11px; }
  .idx-price { font-size: 15px; }

  /* Tab 栏：标签可滚动，刷新缩到图标 */
  .hub-tabs { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .hub-tab { padding: 8px 12px; white-space: nowrap; }
  .updated-hint { display: none; }
  .btn-refresh { padding: 8px 12px; flex-shrink: 0; }

  /* 汇总条：横向滚动，避免压缩成一团 */
  .summary-bar {
    gap: 16px; padding: 12px 14px;
    overflow-x: auto; -webkit-overflow-scrolling: touch;
  }
  .sum-item { flex-shrink: 0; }
  .sum-val { font-size: 17px; }

  .panel { padding: 12px; }

  /* 工具栏：搜索占满整行，其它换行 */
  .wl-toolbar { gap: 8px; }
  .wl-search { min-width: 0; flex: 1 1 100%; order: -1; }
  .sort-chips { flex-wrap: wrap; }

  /* 卡片网格：单列铺满 */
  .card-grid { grid-template-columns: 1fr; gap: 10px; }
  .wl-card { padding: 13px; }
  /* 触屏没有 hover，删除按钮常显 */
  .card-x { opacity: 0.6; }

  /* 列表视图：横向滚动看多列，迷你图隐藏省宽，名称列吸附 */
  .wl-flexrow { gap: 8px; }
  .lc-spark { display: none; }
  .lc-num { width: 60px; font-size: 12px; }
  .lc-name { width: 104px; flex-basis: 104px; padding: 0 6px 0 8px; }
  .wl-list-head, .wl-row { padding-right: 4px; }

  /* 悬浮操作条 / toast：上移避开底部导航 + 安全区 */
  .batch-bar, .undo-toast {
    left: 12px; right: 12px; bottom: calc(64px + var(--safe-bottom));
    transform: none; width: auto;
  }
  .batch-bar { flex-wrap: wrap; gap: 8px; overflow-x: auto; }
  .batch-colors { flex-shrink: 0; }
  .bar-slide-enter-from, .bar-slide-leave-to,
  .toast-fade-enter-from, .toast-fade-leave-to { transform: translateY(14px); }
}

/* ── 标色 / 预警标记 ───────────────────────────────────────── */
.wl-color-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; vertical-align: middle; flex-shrink: 0; }
.wl-alert-flag { font-size: 11px; margin-left: 4px; filter: grayscale(0.1); }
.wl-name { display: inline-flex; align-items: center; }

/* 卡片持仓盈亏条 */
.wl-holding { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 11px; }
.wh-lbl { color: var(--text-3); }
.wh-pnl { font-family: var(--font-mono); font-weight: 700; }
.wh-pnl.up { color: var(--up); } .wh-pnl.down { color: var(--down); }

/* ── 预警铃铛 ──────────────────────────────────────────────── */
.alert-bell-wrap { position: relative; }
.btn-bell {
  position: relative; display: flex; align-items: center; justify-content: center;
  width: 32px; height: 30px; border: 1px solid var(--border); background: var(--bg-elevated);
  color: var(--text-2); border-radius: var(--radius-md); cursor: pointer; margin-right: 6px; transition: all .15s;
}
.btn-bell:hover, .btn-bell.active { color: var(--text-1); border-color: var(--border-light); }
.bell-badge {
  position: absolute; top: -5px; right: -5px; min-width: 16px; height: 16px; padding: 0 4px;
  background: var(--down); color: #fff; font-size: 10px; line-height: 16px; text-align: center;
  border-radius: 8px; font-family: var(--font-mono);
}
.bell-pop {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 40; width: 300px; max-height: 380px; overflow-y: auto;
  background: var(--bg-elevated); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); box-shadow: 0 12px 32px rgba(15,23,42,0.2);
}
.bell-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--bg-elevated); }
.bell-title { font-size: 12px; font-weight: 700; color: var(--text-2); }
.bell-check { font-size: 11px; color: var(--accent); background: transparent; border: none; cursor: pointer; padding: 2px 6px; border-radius: 4px; }
.bell-check:hover { background: var(--accent-dim); }
.bell-empty { padding: 26px 14px; text-align: center; font-size: 13px; color: var(--text-2); line-height: 1.8; }
.bell-list { display: flex; flex-direction: column; }
.bell-item { padding: 9px 12px; border-bottom: 1px solid var(--border); }
.bell-item.unread { background: var(--accent-dim); }
.bell-msg { font-size: 12px; color: var(--text-1); line-height: 1.4; }
.bell-time { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); margin-top: 3px; }

/* ── 右键菜单 ──────────────────────────────────────────────── */
.ctx-menu {
  position: fixed; z-index: 200; width: 210px;
  background: var(--bg-elevated); border: 1px solid var(--border-light);
  border-radius: var(--radius-md); box-shadow: 0 12px 36px rgba(15,23,42,0.24);
  padding: 6px; user-select: none;
}
.ctx-title { font-size: 12px; font-weight: 700; color: var(--text-1); padding: 4px 8px 6px; display: flex; align-items: baseline; gap: 6px; }
.ctx-code { font-size: 10px; color: var(--text-3); font-family: var(--font-mono); font-weight: 400; }
.ctx-section { padding: 4px 8px 6px; }
.ctx-label { font-size: 10px; color: var(--text-3); margin-bottom: 5px; }
.ctx-label-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; }
.ctx-label-row .ctx-label { margin-bottom: 0; }
.ctx-clear-groups { font-size: 10px; color: var(--text-3); background: transparent; border: none; cursor: pointer; padding: 1px 4px; border-radius: 3px; }
.ctx-clear-groups:hover { color: var(--down); background: rgba(239,68,68,0.1); }
.ctx-colors { display: flex; gap: 6px; flex-wrap: wrap; }
.ctx-swatch {
  width: 20px; height: 20px; border-radius: 5px; border: 2px solid transparent; cursor: pointer; padding: 0;
  transition: transform .1s;
}
.ctx-swatch:hover { transform: scale(1.12); }
.ctx-swatch.active { border-color: var(--text-1); box-shadow: 0 0 0 1px var(--bg-elevated) inset; }
.ctx-swatch.clear { background: var(--bg-base); border: 1px dashed var(--border-light); color: var(--text-3); font-size: 13px; line-height: 1; }
.ctx-divider { height: 1px; background: var(--border); margin: 4px 0; }
.ctx-item {
  display: flex; align-items: center; gap: 4px; width: 100%; text-align: left;
  padding: 7px 8px; border: none; background: transparent; color: var(--text-1);
  font-size: 13px; border-radius: 5px; cursor: pointer;
}
.ctx-item:hover { background: var(--bg-surface); }
.ctx-item.danger { color: var(--down); }
.ctx-item.danger:hover { background: rgba(239,68,68,0.12); }
.ctx-tag { margin-left: auto; font-size: 10px; color: var(--accent); background: var(--accent-dim); border-radius: 4px; padding: 0 5px; }
.ctx-groups { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; max-height: 84px; overflow-y: auto; }
.ctx-grp { font-size: 11px; padding: 2px 8px; border-radius: 10px; border: 1px solid var(--border); background: var(--bg-base); color: var(--text-2); cursor: pointer; }
.ctx-grp:hover { border-color: var(--border-light); color: var(--text-1); }
.ctx-grp.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }
.ctx-grp-input { width: 100%; font-size: 12px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-1); padding: 5px 8px; outline: none; }
.ctx-grp-input:focus { border-color: var(--accent); }

/* ── 弹窗（持仓 / 预警）─────────────────────────────────────── */
.modal-mask {
  position: fixed; inset: 0; z-index: 150; background: rgba(15,23,42,0.42);
  display: flex; align-items: center; justify-content: center; padding: 20px;
}
.modal-card {
  width: 360px; max-width: 100%; background: var(--bg-surface);
  border: 1px solid var(--border-light); border-radius: var(--radius-xl);
  box-shadow: 0 20px 60px rgba(15,23,42,0.3); overflow: hidden;
}
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--border); font-size: 14px; font-weight: 700; color: var(--text-1); }
.modal-x { border: none; background: transparent; color: var(--text-3); font-size: 20px; line-height: 1; cursor: pointer; }
.modal-x:hover { color: var(--text-1); }
.modal-body { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.modal-field { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--text-2); }
.modal-field input {
  background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md);
  color: var(--text-1); padding: 8px 10px; font-size: 13px; outline: none;
}
.modal-field input:focus { border-color: var(--accent); }
.modal-hint { font-size: 11px; color: var(--text-3); line-height: 1.5; margin: 0; }
.modal-foot { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); }
.modal-foot-spacer { flex: 1; }
.modal-btn {
  font-size: 13px; padding: 7px 14px; border-radius: var(--radius-md);
  border: 1px solid var(--border); background: var(--bg-elevated); color: var(--text-1); cursor: pointer;
}
.modal-btn:hover { border-color: var(--border-light); }
.modal-btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.modal-btn.primary:hover { background: var(--accent-hover); }
.modal-btn.ghost { color: var(--down); border-color: transparent; }
.modal-btn.ghost:hover { background: rgba(239,68,68,0.1); }

/* 预警表单 */
.alert-form { display: flex; gap: 8px; align-items: center; }
.alert-unit { font-size: 12px; color: var(--text-3); white-space: nowrap; }

/* ── 异动·资讯流 ─────────────────────────────────────────── */
.news-filter { display: flex; gap: 6px; }
.news-feed { display: flex; flex-direction: column; }
.news-item {
  display: flex; gap: 12px; padding: 11px 6px; border-bottom: 1px solid var(--border);
  text-decoration: none; color: inherit; transition: background .12s;
}
.news-item:hover { background: var(--bg-hover, rgba(127,127,127,.06)); }
.news-stock {
  flex: 0 0 96px; display: flex; flex-direction: column; gap: 2px; cursor: pointer;
  padding-top: 1px;
}
.news-stock:hover .ns-name { text-decoration: underline; }
.ns-name { font-size: 13px; font-weight: 600; color: var(--text-1); display: flex; align-items: center; gap: 4px; }
.ns-code { font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.news-main { flex: 1; min-width: 0; }
.news-title { font-size: 13px; line-height: 1.5; color: var(--text-1); }
.news-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 5px; background: var(--text-3); vertical-align: middle; }
.news-dot.positive { background: var(--up); }
.news-dot.negative { background: var(--down); }
.news-type-tag {
  font-size: 10px; padding: 1px 5px; border-radius: 4px; margin-right: 6px;
  background: var(--bg-base); border: 1px solid var(--border); color: var(--text-2);
}
.news-type-tag.ann { background: rgba(234,179,8,.14); border-color: rgba(234,179,8,.4); color: #b88700; }
.news-digest { font-size: 12px; color: var(--text-2); margin-top: 3px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.news-foot { display: flex; gap: 10px; margin-top: 5px; font-size: 11px; color: var(--text-3); }
.news-time { font-variant-numeric: tabular-nums; }

/* ── AI 诊断 ─────────────────────────────────────────────── */
.ai-diag-btn, .ai-group-btn {
  display: inline-flex; align-items: center; gap: 5px; padding: 6px 11px; font-size: 12px;
  background: linear-gradient(135deg, rgba(124,58,237,.14), rgba(59,130,246,.14));
  border: 1px solid rgba(124,58,237,.4); color: var(--text-1); border-radius: var(--radius-md);
  cursor: pointer; font-weight: 600; white-space: nowrap;
}
.ai-diag-btn:hover:not(:disabled), .ai-group-btn:hover:not(:disabled) { border-color: rgba(124,58,237,.7); }
.ai-diag-btn:disabled, .ai-group-btn:disabled { opacity: .6; cursor: default; }
.ai-diag-btn .spin, .ai-group-btn .spin { animation: wl-spin 1s linear infinite; }

/* ── AI 分组弹窗 ─────────────────────────────────────────── */
.ai-group-modal { width: 680px; max-width: 96vw; max-height: 85vh; display: flex; flex-direction: column; }
.ag-loading {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 48px 20px; font-size: 13px; color: var(--text-2);
}
.ag-error {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 40px 20px; font-size: 13px; color: var(--down); text-align: center;
}
.ag-meta {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 10px 16px; background: var(--accent-dim); font-size: 12px; color: var(--text-2);
  border-bottom: 1px solid var(--border);
}
.ag-meta b { color: var(--accent); }
.ag-rerun {
  margin-left: auto; font-size: 11px; color: var(--accent);
  background: transparent; border: 1px solid var(--accent); border-radius: var(--radius-md);
  padding: 3px 8px; cursor: pointer;
}
.ag-rerun:hover { background: var(--accent-dim); }
.ag-body { flex: 1; overflow-y: auto; padding: 0 16px 8px; }
.ag-group { margin-top: 12px; }
.ag-group-head {
  display: flex; align-items: center; gap: 8px; padding: 6px 0;
  border-bottom: 1px solid var(--border); margin-bottom: 4px;
}
.ag-group-name { font-size: 13px; font-weight: 700; color: var(--text-1); }
.ag-group-count { font-size: 11px; color: var(--text-3); font-family: var(--font-mono); }
.ag-row {
  display: flex; align-items: center; gap: 8px; padding: 5px 0;
  border-bottom: 1px solid var(--border); flex-wrap: nowrap; overflow: hidden;
}
.ag-check { flex-shrink: 0; }
.ag-check input { width: 14px; height: 14px; accent-color: var(--accent); cursor: pointer; }
.ag-name { font-size: 13px; font-weight: 600; color: var(--text-1); white-space: nowrap; flex: 0 0 60px; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.ag-code { font-size: 11px; color: var(--text-3); flex-shrink: 0; width: 54px; }
.ag-colors { display: flex; gap: 3px; flex-shrink: 0; }
.ag-swatch {
  width: 16px; height: 16px; border-radius: 4px; border: 2px solid transparent;
  cursor: pointer; padding: 0; flex-shrink: 0; transition: transform .1s;
}
.ag-swatch:hover { transform: scale(1.15); }
.ag-swatch.active { border-color: var(--text-1); }
.ag-swatch.clear {
  background: var(--bg-base); border: 1px dashed var(--border-light);
  color: var(--text-3); font-size: 11px; line-height: 1;
  display: flex; align-items: center; justify-content: center;
}
.ag-grp-input {
  flex: 1; min-width: 80px; max-width: 140px; font-size: 12px;
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1); padding: 3px 7px; outline: none;
}
.ag-grp-input:focus { border-color: var(--accent); }
.ag-reason { font-size: 11px; color: var(--text-3); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ag-sel-all { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.ag-sel-all input { accent-color: var(--accent); }
.wl-ai { display: flex; align-items: center; gap: 6px; margin-top: 7px; font-size: 11px; min-width: 0; }
.wl-ai-tag {
  font-size: 9px; font-weight: 700; padding: 1px 4px; border-radius: 3px; flex: none;
  background: linear-gradient(135deg, #7c3aed, #3b82f6); color: #fff;
}
.wl-ai-score { font-weight: 700; font-variant-numeric: tabular-nums; flex: none; }
.wl-ai-rating { flex: none; }
.wl-ai-comment { color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.alert-type { flex: 1; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-1); padding: 7px 8px; font-size: 12px; outline: none; }
.alert-target { width: 84px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-1); padding: 7px 8px; font-size: 13px; outline: none; }
.alert-rules { display: flex; flex-direction: column; gap: 6px; max-height: 180px; overflow-y: auto; }
.alert-empty { font-size: 12px; color: var(--text-3); text-align: center; padding: 12px; }
.alert-rule { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); }
.ar-desc { font-size: 12px; color: var(--text-1); flex: 1; }
.ar-desc b { font-family: var(--font-mono); color: var(--accent); }
.ar-state { font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.ar-state.on { color: var(--up); background: rgba(34,197,94,0.14); }
.ar-state.off { color: var(--text-3); background: var(--bg-elevated); }
.ar-del { font-size: 11px; color: var(--text-3); background: transparent; border: none; cursor: pointer; padding: 2px 4px; border-radius: 4px; }
.ar-del:hover { color: var(--down); background: rgba(239,68,68,0.1); }
</style>
