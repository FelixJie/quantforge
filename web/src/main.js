import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import ECharts from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, CandlestickChart, BarChart, TreemapChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
} from 'echarts/components'
import axios from 'axios'

import './assets/global.css'

import App from './App.vue'
import AuthView from './views/AuthView.vue'
import Dashboard from './views/Dashboard.vue'
import BacktestView from './views/BacktestView.vue'
import MarketView from './views/MarketView.vue'
import LiveView from './views/LiveView.vue'
import OptimizerView from './views/OptimizerView.vue'
import ScreenerView from './views/ScreenerView.vue'
import NewsView from './views/NewsView.vue'
import SectorView from './views/SectorView.vue'
import AiPicksView from './views/AiPicksView.vue'
import NotificationView from './views/NotificationView.vue'
import LlmStatsView from './views/LlmStatsView.vue'
import StockAnalysisView from './views/StockAnalysisView.vue'
import VerifyView from './views/VerifyView.vue'
import VerifyDetailView from './views/VerifyDetailView.vue'
import MarketHubView from './views/MarketHubView.vue'
import AccountView from './views/AccountView.vue'
import WatchlistView from './views/WatchlistView.vue'
import WatchlistVerifyView from './views/WatchlistVerifyView.vue'
import StockDetailView from './views/StockDetailView.vue'
import ResearchView from './views/ResearchView.vue'
import CapitalFlowView from './views/CapitalFlowView.vue'
import SignalHubView from './views/SignalHubView.vue'
import IndustryResearchDashboard from './views/IndustryResearchDashboard.vue'
import { useAuthStore } from './stores/auth'

use([
  CanvasRenderer, LineChart, CandlestickChart, BarChart, TreemapChart,
  GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, TitleComponent, MarkLineComponent, MarkPointComponent,
])

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/auth', component: AuthView },
    { path: '/', component: Dashboard },
    { path: '/market-hub', component: MarketHubView },
    { path: '/market', component: MarketView },
    { path: '/stock-analysis', component: StockAnalysisView },
    { path: '/news', component: NewsView },
    { path: '/sector', component: SectorView },
    { path: '/ai-picks', component: AiPicksView },
    { path: '/verify', component: VerifyView },
    { path: '/verify-detail', component: VerifyDetailView },
    { path: '/screener', component: ScreenerView },
    { path: '/backtest', component: BacktestView },
    { path: '/optimizer', component: OptimizerView },
    { path: '/live', component: LiveView },
    { path: '/account', component: AccountView },
    { path: '/notification', component: NotificationView },
    { path: '/llm-stats', component: LlmStatsView },
    { path: '/watchlist', component: WatchlistView },
    { path: '/watchlist-verify', component: WatchlistVerifyView },
    { path: '/stock-detail', component: StockDetailView },
    { path: '/research', component: ResearchView },
    { path: '/capital', component: CapitalFlowView },
    { path: '/signal', component: SignalHubView },
    { path: '/industry-research', component: IndustryResearchDashboard },
    // Legacy redirects
    { path: '/predictions', redirect: '/verify' },
    { path: '/strategy', redirect: '/screener' },
    { path: '/yaml-strategy', redirect: '/screener' },
    { path: '/editor', redirect: '/screener' },
  ],
})

const pinia = createPinia()
const app = createApp(App)
app.use(pinia)
app.use(router)
app.component('v-chart', ECharts)

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

  next()
})

app.mount('#app')
