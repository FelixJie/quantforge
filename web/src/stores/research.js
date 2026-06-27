// 产业链投研 — 全局任务跟踪（后台跑 + 完成提醒）
// 单例 reactive store：即使离开「产业链投研」页面，也持续轮询后台分析任务，
// 完成后弹出全局提醒。状态用 localStorage 持久化，刷新页面后仍可恢复跟踪。
import { reactive } from 'vue'
import axios from 'axios'

const LS = 'ir-pending-jobs'

function loadPending() {
  try { return JSON.parse(localStorage.getItem(LS) || '[]') } catch { return [] }
}

export const research = reactive({
  pending: loadPending(),   // [{ slug, keyword, startedAt }]
  progress: {},             // slug -> { status, stage, progress, report_count, pdf_count, error }
  toast: null,              // { slug, keyword, type: 'done'|'error', msg }
  openSlug: null,           // 请求在看板中打开某个 slug
})

function persist() {
  try { localStorage.setItem(LS, JSON.stringify(research.pending)) } catch {}
}

let timer = null
function ensurePoll() {
  if (timer) return
  timer = setInterval(poll, 2000)
  poll()
}

async function poll() {
  if (!research.pending.length) { clearInterval(timer); timer = null; return }
  for (const job of [...research.pending]) {
    try {
      const { data } = await axios.get(`/api/research/keyword-status/${job.slug}`)
      research.progress[job.slug] = data
      if (data.status === 'done') {
        remove(job.slug)
        research.toast = { slug: job.slug, keyword: job.keyword, type: 'done' }
      } else if (data.status === 'error') {
        remove(job.slug)
        research.toast = { slug: job.slug, keyword: job.keyword, type: 'error', msg: data.error }
      } else if (data.status === 'cancelled') {
        // 用户主动中断：停止跟踪，给一个轻提示（复用 error 通道的弱样式即可）
        remove(job.slug)
        research.toast = { slug: job.slug, keyword: job.keyword, type: 'cancelled', msg: '已中断' }
      } else if (data.status === 'not_found') {
        // 任务在服务端丢失（如重启）：超过 15 分钟则放弃跟踪
        if (Date.now() - job.startedAt > 15 * 60 * 1000) remove(job.slug)
      }
    } catch (e) { /* 网络抖动，下次再试 */ }
  }
}

function remove(slug) {
  research.pending = research.pending.filter(j => j.slug !== slug)
  persist()
}

export function startTracking(slug, keyword) {
  if (!research.pending.find(j => j.slug === slug)) {
    research.pending.push({ slug, keyword, startedAt: Date.now() })
    persist()
  }
  research.progress[slug] = { status: 'running', stage: '初始化', progress: 2 }
  ensurePoll()
}

export function dismissToast() { research.toast = null }
export function requestOpen(slug) { research.openSlug = slug }
export function isTracking(slug) { return !!research.pending.find(j => j.slug === slug) }

// 应用加载时若有未完成任务，自动恢复跟踪
if (research.pending.length) ensurePoll()
