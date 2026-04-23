<template>
  <div class="app-shell">
    <!-- ── Mobile sidebar overlay ────────────────────────────── -->
    <div class="sidebar-overlay" :class="{ active: sidebarOpen }" @click="sidebarOpen = false"></div>

    <!-- ── Sidebar ──────────────────────────────────────────── -->
    <nav class="sidebar" :class="{ 'sidebar-open': sidebarOpen, 'sidebar-collapsed': sidebarCollapsed }">
      <!-- Brand -->
      <div class="sidebar-brand">
        <div class="brand-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>
            <polyline points="16 7 22 7 22 13"/>
          </svg>
        </div>
        <span class="brand-name">QuantForge</span>
        <!-- Desktop collapse toggle -->
        <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? '展开导航' : '收起导航'" aria-label="折叠菜单">
          <svg v-if="!sidebarCollapsed" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="9 18 15 12 9 6"/>
          </svg>
        </button>
        <!-- Mobile close button -->
        <button class="sidebar-close" @click="sidebarOpen = false" aria-label="关闭菜单">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      </div>

      <!-- Nav groups -->
      <div class="sidebar-nav">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <div class="nav-group-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items" :key="item.path"
            :to="item.path"
            class="nav-item"
            active-class="nav-active"
            :exact="item.exact"
            :title="sidebarCollapsed ? item.label : undefined"
            @click="sidebarOpen = false"
          >
            <span class="nav-icon" v-html="item.svg"></span>
            <span class="nav-text">{{ item.label }}</span>
          </router-link>
        </div>
      </div>

      <!-- Footer -->
      <div class="sidebar-footer">
        <span :class="['status-dot', apiStatus]"></span>
        <span class="status-label">{{ apiStatus === 'online' ? 'API 在线' : apiStatus === 'offline' ? 'API 离线' : '连接中' }}</span>
      </div>
    </nav>

    <!-- ── Main area ─────────────────────────────────────────── -->
    <div class="main-area">
      <!-- Topbar -->
      <header class="topbar">
        <div class="topbar-left">
          <!-- Hamburger (mobile only) -->
          <button class="hamburger" @click="sidebarOpen = !sidebarOpen" aria-label="打开菜单">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
          <span class="page-title">{{ currentPage.label }}</span>
        </div>
        <div class="topbar-right">
          <div :class="['market-status', isMarketOpen ? 'open' : 'closed']">
            <span class="market-dot"></span>
            <span class="market-label">{{ isMarketOpen ? 'A股 开盘中' : 'A股 休市' }}</span>
          </div>
          <div class="topbar-time">{{ currentTime }}</div>
        </div>
      </header>

      <!-- Page content -->
      <main class="page-content">
        <router-view />
      </main>

      <!-- ── Bottom nav (mobile only) ──────────────────────── -->
      <nav class="bottom-nav">
        <router-link
          v-for="item in bottomNavItems" :key="item.path"
          :to="item.path"
          class="bottom-nav-item"
          active-class="bottom-nav-active"
          :exact="item.exact"
        >
          <span class="bottom-nav-icon" v-html="item.svg"></span>
          <span class="bottom-nav-label">{{ item.label }}</span>
        </router-link>
      </nav>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const apiStatus = ref('checking')
const currentTime = ref('')
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
watch(sidebarCollapsed, v => localStorage.setItem('sidebar-collapsed', String(v)))
let clockTimer = null

// SVG icon paths (Lucide-style, inline)
const icons = {
  dashboard: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
  chart: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>`,
  search: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
  bot: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>`,
  flask: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6l1 9H8L9 3z"/><path d="M6.1 15a3 3 0 0 0 2.19 5h7.42a3 3 0 0 0 2.19-5L15 12H9L6.1 15z"/></svg>`,
  sliders: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>`,
  zap: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  newspaper: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8"/><path d="M15 18h-5"/><path d="M10 6h8v4h-8V6Z"/></svg>`,
  layers: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>`,
  sparkles: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3c.5 2.5 2.5 4.5 5 5-2.5.5-4.5 2.5-5 5-.5-2.5-2.5-4.5-5-5 2.5-.5 4.5-2.5 5-5z"/><path d="M5 3c.3 1.3 1.3 2.3 2.5 2.5C6.3 5.8 5.3 6.8 5 8c-.3-1.3-1.3-2.3-2.5-2.5C3.8 5.3 4.8 4.3 5 3z"/><path d="M19 13c.3 1.3 1.3 2.3 2.5 2.5-1.3.3-2.3 1.3-2.5 2.5-.3-1.3-1.3-2.3-2.5-2.5 1.3-.3 2.3-1.3 2.5-2.5z"/></svg>`,
  checkmark: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>`,
  bell: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`,
  coins: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></svg>`,
  user: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  trending: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
}

// ── Navigation — 7-pillar structure (based on industry research) ──────
const navGroups = [
  {
    label: '总览',
    items: [
      { path: '/', label: '首页', svg: icons.dashboard, exact: true },
    ],
  },
  {
    label: '市场',
    items: [
      { path: '/market-hub',     label: '市场全景', svg: icons.chart },
      { path: '/stock-analysis', label: '个股分析', svg: icons.search },
      { path: '/sector',         label: '行业板块', svg: icons.layers },
      { path: '/news',           label: '财经资讯', svg: icons.newspaper },
    ],
  },
  {
    label: '选股',
    items: [
      { path: '/ai-picks', label: 'AI 推荐', svg: icons.sparkles },
      { path: '/screener', label: '策略选股', svg: icons.bot },
      { path: '/verify',   label: '推荐验证', svg: icons.checkmark },
    ],
  },
  {
    label: '量化研究',
    items: [
      { path: '/backtest',  label: '策略回测',  svg: icons.flask },
      { path: '/optimizer', label: '参数优化',  svg: icons.sliders },
    ],
  },
  {
    label: '交易',
    items: [
      { path: '/live', label: '模拟交易', svg: icons.zap },
    ],
  },
  {
    label: '账户',
    items: [
      { path: '/account', label: '账户管理', svg: icons.user },
    ],
  },
  {
    label: '系统',
    items: [
      { path: '/notification', label: '消息通知', svg: icons.bell },
      { path: '/llm-stats',    label: 'LLM 配置', svg: icons.coins },
    ],
  },
]

const allNavItems = navGroups.flatMap(g => g.items)

// Bottom nav: 5 most-used items for mobile
const bottomNavItems = [
  { path: '/',         label: '首页',  svg: icons.dashboard, exact: true },
  { path: '/market-hub', label: '市场', svg: icons.chart },
  { path: '/ai-picks', label: 'AI选股', svg: icons.sparkles },
  { path: '/backtest', label: '回测',  svg: icons.flask },
  { path: '/account',  label: '账户',  svg: icons.user },
]

const currentPage = computed(() => {
  return allNavItems.find(i => {
    if (i.exact) return route.path === i.path
    return route.path === i.path || route.path.startsWith(i.path + '/')
  }) || { label: 'QuantForge' }
})

const isMarketOpen = computed(() => {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const h = now.getHours(), m = now.getMinutes()
  const t = h * 60 + m
  return (t >= 9 * 60 + 30 && t <= 11 * 60 + 30) || (t >= 13 * 60 && t <= 15 * 60)
})

function updateClock() {
  currentTime.value = new Date().toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

onMounted(async () => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  try {
    await axios.get('/api/system/health')
    apiStatus.value = 'online'
  } catch {
    apiStatus.value = 'offline'
  }
})

onUnmounted(() => clearInterval(clockTimer))
</script>

<style scoped>
.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-base);
}

/* ── Mobile overlay ──────────────────────────────────────── */
.sidebar-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 99;
  backdrop-filter: blur(2px);
}
.sidebar-overlay.active { display: block; }

/* ── Sidebar ─────────────────────────────────────────────── */
.sidebar {
  width: var(--sidebar-w);
  min-width: var(--sidebar-w);
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 100;
  transition: width 0.22s cubic-bezier(0.4,0,0.2,1), min-width 0.22s cubic-bezier(0.4,0,0.2,1);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 12px 12px;
  border-bottom: 1px solid var(--border);
  min-height: 52px;
}
.brand-logo {
  width: 28px; height: 28px;
  background: linear-gradient(135deg, rgba(61,142,248,0.2), rgba(61,142,248,0.08));
  border: 1px solid rgba(61,142,248,0.3);
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(61,142,248,0.2);
}
.brand-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: 0.02em;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
}

/* Close button — hidden on desktop */
.sidebar-close {
  display: none;
  background: none; border: none;
  color: var(--text-2); cursor: pointer;
  padding: 4px; border-radius: var(--radius-sm); line-height: 1; flex-shrink: 0;
}
.sidebar-close:hover { color: var(--text-1); background: var(--bg-hover); }

/* Desktop collapse toggle */
.sidebar-toggle {
  display: flex; align-items: center; justify-content: center;
  background: none; border: none; color: var(--text-3);
  cursor: pointer; padding: 4px; border-radius: var(--radius-sm);
  line-height: 1; flex-shrink: 0;
  transition: color var(--trans-fast), background var(--trans-fast);
  opacity: 0; /* hidden until brand hover */
}
.sidebar-brand:hover .sidebar-toggle { opacity: 1; }
.sidebar-toggle:hover { color: var(--text-1); background: var(--bg-hover); }

/* ── Collapsed sidebar ─────────────────────────────────── */
.sidebar-collapsed { width: 52px !important; min-width: 52px !important; }
.sidebar-collapsed .brand-name { display: none; }
.sidebar-collapsed .nav-group-label { display: none; }
.sidebar-collapsed .nav-text { display: none; }
.sidebar-collapsed .status-label { display: none; }
.sidebar-collapsed .sidebar-brand { justify-content: center; padding: 12px 0; gap: 0; }
.sidebar-collapsed .sidebar-toggle { opacity: 1 !important; }
.sidebar-collapsed .sidebar-footer { justify-content: center; padding: 12px 0; }
.sidebar-collapsed .nav-item { justify-content: center; padding: 10px 0; margin-left: 0; }
.sidebar-collapsed .nav-item:hover { background: var(--bg-hover); }
.sidebar-collapsed .nav-active { border-left-color: var(--accent) !important; box-shadow: inset 3px 0 0 var(--accent); }
.sidebar-collapsed .sidebar-nav { padding: 10px 4px; }
/* tooltip via title attr visible when collapsed */
.sidebar-collapsed .nav-item[title] { position: relative; }

.sidebar-nav {
  flex: 1; overflow-y: auto; overflow-x: hidden;
  padding: 10px 8px;
}
.sidebar-nav::-webkit-scrollbar { width: 3px; }

.nav-group { margin-bottom: 4px; }
.nav-group-label {
  font-size: 9px; font-weight: 700; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.10em;
  padding: 8px 8px 3px; white-space: nowrap;
}

.nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 8px; border-radius: var(--radius-md);
  color: var(--text-2); text-decoration: none;
  font-size: 12px; font-weight: 500;
  transition: background var(--trans-fast), color var(--trans-fast), border-color var(--trans-fast);
  cursor: pointer;
  border-left: 2px solid transparent;
  margin-left: 2px; min-height: 36px;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-1); }
.nav-active {
  background: linear-gradient(90deg, rgba(61,142,248,0.12), rgba(61,142,248,0.04)) !important;
  color: var(--accent) !important;
  border-left-color: var(--accent) !important;
}
.nav-active :deep(svg) { filter: drop-shadow(0 0 3px rgba(61,142,248,0.5)); }
.nav-icon { display: flex; align-items: center; flex-shrink: 0; }
.nav-text { white-space: nowrap; overflow: hidden; }

.sidebar-footer {
  display: flex; align-items: center; gap: 7px;
  padding: 10px 14px; border-top: 1px solid var(--border);
}
.status-dot {
  width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}
.status-dot.online  { background: var(--success); box-shadow: 0 0 8px var(--success); }
.status-dot.offline { background: var(--danger); box-shadow: 0 0 6px var(--danger); }
.status-dot.checking { background: var(--warning); animation: pulse 1.5s infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.4 } }
.status-label { font-size: 10px; color: var(--text-3); letter-spacing: 0.04em; }

/* ── Main area ───────────────────────────────────────────── */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Topbar */
.topbar {
  height: var(--topbar-h);
  min-height: var(--topbar-h);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  flex-shrink: 0;
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.page-title  { font-size: 12px; font-weight: 700; color: var(--text-1); letter-spacing: 0.04em; text-transform: uppercase; }

/* Hamburger — hidden on desktop */
.hamburger {
  display: none;
  background: none;
  border: none;
  color: var(--text-2);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-md);
  line-height: 1;
  flex-shrink: 0;
}
.hamburger:hover { color: var(--text-1); background: var(--bg-hover); }

.topbar-right { display: flex; align-items: center; gap: 16px; }

.market-status {
  display: flex; align-items: center; gap: 5px;
  font-size: 10px; font-weight: 600;
  padding: 3px 9px; border-radius: 20px;
  letter-spacing: 0.04em;
}
.market-status.open   { background: rgba(34,217,122,0.08); color: var(--success); border: 1px solid rgba(34,217,122,0.2); }
.market-status.closed { background: rgba(100,130,160,0.07); color: var(--text-3); border: 1px solid var(--border); }
.market-dot {
  width: 5px; height: 5px; border-radius: 50%; background: currentColor;
}
.market-status.open .market-dot { animation: pulse 2s infinite; box-shadow: 0 0 6px currentColor; }

.topbar-time {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.06em;
}

/* Page content */
.page-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

/* ── Bottom nav (hidden on desktop) ─────────────────────── */
.bottom-nav {
  display: none;
}

/* ── Mobile breakpoint ───────────────────────────────────── */
@media (max-width: 768px) {
  /* Sidebar becomes a fixed slide-in drawer */
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: 260px;
    min-width: 260px;
    transform: translateX(-100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: var(--shadow-float);
  }
  .sidebar.sidebar-open {
    transform: translateX(0);
  }
  .sidebar-close { display: flex; }
  .sidebar-toggle { display: none; }
  /* On mobile, disable collapse so it always shows full sidebar */
  .sidebar.sidebar-collapsed {
    width: 260px !important;
    min-width: 260px !important;
  }
  .sidebar-collapsed .brand-name { display: block; }
  .sidebar-collapsed .nav-group-label { display: block; }
  .sidebar-collapsed .nav-text { display: block; }
  .sidebar-collapsed .status-label { display: block; }

  /* Show hamburger */
  .hamburger { display: flex; }

  /* Topbar adjustments */
  .topbar { padding: 0 12px; }
  .topbar-time { display: none; }
  .market-label { display: none; }
  .market-status { padding: 3px 6px; }

  /* Page content: leave room for bottom nav */
  .page-content {
    padding-bottom: 56px;
  }

  /* Show bottom nav */
  .bottom-nav {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 56px;
    background: var(--bg-surface);
    border-top: 1px solid var(--border);
    z-index: 50;
    box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.4);
  }

  .bottom-nav-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    text-decoration: none;
    color: var(--text-3);
    font-size: 10px;
    font-weight: 500;
    padding: 6px 4px;
    transition: color 0.12s;
    min-height: 44px;
  }
  .bottom-nav-item:hover { color: var(--text-2); }
  .bottom-nav-active { color: var(--accent) !important; }

  .bottom-nav-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .bottom-nav-icon :deep(svg) {
    width: 20px;
    height: 20px;
  }
  .bottom-nav-label { line-height: 1; }
}
</style>
