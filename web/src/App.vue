<template>
  <div class="app-shell">
    <!-- ── Mobile sidebar overlay ────────────────────────────── -->
    <div class="sidebar-overlay" :class="{ active: sidebarOpen }" @click="sidebarOpen = false"></div>

    <!-- ── Sidebar ──────────────────────────────────────────── -->
    <nav class="sidebar" :class="{ 'sidebar-open': sidebarOpen, 'sidebar-collapsed': sidebarCollapsed }">
      <!-- Brand -->
      <div class="sidebar-brand">
        <div class="brand-logo">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#e11d2a" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
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
      <div class="sidebar-nav" @mouseover="onRailOver" @mouseleave="railTip.show = false">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <div class="nav-group-label">{{ group.label }}</div>
          <template v-for="item in group.items" :key="item.path">
            <!-- 可展开父项（机构荐股 / 公众号）：有子分类时点击切换展开 -->
            <div v-if="item.expandable" class="nav-expandable">
              <div
                class="nav-item nav-parent"
                :class="{ 'nav-active': route.path === item.path }"
                :aria-label="sidebarCollapsed ? item.label : undefined"
                role="button"
                tabindex="0"
                :aria-expanded="!!expanded[item.cats]"
                @click="toggleExpand(item)"
                @keydown.enter.prevent="toggleExpand(item)"
                @keydown.space.prevent="toggleExpand(item)"
              >
                <span class="nav-icon" v-html="item.svg" aria-hidden="true"></span>
                <span class="nav-text">{{ item.label }}</span>
                <svg v-if="(catMap[item.cats] || []).length" class="nav-caret"
                  :class="{ open: expanded[item.cats] }"
                  width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </div>
              <div v-show="expanded[item.cats] && !sidebarCollapsed" class="nav-sub">
                <router-link
                  v-for="c in (catMap[item.cats] || [])" :key="catValue(c)"
                  :to="{ path: item.path, query: { category: catValue(c) } }"
                  class="nav-subitem"
                  :class="{ 'nav-active': route.path === item.path && route.query.category === catValue(c) }"
                  @click="sidebarOpen = false"
                >
                  <span class="nav-subtext">{{ c.name }}</span>
                  <span class="nav-subcount">{{ c.count }}</span>
                </router-link>
              </div>
            </div>
            <!-- 普通项 -->
            <router-link
              v-else
              :to="item.path"
              class="nav-item"
              active-class="nav-active"
              :exact="item.exact"
              :aria-label="sidebarCollapsed ? item.label : undefined"
              @click="sidebarOpen = false"
            >
              <span class="nav-icon" v-html="item.svg" aria-hidden="true"></span>
              <span class="nav-text">{{ item.label }}</span>
            </router-link>
          </template>
        </div>
      </div>

      <!-- 折叠态悬浮提示(fixed 浮层,不受侧栏 overflow 裁剪;纯 CSS 气泡会被滚动容器切掉)-->
      <transition name="rail-tip-fade">
        <div v-if="sidebarCollapsed && railTip.show" class="rail-tip" :style="{ top: railTip.top + 'px' }">{{ railTip.text }}</div>
      </transition>

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
          <div class="user-menu" @click="toggleUserMenu" ref="userMenuRef">
            <div class="user-avatar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
              </svg>
            </div>
            <span class="user-name">{{ authStore.user?.username || '用户' }}</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"/>
            </svg>
            <div v-if="showUserMenu" class="user-dropdown">
              <div class="user-dropdown-header">
                <div class="user-dropdown-username">{{ authStore.user?.username }}</div>
                <div class="user-dropdown-email">{{ authStore.user?.email }}</div>
              </div>
              <div class="user-dropdown-divider"></div>
              <button class="user-dropdown-item logout" @click="handleLogout">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
                </svg>
                退出登录
              </button>
            </div>
          </div>
        </div>
      </header>

      <!-- Page content -->
      <main class="page-content">
        <router-view />
      </main>

      <!-- ── 产业链投研 · 后台任务完成提醒 ──────────────────── -->
      <transition name="ir-toast-fade">
        <div v-if="research.toast" class="ir-toast" :class="research.toast.type">
          <span class="ir-toast-icon">{{ research.toast.type === 'done' ? '✅' : (research.toast.type === 'cancelled' ? '🟡' : '⚠️') }}</span>
          <div class="ir-toast-body">
            <div class="ir-toast-title">
              {{ research.toast.type === 'done'
                ? `「${research.toast.keyword}」产业链分析已完成`
                : (research.toast.type === 'cancelled'
                  ? `「${research.toast.keyword}」分析已中断`
                  : `「${research.toast.keyword}」分析失败`) }}
            </div>
            <div class="ir-toast-sub">{{ research.toast.type === 'done' ? '点击查看深度看板' : (research.toast.msg || '请重试') }}</div>
          </div>
          <button v-if="research.toast.type === 'done'" class="ir-toast-btn" @click="openToast">查看</button>
          <button class="ir-toast-close" @click="dismissToast">×</button>
        </div>
      </transition>

      <!-- ── Bottom nav (mobile only) ──────────────────────── -->
      <nav class="bottom-nav">
        <router-link
          v-for="item in bottomNavItems" :key="item.path"
          :to="item.path"
          class="bottom-nav-item"
          active-class="bottom-nav-active"
          :exact="item.exact"
        >
          <span class="bottom-nav-icon" v-html="item.svg" aria-hidden="true"></span>
          <span class="bottom-nav-label">{{ item.label }}</span>
        </router-link>
      </nav>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { useAuthStore } from './stores/auth'
import { research, dismissToast, requestOpen } from './stores/research'

// ── 在线心跳：已登录用户每 30 s 发一次，页面隐藏时暂停 ──────────────────────
let _heartbeatTimer = null
function _startHeartbeat(store) {
  if (_heartbeatTimer) return
  const send = () => {
    if (!store.isAuthenticated || document.hidden) return
    axios.post('/api/admin/heartbeat').catch(() => {})
  }
  send()
  _heartbeatTimer = setInterval(send, 30_000)
}
function _stopHeartbeat() {
  if (_heartbeatTimer) { clearInterval(_heartbeatTimer); _heartbeatTimer = null }
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

function openToast() {
  if (research.toast) {
    requestOpen(research.toast.slug)
    window.open(router.resolve({ path: '/industry-research', query: { slug: research.toast.slug } }).href, '_blank')
    dismissToast()
  }
}
// ── 信息导航的可展开子分类（机构荐股/公众号 按作者动态聚合）──
const catMap = ref({ xingqiu: [], fenchuan: [] })   // { cats键: [{name, count}] }
const expanded = ref({ xingqiu: false, fenchuan: false })

// 分类筛选值：机构荐股按星球(group_id)，公众号按作者(name)
function catValue(c) { return c.group_id ?? c.name }

function toggleExpand(item) {
  // 折叠态：直接进父页面；展开态：切换子菜单
  if (sidebarCollapsed.value) { router.push(item.path); sidebarOpen.value = false; return }
  expanded.value = { ...expanded.value, [item.cats]: !expanded.value[item.cats] }
}

watch(() => authStore.isAuthenticated, (ok) => { if (ok) loadNavCategories() })

// 防重入守卫：onMounted 与 isAuthenticated watch 可能在已登录首屏并发触发，
// 避免对 /api/xingqiu/posts 和 /api/fenchuan/posts 各打两次重复请求。
let loadingNavCats = false

async function loadNavCategories() {
  if (!authStore.isAuthenticated) return
  if (loadingNavCats) return
  loadingNavCats = true
  try {
    // 机构荐股（知识星球）
    try {
      const { data } = await axios.get('/api/xingqiu/posts', { params: { page_size: 1 } })
      catMap.value = { ...catMap.value, xingqiu: data.categories || [] }
    } catch {}
    // 公众号（粉传）
    try {
      const { data } = await axios.get('/api/fenchuan/posts', { params: { page_size: 1 } })
      catMap.value = { ...catMap.value, fenchuan: data.categories || [] }
    } catch {}
    // 当前就在某子页面时，默认展开它，让选中的分类可见
    if (route.path === '/blog') expanded.value.xingqiu = true
    if (route.path === '/fenchuan') expanded.value.fenchuan = true
  } finally {
    loadingNavCats = false
  }
}

const apiStatus = ref('checking')
const currentTime = ref('')
const clockNow = ref(new Date())   // 每秒更新，给 isMarketOpen 当响应式时基
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const showUserMenu = ref(false)
const userMenuRef = ref(null)
watch(sidebarCollapsed, v => localStorage.setItem('sidebar-collapsed', String(v)))
let clockTimer = null

function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
}

// 折叠侧栏的悬浮提示：委托到 .sidebar-nav,鼠标移到某 nav-item 上时
// 读取其(隐藏的)文字,用 fixed 浮层显示在导航条右侧。
const railTip = ref({ show: false, text: '', top: 0 })
function onRailOver(e) {
  if (!sidebarCollapsed.value) return
  const el = e.target.closest('.nav-item')
  if (!el) { railTip.show = false; return }
  const text = el.querySelector('.nav-text')?.textContent?.trim()
  if (!text) { railTip.value = { ...railTip.value, show: false }; return }
  const r = el.getBoundingClientRect()
  railTip.value = { show: true, text, top: r.top + r.height / 2 }
}

function handleClickOutside(event) {
  if (userMenuRef.value && !userMenuRef.value.contains(event.target)) {
    showUserMenu.value = false
  }
}

function handleLogout() {
  authStore.logout()
  router.push('/auth')
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  if (authStore.isAuthenticated) _startHeartbeat(authStore)
})

watch(() => authStore.isAuthenticated, (v) => {
  if (v) _startHeartbeat(authStore)
  else _stopHeartbeat()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside)
  _stopHeartbeat()
})

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
  sunrise: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 18a5 5 0 0 0-10 0"/><line x1="12" y1="2" x2="12" y2="9"/><line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/><line x1="1" y1="18" x2="3" y2="18"/><line x1="21" y1="18" x2="23" y2="18"/><line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/><line x1="23" y1="22" x2="1" y2="22"/><polyline points="8 6 12 2 16 6"/></svg>`,
  sunset: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 18a5 5 0 0 0-10 0"/><line x1="12" y1="9" x2="12" y2="2"/><line x1="4.22" y1="10.22" x2="5.64" y2="11.64"/><line x1="1" y1="18" x2="3" y2="18"/><line x1="21" y1="18" x2="23" y2="18"/><line x1="18.36" y1="11.64" x2="19.78" y2="10.22"/><line x1="23" y1="22" x2="1" y2="22"/><polyline points="16 5 12 9 8 5"/></svg>`,
  coins: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6"/><path d="M18.09 10.37A6 6 0 1 1 10.34 18"/><path d="M7 6h1v4"/><path d="m16.71 13.88.7.71-2.82 2.82"/></svg>`,
  user: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
  trending: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>`,
  star: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>`,
  verify2: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3c.5 2.5 2.5 4.5 5 5-2.5.5-4.5 2.5-5 5-.5-2.5-2.5-4.5-5-5 2.5-.5 4.5-2.5 5-5z"/><path d="M9 9l6 6"/><path d="M15 9l-6 6"/></svg>`,
  fileText: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/></svg>`,
  wallet: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="4" rx="2"/><line x1="3" x2="21" y1="10" y2="10"/></svg>`,
  activity: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>`,
  shield: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
  compare: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="9" width="6" height="12" rx="1"/><rect x="15" y="4" width="6" height="17" rx="1"/><line x1="6" y1="9" x2="6" y2="4"/><line x1="18" y1="4" x2="18" y2="2"/></svg>`,
  funnel: `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>`,
}

// ── Navigation — 7-pillar structure (based on industry research) ──────
const baseNavGroups = [
  {
    label: '总览',
    items: [
      { path: '/', label: '首页', svg: icons.dashboard, exact: true },
      { path: '/morning', label: '每日晨报', svg: icons.sunrise },
      { path: '/review', label: '每日复盘', svg: icons.sunset },
      { path: '/chat', label: 'AI 对话', svg: icons.bot },
    ],
  },
  {
    label: '常用功能',
    items: [
      { path: '/watchlist', label: '自选股', svg: icons.star },
      { path: '/ai-picks', label: 'AI 推荐', svg: icons.sparkles },
      { path: '/quarterly', label: '季报分析', svg: icons.fileText },
      { path: '/market-hub',     label: '市场总览', svg: icons.chart },
      { path: '/price-surge',    label: '涨价逻辑', svg: icons.trending },
      { path: '/industry-research', label: '产业链分析', svg: icons.search },
    ],
  },
  {
    label: '信息',
    items: [
      { path: '/cls', label: '财联社电报', svg: icons.newspaper },
      { path: '/reports', label: '研报', svg: icons.fileText },
      { path: '/blog', label: '机构荐股', svg: icons.newspaper, expandable: true, cats: 'xingqiu' },
      { path: '/fenchuan', label: '公众号', svg: icons.newspaper, expandable: true, cats: 'fenchuan' },
      { path: '/feishu', label: '飞书群', svg: icons.newspaper },
    ],
  },
  {
    label: '选股',
    items: [
      { path: '/screener', label: '策略选股', svg: icons.funnel },
      { path: '/verify',   label: '推荐验证', svg: icons.checkmark },
      { path: '/stock-compare', label: '个股对比', svg: icons.compare },
    ],
  },
  {
    label: '量化研究',
    items: [
      { path: '/backtest',  label: '策略回测',  svg: icons.flask },
    ],
  },
]

// 「管理」分组仅管理员可见——非管理员账号看不到任何后台入口。
const adminNavGroup = {
  label: '管理',
  items: [
    { path: '/admin', label: '管理后台', svg: icons.shield },
  ],
}

const navGroups = computed(() =>
  authStore.isAdmin ? [...baseNavGroups, adminNavGroup] : baseNavGroups
)

const allNavItems = computed(() => navGroups.value.flatMap(g => g.items))

// Bottom nav: 移动端 5 个高频入口（盘中场景：行情/自选/AI 推荐优先）
const bottomNavItems = [
  { path: '/',         label: '首页',  svg: icons.dashboard, exact: true },
  { path: '/market-hub', label: '市场', svg: icons.chart },
  { path: '/watchlist', label: '自选',  svg: icons.star },
  { path: '/ai-picks', label: 'AI 推荐', svg: icons.sparkles },
  { path: '/chat',     label: '对话',  svg: icons.bot },
]

const currentPage = computed(() => {
  return allNavItems.value.find(i => {
    if (i.exact) return route.path === i.path
    return route.path === i.path || route.path.startsWith(i.path + '/')
  }) || { label: 'QuantForge' }
})

// A股法定节假日休市表（按交易所公告，每年初需更新；调休补班的周末本就不开市，无需额外处理）。
const MARKET_HOLIDAYS = new Set([
  // 2026 元旦
  '2026-01-01',
  // 2026 春节
  '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-23', '2026-02-24',
  // 2026 清明
  '2026-04-06',
  // 2026 劳动节
  '2026-05-01', '2026-05-04', '2026-05-05',
  // 2026 端午
  '2026-06-19',
  // 2026 中秋 + 国庆
  '2026-09-25', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08',
])

function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 用每秒更新的 clockNow 作为响应式时基；否则 computed 没有响应式依赖，
// 只在首屏算一次就永久缓存，收盘/周末后仍显示「开盘中」。
const isMarketOpen = computed(() => {
  const now = clockNow.value
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  if (MARKET_HOLIDAYS.has(ymd(now))) return false
  const t = now.getHours() * 60 + now.getMinutes()
  return (t >= 9 * 60 + 30 && t <= 11 * 60 + 30) || (t >= 13 * 60 && t <= 15 * 60)
})

function updateClock() {
  const now = new Date()
  clockNow.value = now
  currentTime.value = now.toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
}

onMounted(async () => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  // 已登录则刷新一次 user，确保拿到最新的 is_admin（旧登录态可能缺该字段，
  // 否则「管理」入口判断不出来）。
  if (authStore.isAuthenticated) {
    authStore.checkAuth()
  }
  loadNavCategories()
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
  background: linear-gradient(135deg, rgba(225,29,42,0.2), rgba(225,29,42,0.08));
  border: 1px solid rgba(225,29,42,0.3);
  border-radius: var(--radius-md);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(225,29,42,0.2);
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
.sidebar-collapsed .nav-item { justify-content: center; padding: 10px 0; }
.sidebar-collapsed .nav-item:hover { background: var(--bg-hover); }
.sidebar-collapsed .sidebar-nav { padding: 10px 4px; }
/* tooltip via title attr visible when collapsed */
.sidebar-collapsed .nav-item[title] { position: relative; }

/* 折叠态悬浮提示(fixed,贴在 52px 导航条右侧;left 用条宽 + 间隙) */
.rail-tip {
  position: fixed;
  left: calc(52px + 6px);
  transform: translateY(-50%);
  z-index: 1200;
  background: var(--bg-elevated);
  border: 1px solid var(--border-light);
  color: var(--text-1);
  font-size: 12px; font-weight: 500; white-space: nowrap;
  padding: 5px 10px; border-radius: var(--radius-md);
  box-shadow: var(--shadow-float);
  pointer-events: none;
}
.rail-tip-fade-enter-active, .rail-tip-fade-leave-active { transition: opacity var(--trans-fast); }
.rail-tip-fade-enter-from, .rail-tip-fade-leave-to { opacity: 0; }

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
  transition: background var(--trans-fast), color var(--trans-fast);
  cursor: pointer;
  min-height: 36px;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text-1); }
.nav-active {
  background: var(--accent-dim) !important;
  color: var(--accent) !important;
  font-weight: 600;
}
.nav-icon { display: flex; align-items: center; flex-shrink: 0; }
.nav-text { white-space: nowrap; overflow: hidden; }

/* 可展开父项 + 子分类 */
.nav-parent .nav-text { flex: 1; }
.nav-caret { flex-shrink: 0; color: var(--text-3); transition: transform var(--trans-fast); }
.nav-caret.open { transform: rotate(90deg); }
.sidebar-collapsed .nav-caret { display: none; }
.nav-sub { display: flex; flex-direction: column; margin: 2px 0 4px 0; }
.nav-subitem {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px 6px 30px; border-radius: var(--radius-md);
  color: var(--text-3); text-decoration: none;
  font-size: 12px; font-weight: 500; min-height: 30px;
  transition: background var(--trans-fast), color var(--trans-fast);
}
.nav-subitem:hover { background: var(--bg-hover); color: var(--text-1); }
.nav-subtext { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.nav-subcount { font-size: 10px; color: var(--text-3); background: var(--bg-base); border-radius: 9px; padding: 1px 7px; flex-shrink: 0; }
.nav-subitem.nav-active .nav-subcount { background: rgba(37,99,235,0.12); color: var(--accent); }

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
.market-status.open   { background: rgba(22,163,74,0.08); color: var(--success); border: 1px solid rgba(22,163,74,0.2); }
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

/* User menu */
.user-menu {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  position: relative;
  transition: background var(--trans-fast);
  color: var(--text-2);
}
.user-menu:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(37,99,235, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
}
.user-name {
  font-size: 13px;
  font-weight: 500;
}

.user-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 220px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 40px rgba(15,23,42,0.12);
  z-index: 1000;
  overflow: hidden;
}
.user-dropdown-header {
  padding: 16px;
  background: rgba(37,99,235, 0.05);
}
.user-dropdown-username {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
}
.user-dropdown-email {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 2px;
}
.user-dropdown-divider {
  height: 1px;
  background: var(--border);
}
.user-dropdown-item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text-2);
  background: none;
  border: none;
  cursor: pointer;
  transition: all var(--trans-fast);
  text-align: left;
}
.user-dropdown-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}
.user-dropdown-item.logout:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
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
    width: min(82vw, 300px);
    min-width: 0;
    padding-top: var(--safe-top);
    padding-left: var(--safe-left);
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
    width: min(82vw, 300px) !important;
    min-width: 0 !important;
  }
  .sidebar-collapsed .brand-name { display: block; }
  .sidebar-collapsed .nav-group-label { display: block; }
  .sidebar-collapsed .nav-text { display: block; }
  .sidebar-collapsed .status-label { display: block; }

  /* Show hamburger */
  .hamburger { display: flex; }

  /* Topbar adjustments */
  .topbar {
    padding: 0 12px;
    padding-top: var(--safe-top);
    height: calc(var(--topbar-h) + var(--safe-top));
    min-height: calc(var(--topbar-h) + var(--safe-top));
  }
  .topbar-time { display: none; }
  .market-label { display: none; }
  .market-status { padding: 3px 6px; }
  .user-name { display: none; }

  /* Page content: leave room for bottom nav + safe area */
  .page-content {
    padding-bottom: calc(56px + var(--safe-bottom));
  }

  /* Show bottom nav */
  .bottom-nav {
    display: flex;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: calc(56px + var(--safe-bottom));
    padding-bottom: var(--safe-bottom);
    background: var(--bg-surface);
    border-top: 1px solid var(--border);
    z-index: 50;
    box-shadow: 0 -4px 16px rgba(15,23,42,0.12);
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

/* ── 产业链投研 · 完成提醒 toast ── */
.ir-toast {
  position: fixed; right: 24px; bottom: 24px; z-index: 3000;
  display: flex; align-items: center; gap: 12px;
  max-width: 380px; padding: 14px 16px;
  background: var(--bg-surface); border: 1px solid var(--border-light);
  border-radius: 12px; box-shadow: 0 8px 28px rgba(15,23,42,0.12);
}
.ir-toast.done { border-color: rgba(22,163,74,0.45); }
.ir-toast.error { border-color: rgba(220,38,38,0.45); }
.ir-toast-icon { font-size: 22px; }
.ir-toast-body { flex: 1; }
.ir-toast-title { font-weight: 600; font-size: 14px; color: var(--text-1); }
.ir-toast-sub { font-size: 12px; color: var(--text-3); margin-top: 3px; }
.ir-toast-btn {
  padding: 6px 14px; border: none; border-radius: 8px;
  background: var(--accent); color: #fff; font-weight: 600; cursor: pointer; font-size: 13px;
}
.ir-toast-close { background: none; border: none; color: var(--text-3); font-size: 20px; cursor: pointer; line-height: 1; }
.ir-toast-fade-enter-active, .ir-toast-fade-leave-active { transition: all .3s ease; }
.ir-toast-fade-enter-from, .ir-toast-fade-leave-to { opacity: 0; transform: translateY(12px); }
</style>
