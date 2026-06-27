<template>
  <div class="chat-view">
    <!-- ══ 会话历史侧栏 ══ -->
    <aside class="session-pane" :class="{ collapsed: paneCollapsed }">
      <div class="pane-head">
        <button class="btn new-chat" @click="newChat" :disabled="streaming">+ 新对话</button>
      </div>
      <div class="session-list">
        <div
          v-for="s in sessions" :key="s.id"
          class="session-item" :class="{ active: s.id === currentId }"
          @click="switchSession(s.id)"
        >
          <input v-if="renamingId === s.id" v-model="renameDraft" class="s-rename"
                 placeholder="会话名称" @click.stop
                 @keyup.enter="confirmRename(s)" @keyup.esc="renamingId = ''"
                 @blur="confirmRename(s)" />
          <div v-else class="s-title" @dblclick.stop="startRename(s)">{{ s.title || '新对话' }}</div>
          <div class="s-meta">{{ fmtTime(s.updated) }} · {{ s.messages.length }} 条</div>
          <button class="s-ren" title="重命名" @click.stop="startRename(s)">✎</button>
          <button class="s-del" title="删除" @click.stop="deleteSession(s.id)">×</button>
        </div>
        <div v-if="sessions.length === 0" class="pane-empty">暂无历史</div>
      </div>
    </aside>

    <!-- ══ 主对话区 ══ -->
    <div class="chat-main">
      <div class="chat-header">
        <div class="header-left">
          <button class="icon-btn" @click="paneCollapsed = !paneCollapsed" title="历史会话">☰</button>
          <h2 class="chat-title">AI 对话</h2>
          <span class="subtitle">聊股票 · 自动带行情/技术面/K线/机构预期/板块/研报</span>
        </div>
        <div class="header-right">
          <button v-if="curMessages.length" class="icon-btn" @click="exportChat"
                  title="导出对话为 Markdown">⬇</button>
          <label class="toggle">
            <input type="checkbox" v-model="useQuotes" @change="persistPrefs" />
            <span>带数据库分析</span>
          </label>
          <label class="toggle" title="勾选后问个股会实时抓取最新新闻/公告（联网，略慢）">
            <input type="checkbox" v-model="useWeb" @change="persistPrefs" />
            <span>查询外网</span>
          </label>
          <label class="toggle" title="多步结构化深度分析（更全面，回复更长更慢）">
            <input type="checkbox" v-model="useDeep" @change="persistPrefs" />
            <span>深度分析</span>
          </label>
        </div>
      </div>

      <div class="messages" ref="msgBox" @scroll="onScroll">
        <div v-if="curMessages.length === 0" class="empty">
          <div class="empty-icon">💬</div>
          <p>问我点关于 A 股的事吧</p>
          <div class="quick-grid">
            <div v-for="g in quickStarts" :key="g.cat" class="quick-cat">
              <div class="quick-cat-title">{{ g.cat }}</div>
              <button class="chip" v-for="ex in g.items" :key="ex" @click="send(ex)">{{ ex }}</button>
            </div>
          </div>
        </div>

        <div
          v-for="(m, i) in curMessages" :key="i"
          class="msg" :class="m.role"
        >
          <template v-if="m.role === 'user'">
            <div v-if="editingIdx === i" class="user-edit">
              <textarea v-model="editDraft" class="edit-area" rows="2"
                        @keydown.enter.exact.prevent="confirmEdit(i)"
                        @keydown.esc="cancelEdit"></textarea>
              <div class="edit-actions">
                <button class="act-btn primary" :disabled="!editDraft.trim() || streaming"
                        @click="confirmEdit(i)">重新提问</button>
                <button class="act-btn" @click="cancelEdit">取消</button>
              </div>
            </div>
            <div v-else class="bubble user-bubble">
              <span class="user-text">{{ m.content }}</span>
              <button v-if="!streaming" class="user-edit-btn" title="编辑并重新提问"
                      @click="startEdit(i, m)">✎</button>
            </div>
          </template>
          <template v-else>
            <div class="bubble assistant-bubble">
              <!-- 首 token 前显示思考动画，避免空气泡像卡死 -->
              <div v-if="!m.content && streaming && i === curMessages.length - 1" class="thinking">
                <span></span><span></span><span></span>
              </div>
              <div v-else v-html="renderMarkdown(m.content)"></div>

              <!-- 对话内出图：识别到的个股迷你日K（答完后出现） -->
              <div v-if="m.stocks && m.stocks.length && m.content && !(streaming && i === curMessages.length - 1)" class="msg-charts">
                <ChatStockChart v-for="c in m.stocks" :key="c" :code="c" />
              </div>

              <!-- 来源溯源：本轮实际用到的数据来源 -->
              <div v-if="m.sources && m.sources.length && m.content && !(streaming && i === curMessages.length - 1)" class="msg-sources">
                <span class="src-label">数据来源</span>
                <span class="src-tag" v-for="s in m.sources" :key="s">{{ s }}</span>
              </div>

              <!-- 操作条：仅在该条已完成(非正在流式)时显示 -->
              <div v-if="m.content && !(streaming && i === curMessages.length - 1)" class="msg-actions">
                <button class="act-btn" @click="copyMsg(m, i)" :title="copiedIdx === i ? '已复制' : '复制'">
                  {{ copiedIdx === i ? '✓ 已复制' : '复制' }}
                </button>
                <button
                  v-if="i === curMessages.length - 1"
                  class="act-btn" @click="regenerate" :disabled="streaming" title="重新生成"
                >重新生成</button>
              </div>

              <!-- 推荐下个问题：点一下直接发送 -->
              <div v-if="m.suggestions && m.suggestions.length && !(streaming && i === curMessages.length - 1)" class="msg-followups">
                <div class="followup-label">💡 接着可以问</div>
                <div class="followup-chips">
                  <button
                    v-for="(s, si) in m.suggestions" :key="si"
                    class="followup-chip" :disabled="streaming" @click="send(s)"
                  >{{ s }}</button>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <button v-if="showJump" class="jump-bottom" @click="jumpToBottom" title="回到底部">↓ 最新</button>

      <div class="composer">
        <textarea
          v-model="draft"
          class="input"
          :placeholder="streaming ? '回复生成中…' : '输入消息，Enter 发送，Shift+Enter 换行'"
          rows="1"
          @keydown.enter.exact.prevent="onEnter"
          @input="autoGrow"
          ref="inputEl"
          :disabled="streaming"
        ></textarea>
        <button v-if="!streaming" class="btn send" :disabled="!draft.trim()" @click="send()">发送</button>
        <button v-else class="btn stop" @click="stop">停止</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { marked } from 'marked'
import ChatStockChart from '../components/ChatStockChart.vue'

marked.setOptions({ breaks: true, gfm: true })

const SESSIONS_KEY = 'qf_chat_sessions'
const CURRENT_KEY = 'qf_chat_current'
const LEGACY_KEY = 'qf_chat_history'

const sessions = ref([])       // [{id, title, messages:[{role,content}], updated}]
const currentId = ref('')
const draft = ref('')
const streaming = ref(false)
const useQuotes = ref(true)
const useWeb = ref(false)
const useDeep = ref(false)
// 手机屏默认收起会话侧栏，避免挤压对话区
const paneCollapsed = ref(typeof window !== 'undefined' && window.innerWidth <= 768)
const msgBox = ref(null)
const inputEl = ref(null)
const copiedIdx = ref(-1)       // 刚复制的消息下标（短暂高亮"已复制"）
const showJump = ref(false)     // 用户向上翻时显示"回到底部"按钮
let stickToBottom = true        // 是否自动跟随流式滚动（用户上翻则停用）
let abortCtrl = null
let copyTimer = null

const current = computed(() => sessions.value.find(s => s.id === currentId.value) || null)
const curMessages = computed(() => current.value ? current.value.messages : [])

// ── 持久化 ──
function newId() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}
function persist() {
  try { localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions.value.slice(0, 50))) } catch { /* ignore */ }
  try { localStorage.setItem(CURRENT_KEY, currentId.value) } catch { /* ignore */ }
}
function persistPrefs() {
  try { localStorage.setItem('qf_chat_use_quotes', useQuotes.value ? '1' : '0') } catch { /* ignore */ }
  try { localStorage.setItem('qf_chat_use_web', useWeb.value ? '1' : '0') } catch { /* ignore */ }
  try { localStorage.setItem('qf_chat_use_deep', useDeep.value ? '1' : '0') } catch { /* ignore */ }
}
function load() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (raw) sessions.value = JSON.parse(raw) || []
  } catch { sessions.value = [] }

  // 迁移旧单会话历史
  if (sessions.value.length === 0) {
    try {
      const legacy = localStorage.getItem(LEGACY_KEY)
      const msgs = legacy ? JSON.parse(legacy) : []
      if (Array.isArray(msgs) && msgs.length) {
        sessions.value = [mkSession(msgs)]
        localStorage.removeItem(LEGACY_KEY)
      }
    } catch { /* ignore */ }
  }

  const cur = localStorage.getItem(CURRENT_KEY)
  if (cur && sessions.value.some(s => s.id === cur)) {
    currentId.value = cur
  } else if (sessions.value.length) {
    currentId.value = sessions.value[0].id
  } else {
    ensureSession()
  }

  const uq = localStorage.getItem('qf_chat_use_quotes')
  if (uq !== null) useQuotes.value = uq === '1'
  const uw = localStorage.getItem('qf_chat_use_web')
  if (uw !== null) useWeb.value = uw === '1'
  const ud = localStorage.getItem('qf_chat_use_deep')
  if (ud !== null) useDeep.value = ud === '1'
}

function mkSession(messages = []) {
  return {
    id: newId(),
    title: titleFrom(messages),
    messages,
    updated: Date.now(),
  }
}
function titleFrom(messages) {
  const first = messages.find(m => m.role === 'user')
  if (!first) return '新对话'
  return first.content.slice(0, 20)
}
function ensureSession() {
  // 复用置顶的空会话，避免堆一堆空白对话
  const top = sessions.value[0]
  if (top && top.messages.length === 0) {
    currentId.value = top.id
    return
  }
  const s = mkSession()
  sessions.value.unshift(s)
  currentId.value = s.id
  persist()
}
function newChat() {
  if (streaming.value) return
  ensureSession()
  draft.value = ''
  nextTick(() => { autoGrow(); scrollToBottom() })
}
function switchSession(id) {
  if (streaming.value) return
  editingIdx.value = -1
  currentId.value = id
  persist()
  // 手机上选完会话自动收起抽屉
  if (window.innerWidth <= 768) paneCollapsed.value = true
  nextTick(scrollToBottom)
}
function deleteSession(id) {
  if (streaming.value) return
  const idx = sessions.value.findIndex(s => s.id === id)
  if (idx === -1) return
  sessions.value.splice(idx, 1)
  if (currentId.value === id) {
    if (sessions.value.length) currentId.value = sessions.value[0].id
    else ensureSession()
  }
  persist()
}

function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return hm
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

// 仅在用户处于底部附近时跟随流式滚动，避免向上翻看历史时被强行拽回底部。
function scrollToBottom(force = false) {
  if (!force && !stickToBottom) return
  nextTick(() => { const el = msgBox.value; if (el) el.scrollTop = el.scrollHeight })
}
// 距底 < 80px 视为"贴底"，据此决定是否继续跟随；上翻则显示"回到底部"。
function onScroll() {
  const el = msgBox.value
  if (!el) return
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  stickToBottom = nearBottom
  showJump.value = !nearBottom && streaming.value
}
function jumpToBottom() {
  stickToBottom = true
  showJump.value = false
  scrollToBottom(true)
}
function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
function onEnter(e) {
  if (e.isComposing) return
  send()
}

// ── 发送 + 流式接收 ──
async function send(preset) {
  const text = (preset ?? draft.value).trim()
  if (!text || streaming.value) return
  if (!current.value) ensureSession()

  const sess = current.value
  sess.messages.push({ role: 'user', content: text })
  if (!sess.title || sess.title === '新对话') sess.title = titleFrom(sess.messages)
  sess.updated = Date.now()
  // 把活动会话顶到最前
  const idx = sessions.value.indexOf(sess)
  if (idx > 0) { sessions.value.splice(idx, 1); sessions.value.unshift(sess) }

  draft.value = ''
  nextTick(autoGrow)
  const assistant = { role: 'assistant', content: '', stocks: [], sources: [], suggestions: [] }
  sess.messages.push(assistant)
  streaming.value = true
  stickToBottom = true            // 发送新消息时强制贴底
  scrollToBottom(true)
  persist()

  abortCtrl = new AbortController()
  try {
    const token = localStorage.getItem('token') || ''
    const resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        messages: sess.messages.slice(0, -1).map(m => ({ role: m.role, content: m.content })),
        use_quotes: useQuotes.value,
        use_web: useWeb.value,
        deep: useDeep.value,
        session_id: sess.id,
        title: sess.title || '',
      }),
      signal: abortCtrl.signal,
    })
    if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status)

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop()
      for (const part of parts) {
        const line = part.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload) continue
        let obj
        try { obj = JSON.parse(payload) } catch { continue }
        if (obj.delta) {
          assistant.content += obj.delta
          scrollToBottom()
        } else if (obj.meta) {
          // 识别到的个股(画迷你图) + 实际数据来源(溯源标签)
          assistant.stocks = obj.meta.stocks || []
          assistant.sources = obj.meta.sources || []
        } else if (obj.suggestions) {
          assistant.suggestions = obj.suggestions
        } else if (obj.error) {
          assistant.content += `\n\n⚠️ ${obj.error}`
        }
      }
    }
    if (!assistant.content) assistant.content = '（无回复）'
  } catch (e) {
    if (e.name === 'AbortError') {
      if (!assistant.content) assistant.content = '（已停止）'
    } else {
      assistant.content += (assistant.content ? '\n\n' : '') + '⚠️ 请求失败：' + (e.message || e)
    }
  } finally {
    streaming.value = false
    showJump.value = false
    abortCtrl = null
    sess.updated = Date.now()
    persist()
    scrollToBottom()
  }
}

function stop() {
  if (abortCtrl) abortCtrl.abort()
}

// ── Markdown 渲染（marked + GFM：支持表格 / 有序无序列表 / 代码块 / 引用）──
function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch {
    // 解析失败兜底为纯文本转义，绝不抛错中断渲染
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }
}

// ── 复制整条回复 ──
async function copyMsg(m, i) {
  try {
    await navigator.clipboard.writeText(m.content)
  } catch {
    // 退化方案：选区复制
    const ta = document.createElement('textarea')
    ta.value = m.content
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
  copiedIdx.value = i
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => { copiedIdx.value = -1 }, 1500)
}

// ── 重新生成最后一条回复（丢弃旧回复，用同样的上文再问一次）──
function regenerate() {
  if (streaming.value || !current.value) return
  const msgs = current.value.messages
  if (!msgs.length || msgs[msgs.length - 1].role !== 'assistant') return
  msgs.pop()   // 移除上一条 assistant 回复
  const lastUser = msgs.length && msgs[msgs.length - 1].role === 'user'
    ? msgs.pop().content : ''
  persist()
  if (lastUser) send(lastUser)
}

// ── 编辑并重新提问：改某条历史用户消息，截断其后内容、用新问题重新生成 ──
const editingIdx = ref(-1)
const editDraft = ref('')
function startEdit(i, m) {
  if (streaming.value) return
  editingIdx.value = i
  editDraft.value = m.content
}
function cancelEdit() { editingIdx.value = -1; editDraft.value = '' }
function confirmEdit(i) {
  const text = editDraft.value.trim()
  if (!text || streaming.value || !current.value) return
  current.value.messages.splice(i)   // 丢弃这条及其之后的所有消息
  editingIdx.value = -1
  editDraft.value = ''
  persist()
  send(text)
}

// ── 会话重命名 ──
const renamingId = ref('')
const renameDraft = ref('')
function startRename(s) {
  if (streaming.value) return
  renamingId.value = s.id
  renameDraft.value = s.title === '新对话' ? '' : s.title
  nextTick(() => {
    const el = document.querySelector('.s-rename')
    if (el) el.focus()
  })
}
function confirmRename(s) {
  const t = renameDraft.value.trim()
  if (t) { s.title = t; persist() }
  renamingId.value = ''
}

// ── 导出当前会话为 Markdown ──
function exportChat() {
  const s = current.value
  if (!s || !s.messages.length) return
  const lines = [`# ${s.title || 'AI 对话'}`, '', `> 导出于 ${new Date().toLocaleString()}`, '']
  for (const m of s.messages) {
    lines.push(m.role === 'user' ? '## 🙋 我' : '## 🤖 AI')
    lines.push('', m.content || '', '')
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${(s.title || 'chat').slice(0, 20).replace(/[\\/:*?"<>|]/g, '_')}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

// ── 空状态：分类快捷入口（让「个股/板块/选股/自选」能力一眼可发现）──
const quickStarts = [
  { cat: '📊 个股诊断', items: ['贵州茅台现在估值贵吗？对比机构目标价', '分析下 300750 的技术面和资金面'] },
  { cat: '🏭 板块研判', items: ['光伏板块最近怎么看？领涨领跌是哪些', '半导体板块机构怎么看？有哪些主线'] },
  { cat: '🔍 智能选股', items: ['帮我找市盈率低于20、换手率大于5%的股票', '市值500亿以上、今天涨幅超3%的票'] },
  { cat: '⭐ 我的自选', items: ['点评下我的自选股', '我的持仓有什么风险'] },
]

onMounted(() => { load(); scrollToBottom(true) })
</script>

<style scoped>
.chat-view { display: flex; height: 100%; min-height: 0; }

/* ── 会话侧栏 ── */
.session-pane {
  width: 232px; flex-shrink: 0; display: flex; flex-direction: column;
  border-right: 1px solid var(--border, #2a2a35); background: var(--bg-base, #15151b);
  transition: width .18s ease, margin-left .18s ease; overflow: hidden;
}
.session-pane.collapsed { width: 0; margin-left: 0; border-right: none; }
.pane-head { padding: 12px; flex-shrink: 0; }
.new-chat { width: 100%; background: var(--accent, #3b82f6); color: #fff; }
.session-list { flex: 1; overflow-y: auto; padding: 0 8px 12px; }
.session-item {
  position: relative; padding: 10px 28px 10px 12px; border-radius: 8px;
  cursor: pointer; margin-bottom: 4px;
}
.session-item:hover { background: var(--bg-elevated, #1c1c24); }
.session-item.active { background: var(--bg-elevated, #1c1c24); }
.s-title { font-size: 13px; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.s-meta { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.s-del, .s-ren {
  position: absolute; top: 8px; width: 20px; height: 20px;
  border: none; background: transparent; color: var(--text-3); font-size: 14px;
  cursor: pointer; border-radius: 4px; opacity: 0; line-height: 1;
}
.s-del { right: 6px; font-size: 16px; }
.s-ren { right: 28px; }
.session-item:hover .s-del, .session-item:hover .s-ren { opacity: 1; }
.s-del:hover { background: rgba(239,68,68,.18); color: #ef4444; }
.s-ren:hover { background: var(--bg-base, #15151b); color: var(--accent, #3b82f6); }
.s-rename {
  width: 100%; box-sizing: border-box; padding: 4px 8px; font-size: 13px;
  background: var(--bg-base, #15151b); border: 1px solid var(--accent, #3b82f6);
  border-radius: 6px; color: var(--text-1); outline: none;
}
.pane-empty { color: var(--text-3); font-size: 12px; text-align: center; padding: 20px 0; }

/* ── 主区 ── */
.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; position: relative; }
.chat-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-bottom: 1px solid var(--border, #2a2a35); flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 10px; }
.icon-btn {
  border: none; background: transparent; color: var(--text-2); font-size: 18px;
  cursor: pointer; padding: 2px 6px; border-radius: 6px;
}
.icon-btn:hover { background: var(--bg-elevated, #1c1c24); color: var(--text-1); }
.chat-title { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 0; }
.subtitle { font-size: 12px; color: var(--text-3); }
.header-right { display: flex; align-items: center; gap: 14px; }
.toggle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; user-select: none; }
.toggle input { cursor: pointer; }

/* ── 消息区 ── */
.messages { flex: 1; min-height: 0; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
.empty { margin: auto; text-align: center; color: var(--text-3); }
.empty-icon { font-size: 40px; }
.empty p { margin: 8px 0 18px; }
.chip {
  background: var(--bg-elevated, #1c1c24); border: 1px solid var(--border, #2a2a35);
  color: var(--text-2); border-radius: 16px; padding: 7px 14px; font-size: 13px; cursor: pointer;
}
.chip:hover { border-color: var(--accent, #3b82f6); color: var(--text-1); }

/* ── 空状态：分类快捷入口 ── */
.quick-grid {
  display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr));
  gap: 16px; max-width: 620px; margin-top: 6px; text-align: left;
}
.quick-cat { display: flex; flex-direction: column; gap: 8px; }
.quick-cat-title { font-size: 12px; color: var(--text-2); font-weight: 600; }
.quick-cat .chip { width: 100%; text-align: left; }
@media (max-width: 768px) { .quick-grid { grid-template-columns: 1fr; } }

/* ── 用户消息：编辑并重新提问 ── */
.user-bubble { position: relative; display: inline-flex; align-items: flex-start; gap: 6px; }
.user-edit-btn {
  border: none; background: transparent; color: rgba(255,255,255,.7); cursor: pointer;
  font-size: 13px; padding: 0 2px; opacity: 0; transition: opacity .15s; flex-shrink: 0;
}
.msg.user:hover .user-edit-btn { opacity: 1; }
.user-edit-btn:hover { color: #fff; }
.user-edit { width: min(76%, 560px); display: flex; flex-direction: column; gap: 8px; }
.edit-area {
  width: 100%; box-sizing: border-box; resize: vertical; min-height: 56px;
  background: var(--bg-elevated, #1c1c24); border: 1px solid var(--accent, #3b82f6);
  border-radius: 10px; padding: 10px 12px; color: var(--text-1);
  font-size: 14px; line-height: 1.5; font-family: inherit; outline: none;
}
.edit-actions { display: flex; gap: 8px; justify-content: flex-end; }
.act-btn.primary { background: var(--accent, #3b82f6); color: #fff; border-color: var(--accent, #3b82f6); }
.act-btn.primary:hover:not(:disabled) { opacity: .9; color: #fff; }

.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.bubble { max-width: 76%; padding: 11px 15px; border-radius: 14px; font-size: 14px; line-height: 1.65; word-break: break-word; }
.msg.user .bubble { background: var(--accent, #3b82f6); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant .bubble {
  background: var(--bg-elevated, #1c1c24); color: var(--text-1);
  border: 1px solid var(--border, #2a2a35); border-bottom-left-radius: 4px;
}
.bubble :deep(h1), .bubble :deep(h2), .bubble :deep(h3), .bubble :deep(h4) {
  margin: 12px 0 6px; font-size: 14px; font-weight: 700; color: var(--text-1); line-height: 1.4;
}
.bubble :deep(h1):first-child, .bubble :deep(h2):first-child,
.bubble :deep(h3):first-child, .bubble :deep(h4):first-child,
.bubble :deep(p):first-child { margin-top: 0; }
.bubble :deep(p) { margin: 6px 0; }
.bubble :deep(ul), .bubble :deep(ol) { margin: 6px 0; padding-left: 22px; }
.bubble :deep(li) { margin: 3px 0; }
.bubble :deep(code) { background: rgba(127,127,127,.18); padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono, monospace); font-size: 13px; }
.bubble :deep(pre) {
  background: rgba(0,0,0,.28); border: 1px solid var(--border, #2a2a35);
  border-radius: 8px; padding: 10px 12px; margin: 8px 0; overflow-x: auto;
}
.bubble :deep(pre code) { background: none; padding: 0; font-size: 12.5px; line-height: 1.5; }
.bubble :deep(strong) { color: var(--text-1); font-weight: 700; }
.bubble :deep(a) { color: var(--accent, #3b82f6); text-decoration: none; }
.bubble :deep(a:hover) { text-decoration: underline; }
.bubble :deep(blockquote) {
  margin: 8px 0; padding: 4px 12px; border-left: 3px solid var(--accent, #3b82f6);
  color: var(--text-2); background: rgba(127,127,127,.06); border-radius: 0 6px 6px 0;
}
.bubble :deep(table) { border-collapse: collapse; margin: 8px 0; font-size: 13px; width: 100%; }
.bubble :deep(th), .bubble :deep(td) {
  border: 1px solid var(--border, #2a2a35); padding: 5px 9px; text-align: left;
}
.bubble :deep(th) { background: rgba(127,127,127,.12); font-weight: 600; }
.bubble :deep(hr) { border: none; border-top: 1px solid var(--border, #2a2a35); margin: 10px 0; }

/* ── 思考中动画（首 token 前）── */
.thinking { display: flex; gap: 5px; padding: 4px 2px; }
.thinking span {
  width: 7px; height: 7px; border-radius: 50%; background: var(--text-3, #8a94a6);
  animation: thinking-bounce 1.2s infinite ease-in-out both;
}
.thinking span:nth-child(1) { animation-delay: -0.24s; }
.thinking span:nth-child(2) { animation-delay: -0.12s; }
@keyframes thinking-bounce {
  0%, 80%, 100% { transform: scale(.6); opacity: .4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ── 回复操作条 ── */
.assistant-bubble { position: relative; }
.msg-actions { display: flex; gap: 8px; margin-top: 8px; opacity: 0; transition: opacity .15s; }
.msg.assistant:hover .msg-actions { opacity: 1; }
.act-btn {
  border: 1px solid var(--border, #2a2a35); background: transparent; color: var(--text-3);
  font-size: 12px; padding: 3px 10px; border-radius: 6px; cursor: pointer;
}
.act-btn:hover:not(:disabled) { color: var(--text-1); border-color: var(--accent, #3b82f6); }
.act-btn:disabled { opacity: .4; cursor: not-allowed; }

/* ── 对话内出图 ── */
.msg-charts { margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }

/* ── 来源溯源标签 ── */
.msg-sources { margin-top: 8px; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.src-label { font-size: 11px; color: var(--text-3); }
.src-tag {
  font-size: 11px; color: var(--text-2); padding: 1px 7px; border-radius: 10px;
  background: rgba(59, 130, 246, .12); border: 1px solid rgba(59, 130, 246, .25);
}

/* ── 推荐下个问题 ── */
.msg-followups {
  margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border, #2a2a35);
}
.followup-label { font-size: 11px; color: var(--text-3); margin-bottom: 7px; letter-spacing: .02em; }
.followup-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.followup-chip {
  font-size: 12.5px; color: var(--text-2); cursor: pointer;
  background: var(--bg-elevated, #1c1c24); border: 1px solid var(--border, #2a2a35);
  border-radius: 14px; padding: 5px 12px; text-align: left;
}
.followup-chip::before { content: "↳ "; color: var(--accent, #3b82f6); }
.followup-chip:hover:not(:disabled) { border-color: var(--accent, #3b82f6); color: var(--text-1); }
.followup-chip:disabled { opacity: .5; cursor: not-allowed; }

/* ── 回到底部浮钮 ── */
.jump-bottom {
  position: absolute; right: 24px; bottom: 92px; z-index: 5;
  border: 1px solid var(--border, #2a2a35); background: var(--bg-elevated, #1c1c24);
  color: var(--text-1); font-size: 12px; padding: 6px 12px; border-radius: 16px;
  cursor: pointer; box-shadow: var(--shadow-float, 0 4px 12px rgba(0,0,0,.3));
}
.jump-bottom:hover { border-color: var(--accent, #3b82f6); }

/* ── 输入区 ── */
.composer { display: flex; gap: 10px; align-items: flex-end; padding: 14px 20px; border-top: 1px solid var(--border, #2a2a35); flex-shrink: 0; }
.input {
  flex: 1; resize: none; max-height: 160px;
  background: var(--bg-elevated, #1c1c24); border: 1px solid var(--border, #2a2a35);
  border-radius: 10px; padding: 11px 14px; color: var(--text-1);
  font-size: 14px; line-height: 1.5; font-family: inherit; outline: none;
}
.input:focus { border-color: var(--accent, #3b82f6); }
.btn { border: none; border-radius: 10px; padding: 11px 20px; font-size: 14px; font-weight: 600; cursor: pointer; white-space: nowrap; }
.btn:disabled { opacity: .45; cursor: not-allowed; }
.btn.send { background: var(--accent, #3b82f6); color: #fff; }
.btn.stop { background: #ef4444; color: #fff; }

/* ── 移动端：会话侧栏变浮层抽屉 ── */
@media (max-width: 768px) {
  .chat-view { position: relative; }
  .session-pane {
    position: absolute; left: 0; top: 0; bottom: 0; z-index: 20;
    width: min(78vw, 260px);
    background: var(--bg-surface);
    box-shadow: var(--shadow-float);
  }
  .session-pane.collapsed { width: 0; box-shadow: none; }
  .chat-header { padding: 10px 12px; flex-wrap: wrap; gap: 8px; }
  .subtitle { display: none; }
  /* 开关区横向滚动，不换行挤压 */
  .header-right { overflow-x: auto; flex-wrap: nowrap; -webkit-overflow-scrolling: touch; gap: 10px; }
  .toggle { flex-shrink: 0; white-space: nowrap; }
  .messages { padding: 14px 12px; }
  .bubble { max-width: 88%; }
  .composer { padding: 10px 12px; }
}
</style>
