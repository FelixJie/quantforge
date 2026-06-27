import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import axios from 'axios'

import './assets/global.css'

import App from './App.vue'
// 首屏两页同步加载(登录/首页),其余路由全部懒加载切 chunk,
// 缩小首包体积(ECharts 等重依赖只在用到的页面才下载)。
import AuthView from './views/AuthView.vue'
import Dashboard from './views/Dashboard.vue'
import { useAuthStore } from './stores/auth'

// ── API 基地址 ──────────────────────────────────────────────
// Web(浏览器/dev/部署):空串 → 走相对 /api,由 Vite 代理或 nginx 转发。
// 手机 App(Capacitor):页面从 localhost 本地文件加载,相对 /api 失效,
// 必须指向云端绝对地址。由 .env 的 VITE_API_BASE 注入(见 web/.env.app)。
const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

// axios:所有 axios.get('/api/...') 自动加前缀
axios.defaults.baseURL = API_BASE

// fetch:6 处流式/直取接口用的是原生 fetch,不吃 axios 配置,
// 在此包一层,把根相对的 /api 请求改写到云端,并自动带上鉴权头。
if (API_BASE && typeof window !== 'undefined' && window.fetch) {
  const _origFetch = window.fetch.bind(window)
  window.fetch = (input, init = {}) => {
    try {
      let url = typeof input === 'string' ? input : input?.url
      if (typeof url === 'string' && url.startsWith('/api')) {
        const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined))
        const token = useAuthStore().token
        if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
        if (typeof input === 'string') {
          return _origFetch(API_BASE + url, { ...init, headers })
        }
        return _origFetch(new Request(API_BASE + url, input), { ...init, headers })
      }
    } catch (e) { /* 回退到原生 fetch */ }
    return _origFetch(input, init)
  }
}

const BacktestView = () => import('./views/BacktestView.vue')
const ScreenerView = () => import('./views/ScreenerView.vue')
const AiPicksView = () => import('./views/AiPicksView.vue')
const QuarterlyView = () => import('./views/QuarterlyView.vue')
const LlmStatsView = () => import('./views/LlmStatsView.vue')
const VerifyView = () => import('./views/VerifyView.vue')
const VerifyDetailView = () => import('./views/VerifyDetailView.vue')
const MarketHubView = () => import('./views/MarketHubView.vue')
const WatchlistView = () => import('./views/WatchlistView.vue')
const StockCompareView = () => import('./views/StockCompareView.vue')
const IndustryResearchDashboard = () => import('./views/IndustryResearchDashboard.vue')
const BlogView = () => import('./views/BlogView.vue')
const FenchuanView = () => import('./views/FenchuanView.vue')
const FeishuView = () => import('./views/FeishuView.vue')
const ReportsView = () => import('./views/ReportsView.vue')
const ClsTelegraphView = () => import('./views/ClsTelegraphView.vue')
const StockPage = () => import('./views/StockPage.vue')
const ChatView = () => import('./views/ChatView.vue')
const AdminView = () => import('./views/AdminView.vue')
// 晨报 + 复盘合并为「每日报告」单页（内部标签切换）；旧 MorningView/ReviewView 保留备用。
const DailyReportView = () => import('./views/DailyReportView.vue')
const PriceSurgeView = () => import('./views/PriceSurgeView.vue')

// ECharts 不在此全局注册：图表页各自 `import VChart from './charts'`，
// 避免 echarts 进首包（见 src/charts.js）。

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/auth', component: AuthView },
    { path: '/', component: Dashboard },
    { path: '/report', component: DailyReportView },
    { path: '/morning', component: DailyReportView },
    { path: '/review', component: DailyReportView },
    { path: '/market-hub', component: MarketHubView },
    // 个股详情副页（内容区整页切换，带返回按钮，侧边栏无入口）
    { path: '/stock/:code', component: StockPage },
    // 旧深链兼容 → 副页
    { path: '/stock-analysis', redirect: to => ({ path: `/stock/${to.query.symbol || ''}` }) },
    { path: '/stock-detail', redirect: to => ({ path: `/stock/${to.query.symbol || ''}` }) },
    { path: '/market', redirect: '/market-hub' },
    { path: '/news', redirect: '/cls' },
    { path: '/cls', component: ClsTelegraphView },
    // 行业板块已并入市场总览（独立 Tab），旧入口重定向到该 Tab
    { path: '/sector', redirect: '/market-hub?tab=sector' },
    { path: '/ai-picks', component: AiPicksView },
    { path: '/quarterly', component: QuarterlyView },
    { path: '/chat', component: ChatView },
    { path: '/verify', component: VerifyView },
    { path: '/verify-detail', component: VerifyDetailView },
    { path: '/screener', component: ScreenerView },
    { path: '/backtest', component: BacktestView },
    { path: '/optimizer', redirect: '/backtest' },
    { path: '/live', redirect: '/backtest' },
    { path: '/llm-stats', component: LlmStatsView },
    { path: '/watchlist', component: WatchlistView },
    { path: '/stock-compare', component: StockCompareView },
    { path: '/industry-research', component: IndustryResearchDashboard },
    { path: '/blog', component: BlogView },
    { path: '/fenchuan', component: FenchuanView },
    { path: '/feishu', component: FeishuView },
    { path: '/reports', component: ReportsView },
    // 管理后台 —— 仅 admin 账号可进入（路由守卫 + 后端 403 双重拦截）
    { path: '/admin', component: AdminView, meta: { requiresAdmin: true } },
    { path: '/price-surge', component: PriceSurgeView },
    // Legacy redirects
    { path: '/predictions', redirect: '/verify' },
    { path: '/strategy', redirect: '/screener' },
    { path: '/yaml-strategy', redirect: '/screener' },
    { path: '/editor', redirect: '/screener' },
    { path: '/research', redirect: '/' },
    { path: '/capital', redirect: '/' },
    { path: '/signal', redirect: '/' },
    { path: '/watchlist-verify', redirect: '/verify' },
  ],
})

const pinia = createPinia()
const app = createApp(App)
app.use(pinia)
app.use(router)

const authStore = useAuthStore()

// Configure axios
axios.interceptors.request.use(
  (config) => {
    const token = authStore.token
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

axios.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response && error.response.status === 401) {
      authStore.logout()
      router.push('/auth')
    }
    return Promise.reject(error)
  }
)

// Route guard
router.beforeEach(async (to, from, next) => {
  const isAuthPage = to.path === '/auth'
  const isAuthenticated = authStore.isAuthenticated

  if (!isAuthenticated && !isAuthPage) {
    const isValid = await authStore.checkAuth()
    if (!isValid) {
      next('/auth')
      return
    }
  }

  if (isAuthenticated && isAuthPage) {
    next('/')
    return
  }

  // 管理后台守卫：非管理员账号直接弹回首页（后端也会 403 兜底）
  if (to.meta?.requiresAdmin && !authStore.isAdmin) {
    next('/')
    return
  }

  next()
})

app.mount('#app')
