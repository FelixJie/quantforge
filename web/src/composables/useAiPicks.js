// 后台「AI 每日荐股」逻辑：查看状态、手动重跑、历次生成记录，支持按策略切换。
import { ref, computed, onUnmounted } from 'vue'
import axios from 'axios'

export function useAiPicks() {
  const status = ref({})
  const strategy = ref('momentum')   // 当前选中的策略键
  // 可重跑的全部策略（从后端动态拉取，兜底内置四种，新增策略后台自动出现）
  const strategies = ref([
    { key: 'momentum', label: '动能买点' },
    { key: 'pring', label: '普林格KST周期' },
    { key: 'ultra', label: '超短量价' },
    { key: 'probe', label: '试盘点' },
  ])
  const history = ref([])
  const busy = ref(false)
  const msg = ref('')
  const msgType = ref('')
  let timer = null
  let _wasRunning = false             // 侦测「跑完」以刷新生成记录

  const strategyLabel = computed(() =>
    strategies.value.find(s => s.key === strategy.value)?.label || strategy.value
  )

  async function loadStrategies() {
    try {
      const { data } = await axios.get('/api/ai-picks/strategies')
      if (Array.isArray(data.strategies) && data.strategies.length) {
        strategies.value = data.strategies
      }
    } catch (e) { /* 静默：保留内置兜底 */ }
  }

  async function loadStatus() {
    try {
      const { data } = await axios.get('/api/admin/ai-picks/status', {
        params: { strategy: strategy.value },
      })
      // 由「进行中」转「结束」时产出已落盘，刷新一次生成记录
      if (_wasRunning && !data.running) loadHistory()
      _wasRunning = !!data.running
      status.value = data
    } catch (e) { /* 静默：保留上次数据 */ }
  }

  async function loadHistory() {
    try {
      const { data } = await axios.get('/api/admin/ai-picks/history', {
        params: { strategy: strategy.value },
      })
      history.value = data.history || []
    } catch (e) { /* 静默 */ }
  }

  async function onStrategyChange() {
    await Promise.all([loadStatus(), loadHistory()])
  }

  function ensurePoll() {
    if (timer) return
    timer = setInterval(() => { if (!document.hidden) loadStatus() }, 3000)
  }
  function stopPoll() {
    if (timer) { clearInterval(timer); timer = null }
  }

  async function refresh() {
    if (busy.value || status.value.running) return
    busy.value = true
    msg.value = ''
    try {
      const { data } = await axios.post('/api/admin/ai-picks/refresh', null, {
        params: { force: true, strategy: strategy.value },
      })
      if (data.status === 'started') {
        msg.value = data.message || 'AI 分析已在后台启动，约 1 分钟后完成'
        msgType.value = 'ok'
        _wasRunning = true
      } else {
        msg.value = data.message || '无法启动'
        msgType.value = data.status === 'already_running' ? 'err' : 'ok'
      }
      await loadStatus()
    } catch (e) {
      msg.value = '重跑失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    } finally {
      busy.value = false
    }
  }

  function init() {
    loadStrategies()
    loadStatus()
    loadHistory()
    ensurePoll()
  }

  onUnmounted(stopPoll)

  return {
    status, strategy, strategies, history, busy, msg, msgType, strategyLabel,
    init, onStrategyChange, refresh,
  }
}
