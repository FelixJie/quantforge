// 后台「公众号(纷传)扫码授权」逻辑：拉取二维码、轮询扫码状态、维护授权态。
import { ref, onUnmounted } from 'vue'
import axios from 'axios'

export function useFenchuan() {
  const status = ref({ token_set: false, updated_at: 0, count: 0 })
  const qr = ref('')               // 二维码 data URL
  const scene = ref('')
  const state = ref('')            // '' | 'pending' | 'done' | 'register' | 'expired'
  const loadingQr = ref(false)
  const msg = ref('')
  const msgType = ref('')          // 'ok' | 'err'
  let pollTimer = null
  let attempts = 0                 // 单张二维码最多轮询次数，超时即判失效

  async function loadStatus() {
    try {
      const { data } = await axios.get('/api/fenchuan/status')
      status.value = data
    } catch (e) { /* 静默 */ }
  }

  function stopPoll() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
  }

  async function startQr() {
    if (loadingQr.value) return
    stopPoll()
    loadingQr.value = true
    state.value = ''
    msg.value = ''
    qr.value = ''
    try {
      const { data } = await axios.post('/api/fenchuan/qr/start')
      if (!data.ok) {
        msg.value = data.error || '获取二维码失败'
        msgType.value = 'err'
        return
      }
      qr.value = data.qr
      scene.value = data.scene
      state.value = 'pending'
      attempts = 0
      msg.value = '请用微信扫码…'
      msgType.value = 'ok'
      poll()
    } catch (e) {
      msg.value = e.response?.status === 403
        ? '无权操作：仅管理员可授权。'
        : '获取二维码失败：' + (e.response?.data?.detail || e.message)
      msgType.value = 'err'
    } finally {
      loadingQr.value = false
    }
  }

  function poll() {
    stopPoll()
    // 二维码约 5 分钟有效（100×3s），超时自动判失效
    if (attempts >= 100) {
      state.value = 'expired'
      msg.value = '二维码已超时，请刷新'
      msgType.value = 'err'
      return
    }
    pollTimer = setTimeout(async () => {
      attempts++
      try {
        const { data } = await axios.get('/api/fenchuan/qr/poll', { params: { scene: scene.value } })
        if (data.state === 'done') {
          state.value = 'done'
          msg.value = '✅ 授权成功，公众号内容将自动更新'
          msgType.value = 'ok'
          await loadStatus()
          return
        }
        if (data.state === 'register') {
          state.value = 'register'
          msg.value = data.error || '该微信尚未注册纷传'
          msgType.value = 'err'
          return
        }
        if (data.state === 'expired') {
          state.value = 'expired'
          msg.value = data.error || '二维码已失效，请刷新'
          msgType.value = 'err'
          return
        }
        poll()  // pending
      } catch (e) {
        poll()  // 网络抖动，继续轮询
      }
    }, 3000)
  }

  onUnmounted(stopPoll)

  return { status, qr, state, loadingQr, msg, msgType, loadStatus, startQr }
}
