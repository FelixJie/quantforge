// 后台「产业链研报精读」逻辑：启动分析、轮询进度、每日定时关键词清单、已生成报告增删查。
// 从 AdminView 抽出，让视图只管渲染。
import { ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { startTracking, requestOpen } from '../stores/research'

export function useResearch() {
  const router = useRouter()

  const keyword = ref('')          // 单关键词输入框（兼容旧用法 / 关键词录入框）
  const name = ref('')             // 命名主题：分析名称（可选）
  const kwList = ref([])           // 命名主题：已添加的关键词清单
  const limit = ref(0)
  const busy = ref(false)
  const msg = ref('')
  const msgType = ref('')          // 'ok' | 'err'
  const running = ref([])          // [{ slug, keyword, stage, progress, ... }]
  const queue = ref([])            // 等待队列 [{ slug, keyword, position, enqueued_at }]
  const reports = ref([])
  const maxConcurrent = ref(3)     // 并行上限（由后端 jobs 接口同步）
  const dailyKeywords = ref([])    // 每日定时清单 [{ keyword, slug, manual }]（默认含全部历史报告）
  const excludedCount = ref(0)     // 已移除（排除）项数量
  const newDaily = ref('')
  const dailyBusy = ref(false)
  const cancelling = ref({})       // slug -> true：已点过中断，等服务端落终态
  let timer = null

  async function loadJobs() {
    try {
      const { data } = await axios.get('/api/admin/research/jobs')
      running.value = data.running || []
      queue.value = data.queue || []
      reports.value = data.reports || []
      if (data.max_concurrent) maxConcurrent.value = data.max_concurrent
      // 已离开运行列表（落终态）的 slug 清掉「取消中」标记
      const live = new Set(running.value.map(j => j.slug))
      const next = {}
      for (const s of Object.keys(cancelling.value)) if (live.has(s)) next[s] = true
      cancelling.value = next
    } catch (e) { /* 静默：保留上次数据 */ }
  }

  function applyDailyData(data) {
    dailyKeywords.value = data.keywords || []
    excludedCount.value = data.excluded_count || 0
  }

  async function loadDailyKeywords() {
    try {
      const { data } = await axios.get('/api/admin/research/daily-keywords')
      applyDailyData(data)
    } catch (e) { /* 静默 */ }
  }

  async function addDailyKeyword() {
    const kw = newDaily.value.trim()
    if (!kw || dailyBusy.value) return
    dailyBusy.value = true
    try {
      const { data } = await axios.post('/api/admin/research/daily-keywords', null, {
        params: { keyword: kw },
      })
      applyDailyData(data)
      newDaily.value = ''
    } catch (e) {
      msg.value = '添加失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    } finally {
      dailyBusy.value = false
    }
  }

  function isDailyKeyword(slug) {
    return dailyKeywords.value.some(k => k.slug === slug)
  }

  // 一键纳入全部历史：清空「已移除」集合，让所有已生成报告主题重新进入每日定时
  async function includeAllDaily() {
    if (dailyBusy.value) return
    if (excludedCount.value && !confirm(`恢复之前移除的 ${excludedCount.value} 个主题，并把全部历史报告纳入每日定时？`)) return
    dailyBusy.value = true
    try {
      const { data } = await axios.post('/api/admin/research/daily-keywords/include-all')
      applyDailyData(data)
      msg.value = data.restored_count ? `已恢复 ${data.restored_count} 个，当前共 ${data.count} 个每日定时` : `全部已纳入，当前共 ${data.count} 个`
      msgType.value = 'ok'
    } catch (e) {
      msg.value = '一键纳入失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    } finally {
      dailyBusy.value = false
    }
  }

  async function removeDailyKeyword(k) {
    if (!confirm(`将「${k.keyword}」移出每日定时？移出后即使有报告也不再自动重跑（可用「一键纳入全部历史」恢复）。`)) return
    try {
      const { data } = await axios.delete(`/api/admin/research/daily-keywords/${encodeURIComponent(k.keyword)}`)
      applyDailyData(data)
    } catch (e) {
      msg.value = '移除失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    }
  }

  // 报告行的「每日」开关：已在每日 → 移出；不在 → 加入
  async function toggleDailyForReport(r) {
    const kw = r.display_name || r.keyword
    if (!kw) return
    if (isDailyKeyword(r.slug)) {
      await removeDailyKeyword({ keyword: kw })
    } else {
      try {
        const { data } = await axios.post('/api/admin/research/daily-keywords', null, { params: { keyword: kw } })
        applyDailyData(data)
      } catch (e) {
        msg.value = '加入每日失败：' + (e.response?.data?.detail || e.message)
        msgType.value = 'err'
      }
    }
  }

  function ensurePoll() {
    if (timer) return
    timer = setInterval(() => { if (!document.hidden) loadJobs() }, 3000)
  }
  function stopPoll() {
    if (timer) { clearInterval(timer); timer = null }
  }

  // 把输入框里的文本按分隔符拆成关键词加入清单（支持逗号/、/空格/换行 一次加多个）
  function addKeyword() {
    const parts = (keyword.value || '').split(/[,，、\s]+/).map(s => s.trim()).filter(Boolean)
    for (const p of parts) if (!kwList.value.includes(p)) kwList.value.push(p)
    keyword.value = ''
  }
  function removeKeyword(k) {
    kwList.value = kwList.value.filter(x => x !== k)
  }

  async function start() {
    if (busy.value) return
    // 收集关键词：已添加的清单 + 输入框里尚未回车的残留文本
    const pending = (keyword.value || '').split(/[,，、\s]+/).map(s => s.trim()).filter(Boolean)
    let kws = [...new Set([...kwList.value, ...pending])]
    // 未填关键词但填了分析名称：默认用分析名称作为检索关键词
    if (!kws.length && name.value.trim()) kws = [name.value.trim()]
    if (!kws.length) { msg.value = '请至少添加一个关键词或填写分析名称'; msgType.value = 'err'; return }
    const display = (name.value || '').trim() || kws[0]
    busy.value = true
    msg.value = ''
    try {
      const { data } = await axios.post('/api/admin/research/analyze', null, {
        params: { name: name.value.trim(), keywords: kws.join(','), read_limit: limit.value },
      })
      if (data.status === 'started') {
        msg.value = data.message || '已在后台启动'
        msgType.value = 'ok'
        keyword.value = ''; name.value = ''; kwList.value = []
        startTracking(data.slug, display)   // 复用全局研报跟踪，完成后弹全局提醒
      } else if (data.status === 'queued' || data.status === 'already_queued') {
        // 并发已满 → 已排进等待队列，有空闲名额自动开始
        msg.value = data.message || '已加入排队队列'
        msgType.value = 'ok'
        keyword.value = ''; name.value = ''; kwList.value = []
      } else {
        msg.value = data.message || '无法启动'
        msgType.value = 'err'
      }
      await loadJobs()
      ensurePoll()
    } catch (e) {
      msg.value = '启动失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    } finally {
      busy.value = false
    }
  }

  async function cancel(job) {
    const already = !!cancelling.value[job.slug]
    // 首次点击=正常中断；已在「取消中」时再点=强制结束（兜底僵尸/卡死任务）
    const tip = already
      ? `「${job.keyword}」迟迟没停下？强制结束会立即清掉该任务（已生成报告不受影响）。`
      : `确定中断「${job.keyword}」的分析？已采集/已精读的部分会保留，本轮不再生成新报告。`
    if (!confirm(tip)) return
    cancelling.value = { ...cancelling.value, [job.slug]: true }
    try {
      await axios.post(`/api/admin/research/cancel/${encodeURIComponent(job.slug)}`,
        null, { params: { force: already } })
      await loadJobs()
    } catch (e) {
      msg.value = '中断失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
      if (!already) { const m = { ...cancelling.value }; delete m[job.slug]; cancelling.value = m }
    }
  }

  async function dequeue(item) {
    if (!confirm(`将「${item.keyword}」移出等待队列？`)) return
    try {
      await axios.delete(`/api/admin/research/queue/${encodeURIComponent(item.slug)}`)
      await loadJobs()
    } catch (e) {
      msg.value = '移除失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    }
  }

  // 调整排队优先级：direction = up/down/top/bottom（队首=下一个开跑）
  async function moveQueue(item, direction) {
    try {
      await axios.post(`/api/admin/research/queue/${encodeURIComponent(item.slug)}/move`,
        null, { params: { direction } })
      await loadJobs()
    } catch (e) {
      msg.value = '调整顺序失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    }
  }

  function viewReport(r) {
    requestOpen(r.slug)
    window.open(router.resolve({ path: '/industry-research', query: { slug: r.slug } }).href, '_blank')
  }

  // 重试一条失败记录：用其关键词重新启动分析（成功后失败记录会被后端清除）
  async function retryReport(r) {
    const kw = r.keyword || r.display_name
    if (!kw) return
    try {
      const { data } = await axios.post('/api/admin/research/analyze', null, {
        params: { keyword: kw, read_limit: 0 },
      })
      if (data.status === 'started') {
        msg.value = `已重新启动「${kw}」的分析`
        msgType.value = 'ok'
        startTracking(data.slug, kw)
        ensurePoll()
      } else {
        msg.value = data.message || '无法启动'
        msgType.value = 'err'
      }
      await loadJobs()
    } catch (e) {
      msg.value = '重试失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    }
  }

  async function deleteReport(r) {
    if (!confirm(`确定删除「${r.display_name || r.keyword}」的分析报告？`)) return
    try {
      await axios.delete(`/api/admin/research/jobs/${r.slug}`)
      await loadJobs()
    } catch (e) {
      msg.value = '删除失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    }
  }

  function init() {
    loadJobs()
    loadDailyKeywords()
    ensurePoll()
  }

  onUnmounted(stopPoll)

  return {
    keyword, name, kwList, limit, busy, msg, msgType, running, queue, reports, maxConcurrent,
    dailyKeywords, excludedCount, newDaily, dailyBusy, cancelling,
    init, loadJobs, addKeyword, removeKeyword, addDailyKeyword, isDailyKeyword, removeDailyKeyword,
    includeAllDaily, toggleDailyForReport,
    start, viewReport, deleteReport, retryReport, cancel, dequeue, moveQueue,
  }
}
