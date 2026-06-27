<template>
  <div class="admin-view">

    <!-- ── 页头 ─────────────────────────────────────────────────── -->
    <div class="page-hdr">
      <div class="page-hdr-left">
        <h1 class="page-title">管理后台</h1>
        <span class="page-date">{{ fmtDate(new Date().toISOString()) }}</span>
      </div>
      <button class="hdr-refresh" @click="loadAll" :disabled="loading">
        <svg :class="['ri', { spin: loading }]" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
          <path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
        </svg>
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>

    <!-- ── 顶部指标卡片 ────────────────────────────────────────── -->
    <div class="metric-grid">
      <!-- 用户 -->
      <div class="mc">
        <div class="mc-icon mc-blue">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">注册用户</div>
          <div class="mc-val">{{ overview.user_count ?? '—' }}</div>
          <div class="mc-sub">管理员 {{ overview.admin_count ?? 0 }}</div>
        </div>
      </div>
      <!-- 今日活跃 -->
      <div class="mc mc-accent">
        <div class="mc-icon mc-green">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">
            今日活跃
            <span v-if="overview.dau != null" class="delta" :class="deltaClass">{{ deltaText }}</span>
          </div>
          <div class="mc-val">{{ overview.dau ?? '—' }}</div>
          <div class="mc-sub">周活 {{ overview.wau ?? 0 }} · 月活 {{ overview.mau ?? 0 }}</div>
        </div>
      </div>
      <!-- 在线 -->
      <div class="mc mc-online">
        <div class="mc-icon mc-emerald">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">当前在线</div>
          <div class="mc-val">{{ onlineUsers.length }}</div>
          <div class="mc-sub mc-online-names">
            <template v-if="onlineUsers.length">
              <span v-for="u in onlineUsers.slice(0,4)" :key="u.username" class="online-pip">{{ u.username }}</span>
              <span v-if="onlineUsers.length > 4" class="mc-sub">+{{ onlineUsers.length - 4 }}</span>
            </template>
            <span v-else>暂无在线用户</span>
          </div>
        </div>
      </div>
      <!-- 粘性 -->
      <div class="mc">
        <div class="mc-icon mc-purple">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">用户粘性</div>
          <div class="mc-val">{{ overview.stickiness != null ? (overview.stickiness * 100).toFixed(0) + '%' : '—' }}</div>
          <div class="mc-sub">DAU / MAU</div>
        </div>
      </div>
      <!-- LLM -->
      <div class="mc">
        <div class="mc-icon mc-orange">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">LLM 调用</div>
          <div class="mc-val">{{ overview.total_calls ?? '—' }}</div>
          <div class="mc-sub">累计次数</div>
        </div>
      </div>
      <!-- Token -->
      <div class="mc">
        <div class="mc-icon mc-cyan">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">Token 用量</div>
          <div class="mc-val">{{ fmtK((overview.total_input_tokens||0)+(overview.total_output_tokens||0)) }}</div>
          <div class="mc-sub">入 {{ fmtK(overview.total_input_tokens) }} · 出 {{ fmtK(overview.total_output_tokens) }}</div>
        </div>
      </div>
      <!-- 费用 -->
      <div class="mc mc-cost">
        <div class="mc-icon mc-red">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">预估费用</div>
          <div class="mc-val">{{ fmtUsd(overview.total_cost_usd) }}</div>
          <svg v-if="costSpark.pts" class="mc-spark" viewBox="0 0 120 24" preserveAspectRatio="none">
            <polyline class="spark-area" :points="costSpark.area" />
            <polyline class="spark-line" :points="costSpark.pts" />
          </svg>
          <div v-else class="mc-sub">近 14 天趋势</div>
        </div>
      </div>
      <!-- 自选 -->
      <div class="mc">
        <div class="mc-icon mc-blue">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
        </div>
        <div class="mc-body">
          <div class="mc-label">自选股总数</div>
          <div class="mc-val">{{ overview.watchlist_total ?? '—' }}</div>
          <div class="mc-sub">跨所有账号</div>
        </div>
      </div>
    </div>

    <!-- ── Tab 导航 ───────────────────────────────────────────── -->
    <div class="tab-nav">
      <div class="tab-nav-scroll">
        <button v-for="t in tabs" :key="t.key"
                :class="['tab-btn', { active: tab === t.key }]"
                @click="tab = t.key">
          {{ t.label }}
          <span v-if="t.key === 'users' && onlineUsers.length" class="tab-badge">{{ onlineUsers.length }} 在线</span>
        </button>
      </div>
    </div>

    <!-- ══════════════════ 活跃统计 ══════════════════════════════ -->
    <div v-if="tab === 'activity'" class="content-area">

      <!-- DAU 趋势 -->
      <div class="card chart-card">
        <div class="card-head">
          <span class="card-title">每日活跃趋势（DAU）</span>
          <div class="seg-group">
            <button v-for="d in [7, 30, 90]" :key="d"
                    :class="['seg', { active: actDays === d }]"
                    @click="setActDays(d)">{{ d }}天</button>
          </div>
        </div>
        <svg v-if="dauChart.pts" class="dau-svg" :viewBox="`0 0 ${dauW} ${dauH}`" preserveAspectRatio="none">
          <defs>
            <linearGradient id="dauGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.18"/>
              <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
            </linearGradient>
          </defs>
          <polyline class="dau-area" :points="dauChart.area" fill="url(#dauGrad)" stroke="none"/>
          <polyline class="dau-line" :points="dauChart.pts" />
        </svg>
        <div v-else class="chart-empty">暂无数据</div>
        <div class="chart-foot">
          <span>{{ activity.dau_series[0]?.day?.slice(5) }}</span>
          <span class="chart-peak">峰值 {{ dauChart.max }} 人</span>
          <span>{{ activity.dau_series.at(-1)?.day?.slice(5) }}</span>
        </div>
      </div>

      <!-- 查询量级 + 小时分布 -->
      <div class="two-col" v-if="queryDist.volume?.total || queryDist.hourly?.length">
        <!-- 量级摘要 -->
        <div class="card" v-if="queryDist.volume?.total">
          <div class="card-head"><span class="card-title">请求量统计</span>
            <div class="seg-group">
              <button v-for="d in [7, 30, 90]" :key="d"
                      :class="['seg', { active: queryDays === d }]"
                      @click="setQueryDays(d)">{{ d }}天</button>
            </div>
          </div>
          <div class="vol-grid">
            <div class="vol-item">
              <div class="vol-label">总请求量</div>
              <div class="vol-val">{{ queryDist.volume.total.toLocaleString() }}</div>
            </div>
            <div class="vol-item">
              <div class="vol-label">日均</div>
              <div class="vol-val">{{ queryDist.volume.daily_avg }}</div>
            </div>
            <div class="vol-item">
              <div class="vol-label">单日峰值</div>
              <div class="vol-val">{{ queryDist.volume.peak }}</div>
              <div class="vol-sub">{{ queryDist.volume.peak_day?.slice(5) }}</div>
            </div>
            <div class="vol-item" :class="queryDist.volume.week_over_week_pct >= 0 ? 'vol-up' : 'vol-down'">
              <div class="vol-label">周环比</div>
              <div class="vol-val">{{ queryDist.volume.week_over_week_pct >= 0 ? '+' : '' }}{{ queryDist.volume.week_over_week_pct }}%</div>
              <div class="vol-sub">{{ queryDist.volume.recent_7d }} vs {{ queryDist.volume.prev_7d }}</div>
            </div>
          </div>
        </div>

        <!-- 小时分布 -->
        <div class="card" v-if="queryDist.hourly?.length">
          <div class="card-head"><span class="card-title">请求量 · 24小时分布</span>
            <span class="card-meta">峰值 {{ peakHour }}:00 · {{ peakHourEvents }} 次</span>
          </div>
          <div class="hour-chart">
            <div v-for="h in queryDist.hourly" :key="h.hour" class="hc-col"
                 :title="`${h.hour}:00 — ${h.events} 次`">
              <div class="hc-bar" :class="{ peak: h.hour === peakHour }"
                   :style="{ height: hourBarH(h.events) + '%' }"></div>
              <span class="hc-x">{{ h.hour % 6 === 0 ? String(h.hour).padStart(2,'0') : '' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 功能热度 + 留存 -->
      <div class="two-col">
        <div class="card">
          <div class="card-head">
            <span class="card-title">功能热度</span>
            <span class="card-meta">近 {{ activity.window_days }} 天</span>
          </div>
          <div v-for="f in activity.by_feature" :key="f.feature" class="heat-row">
            <span class="heat-name">{{ f.feature }}</span>
            <div class="heat-track">
              <div class="heat-fill" :style="{ width: heatPct(f.events) + '%' }"></div>
            </div>
            <span class="heat-num">{{ f.events }}<span class="heat-u">·{{ f.users }}人</span></span>
          </div>
          <div v-if="!activity.by_feature?.length" class="empty-state">暂无活跃记录</div>
        </div>

        <div class="card">
          <div class="card-head">
            <span class="card-title">新增 / 次日留存</span>
            <span class="card-meta">近 14 天</span>
          </div>
          <table class="tbl compact">
            <thead><tr><th>日期</th><th class="r">新增</th><th class="r">次日留存</th><th class="r">留存率</th></tr></thead>
            <tbody>
              <tr v-for="r in retentionRows" :key="r.day">
                <td class="mono muted">{{ r.day.slice(5) }}</td>
                <td class="r bold">{{ r.new_users }}</td>
                <td class="r">{{ r.retained_d1 }}</td>
                <td class="r" :class="{ muted: !r.new_users }">
                  {{ r.new_users ? r.retention_d1_pct + '%' : '—' }}
                </td>
              </tr>
              <tr v-if="!retentionRows.length"><td colspan="4" class="empty-state">暂无新增</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ══════════════════ 用户与自选 ══════════════════════════════ -->
    <div v-if="tab === 'users'" class="content-area">
      <div class="card no-pad">
        <div class="toolbar">
          <input v-model="userQuery" class="search-box" placeholder="搜索账号 / 邮箱…" />
          <div class="filter-pills">
            <button :class="['pill', { active: userFilter==='all' }]" @click="userFilter='all'">全部 {{ users.length }}</button>
            <button :class="['pill', { active: userFilter==='online' }]" @click="userFilter='online'">
              <span class="pill-dot"></span>在线 {{ onlineUsers.length }}
            </button>
            <button :class="['pill', { active: userFilter==='today' }]" @click="userFilter='today'">今日活跃</button>
          </div>
          <span class="toolbar-count">显示 {{ displayUsers.length }} / {{ users.length }}</span>
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead>
              <tr>
                <th :class="thCls('username')" @click="sortUsers('username')">账号{{ sortInd('username') }}</th>
                <th>角色</th>
                <th :class="thCls('last_seen')" @click="sortUsers('last_seen')">在线状态{{ sortInd('last_seen') }}</th>
                <th :class="thCls('days_30',true)" @click="sortUsers('days_30')">活跃天(30d){{ sortInd('days_30') }}</th>
                <th :class="thCls('watchlist',true)" @click="sortUsers('watchlist')">自选股{{ sortInd('watchlist') }}</th>
                <th :class="thCls('calls',true)" @click="sortUsers('calls')">调用{{ sortInd('calls') }}</th>
                <th class="r">入 token</th>
                <th class="r">出 token</th>
                <th :class="thCls('cost',true)" @click="sortUsers('cost')">费用{{ sortInd('cost') }}</th>
                <th :class="thCls('created')" @click="sortUsers('created')">注册{{ sortInd('created') }}</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in displayUsers" :key="u.id" :class="{ 'row-online': isOnline(u.username) }">
                <td>
                  <div class="user-cell">
                    <span v-if="isOnline(u.username)" class="live-dot"></span>
                    <span class="bold">{{ u.username }}</span>
                  </div>
                  <div class="user-email">{{ u.email || '' }}</div>
                </td>
                <td>
                  <span v-if="u.is_super" class="badge super">超管</span>
                  <span v-else-if="u.is_admin" class="badge admin">管理员</span>
                  <span v-else class="badge">普通</span>
                </td>
                <td>
                  <span v-if="isOnline(u.username)" class="status-online">● 在线中</span>
                  <span v-else-if="u.activity?.active_today" class="status-today">今日活跃</span>
                  <span v-else class="muted mono text-xs">{{ fmtTime(u.activity?.last_seen) || '—' }}</span>
                </td>
                <td class="r">{{ u.activity?.days_30 || 0 }}</td>
                <td class="r">{{ u.watchlist_count }}</td>
                <td class="r">{{ u.tokens.calls }}</td>
                <td class="r">{{ fmtK(u.tokens.input_tokens) }}</td>
                <td class="r">{{ fmtK(u.tokens.output_tokens) }}</td>
                <td class="r">{{ fmtUsd(u.tokens.cost_usd) }}</td>
                <td class="muted text-xs">{{ fmtDate(u.created_at) }}</td>
                <td class="row-actions">
                  <button class="act-btn" @click="openWatchlist(u)">自选</button>
                  <button class="act-btn" @click="openUserChats(u)">对话</button>
                  <template v-if="isSuper">
                    <button v-if="u.env_admin" class="act-btn muted" disabled>锁定</button>
                    <button v-else-if="u.username === myUsername" class="act-btn muted" disabled>本人</button>
                    <button v-else-if="u.is_admin" class="act-btn danger"
                            :disabled="adminBusyId === u.id" @click="toggleAdmin(u, false)">撤权</button>
                    <button v-else class="act-btn"
                            :disabled="adminBusyId === u.id" @click="toggleAdmin(u, true)">设管</button>
                  </template>
                </td>
              </tr>
              <tr v-if="!displayUsers.length && !loading">
                <td colspan="11" class="empty-state">{{ userQuery ? '没有匹配的用户' : '暂无用户' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ══════════════════ 管理员配置 ══════════════════════════════ -->
    <div v-if="tab === 'admins'" class="content-area">
      <div class="card">
        <div class="card-head"><span class="card-title">添加管理员</span></div>
        <p class="hint-text">按用户名添加管理员，未注册账号也可预授权（登录后即生效）。仅超级管理员可操作。</p>
        <div class="form-row">
          <input v-model="newAdmin" class="form-input" placeholder="输入用户名，如 zhangsan"
                 @keyup.enter="addAdmin" :disabled="adminCfgBusy" />
          <button class="btn-primary" @click="addAdmin" :disabled="adminCfgBusy || !newAdmin.trim()">
            {{ adminCfgBusy ? '添加中…' : '设为管理员' }}
          </button>
        </div>
        <div v-if="adminCfgMsg" :class="['form-msg', adminCfgMsgType]">{{ adminCfgMsg }}</div>
      </div>

      <div class="card no-pad">
        <div class="card-head" style="padding:14px 16px 0">
          <span class="card-title">当前管理员</span>
          <span class="card-meta">共 {{ adminList.length }} 个</span>
        </div>
        <table class="tbl compact" style="margin-top:8px">
          <thead><tr><th>用户名</th><th>级别</th><th>来源</th><th>状态</th><th></th></tr></thead>
          <tbody>
            <tr v-for="a in adminList" :key="a.username">
              <td class="bold">{{ a.username }}</td>
              <td><span :class="['badge', a.super ? 'super' : 'admin']">{{ a.super ? '超级管理员' : '管理员' }}</span></td>
              <td class="muted">{{ a.super ? '系统最高' : (a.locked ? '内置/环境' : '后台配置') }}</td>
              <td class="muted">{{ a.registered ? '已注册' : '预授权' }}</td>
              <td class="row-actions">
                <button v-if="a.super || a.locked" class="act-btn muted" disabled>锁定</button>
                <button v-else-if="a.username === myUsername" class="act-btn muted" disabled>本人</button>
                <button v-else class="act-btn danger" :disabled="adminCfgBusy" @click="removeAdmin(a)">撤销</button>
              </td>
            </tr>
            <tr v-if="!adminList.length && !loading"><td colspan="5" class="empty-state">暂无管理员</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════════ AI 对话 ══════════════════════════════════ -->
    <div v-if="tab === 'chats'" class="content-area">
      <div class="card no-pad">
        <div v-if="chatFilterUser" class="filter-notice">
          正在查看 <strong>{{ chatFilterUser }}</strong> 的对话
          <button class="link-btn" @click="clearChatFilter">查看全部</button>
        </div>
        <table class="tbl">
          <thead><tr><th>账号</th><th>会话标题</th><th class="r">消息数</th><th>开始</th><th>最近</th><th></th></tr></thead>
          <tbody>
            <tr v-for="s in chatSessions" :key="s.session_id">
              <td class="bold">{{ s.username || '匿名' }}</td>
              <td>{{ s.title }}</td>
              <td class="r">{{ s.message_count }}</td>
              <td class="muted mono text-xs">{{ fmtTime(s.first_ts) }}</td>
              <td class="muted mono text-xs">{{ fmtTime(s.last_ts) }}</td>
              <td><button class="act-btn" @click="openChat(s)">查看</button></td>
            </tr>
            <tr v-if="!chatSessions.length && !loading"><td colspan="6" class="empty-state">暂无对话记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════════ AI 荐股 ══════════════════════════════════ -->
    <div v-if="tab === 'aipicks'" class="content-area">
      <div class="card">
        <div class="card-head">
          <span class="card-title">AI 每日荐股</span>
          <span v-if="apStatus.running" class="status-badge running">● 生成中</span>
          <span v-else-if="apStatus.has_current_slot" class="status-badge done">已生成</span>
          <span v-else class="status-badge idle">待生成</span>
        </div>
        <p class="hint-text">例行荐股由后台计划任务自动生成（工作日午盘 11:35 / 收盘后 15:05），对外页面只读最新结果。</p>
        <div class="ap-status-grid">
          <div class="ap-kv"><div class="ap-k">当前时段</div><div class="ap-v">{{ apStatus.slot_label || '—' }}</div></div>
          <div class="ap-kv"><div class="ap-k">最新生成</div><div class="ap-v">{{ apStatus.generated_at ? fmtTime(apStatus.generated_at) : '—' }}</div></div>
          <div class="ap-kv"><div class="ap-k">荐股数</div><div class="ap-v">{{ apStatus.pick_count ?? '—' }}</div></div>
          <div class="ap-kv"><div class="ap-k">扫描覆盖</div><div class="ap-v">{{ apStatus.kline_cached_codes ?? '—' }} / {{ apStatus.market_codes ?? '—' }}</div></div>
        </div>
        <div class="form-row">
          <select v-model="apStrategy" class="form-select" :disabled="apBusy || apStatus.running" @change="onAiStrategyChange">
            <option v-for="s in apStrategies" :key="s.key" :value="s.key">{{ s.label }}</option>
          </select>
          <button class="btn-primary" @click="refreshAiPicks" :disabled="apBusy || apStatus.running">
            {{ apBusy || apStatus.running ? '生成中…' : '立即重跑' }}
          </button>
        </div>
        <div v-if="apMsg" :class="['form-msg', apMsgType]">{{ apMsg }}</div>
      </div>

      <div class="card no-pad">
        <div class="card-head" style="padding:14px 16px 0">
          <span class="card-title">生成记录</span>
          <span class="card-meta">{{ apStrategyLabel }} · {{ apHistory.length }} 次</span>
        </div>
        <table class="tbl compact" style="margin-top:8px">
          <thead><tr><th>日期</th><th>时段</th><th>策略</th><th class="r">荐股数</th><th>大盘研判</th><th>生成时间</th></tr></thead>
          <tbody>
            <tr v-for="h in apHistory" :key="h.key">
              <td class="mono bold">{{ h.date }}</td>
              <td>{{ h.slot_label }}</td>
              <td><span class="badge">{{ h.strategy_label }}</span></td>
              <td class="r">{{ h.pick_count }}<span v-if="h.no_buy_point" class="noteg">无买点</span></td>
              <td class="muted rs-summary">{{ h.market_summary || '—' }}</td>
              <td class="muted mono text-xs">{{ fmtTime(h.generated_at) }}</td>
            </tr>
            <tr v-if="!apHistory.length && !loading"><td colspan="6" class="empty-state">暂无记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════════ 产业链分析 ═══════════════════════════════ -->
    <div v-if="tab === 'research'" class="content-area">

      <!-- MAP 缓存 -->
      <div class="card" v-if="mapCache.total">
        <div class="card-head">
          <span class="card-title">研报 MAP 缓存 · 模型分布</span>
          <span class="card-meta">{{ mapCache.total }} 篇已抽取
            <button class="icon-btn" @click="loadMapCache" title="刷新">↻</button>
          </span>
        </div>
        <div class="mc-model-list">
          <div v-for="m in mapCache.by_model" :key="m.model" class="mc-model-row">
            <span class="tier-badge" :class="mcTierClass(m.model_tier)">{{ m.model_tier }}</span>
            <span class="model-name">{{ m.model }}</span>
            <div class="model-track"><div class="model-fill" :style="{ width: mcPct(m.count) + '%' }"></div></div>
            <span class="model-cnt">{{ m.count }} 篇</span>
          </div>
        </div>
      </div>

      <!-- 启动分析 -->
      <div class="card">
        <div class="card-head"><span class="card-title">启动产业链研报精读</span></div>
        <p class="hint-text">给分析取个名字、添加一个或多个关键词，<b>所有关键词都会作为检索材料</b>一起精读并汇总成一份命名报告。最多 {{ rsMaxConcurrent }} 个并行；超出会自动排队，跑完一个接着跑下一个。</p>
        <div class="form-row slim">
          <input v-model="rsName" class="form-input" placeholder="分析名称（可选，如 光通信产业链）" :disabled="rsBusy" />
        </div>
        <div class="form-row">
          <input v-model="rsKeyword" class="form-input" placeholder="输入关键词后回车添加，可一次输入多个（逗号/空格分隔）"
                 @keyup.enter="addResearchKw" :disabled="rsBusy" />
          <button class="btn-ghost" @click="addResearchKw" :disabled="rsBusy || !rsKeyword.trim()">添加</button>
        </div>
        <div v-if="rsKwList.length" class="tag-list" style="margin:2px 0 10px">
          <span v-for="k in rsKwList" :key="k" class="kw-tag">
            {{ k }}
            <button class="kw-x" @click="removeResearchKw(k)" :disabled="rsBusy">×</button>
          </span>
        </div>
        <div class="form-row">
          <select v-model.number="rsLimit" class="form-select" :disabled="rsBusy">
            <option :value="0">精读全部</option>
            <option :value="100">最多 100 篇</option>
            <option :value="300">最多 300 篇</option>
            <option :value="500">最多 500 篇</option>
          </select>
          <button class="btn-primary" @click="startResearch" :disabled="rsBusy || (!rsKwList.length && !rsKeyword.trim())">
            {{ rsBusy ? '启动中…' : '开始分析' }}
          </button>
        </div>
        <div v-if="rsMsg" :class="['form-msg', rsMsgType]">{{ rsMsg }}</div>
      </div>

      <!-- 每日定时清单 -->
      <div class="card">
        <div class="card-head">
          <span class="card-title">每日定时清单</span>
          <span class="card-meta">{{ rsDailyKeywords.length }} 个 · 每天到点按顺序连跑</span>
        </div>
        <p class="hint-text">
          <b>默认纳入全部已生成报告</b>，新报告自动加入、按更新时间倒序逐个重跑；可手动新增额外关键词，或把不想每日跑的移出。
          <span v-if="rsExcludedCount">当前已移除 <b>{{ rsExcludedCount }}</b> 个。</span>
        </p>
        <div class="tag-list">
          <span v-for="k in rsDailyKeywords" :key="k.slug" class="kw-tag" :class="{ manual: k.manual }"
                :title="k.manual ? '手动新增' : '来自已生成报告'">
            {{ k.keyword }}
            <button class="kw-x" @click="removeDailyKeyword(k)" title="移出每日定时">×</button>
          </span>
          <span v-if="!rsDailyKeywords.length" class="muted">暂无（生成一份报告后会自动纳入）</span>
        </div>
        <div class="form-row slim">
          <input v-model="rsNewDaily" class="form-input" placeholder="新增每日关键词（尚无报告也可加）"
                 @keyup.enter="addDailyKeyword" :disabled="rsDailyBusy" />
          <button class="btn-primary" @click="addDailyKeyword" :disabled="rsDailyBusy || !rsNewDaily.trim()">
            {{ rsDailyBusy ? '添加中…' : '加入' }}
          </button>
          <button v-if="rsExcludedCount" class="btn-ghost" @click="includeAllDaily" :disabled="rsDailyBusy"
                  title="清空已移除，把全部历史报告重新纳入每日定时">
            一键纳入全部历史
          </button>
        </div>
      </div>

      <!-- 运行中的任务 -->
      <div v-if="rsRunning.length" class="card">
        <div class="card-head"><span class="card-title">正在运行</span><span class="card-meta">{{ rsRunning.length }} / {{ rsMaxConcurrent }} 并行</span></div>
        <div class="job-grid">
          <div v-for="j in rsRunning" :key="j.slug" class="job-card" :class="{ cancelling: isCancelling(j) }">
            <div class="job-top">
              <span class="job-kw">{{ j.keyword }}</span>
              <span class="job-pct">{{ Math.round(j.progress||0) }}%</span>
              <button class="job-cancel" :class="{ force: isCancelling(j) }" @click="cancelResearch(j)">
                {{ isCancelling(j) ? '强制' : '中断' }}
              </button>
            </div>
            <div class="job-bar"><div class="job-fill" :class="{ indet: isCancelling(j) }" :style="{ width:(j.progress||0)+'%' }"></div></div>
            <div class="job-stage-row">
              <span class="job-stage">{{ isCancelling(j) ? '取消中…' : (j.stage||'处理中') }}</span>
              <span v-if="j.started_at" class="chip time" title="已运行时长">🕒 {{ elapsedText(j.started_at) }}</span>
              <span v-if="j.eta_text && !isCancelling(j)" class="chip accent" title="预计剩余">⏳ {{ j.eta_text }}</span>
            </div>
            <div class="job-meta">
              <span v-if="j.report_count" class="chip">研报 {{ j.report_count }} 篇</span>
              <span v-if="j.n_blog" class="chip">机构荐股 {{ j.n_blog }} 篇</span>
              <span v-if="j.pdf_total" class="chip">PDF {{ j.pdf_done||0 }}/{{ j.pdf_total }}</span>
              <span v-if="j.cached_count" class="chip cache">缓存命中 {{ j.cached_count }}</span>
              <span v-if="j.map_total" class="chip">逐篇提取 {{ j.map_done||0 }}/{{ j.map_total }}</span>
              <span v-if="j.read_total" class="chip">精读 {{ j.read_done||0 }}/{{ j.read_total }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 等待队列：手动触发超并发的排队项，跑完一个自动顶上 -->
      <div v-if="rsQueue.length" class="card">
        <div class="card-head"><span class="card-title">等待队列</span><span class="card-meta">{{ rsQueue.length }} 个排队中 · 有空闲名额自动开始</span></div>
        <div class="queue-list">
          <div v-for="(q, i) in rsQueue" :key="q.slug" class="queue-row">
            <span class="queue-pos">{{ q.position }}</span>
            <span class="queue-kw">{{ q.keyword }}<small v-if="q.keywords && q.keywords.length > 1" class="queue-kws"> · {{ q.keywords.join('、') }}</small></span>
            <span class="queue-meta muted">{{ fmtTime(q.enqueued_at) }} 加入</span>
            <div class="queue-acts">
              <button class="ord-btn" title="置顶" :disabled="i === 0" @click="moveResearch(q, 'top')">⇧</button>
              <button class="ord-btn" title="上移" :disabled="i === 0" @click="moveResearch(q, 'up')">↑</button>
              <button class="ord-btn" title="下移" :disabled="i === rsQueue.length - 1" @click="moveResearch(q, 'down')">↓</button>
              <button class="act-btn danger" @click="dequeueResearch(q)">移出</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 已生成报告 -->
      <div class="card no-pad">
        <div class="card-head" style="padding:14px 16px 0">
          <span class="card-title">已生成报告</span>
          <span class="card-meta">{{ rsReports.length }} 份</span>
        </div>
        <table class="tbl compact" style="margin-top:8px">
          <thead><tr><th>关键词</th><th class="r">研报篇数</th><th>摘要</th><th>生成时间</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in rsReports" :key="r.slug" :class="{ 'row-err': r.status==='error' }">
              <td class="bold">{{ r.display_name||r.keyword }}
                <span v-if="r.status==='error'" class="fail-badge">失败</span>
                <span v-if="isDailyKeyword(r.slug)" class="daily-badge">每日</span>
                <div v-if="r.keywords && r.keywords.length > 1" class="rs-kws">{{ r.keywords.join('、') }}</div>
              </td>
              <td class="r">{{ r.report_count }}</td>
              <td class="muted rs-summary">
                <span v-if="r.status==='error'" class="err-text" :title="r.error">{{ r.error||'未知错误' }}</span>
                <span v-else>{{ r.summary||'—' }}</span>
              </td>
              <td class="muted mono text-xs">{{ fmtTime(r.created_at) }}</td>
              <td class="row-actions">
                <button v-if="r.status!=='error'" class="act-btn" @click="viewReport(r)">查看</button>
                <button v-else class="act-btn" @click="retryReport(r)">重试</button>
                <button class="act-btn" :class="{ on: isDailyKeyword(r.slug) }" @click="toggleDailyForReport(r)"
                        :title="isDailyKeyword(r.slug) ? '已纳入每日定时，点此移出' : '加入每日定时'">
                  {{ isDailyKeyword(r.slug) ? '每日 ✓' : '加每日' }}
                </button>
                <button class="act-btn danger" @click="deleteReport(r)">删除</button>
              </td>
            </tr>
            <tr v-if="!rsReports.length&&!loading"><td colspan="5" class="empty-state">暂无报告</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════════ 公众号授权 ══════════════════════════════ -->
    <div v-if="tab === 'fenchuan'" class="content-area">
      <div class="card">
        <div class="card-head">
          <span class="card-title">公众号内容授权（纷传）</span>
          <div class="fc-status-badge" :class="fcStatus.token_set ? 'ok' : 'warn'">
            <span class="fc-dot"></span>{{ fcStatus.token_set ? '已授权' : '未授权' }}
            <span v-if="fcStatus.updated_at" class="muted"> · 上次 {{ fmtTime(fcStatus.updated_at) }}</span>
          </div>
        </div>
        <p class="hint-text">用绑定纷传的微信扫码即可授权，任何管理员扫码全站共享，约 7 天后过期。</p>
        <div class="fc-layout">
          <div class="fc-qr-wrap">
            <div v-if="fcQr" class="fc-qr-box">
              <img :src="fcQr" alt="微信扫码" class="fc-qr-img" :class="{ dim: fcState==='expired' }" />
              <div v-if="fcState==='expired'" class="fc-mask">
                二维码已失效<br/><button class="link-btn" @click="startFcQr">点此刷新</button>
              </div>
              <div v-else-if="fcState==='done'" class="fc-mask done">✅ 授权成功</div>
            </div>
            <div v-else class="fc-placeholder">{{ fcLoadingQr ? '生成中…' : '点右侧获取二维码' }}</div>
          </div>
          <div class="fc-steps">
            <button class="btn-primary" @click="startFcQr" :disabled="fcLoadingQr">
              {{ fcQr ? '刷新二维码' : '获取二维码' }}
            </button>
            <div class="step-list">
              <p class="step">1. 用绑定纷传的微信「扫一扫」</p>
              <p class="step">2. 在手机上点确认登录</p>
              <p class="step">3. 本页显示「授权成功」即可</p>
            </div>
            <p v-if="fcMsg" :class="['form-msg', fcMsgType]">{{ fcMsg }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════════════════ 飞书授权 ════════════════════════════════ -->
    <div v-if="tab === 'feishu'" class="content-area">
      <div class="card">
        <div class="card-head">
          <span class="card-title">飞书群消息授权</span>
          <div class="fc-status-badge" :class="feishuStatus.authed && !feishuStatus.uat_expired ? 'ok' : 'warn'">
            <span class="fc-dot"></span>
            {{ feishuStatus.authed && !feishuStatus.uat_expired ? '已授权' : feishuStatus.authed ? 'Token 已过期' : '未授权' }}
            <span v-if="feishuStatus.user_name" class="muted"> · {{ feishuStatus.user_name }}</span>
          </div>
        </div>
        <!-- 授权模式切换 -->
        <div class="seg-row" style="margin-bottom:12px">
          <button class="seg-btn" :class="{ active: feishuStatus.auth_mode !== 'user' }"
                  @click="setFeishuMode('tenant')" :disabled="feishuModeBusy">应用身份（自动授权）</button>
          <button class="seg-btn" :class="{ active: feishuStatus.auth_mode === 'user' }"
                  @click="setFeishuMode('user')" :disabled="feishuModeBusy">用户 OAuth 授权</button>
        </div>

        <!-- 应用身份：全自动，无需点授权 -->
        <template v-if="feishuStatus.auth_mode !== 'user'">
          <p class="hint-text">应用身份自动授权已开启：以机器人（App）身份直接读取它所在群的消息，<strong>无需任何点击授权</strong>，后台每 30 分钟自动增量抓取。请确保机器人已被拉进目标群并具备消息读取权限。</p>
          <div class="fc-layout">
            <div class="fc-steps" style="flex:1">
              <div class="btn-row">
                <button class="btn-ghost" @click="refreshFeishu" :disabled="feishuRefreshing">
                  {{ feishuRefreshing ? '抓取中…' : '立即抓取' }}
                </button>
              </div>
              <p v-if="feishuMsg" :class="['form-msg', feishuMsgType]" style="margin-top:12px">{{ feishuMsg }}</p>
            </div>
          </div>
        </template>

        <!-- 用户 OAuth：保留作兜底（机器人不在群、读不到时可切回） -->
        <template v-else>
          <p class="hint-text">用你的飞书账号 OAuth 授权，系统将自动拉取你所在全部群的消息（每 30 分钟增量一次）。</p>
          <div class="fc-layout">
            <div class="fc-steps" style="flex:1">
              <div class="step-list" style="margin-bottom:16px">
                <p class="step">1. 点「去飞书授权」，在新窗口完成授权</p>
                <p class="step">2. 授权后飞书跳回本站，此页面刷新即可</p>
                <p class="step">3. 后台每 30 分钟自动增量抓取群消息</p>
              </div>
              <div class="btn-row">
                <button class="btn-primary" @click="openFeishuAuth" :disabled="feishuAuthLoading">
                  {{ feishuAuthLoading ? '获取中…' : '去飞书授权' }}
                </button>
                <button class="btn-ghost" @click="refreshFeishu" :disabled="feishuRefreshing"
                        v-if="feishuStatus.authed">
                  {{ feishuRefreshing ? '抓取中…' : '立即抓取' }}
                </button>
              </div>
              <p v-if="feishuMsg" :class="['form-msg', feishuMsgType]" style="margin-top:12px">{{ feishuMsg }}</p>
            </div>
          </div>
        </template>
        <div class="fc-layout">

          <!-- 状态卡 -->
          <div class="fc-info-box" v-if="feishuStatus.authed">
            <div class="info-row">
              <span class="info-label">消息总数</span>
              <span class="info-val">{{ feishuStatus.count?.toLocaleString() ?? '—' }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">群数量</span>
              <span class="info-val">{{ feishuStatus.last_run?.chats ?? '—' }}</span>
            </div>
            <div class="info-row">
              <span class="info-label">上次抓取</span>
              <span class="info-val">{{ feishuStatus.last_fetch ? fmtTime(feishuStatus.last_fetch) : '—' }}</span>
            </div>
            <div class="info-row" v-if="feishuStatus.last_run?.error">
              <span class="info-label">上次错误</span>
              <span class="info-val warn-text">{{ feishuStatus.last_run.error }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════════════════ Token 用量 ════════════════════════════════ -->
    <div v-if="tab === 'tokens'" class="content-area">
      <!-- 趋势 -->
      <div class="card" v-if="tokenDaily.length">
        <div class="card-head">
          <span class="card-title">每日成本趋势</span>
          <span class="card-meta">近 {{ tokenDaily.length }} 天 · 峰值 {{ fmtUsd(tokenMaxCost) }}</span>
        </div>
        <div class="cost-bars">
          <div v-for="d in tokenDaily" :key="d.day" class="cb-col"
               :title="`${d.day} · ${d.calls}次 · ${fmtUsd(d.cost_usd)}`">
            <div class="cb-bar" :style="{ height: barH(d.cost_usd) + '%' }"></div>
            <span class="cb-x">{{ d.day.slice(5) }}</span>
          </div>
        </div>
      </div>

      <div class="two-col">
        <div class="card no-pad">
          <div class="card-head" style="padding:14px 16px 0"><span class="card-title">按账号</span></div>
          <table class="tbl compact" style="margin-top:8px">
            <thead><tr><th>账号</th><th class="r">次数</th><th class="r">入</th><th class="r">出</th><th class="r">费用</th></tr></thead>
            <tbody>
              <tr v-for="(v,k) in tokens.by_user" :key="k">
                <td class="bold">{{ k }}</td><td class="r">{{ v.calls }}</td>
                <td class="r">{{ fmtK(v.input_tokens) }}</td><td class="r">{{ fmtK(v.output_tokens) }}</td>
                <td class="r">{{ fmtUsd(v.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="card no-pad">
          <div class="card-head" style="padding:14px 16px 0"><span class="card-title">按功能</span></div>
          <table class="tbl compact" style="margin-top:8px">
            <thead><tr><th>功能</th><th class="r">次数</th><th class="r">入</th><th class="r">出</th><th class="r">费用</th></tr></thead>
            <tbody>
              <tr v-for="(v,k) in tokens.by_caller" :key="k">
                <td class="bold">{{ k }}</td><td class="r">{{ v.calls }}</td>
                <td class="r">{{ fmtK(v.input_tokens) }}</td><td class="r">{{ fmtK(v.output_tokens) }}</td>
                <td class="r">{{ fmtUsd(v.cost_usd) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card no-pad">
        <div class="card-head" style="padding:14px 16px 0"><span class="card-title">按模型</span></div>
        <table class="tbl compact" style="margin-top:8px">
          <thead><tr><th>模型</th><th class="r">次数</th><th class="r">入</th><th class="r">出</th><th class="r">费用</th></tr></thead>
          <tbody>
            <tr v-for="(v,k) in tokens.by_model" :key="k">
              <td class="bold mono">{{ k }}</td><td class="r">{{ v.calls }}</td>
              <td class="r">{{ fmtK(v.input_tokens) }}</td><td class="r">{{ fmtK(v.output_tokens) }}</td>
              <td class="r">{{ fmtUsd(v.cost_usd) }}</td>
            </tr>
            <tr v-if="!Object.keys(tokens.by_model||{}).length"><td colspan="5" class="empty-state">暂无记录</td></tr>
          </tbody>
        </table>
      </div>

      <div class="card no-pad">
        <div class="card-head" style="padding:14px 16px 0"><span class="card-title">最近调用</span></div>
        <table class="tbl compact" style="margin-top:8px">
          <thead><tr><th>时间</th><th>账号</th><th>功能</th><th>模型</th><th class="r">入</th><th class="r">出</th><th class="r">费用</th></tr></thead>
          <tbody>
            <tr v-for="(c,i) in tokens.recent_calls" :key="i">
              <td class="muted mono text-xs">{{ fmtTime(c.ts) }}</td>
              <td>{{ c.user||'—' }}</td><td>{{ c.caller }}</td><td class="muted">{{ c.model }}</td>
              <td class="r">{{ c.input_tokens }}</td><td class="r">{{ c.output_tokens }}</td>
              <td class="r">{{ fmtUsd(c.cost_usd) }}</td>
            </tr>
            <tr v-if="!tokens.recent_calls?.length&&!loading"><td colspan="7" class="empty-state">暂无调用记录</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════════════════ LLM 配置 ════════════════════════════════ -->
    <div v-if="tab === 'llm'" class="content-area llm-wrap">
      <LlmStatsView :config-only="true" />
    </div>

    <!-- ══════ 弹层：自选股 ══════════════════════════════════════════ -->
    <div v-if="wlModal" class="overlay" @click.self="wlModal = null">
      <div class="modal">
        <div class="modal-hdr">
          <div><div class="modal-ttl">{{ wlModal.user.username }} 的自选股</div>
            <div class="modal-sub">{{ wlModal.count }} 只</div></div>
          <button class="modal-x" @click="wlModal = null">×</button>
        </div>
        <div class="modal-body">
          <table class="tbl compact">
            <thead><tr><th>代码</th><th>名称</th><th>标签</th><th>备注</th><th>加入时间</th></tr></thead>
            <tbody>
              <tr v-for="it in wlModal.items" :key="it.code">
                <td class="mono bold">{{ it.code }}</td><td>{{ it.name }}</td>
                <td><span v-for="t in it.tags" :key="t" class="tag">{{ t }}</span></td>
                <td class="muted">{{ it.notes||'—' }}</td>
                <td class="muted mono text-xs">{{ fmtDate(it.added_at) }}</td>
              </tr>
              <tr v-if="!wlModal.items.length"><td colspan="5" class="empty-state">暂无自选股</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ══════ 弹层：对话内容 ════════════════════════════════════════ -->
    <div v-if="chatModal" class="overlay" @click.self="chatModal = null">
      <div class="modal modal-wide">
        <div class="modal-hdr">
          <div><div class="modal-ttl">{{ chatModal.session.title }}</div>
            <div class="modal-sub">{{ chatModal.session.username||'匿名' }} · {{ chatModal.session.message_count }} 条 · {{ fmtTime(chatModal.session.last_ts) }}</div>
          </div>
          <button class="modal-x" @click="chatModal = null">×</button>
        </div>
        <div class="modal-body chat-body">
          <div v-if="chatModal.loading" class="empty-state">加载中…</div>
          <div v-else-if="chatModal.err" class="empty-state">加载失败：{{ chatModal.err }}</div>
          <template v-else>
            <div v-for="(m,i) in chatModal.messages" :key="i" :class="['chat-msg', m.role]">
              <div class="chat-role">{{ m.role==='user'?'用户':'AI' }}<span class="chat-ts">{{ fmtTime(m.ts) }}</span></div>
              <div class="chat-bubble">{{ m.content }}</div>
            </div>
            <div v-if="!chatModal.messages.length" class="empty-state">该会话无消息</div>
          </template>
        </div>
      </div>
    </div>

    <div v-if="error" class="err-banner">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { fmtK, fmtDate, fmtTime, fmtUsd, sparkline } from '../utils/adminFormat'
import { useResearch } from '../composables/useResearch'
import { useAiPicks } from '../composables/useAiPicks'
import { useFenchuan } from '../composables/useFenchuan'
import { useAuthStore } from '../stores/auth'
import LlmStatsView from './LlmStatsView.vue'

const router = useRouter()
const auth = useAuthStore()
const myUsername = computed(() => auth.user?.username || '')
const isSuper = computed(() => !!auth.user?.is_super)

// 飞书授权状态（提前声明，tabs 需据 auth_mode 决定是否展示「飞书授权」tab）
const feishuStatus = ref({ authed: false, uat_expired: true, auth_mode: 'tenant', user_name: '', count: 0, last_fetch: null, last_run: {} })

const tabs = computed(() => [
  { key: 'activity', label: '活跃统计' },
  { key: 'users', label: '用户与自选' },
  ...(isSuper.value ? [{ key: 'admins', label: '管理员' }] : []),
  { key: 'chats', label: 'AI 对话' },
  { key: 'aipicks', label: 'AI 荐股' },
  { key: 'research', label: '产业链分析' },
  { key: 'fenchuan', label: '公众号授权' },
  // 应用身份自动授权时无需手动授权，不展示该 tab；仅用户 OAuth 模式才显示
  ...(feishuStatus.value.auth_mode === 'user' ? [{ key: 'feishu', label: '飞书授权' }] : []),
  { key: 'tokens', label: 'Token 用量' },
  { key: 'llm', label: 'LLM 配置' },
])
const _tabKeys = ['activity', 'users', 'admins', 'chats', 'aipicks', 'research', 'fenchuan', 'feishu', 'tokens', 'llm']
const tab = ref(_tabKeys.includes(router.currentRoute.value.query.tab)
  ? router.currentRoute.value.query.tab : 'activity')

const overview = ref({})
const users = ref([])
const tokens = ref({ by_user: {}, by_caller: {}, by_model: {}, daily_series: [], recent_calls: [] })
const activity = ref({ active: {}, dau_series: [], by_feature: [], retention: [] })
const chatSessions = ref([])
const chatFilterUser = ref('')
const wlModal = ref(null)
const chatModal = ref(null)
const loading = ref(false)
const error = ref('')
const onlineUsers = ref([])
const queryDist = ref({ window_days: 7, hourly: [], volume: {}, by_feature: [] })
const queryDays = ref(7)

const {
  keyword: rsKeyword, name: rsName, kwList: rsKwList,
  limit: rsLimit, busy: rsBusy, msg: rsMsg, msgType: rsMsgType,
  running: rsRunning, queue: rsQueue, reports: rsReports, maxConcurrent: rsMaxConcurrent,
  dailyKeywords: rsDailyKeywords, excludedCount: rsExcludedCount, newDaily: rsNewDaily, dailyBusy: rsDailyBusy,
  cancelling: rsCancelling,
  init: initResearch, addKeyword: addResearchKw, removeKeyword: removeResearchKw,
  addDailyKeyword, isDailyKeyword, removeDailyKeyword, includeAllDaily, toggleDailyForReport,
  start: startResearch, viewReport, deleteReport, retryReport, cancel: cancelResearch,
  dequeue: dequeueResearch, moveQueue: moveResearch,
} = useResearch()

function isCancelling(j) {
  return !!rsCancelling.value[j.slug] || (j.stage && j.stage.includes('取消'))
}

// 「已用时」计时器：每秒走一格，据 started_at 计算运行时长（mm:ss / h时mm分）
const nowTs = ref(Date.now())
let _elapsedTimer = null
onMounted(() => { _elapsedTimer = setInterval(() => { nowTs.value = Date.now() }, 1000) })
onUnmounted(() => { if (_elapsedTimer) clearInterval(_elapsedTimer) })

function elapsedText(startedAt) {
  if (!startedAt) return ''
  const t = new Date(startedAt).getTime()
  if (!t) return ''
  let s = Math.max(0, Math.floor((nowTs.value - t) / 1000))
  const h = Math.floor(s / 3600); s -= h * 3600
  const m = Math.floor(s / 60); s -= m * 60
  const pad = n => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

const {
  status: apStatus, strategy: apStrategy, strategies: apStrategies, history: apHistory, busy: apBusy,
  msg: apMsg, msgType: apMsgType, strategyLabel: apStrategyLabel,
  init: initAiPicks, onStrategyChange: onAiStrategyChange, refresh: refreshAiPicks,
} = useAiPicks()

const {
  status: fcStatus, qr: fcQr, state: fcState, loadingQr: fcLoadingQr,
  msg: fcMsg, msgType: fcMsgType, loadStatus: loadFcStatus, startQr: startFcQr,
} = useFenchuan()

// ── 飞书授权 ──────────────────────────────────────────────────────────────────
// feishuStatus 已在 tabs 之前声明
const feishuAuthLoading = ref(false)
const feishuRefreshing = ref(false)
const feishuModeBusy = ref(false)
const feishuMsg = ref('')
const feishuMsgType = ref('')

async function setFeishuMode(mode) {
  if (feishuModeBusy.value || feishuStatus.value.auth_mode === mode) return
  feishuModeBusy.value = true
  feishuMsg.value = ''
  try {
    await axios.put('/api/feishu/config', { auth_mode: mode })
    await loadFeishuStatus()
    feishuMsg.value = mode === 'tenant'
      ? '已切到应用身份自动授权，无需点击，后台会自动抓取'
      : '已切到用户 OAuth 授权，请点「去飞书授权」'
    feishuMsgType.value = 'ok'
  } catch (e) {
    feishuMsg.value = '切换失败：' + (e.response?.data?.detail || e.message)
    feishuMsgType.value = 'err'
  } finally {
    feishuModeBusy.value = false
  }
}

async function loadFeishuStatus() {
  try {
    const { data } = await axios.get('/api/feishu/status')
    feishuStatus.value = data
  } catch (e) { /* 静默 */ }
}

async function openFeishuAuth() {
  feishuAuthLoading.value = true
  feishuMsg.value = ''
  try {
    const { data } = await axios.get('/api/feishu/auth-url')
    window.open(data.url, '_blank', 'width=800,height=600')
    feishuMsg.value = '已打开飞书授权窗口，完成授权后点「立即抓取」或刷新页面'
    feishuMsgType.value = 'ok'
  } catch (e) {
    feishuMsg.value = '获取授权链接失败：' + (e.response?.data?.detail || e.message)
    feishuMsgType.value = 'err'
  } finally {
    feishuAuthLoading.value = false
  }
}

async function refreshFeishu() {
  feishuRefreshing.value = true
  feishuMsg.value = ''
  try {
    const { data } = await axios.post('/api/feishu/refresh')
    feishuStatus.value = { ...feishuStatus.value, ...data }
    feishuMsg.value = data.ok
      ? `✅ 抓取完成，新增 ${data.added} 条消息`
      : `⚠️ ${data.error || '抓取失败'}`
    feishuMsgType.value = data.ok ? 'ok' : 'err'
    await loadFeishuStatus()
  } catch (e) {
    feishuMsg.value = e.response?.status === 401
      ? '未授权，请先完成飞书授权'
      : '抓取失败：' + (e.response?.data?.detail || e.message)
    feishuMsgType.value = 'err'
  } finally {
    feishuRefreshing.value = false
  }
}

// ── 概览派生 ──────────────────────────────────────────────────────────────────
const deltaText = computed(() => {
  const d = overview.value.dau_delta
  if (d == null) return ''
  if (d > 0) return `↑ ${d}`
  if (d < 0) return `↓ ${-d}`
  return '持平'
})
const deltaClass = computed(() => {
  const d = overview.value.dau_delta || 0
  return d > 0 ? 'up' : d < 0 ? 'down' : 'flat'
})
const costSpark = computed(() =>
  sparkline((overview.value.cost_series || []).map(d => d.cost_usd), 120, 24)
)

// ── 用户表 ────────────────────────────────────────────────────────────────────
const userQuery = ref('')
const userFilter = ref('all')  // all | online | today
const userSort = ref({ key: '', dir: 'desc' })

function sortUsers(key) {
  if (userSort.value.key === key) {
    userSort.value = { key, dir: userSort.value.dir === 'asc' ? 'desc' : 'asc' }
  } else {
    userSort.value = { key, dir: 'desc' }
  }
}
function thCls(key, num = false) {
  return ['sortable', { r: num, sorted: userSort.value.key === key }]
}
function sortInd(key) {
  if (userSort.value.key !== key) return ''
  return userSort.value.dir === 'asc' ? ' ▲' : ' ▼'
}

const _userVal = {
  username:  u => u.username || '',
  last_seen: u => u.activity?.last_seen || '',
  days_30:   u => u.activity?.days_30 || 0,
  watchlist: u => u.watchlist_count || 0,
  calls:     u => u.tokens?.calls || 0,
  cost:      u => u.tokens?.cost_usd || 0,
  created:   u => u.created_at || '',
}
const displayUsers = computed(() => {
  const q = userQuery.value.trim().toLowerCase()
  let arr = users.value
  if (q) arr = arr.filter(u => (u.username||'').toLowerCase().includes(q) || (u.email||'').toLowerCase().includes(q))
  if (userFilter.value === 'online') arr = arr.filter(u => isOnline(u.username))
  if (userFilter.value === 'today') arr = arr.filter(u => u.activity?.active_today || isOnline(u.username))
  const { key, dir } = userSort.value
  if (key && _userVal[key]) {
    const get = _userVal[key]
    arr = [...arr].sort((a, b) => {
      const av = get(a), bv = get(b)
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
      return dir === 'asc' ? cmp : -cmp
    })
  }
  return arr
})

// ── 活跃统计 ──────────────────────────────────────────────────────────────────
const actDays = ref(30)
const dauW = 600, dauH = 100

const dauChart = computed(() => {
  const s = activity.value.dau_series || []
  if (!s.length) return { pts: '', area: '', max: 0 }
  const max = Math.max(1, ...s.map(d => d.users))
  const n = s.length
  const x = i => (n === 1 ? dauW / 2 : (i / (n - 1)) * dauW)
  const y = v => dauH - 4 - (v / max) * (dauH - 8)
  const pts = s.map((d, i) => `${x(i).toFixed(1)},${y(d.users).toFixed(1)}`).join(' ')
  const area = `0,${dauH} ` + pts + ` ${dauW},${dauH}`
  return { pts, area, max }
})

const retentionRows = computed(() => [...(activity.value.retention || [])].reverse())
const _maxFeature = computed(() => Math.max(1, ...(activity.value.by_feature || []).map(f => f.events)))
function heatPct(v) { return Math.max(2, (v / _maxFeature.value) * 100) }

async function setActDays(d) {
  actDays.value = d
  try {
    const { data } = await axios.get('/api/admin/activity', { params: { days: d } })
    activity.value = data
  } catch (e) { /* 静默 */ }
}

// ── 在线状态 ──────────────────────────────────────────────────────────────────
const _onlineSet = computed(() => new Set(onlineUsers.value.map(u => u.username)))
function isOnline(username) { return _onlineSet.value.has(username) }

async function loadOnlineUsers() {
  try {
    const { data } = await axios.get('/api/admin/presence')
    onlineUsers.value = data.online || []
  } catch (e) { /* 静默 */ }
}

// ── 查询分布 ──────────────────────────────────────────────────────────────────
const peakHour = computed(() => {
  const h = queryDist.value.hourly || []
  if (!h.length) return 0
  let best = h[0]; h.forEach(x => { if (x.events > best.events) best = x })
  return best.hour
})
const peakHourEvents = computed(() => {
  const h = queryDist.value.hourly || []
  return h.find(x => x.hour === peakHour.value)?.events || 0
})
const _maxHour = computed(() => Math.max(1, ...(queryDist.value.hourly || []).map(h => h.events)))
function hourBarH(v) { return Math.max(2, (v / _maxHour.value) * 100) }

async function setQueryDays(d) {
  queryDays.value = d
  try {
    const { data } = await axios.get('/api/admin/query-distribution', { params: { days: d } })
    queryDist.value = data
  } catch (e) { /* 静默 */ }
}

// ── Token 趋势 ────────────────────────────────────────────────────────────────
const tokenDaily = computed(() => (tokens.value.daily_series || []).slice(-14))
const tokenMaxCost = computed(() => Math.max(0, ...tokenDaily.value.map(d => d.cost_usd || 0)))
function barH(c) {
  const max = tokenMaxCost.value
  if (!max) return 2
  return Math.max(2, (c / max) * 100)
}

// ── 研报 MAP 缓存 ─────────────────────────────────────────────────────────────
const mapCache = ref({ total: 0, by_model: [] })
async function loadMapCache() {
  try {
    const { data } = await axios.get('/api/research/map-cache-stats')
    mapCache.value = data || { total: 0, by_model: [] }
  } catch (e) { /* 静默 */ }
}
function mcPct(c) {
  const max = Math.max(1, ...(mapCache.value.by_model || []).map(m => m.count))
  return Math.max(3, (c / max) * 100)
}
function mcTierClass(t) { return t >= 100 ? 'hi' : t >= 60 ? 'mid' : 'lo' }

// ── 核心加载 ──────────────────────────────────────────────────────────────────
async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [ov, us, tk, ac, ch, pres, qd] = await Promise.all([
      axios.get('/api/admin/overview'),
      axios.get('/api/admin/users'),
      axios.get('/api/admin/tokens'),
      axios.get('/api/admin/activity', { params: { days: actDays.value } }),
      axios.get('/api/admin/chats'),
      axios.get('/api/admin/presence'),
      axios.get('/api/admin/query-distribution', { params: { days: queryDays.value } }),
    ])
    overview.value = ov.data
    users.value = us.data.users
    tokens.value = tk.data
    activity.value = ac.data
    chatSessions.value = ch.data.sessions || []
    onlineUsers.value = pres.data.online || []
    queryDist.value = qd.data
  } catch (e) {
    error.value = e.response?.status === 403
      ? '无权访问：仅管理员可查看后台。'
      : ('加载失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

// ── 管理员配置 ────────────────────────────────────────────────────────────────
const adminBusyId = ref('')
const adminList = ref([])
const newAdmin = ref('')
const adminCfgBusy = ref(false)
const adminCfgMsg = ref('')
const adminCfgMsgType = ref('ok')

async function loadAdmins() {
  try {
    const { data } = await axios.get('/api/admin/admins')
    adminList.value = data.admins || []
    if (overview.value.admin_count != null) overview.value.admin_count = adminList.value.length
  } catch (e) { /* 静默 */ }
}

async function addAdmin() {
  const name = newAdmin.value.trim()
  if (!name) return
  adminCfgBusy.value = true; adminCfgMsg.value = ''
  try {
    const { data } = await axios.post('/api/admin/admins', { username: name })
    adminList.value = data.admins || []
    if (overview.value.admin_count != null) overview.value.admin_count = adminList.value.length
    newAdmin.value = ''
    adminCfgMsg.value = `已将「${name}」设为管理员`; adminCfgMsgType.value = 'ok'
  } catch (e) {
    adminCfgMsg.value = '添加失败：' + (e.response?.data?.detail || e.message)
    adminCfgMsgType.value = 'err'
  } finally { adminCfgBusy.value = false }
}

async function removeAdmin(a) {
  if (!confirm(`确定撤销「${a.username}」的管理员权限吗？`)) return
  adminCfgBusy.value = true; adminCfgMsg.value = ''
  try {
    const { data } = await axios.delete(`/api/admin/admins/${encodeURIComponent(a.username)}`)
    adminList.value = data.admins || []
    if (overview.value.admin_count != null) overview.value.admin_count = adminList.value.length
    adminCfgMsg.value = `已撤销「${a.username}」的管理员权限`; adminCfgMsgType.value = 'ok'
  } catch (e) {
    adminCfgMsg.value = '撤销失败：' + (e.response?.data?.detail || e.message)
    adminCfgMsgType.value = 'err'
  } finally { adminCfgBusy.value = false }
}

async function toggleAdmin(u, makeAdmin) {
  const verb = makeAdmin ? '设为管理员' : '取消其管理员'
  if (!confirm(`确定要将「${u.username}」${verb}吗？`)) return
  adminBusyId.value = u.id
  error.value = ''
  try {
    const { data } = await axios.post(`/api/admin/users/${u.id}/admin`, { is_admin: makeAdmin })
    Object.assign(u, data.user)
    await loadAdmins()
  } catch (e) {
    error.value = '操作失败：' + (e.response?.data?.detail || e.message)
  } finally { adminBusyId.value = '' }
}

async function openWatchlist(u) {
  try {
    const { data } = await axios.get(`/api/admin/users/${u.id}/watchlist`)
    wlModal.value = data
  } catch (e) {
    error.value = '加载自选股失败：' + (e.response?.data?.detail || e.message)
  }
}

async function openUserChats(u) {
  try {
    const { data } = await axios.get(`/api/admin/users/${u.id}/chats`)
    chatSessions.value = data.sessions || []
    chatFilterUser.value = u.username
    tab.value = 'chats'
  } catch (e) {
    error.value = '加载对话失败：' + (e.response?.data?.detail || e.message)
  }
}

async function openChat(s) {
  chatModal.value = { session: s, messages: [], loading: true }
  try {
    const { data } = await axios.get(`/api/admin/chats/${s.session_id}`)
    chatModal.value = { session: s, messages: data.messages || [], loading: false }
  } catch (e) {
    chatModal.value = { session: s, messages: [], loading: false,
      err: e.response?.data?.detail || e.message }
  }
}

async function clearChatFilter() {
  chatFilterUser.value = ''
  try {
    const { data } = await axios.get('/api/admin/chats')
    chatSessions.value = data.sessions || []
  } catch (e) { /* 静默 */ }
}

let _presenceTimer = null
onMounted(() => {
  loadAll()
  loadMapCache()
  initResearch()
  initAiPicks()
  loadFcStatus()
  loadFeishuStatus()
  if (isSuper.value) loadAdmins()
  _presenceTimer = setInterval(loadOnlineUsers, 30_000)
})
onUnmounted(() => {
  if (_presenceTimer) clearInterval(_presenceTimer)
})
</script>

<style scoped>
/* ── 基础布局 ───────────────────────────────────────────────────────── */
.admin-view {
  padding: 20px 24px 40px;
  max-width: 1360px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ── 页头 ──────────────────────────────────────────────────────────── */
.page-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-1);
  margin: 0;
  line-height: 1.2;
}
.page-date {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 2px;
}
.hdr-refresh {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-2);
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.hdr-refresh:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-1); }
.hdr-refresh:disabled { opacity: .55; cursor: default; }
.ri { flex-shrink: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin .8s linear infinite; }

/* ── 指标卡 ────────────────────────────────────────────────────────── */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 10px;
}
.mc {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 14px;
  position: relative;
  overflow: hidden;
  transition: box-shadow .15s;
}
.mc:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); }
.mc-accent { border-color: var(--accent); }
.mc-accent .mc-val { color: var(--accent); }
.mc-online { border-color: #16a34a33; }
.mc-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}
.mc-blue   { background: rgba(59,130,246,0.12);  color: #3b82f6; }
.mc-green  { background: rgba(34,197,94,0.12);   color: #22c55e; }
.mc-emerald{ background: rgba(16,185,129,0.12);  color: #10b981; }
.mc-purple { background: rgba(139,92,246,0.12);  color: #8b5cf6; }
.mc-orange { background: rgba(249,115,22,0.12);  color: #f97316; }
.mc-cyan   { background: rgba(6,182,212,0.12);   color: #06b6d4; }
.mc-red    { background: rgba(239,68,68,0.12);   color: #ef4444; }
.mc-body { flex: 1; min-width: 0; }
.mc-label {
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.04em;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 3px;
}
.mc-val { font-size: 22px; font-weight: 700; color: var(--text-1); line-height: 1.1; margin-bottom: 3px; }
.mc-sub { font-size: 11px; color: var(--text-3); }
.mc-spark { width: 100%; height: 24px; display: block; margin-top: 6px; }
.spark-line { fill: none; stroke: var(--accent); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.spark-area { fill: var(--accent); opacity: .12; stroke: none; }
.delta { font-size: 10px; font-weight: 600; padding: 1px 5px; border-radius: 6px; }
.delta.up   { color: #16a34a; background: rgba(22,163,74,.12); }
.delta.down { color: #dc2626; background: rgba(220,38,38,.12); }
.delta.flat { color: var(--text-3); background: var(--bg-hover); }
.mc-online-names { display: flex; flex-wrap: wrap; gap: 3px 8px; margin-top: 4px; }
.online-pip {
  font-size: 11px;
  color: #16a34a;
  background: rgba(22,163,74,.1);
  border-radius: 4px;
  padding: 1px 5px;
}

/* ── Tab 导航 ──────────────────────────────────────────────────────── */
.tab-nav {
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-base, var(--bg-surface));
  margin: 0 -24px;
  padding: 0 24px;
}
.tab-nav-scroll {
  display: flex;
  gap: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.tab-nav-scroll::-webkit-scrollbar { display: none; }
.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border: none;
  background: none;
  color: var(--text-3);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all .15s;
}
.tab-btn:hover { color: var(--text-1); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
.tab-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(22,163,74,.15);
  color: #16a34a;
  font-weight: 600;
}

/* ── 内容区 ────────────────────────────────────────────────────────── */
.content-area {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ── 卡片 ──────────────────────────────────────────────────────────── */
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  overflow: hidden;
}
.card.no-pad { padding: 0; }
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 8px;
  flex-wrap: wrap;
}
.card-title { font-size: 13px; font-weight: 600; color: var(--text-1); }
.card-meta  { font-size: 12px; color: var(--text-3); }

/* ── 两列布局 ──────────────────────────────────────────────────────── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }

/* ── 图表 ──────────────────────────────────────────────────────────── */
.chart-card { }
.dau-svg { width: 100%; height: 100px; display: block; }
.dau-line { fill: none; stroke: var(--accent); stroke-width: 2; vector-effect: non-scaling-stroke; }
.dau-area { stroke: none; }
.chart-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-3);
  margin-top: 4px;
  font-family: var(--font-mono);
}
.chart-peak { color: var(--text-2); }
.chart-empty { height: 100px; display: flex; align-items: center; justify-content: center; color: var(--text-3); font-size: 13px; }

/* 查询量级 */
.vol-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.vol-item { background: var(--bg-hover); border-radius: 8px; padding: 10px 12px; }
.vol-label { font-size: 11px; color: var(--text-3); letter-spacing: .03em; }
.vol-val { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 2px 0; }
.vol-sub { font-size: 11px; color: var(--text-3); }
.vol-up .vol-val { color: #16a34a; }
.vol-down .vol-val { color: #dc2626; }

/* 小时分布 */
.hour-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 80px;
  border-bottom: 1px solid var(--border);
  padding-top: 6px;
}
.hc-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.hc-bar { width: 72%; min-height: 2px; background: var(--accent); opacity: .55; border-radius: 2px 2px 0 0; transition: height .3s; }
.hc-bar.peak { opacity: 1; background: #f59e0b; }
.hc-col:hover .hc-bar { opacity: 1; }
.hc-x { font-size: 9px; color: var(--text-3); margin-top: 3px; font-family: var(--font-mono); }

/* 功能热度 */
.heat-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.heat-name { width: 60px; font-size: 12px; color: var(--text-2); flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.heat-track { flex: 1; background: var(--bg-hover); border-radius: 3px; height: 14px; overflow: hidden; }
.heat-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .3s; opacity: .75; }
.heat-num { width: 80px; text-align: right; font-size: 12px; color: var(--text-1); font-variant-numeric: tabular-nums; flex-shrink: 0; }
.heat-u { color: var(--text-3); margin-left: 4px; }

/* 分段选择器 */
.seg-group { display: flex; gap: 3px; }
.seg {
  padding: 3px 10px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-3);
  border-radius: 12px;
  font-size: 11px;
  cursor: pointer;
  transition: all .12s;
}
.seg.active { background: var(--accent); color: #fff; border-color: var(--accent); }

/* ── 表格 ──────────────────────────────────────────────────────────── */
.tbl-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th {
  text-align: left;
  padding: 9px 12px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  background: var(--bg-hover);
  position: sticky;
  top: 0;
}
.tbl th.sortable { cursor: pointer; user-select: none; }
.tbl th.sortable:hover { color: var(--text-1); }
.tbl th.sorted { color: var(--accent); }
.tbl td { padding: 9px 12px; border-bottom: 1px solid var(--border); color: var(--text-2); vertical-align: middle; }
.tbl.compact th, .tbl.compact td { padding: 6px 12px; }
.tbl tbody tr:hover { background: var(--bg-hover); }
.tbl .r { text-align: right; font-variant-numeric: tabular-nums; }
.bold { color: var(--text-1); font-weight: 600; }
.muted { color: var(--text-3); }
.mono { font-family: var(--font-mono); }
.text-xs { font-size: 12px; }

/* ── 工具栏 ─────────────────────────────────────────────────────────── */
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.search-box {
  flex: 0 0 220px;
  padding: 6px 10px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--bg-base, var(--bg-hover));
  color: var(--text-1);
}
.search-box:focus { outline: none; border-color: var(--accent); }
.filter-pills { display: flex; gap: 6px; }
.pill {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-3);
  border-radius: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 5px;
  transition: all .12s;
}
.pill:hover { color: var(--text-1); }
.pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.pill-dot { width: 6px; height: 6px; border-radius: 50%; background: #16a34a; }
.toolbar-count { font-size: 12px; color: var(--text-3); margin-left: auto; }

/* ── 用户行 ─────────────────────────────────────────────────────────── */
.user-cell { display: flex; align-items: center; gap: 7px; }
.user-email { font-size: 11px; color: var(--text-3); margin-top: 1px; }
.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #16a34a; flex-shrink: 0;
  box-shadow: 0 0 0 2px rgba(22,163,74,.25);
  animation: livepulse 2s ease-in-out infinite;
}
@keyframes livepulse { 0%,100% { box-shadow: 0 0 0 2px rgba(22,163,74,.25); } 50% { box-shadow: 0 0 0 4px rgba(22,163,74,.1); } }
.row-online td:first-child { position: relative; }
.status-online { color: #16a34a; font-size: 12px; font-weight: 600; }
.status-today  { color: #4ade80; font-size: 12px; }

/* ── 徽章 ───────────────────────────────────────────────────────────── */
.badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 8px;
  background: var(--bg-hover);
  color: var(--text-3);
  border: 1px solid var(--border);
  white-space: nowrap;
}
.badge.admin { background: rgba(225,29,42,.1); color: #e11d2a; border-color: rgba(225,29,42,.25); }
.badge.super { background: rgba(139,92,246,.12); color: #8b5cf6; border-color: rgba(139,92,246,.3); }

/* ── 操作按钮 ───────────────────────────────────────────────────────── */
.row-actions { display: flex; gap: 8px; white-space: nowrap; }
.act-btn {
  padding: 3px 8px;
  font-size: 12px;
  border: 1px solid var(--border);
  background: var(--bg-hover);
  color: var(--accent);
  border-radius: 6px;
  cursor: pointer;
  transition: all .12s;
}
.act-btn:hover:not(:disabled) { background: var(--accent); color: #fff; border-color: var(--accent); }
.act-btn:disabled { opacity: .45; cursor: default; color: var(--text-3); }
.act-btn.muted { color: var(--text-3); }
.act-btn.on { background: rgba(59,130,246,.12); color: var(--accent); border-color: var(--accent); font-weight: 600; }
.act-btn.danger { color: #dc2626; }
.act-btn.danger:hover:not(:disabled) { background: #dc2626; border-color: #dc2626; color: #fff; }
.link-btn { background: none; border: none; color: var(--accent); cursor: pointer; font-size: 13px; padding: 0; }
.link-btn:hover { text-decoration: underline; }

/* ── 表单 ───────────────────────────────────────────────────────────── */
.form-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
.form-row.slim { max-width: 440px; }
.form-input {
  flex: 1;
  min-width: 160px;
  padding: 8px 12px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-hover);
  color: var(--text-1);
}
.form-input:focus { outline: none; border-color: var(--accent); }
.form-select {
  padding: 8px 10px;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-hover);
  color: var(--text-1);
  cursor: pointer;
}
.btn-primary {
  padding: 8px 18px;
  font-size: 13px;
  font-weight: 600;
  border: none;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
  white-space: nowrap;
  transition: opacity .12s;
}
.btn-primary:disabled { opacity: .55; cursor: default; }
.btn-ghost {
  padding: 8px 18px; font-size: 13px; font-weight: 600; border-radius: 8px;
  background: transparent; border: 1.5px solid var(--border); color: var(--text-2);
  cursor: pointer; white-space: nowrap; transition: border-color .12s, color .12s;
}
.btn-ghost:hover { border-color: var(--accent); color: var(--accent); }
.btn-ghost:disabled { opacity: .55; cursor: default; }
.btn-row { display: flex; gap: 10px; flex-wrap: wrap; }
.seg-row { display: inline-flex; gap: 0; border: 1.5px solid var(--border); border-radius: 8px; overflow: hidden; flex-wrap: wrap; }
.seg-btn {
  padding: 7px 14px; font-size: 13px; font-weight: 600; border: none;
  background: transparent; color: var(--text-2); cursor: pointer; transition: background .12s, color .12s;
}
.seg-btn + .seg-btn { border-left: 1.5px solid var(--border); }
.seg-btn.active { background: var(--accent); color: #fff; }
.seg-btn:disabled { opacity: .55; cursor: default; }
.fc-info-box {
  min-width: 200px; background: var(--bg-2); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;
}
.info-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.info-label { font-size: 12px; color: var(--text-3); }
.info-val { font-size: 13px; font-weight: 600; color: var(--text-1); }
.warn-text { color: #dc2626 !important; font-weight: 400 !important; font-size: 12px !important; }
.form-msg { margin-top: 10px; font-size: 13px; padding: 7px 12px; border-radius: 7px; }
.form-msg.ok  { background: rgba(22,163,74,.1); color: #16a34a; }
.form-msg.err { background: rgba(239,68,68,.1); color: #dc2626; }
.hint-text { font-size: 12px; color: var(--text-3); line-height: 1.6; margin: 0 0 4px; }

/* ── 标签 ───────────────────────────────────────────────────────────── */
.tag { display: inline-block; font-size: 11px; padding: 1px 6px; margin-right: 3px; background: rgba(37,99,235,.1); color: var(--accent); border-radius: 6px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }
.kw-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px 4px 10px;
  font-size: 13px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 14px;
}
.kw-tag.manual { border-color: var(--accent); background: rgba(59,130,246,.08); }
.kw-tag.manual::before { content: '＋'; font-size: 11px; color: var(--accent); margin-right: 1px; }
.kw-x { border: none; background: none; cursor: pointer; color: var(--text-3); font-size: 15px; line-height: 1; padding: 0; }
.kw-x:hover { color: #dc2626; }

/* ── AI 荐股 ────────────────────────────────────────────────────────── */
.status-badge { font-size: 11px; padding: 2px 8px; border-radius: 8px; font-weight: 600; }
.status-badge.running { color: #f59e0b; background: rgba(245,158,11,.12); }
.status-badge.done    { color: #16a34a; background: rgba(22,163,74,.12); }
.status-badge.idle    { color: var(--text-3); background: var(--bg-hover); }
.ap-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}
.ap-kv { background: var(--bg-hover); border-radius: 8px; padding: 10px 12px; }
.ap-k { font-size: 11px; color: var(--text-3); }
.ap-v { font-size: 15px; font-weight: 600; color: var(--text-1); margin-top: 3px; }
.noteg { font-size: 10px; margin-left: 5px; padding: 1px 5px; border-radius: 6px; background: rgba(240,180,40,.14); color: #b8860b; }
.rs-summary { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fail-badge  { font-size: 10px; margin-left: 5px; padding: 1px 5px; border-radius: 4px; background: rgba(220,38,38,.12); color: #dc2626; font-weight: 600; }
.daily-badge { font-size: 10px; margin-left: 5px; padding: 1px 5px; border-radius: 4px; background: rgba(59,130,246,.12); color: var(--accent); font-weight: 600; }
.row-err { background: rgba(220,38,38,.03); }
.err-text { color: #dc2626; }

/* ── 研报任务卡片 ───────────────────────────────────────────────────── */
.job-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.job-card { background: var(--bg-hover); border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
.job-card.cancelling { opacity: .7; }
.job-top { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.job-kw { font-size: 14px; font-weight: 600; color: var(--text-1); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-pct { font-size: 13px; font-weight: 600; color: var(--accent); font-variant-numeric: tabular-nums; }
.job-cancel { padding: 2px 8px; font-size: 11px; border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-2); border-radius: 5px; cursor: pointer; }
.job-cancel:hover { color: #dc2626; border-color: #dc2626; }
.job-cancel.force { color: #dc2626; border-color: #dc2626; }
.job-bar { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-bottom: 8px; }
.job-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width .4s; }
.job-fill.indet { background: #f59e0b; animation: pulse 1.1s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
.job-stage-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.job-meta { display: flex; flex-wrap: wrap; gap: 5px; }
.job-stage { font-size: 12px; color: var(--text-2); font-weight: 600; flex: 1; min-width: 0; }
.chip { font-size: 11px; color: var(--text-3); background: var(--bg-surface); border-radius: 4px; padding: 1px 6px; font-variant-numeric: tabular-nums; }
.chip.accent { color: var(--accent); }
.chip.time { color: var(--text-2); }
.chip.cache { color: #16a34a; }

/* ── 等待队列 ───────────────────────────────────────────────────────── */
.queue-list { display: flex; flex-direction: column; gap: 6px; }
.queue-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: var(--bg-hover); border: 1px solid var(--border); border-radius: 8px; }
.queue-pos { width: 22px; height: 22px; flex: none; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: var(--text-2); background: var(--bg-surface); border-radius: 50%; }
.queue-kw { font-size: 14px; font-weight: 600; color: var(--text-1); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.queue-meta { font-size: 12px; white-space: nowrap; }
.queue-kws { color: var(--text-3); font-weight: 400; font-size: 12px; }
.queue-acts { display: flex; align-items: center; gap: 6px; flex: none; }
.ord-btn { width: 26px; height: 26px; flex: none; display: flex; align-items: center; justify-content: center; font-size: 13px; line-height: 1; color: var(--text-2); background: var(--bg-surface); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; }
.ord-btn:hover:not(:disabled) { color: var(--text-1); border-color: var(--accent, #4a9eff); }
.ord-btn:disabled { opacity: .35; cursor: not-allowed; }
.rs-kws { font-size: 11px; color: var(--text-3); font-weight: 400; margin-top: 2px; }

/* ── 研报 MAP 模型分布 ──────────────────────────────────────────────── */
.mc-model-list { display: flex; flex-direction: column; gap: 8px; }
.mc-model-row { display: grid; grid-template-columns: 36px 1fr 1fr 52px; align-items: center; gap: 10px; }
.tier-badge { font-size: 11px; font-weight: 700; text-align: center; border-radius: 5px; padding: 2px 0; }
.tier-badge.hi  { color: #7c3aed; background: rgba(124,58,237,.13); }
.tier-badge.mid { color: #0891b2; background: rgba(8,145,178,.13); }
.tier-badge.lo  { color: var(--text-3); background: var(--bg-hover); }
.model-name { font-size: 13px; font-weight: 600; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-track { height: 8px; background: var(--bg-hover); border-radius: 4px; overflow: hidden; }
.model-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #3b82f6); border-radius: 4px; transition: width .3s; }
.model-cnt { font-size: 12px; color: var(--text-2); text-align: right; }
.icon-btn { background: none; border: none; cursor: pointer; color: var(--text-3); font-size: 13px; margin-left: 4px; }
.icon-btn:hover { color: var(--text-1); }

/* ── Token 趋势 ─────────────────────────────────────────────────────── */
.cost-bars {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 90px;
  padding-top: 6px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 4px;
}
.cb-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; min-width: 0; }
.cb-bar { width: 68%; max-width: 20px; min-height: 2px; background: var(--accent); opacity: .72; border-radius: 3px 3px 0 0; transition: height .3s; }
.cb-col:hover .cb-bar { opacity: 1; }
.cb-x { font-size: 9px; color: var(--text-3); margin-top: 3px; font-family: var(--font-mono); white-space: nowrap; }

/* ── 公众号 ─────────────────────────────────────────────────────────── */
.fc-status-badge { display: flex; align-items: center; gap: 5px; font-size: 12px; padding: 3px 8px; border-radius: 8px; }
.fc-status-badge.ok   { color: #16a34a; background: rgba(22,163,74,.1); }
.fc-status-badge.warn { color: #f59e0b; background: rgba(245,158,11,.1); }
.fc-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.fc-layout { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; margin-top: 12px; }
.fc-qr-wrap { flex-shrink: 0; }
.fc-qr-box {
  position: relative;
  width: 200px;
  height: 200px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.fc-qr-img { width: 100%; height: 100%; object-fit: contain; }
.fc-qr-img.dim { opacity: .18; }
.fc-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  text-align: center;
  font-size: 13px;
  color: var(--text-1);
  background: rgba(255,255,255,.85);
}
.fc-mask.done { background: rgba(22,163,74,.12); color: #16a34a; font-size: 16px; font-weight: 600; }
.fc-placeholder {
  width: 200px;
  height: 200px;
  border: 1px dashed var(--border);
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-3);
  text-align: center;
  padding: 16px;
}
.fc-steps { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
.step-list { display: flex; flex-direction: column; gap: 4px; }
.step { font-size: 12px; color: var(--text-2); margin: 0; }

/* ── 聊天过滤条 ─────────────────────────────────────────────────────── */
.filter-notice {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  font-size: 13px;
  color: var(--text-2);
  border-bottom: 1px solid var(--border);
  background: var(--bg-hover);
}

/* ── 空状态 ─────────────────────────────────────────────────────────── */
.empty-state { text-align: center; color: var(--text-3); padding: 24px; font-size: 13px; }

/* ── 弹层 ───────────────────────────────────────────────────────────── */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}
.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  width: min(720px, 94vw);
  max-height: 82vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0,0,0,.3);
}
.modal.modal-wide { width: min(780px, 96vw); }
.modal-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.modal-ttl { font-size: 15px; font-weight: 700; color: var(--text-1); }
.modal-sub { font-size: 12px; color: var(--text-3); margin-top: 2px; }
.modal-x { background: none; border: none; font-size: 22px; color: var(--text-3); cursor: pointer; line-height: 1; }
.modal-body { overflow-y: auto; }

/* ── 对话内容 ────────────────────────────────────────────────────────── */
.chat-body { padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
.chat-msg { display: flex; flex-direction: column; gap: 4px; }
.chat-msg.user { align-items: flex-end; }
.chat-role {
  font-size: 11px;
  color: var(--text-3);
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-ts { font-family: var(--font-mono); }
.chat-bubble {
  max-width: 82%;
  padding: 9px 13px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-msg.user .chat-bubble { background: var(--accent); color: #fff; border-bottom-right-radius: 3px; }
.chat-msg.assistant .chat-bubble { background: var(--bg-hover); color: var(--text-1); border-bottom-left-radius: 3px; }

/* ── LLM 嵌入 ────────────────────────────────────────────────────────── */
.llm-wrap :deep(.llm-wrap) { padding: 0; }
.llm-wrap :deep(.llm-header) { display: none; }

/* ── 错误条 ──────────────────────────────────────────────────────────── */
.err-banner {
  padding: 12px 16px;
  border-radius: 8px;
  background: rgba(239,68,68,.1);
  color: #dc2626;
  border: 1px solid rgba(239,68,68,.3);
  font-size: 13px;
}

/* ── 响应式 ──────────────────────────────────────────────────────────── */
@media (max-width: 900px) {
  .two-col { grid-template-columns: 1fr; }
  .metric-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
@media (max-width: 600px) {
  .admin-view { padding: 12px 14px 32px; gap: 12px; }
  .tab-nav { margin: 0 -14px; padding: 0 14px; }
  .metric-grid { grid-template-columns: 1fr 1fr; }
  .vol-grid { grid-template-columns: 1fr 1fr; }
  .toolbar { gap: 8px; }
  .filter-pills { overflow-x: auto; -webkit-overflow-scrolling: touch; flex-wrap: nowrap; }
  .fc-layout { flex-direction: column; }
  .fc-qr-box, .fc-placeholder { width: 180px; height: 180px; }
  .job-grid { grid-template-columns: 1fr; }
  .queue-meta { display: none; }
}
</style>
