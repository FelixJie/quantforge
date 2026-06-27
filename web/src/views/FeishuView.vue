<template>
  <div class="fs-view">
    <!-- ══ 模式切换 ══════════════════════════════════════════ -->
    <div class="mode-tabs">
      <button class="mode-tab" :class="{ active: mode === 'messages' }" @click="mode = 'messages'">消息检索</button>
      <button class="mode-tab" :class="{ active: mode === 'summary' }" @click="switchSummary">每日汇总</button>
      <button class="mode-tab gear" :class="{ active: showSettings }" @click="toggleSettings" title="群标签设置">⚙ 群标签</button>
    </div>

    <!-- ══ 群标签设置面板 ════════════════════════════════════ -->
    <div v-if="showSettings" class="settings-panel">
      <div class="set-head">
        <h3>群标签设置</h3>
        <span class="set-note">拖动顺序用 ↑↓；「只看转发前缀」可填多个（逗号分隔，如 <code>3, 胡汉三</code>）；勾选「汇总」决定每日汇总包含哪些群。</span>
      </div>
      <div v-if="!draft.length" class="state sm">还没抓到任何群。请先到管理后台完成飞书授权并「立即抓取」。</div>
      <div v-else class="set-list">
        <div v-for="(g, i) in draft" :key="g.chat_id" class="set-row">
          <div class="set-order">
            <button class="ord-btn" :disabled="i === 0" @click="moveGroup(i, -1)" title="上移">↑</button>
            <button class="ord-btn" :disabled="i === draft.length - 1" @click="moveGroup(i, 1)" title="下移">↓</button>
          </div>
          <div class="set-name" :title="g.chat_id">{{ g.name }}</div>
          <input
            v-model="g.markersStr" class="set-marker"
            placeholder="只看转发前缀，可多个：3, 胡汉三"
          />
          <label class="set-sum">
            <input type="checkbox" v-model="g.in_summary" /> 汇总
          </label>
        </div>
      </div>
      <div class="set-actions">
        <button class="btn ghost sm" @click="showSettings = false">取消</button>
        <button class="btn sm" @click="saveGroupPrefs" :disabled="savingPrefs || !draft.length">
          {{ savingPrefs ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <!-- ══ 顶栏 ══════════════════════════════════════════════ -->
    <div class="fs-header" v-show="mode === 'messages'">
      <div class="header-left">
        <h2 class="fs-title">飞书群消息</h2>
        <div class="status-pills">
          <span class="pill">{{ status.count?.toLocaleString() ?? 0 }} 条</span>
          <span class="pill">{{ groups.length }} 群</span>
          <span class="pill" :class="status.authed && !status.uat_expired ? 'ok' : 'warn'">
            {{ status.authed && !status.uat_expired ? '已授权' : status.authed ? 'Token 过期' : '未授权' }}
          </span>
          <span class="pill" v-if="status.last_fetch">更新 {{ fmtTime(status.last_fetch) }}</span>
        </div>
      </div>
      <div class="header-right">
        <input
          v-model="search" class="search-box" placeholder="搜索消息 / 群名…"
          @keyup.enter="loadMessages(1)"
        />
        <label class="dedup-toggle" v-if="!activeChat" title="同一条转发在多个群重复时只显示一条">
          <input type="checkbox" v-model="dedup" @change="loadMessages(1)" /> 去重
        </label>
        <button class="btn" @click="refresh" :disabled="refreshing">
          {{ refreshing ? '抓取中…' : '立即抓取' }}
        </button>
      </div>
    </div>

    <!-- ══ 消息检索模式 ══════════════════════════════════════ -->
    <div v-show="mode === 'messages'">
      <!-- 群标签（置顶优先，点击即查询）-->
      <div class="quick-chips" v-if="groups.length">
        <button class="chip" :class="{ on: !activeChat }" @click="pickGroup('')">全部群</button>
        <button
          v-for="g in tabGroups" :key="g.chat_id"
          class="chip" :class="{ on: activeChat === g.chat_id }"
          @click="pickGroup(g.chat_id)"
        >
          {{ g.name }}
          <span v-if="g.markers && g.markers.length" class="chip-mark">仅「{{ g.markers.join(' / ') }}：」</span>
        </button>
        <button
          class="chip add" :class="{ on: showAllGroups }"
          @click="showAllGroups = !showAllGroups"
          :title="hasPins ? '管理置顶标签' : '把常用群置顶为标签'"
        >{{ showAllGroups ? '收起' : (hasPins ? '＋标签' : '置顶标签') }}</button>
      </div>

      <!-- 置顶挑选：点 ★ 把常用群放到上方标签栏（按账户记忆）-->
      <div v-if="showAllGroups && groups.length" class="pin-picker">
        <div class="pin-tip">点 <b>★</b> 把常用群置顶到标签栏，点击标签即可一键查询。设置按账户保存，换设备也记得。</div>
        <div class="pin-list">
          <button
            v-for="g in groups" :key="g.chat_id"
            class="pin-item" :class="{ pinned: isPinned(g.chat_id) }"
            @click="togglePin(g.chat_id)"
          >
            <span class="star">{{ isPinned(g.chat_id) ? '★' : '☆' }}</span>
            <span class="pin-name">{{ g.name }}</span>
          </button>
        </div>
      </div>

      <!-- 授权提示 -->
      <div v-if="!status.authed" class="info-banner">
        🔑 飞书尚未授权，无法拉取群消息。请到
        <router-link to="/admin?tab=feishu" class="banner-link">管理后台「飞书授权」</router-link>
        用飞书账号完成 OAuth 授权。
      </div>
      <div v-else-if="status.uat_expired" class="info-banner warn">
        ⚠️ 飞书 Token 已过期，可能拉不到新消息。请到
        <router-link to="/admin?tab=feishu" class="banner-link">管理后台「飞书授权」</router-link>
        重新授权。
      </div>

      <!-- ══ 列表 ══════════════════════════════════════════════ -->
      <div v-if="loading" class="state">加载中…</div>
      <div v-else-if="!messages.length" class="state">
        <p>暂无消息。</p>
        <p class="hint">{{ search || activeChat ? '换个搜索词或群试试。' : '点「立即抓取」拉取最新群消息。' }}</p>
      </div>

      <div v-else class="msg-feed">
        <template v-for="g in grouped" :key="g.date">
          <div class="date-divider"><span>{{ g.date }}</span></div>
          <article v-for="m in g.items" :key="m.message_id" class="msg-card"
                   :class="{ system: m.msg_type === 'system' }">
            <div class="msg-avatar" :style="{ background: chatColor(m.chat_id || m.chat_name) }">
              {{ avatarChar(m.chat_name) }}
            </div>
            <div class="msg-main">
              <header class="msg-head">
                <span class="msg-chat">{{ m.chat_name || '未命名群' }}</span>
                <span class="msg-time">{{ fmtClock(m.created_at) }}</span>
                <span v-if="m.msg_type === 'interactive' || m.msg_type === 'post'" class="msg-type">
                  {{ m.msg_type === 'interactive' ? '卡片' : '富文本' }}
                </span>
              </header>
              <div class="msg-body">
                <template v-for="(seg, i) in renderSegments(m)" :key="i">
                  <img v-if="seg.type === 'image'" :src="seg.url" class="msg-img" loading="lazy"
                       @click="openLightbox([seg.url], 0)" @error="onImgError" />
                  <p v-else-if="seg.text" class="msg-text" v-html="seg.html"></p>
                </template>
              </div>
            </div>
          </article>
        </template>
      </div>

      <!-- 分页 -->
      <div v-if="total > pageSize && !dedup" class="pager">
        <button class="btn ghost" :disabled="page <= 1" @click="loadMessages(page - 1)">上一页</button>
        <span class="pager-info">{{ page }} / {{ totalPages }}</span>
        <button class="btn ghost" :disabled="page >= totalPages" @click="loadMessages(page + 1)">下一页</button>
      </div>
    </div>

    <!-- ══ 每日汇总模式 ══════════════════════════════════════ -->
    <div v-show="mode === 'summary'" class="summary-wrap">
      <div class="sum-header">
        <div class="header-left">
          <h2 class="fs-title">每日汇总</h2>
          <div class="status-pills">
            <span class="pill" :title="summaryGroupNames">{{ summaryGroupLabel }}</span>
            <span class="pill" v-if="summary.window_start">
              {{ fmtRange(summary.window_start, summary.window_end) }}
            </span>
            <span class="pill" v-if="summary.msg_count">{{ summary.msg_count }} 条</span>
          </div>
        </div>
        <div class="header-right">
          <select v-model="summaryDay" class="chat-select" @change="loadSummary">
            <option value="">今天（{{ todayStr }}）</option>
            <option v-for="d in summaryDates" :key="d.day" :value="d.day">
              {{ d.day }}（{{ d.msg_count }} 条）
            </option>
          </select>
          <button class="btn" @click="refreshSummary" :disabled="summaryLoading">
            {{ summaryLoading ? '汇总中…' : '刷新汇总' }}
          </button>
        </div>
      </div>

      <p class="sum-note">
        窗口为「昨天 16:00 → 现在」。选择想汇总的群（按账户记忆），点「刷新汇总」生成你专属的当日要点；重复信息会自动过滤。
      </p>

      <!-- 自选汇总群（按账户记忆）-->
      <div class="sum-groups" v-if="groups.length">
        <div class="sg-head">
          <span class="sg-label">汇总范围</span>
          <span class="sg-count">{{ summarySel.length ? `已选 ${summarySel.length} 群` : `全部 ${groups.length} 群` }}</span>
          <button class="link-btn" @click="selectAllSummary" :disabled="!summarySel.length">全选</button>
        </div>
        <div class="sg-chips">
          <button
            v-for="g in groups" :key="g.chat_id"
            class="sg-chip" :class="{ on: isSummarySel(g.chat_id) }"
            @click="toggleSummaryGroup(g.chat_id)"
          >
            <span class="sg-tick">{{ isSummarySel(g.chat_id) ? '✓' : '' }}</span>{{ g.name }}
          </button>
        </div>
      </div>

      <div v-if="summaryLoading" class="state">正在拉取并汇总群消息，请稍候（约十几秒）…</div>
      <div v-else-if="!summary.summary" class="state">
        <p>今天还没有汇总。</p>
        <p class="hint">点「刷新汇总」生成昨天 16:00 至现在的群要点。</p>
      </div>
      <div v-else class="sum-body">
        <div class="sum-meta" v-if="summary.generated_at">生成于 {{ fmtTime(summary.generated_at) }}</div>
        <div class="md" v-html="renderMarkdown(summary.summary)"></div>
      </div>
    </div>

    <!-- 图片放大 -->
    <transition name="fade">
      <div v-if="lightbox.open" class="lightbox" @click="lightbox.open = false">
        <button class="lb-close" @click.stop="lightbox.open = false" aria-label="关闭">✕</button>
        <img class="lb-img" :src="lightbox.url" @click.stop @error="onImgError" />
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import axios from 'axios'
import { marked } from 'marked'
import { useAuthStore } from '../stores/auth'

marked.setOptions({ breaks: true, gfm: true })

const auth = useAuthStore()
const mode = ref('messages')          // 'messages' | 'summary'

// 全部群标签 + 偏好
const groups = ref([])                // [{chat_id, name, markers:[], in_summary}]
const showSettings = ref(false)
const draft = ref([])                 // 设置面板工作副本
const savingPrefs = ref(false)

// ── 个人习惯（按账户存 localStorage，云端无关）────────────────────────────
const pinned = ref([])                // 置顶标签 chat_id 列表（标签栏只显示这些群）
const summarySel = ref([])            // 自选汇总群 chat_id 列表（空=全部群）
const showAllGroups = ref(false)      // 标签栏是否展开「全部群」用于挑选置顶

function _prefKey() { return `feishu_prefs_${auth.user?.id || 'anon'}` }
function _saveLocalPrefs() {
  try {
    localStorage.setItem(_prefKey(), JSON.stringify({
      pinned: pinned.value, summary: summarySel.value,
    }))
  } catch { /* ignore */ }
}
function restoreLocalPrefs() {
  let p = {}
  try { p = JSON.parse(localStorage.getItem(_prefKey()) || '{}') } catch { p = {} }
  const ids = new Set(groups.value.map(g => g.chat_id))
  // 只保留仍存在的群，避免群被删后残留脏 id
  pinned.value = (Array.isArray(p.pinned) ? p.pinned : []).filter(id => ids.has(id))
  summarySel.value = (Array.isArray(p.summary) ? p.summary : []).filter(id => ids.has(id))
}

// 每日汇总
const summary = reactive({ day: '', summary: '', msg_count: 0, window_start: '', window_end: '', generated_at: '' })
const summaryDates = ref([])
const summaryDay = ref('')            // '' = 今天
const summaryLoading = ref(false)

const messages = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const loading = ref(false)
const refreshing = ref(false)
const search = ref('')
const activeChat = ref('')
const dedup = ref(true)               // 「全部群」时跨群去重

const status = reactive({
  count: 0, last_fetch: null, authed: false, uat_expired: true, user_name: '',
})

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// ── 置顶标签 ────────────────────────────────────────────────
const hasPins = computed(() => pinned.value.length > 0)
// 标签栏可点的群：有置顶就只显示置顶（按置顶顺序），否则显示全部群
const tabGroups = computed(() => {
  if (!hasPins.value) return groups.value
  const map = new Map(groups.value.map(g => [g.chat_id, g]))
  return pinned.value.map(id => map.get(id)).filter(Boolean)
})
function isPinned(id) { return pinned.value.includes(id) }
function togglePin(id) {
  const i = pinned.value.indexOf(id)
  if (i >= 0) pinned.value.splice(i, 1)
  else pinned.value.push(id)
  _saveLocalPrefs()
}

// ── 自选汇总群（空=全部）────────────────────────────────────
function isSummarySel(id) {
  return summarySel.value.length ? summarySel.value.includes(id) : true
}
function toggleSummaryGroup(id) {
  if (!summarySel.value.length) {
    // 从「全部」首次取消某群：先展开成显式全集再去掉它
    summarySel.value = groups.value.map(g => g.chat_id).filter(x => x !== id)
  } else {
    const i = summarySel.value.indexOf(id)
    if (i >= 0) summarySel.value.splice(i, 1)
    else summarySel.value.push(id)
    // 选满即等价于「全部」，回到空集（用全局缓存更省）
    if (summarySel.value.length === groups.value.length) summarySel.value = []
  }
  _saveLocalPrefs()
  loadSummary()
}
function selectAllSummary() { summarySel.value = []; _saveLocalPrefs(); loadSummary() }
// 汇总请求参数：全部/空 → 不传（走全局当日汇总），子集 → 传 chat_id 串
const summaryParam = computed(() => {
  const n = summarySel.value.length
  if (!n || n === groups.value.length) return undefined
  return summarySel.value.join(',')
})

// 汇总范围群名
const summaryGroups = computed(() =>
  summarySel.value.length ? groups.value.filter(g => summarySel.value.includes(g.chat_id)) : groups.value)
const summaryGroupNames = computed(() => summaryGroups.value.map(g => g.name).join(' · '))
const summaryGroupLabel = computed(() => {
  const arr = summaryGroups.value
  if (!arr.length) return '未选择群'
  if (arr.length <= 4) return summaryGroupNames.value
  return `${arr.slice(0, 4).map(g => g.name).join(' · ')} 等 ${arr.length} 群`
})

// 按日期分组（保持后端的倒序）
const grouped = computed(() => {
  const out = []
  let cur = null
  for (const m of messages.value) {
    const d = dayLabel(m.created_at)
    if (!cur || cur.date !== d) { cur = { date: d, items: [] }; out.push(cur) }
    cur.items.push(m)
  }
  return out
})

const lightbox = reactive({ open: false, url: '' })
function openLightbox(urls, i) { lightbox.url = urls[i] || ''; lightbox.open = true }
function onImgError(e) { if (e?.target) e.target.style.display = 'none' }

const todayStr = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })

function renderMarkdown(text) {
  if (!text) return ''
  try { return marked.parse(text) }
  catch { return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
}
function fmtRange(a, b) {
  const f = s => { const d = new Date(s); return isNaN(d) ? '' : d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
  return a ? `${f(a)} → ${f(b)}` : ''
}

// ── 时间格式化 ──────────────────────────────────────────────
function fmtTime(s) {
  if (!s) return ''
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return s }
}
function fmtClock(s) {
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}
function dayLabel(s) {
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return '未知日期'
    const today = new Date(); today.setHours(0, 0, 0, 0)
    const that = new Date(d); that.setHours(0, 0, 0, 0)
    const diff = Math.round((today - that) / 86400000)
    if (diff === 0) return '今天'
    if (diff === 1) return '昨天'
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', weekday: 'short' })
  } catch { return '未知日期' }
}

// ── 群头像（取群名首字 + 稳定配色）──────────────────────────
const COLORS = ['#2563eb', '#0891b2', '#7c3aed', '#db2777', '#ea580c', '#16a34a', '#ca8a04', '#dc2626']
function chatColor(key) {
  const s = String(key || '')
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return COLORS[h % COLORS.length]
}
function avatarChar(name) {
  const s = (name || '群').trim()
  return s ? s[0] : '群'
}

// ── 内容渲染：图片 + 话题标签 + 链接 ────────────────────────
const IMG_MD = /!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/g
const IMG_BARE = /(https?:\/\/[^\s)]+\.(?:jpg|jpeg|png|gif|webp)(?:\?[^\s)]*)?)/gi

function escapeHtml(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
// 文本片段高亮：#话题# → chip，裸链接 → a，换行 → <br>
function highlight(text) {
  let html = escapeHtml(text)
  html = html.replace(/#([^#\n]{1,30})#/g, '<span class="tag">#$1#</span>')
  html = html.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
  return html.replace(/\n/g, '<br>')
}

// 把整体清洗（去全角空格噪声/多余空行），并切成 图片/文本 片段
function renderSegments(m) {
  let raw = m.content_text || ''
  if (!raw) return [{ type: 'text', text: `[${m.msg_type || '非文本'}消息]`, html: `<span class="muted">[${m.msg_type || '非文本'}消息]</span>` }]

  // 收集图片 URL
  const imgs = []
  let mt
  IMG_MD.lastIndex = 0
  while ((mt = IMG_MD.exec(raw)) !== null) imgs.push(mt[1])
  let textOnly = raw.replace(IMG_MD, ' ')
  IMG_BARE.lastIndex = 0
  while ((mt = IMG_BARE.exec(textOnly)) !== null) imgs.push(mt[1])
  textOnly = textOnly.replace(IMG_BARE, ' ')

  // 清洗：全角空格→普通空格、压缩 3+ 空行、首尾裁剪
  textOnly = textOnly.replace(/　/g, ' ').replace(/[ \t]+\n/g, '\n')
                     .replace(/\n{3,}/g, '\n\n').trim()

  const segs = []
  if (textOnly) segs.push({ type: 'text', text: textOnly, html: highlight(textOnly) })
  for (const u of imgs) segs.push({ type: 'image', url: u })
  return segs.length ? segs : [{ type: 'text', text: '', html: '' }]
}

// ── 数据加载 ────────────────────────────────────────────────
async function loadStatus() {
  try { Object.assign(status, (await axios.get('/api/feishu/status')).data) } catch (e) { /* ignore */ }
}
async function loadGroups() {
  try { groups.value = (await axios.get('/api/feishu/groups')).data.groups || [] }
  catch (e) { groups.value = [] }
  restoreLocalPrefs()
}
async function loadMessages(p = 1) {
  loading.value = true
  page.value = p
  try {
    const { data } = await axios.get('/api/feishu/messages', {
      params: {
        page: p, page_size: pageSize,
        search: search.value || undefined,
        chat_id: activeChat.value || undefined,
        dedup: !activeChat.value && dedup.value ? true : undefined,
      },
    })
    messages.value = data.messages || []
    total.value = data.total || 0
  } catch (e) {
    messages.value = []; total.value = 0
  } finally { loading.value = false }
}
async function refresh() {
  refreshing.value = true
  try {
    await axios.post('/api/feishu/refresh')
    await Promise.all([loadStatus(), loadGroups(), loadMessages(1)])
  } catch (e) { /* ignore */ } finally { refreshing.value = false }
}
function pickGroup(chatId) {
  activeChat.value = chatId
  loadMessages(1)
}

// ── 群标签设置 ──────────────────────────────────────────────
function toggleSettings() {
  showSettings.value = !showSettings.value
  if (showSettings.value) {
    draft.value = groups.value.map(g => ({
      chat_id: g.chat_id,
      name: g.name,
      markersStr: (g.markers || []).join(', '),
      in_summary: g.in_summary !== false,
    }))
  }
}
function moveGroup(i, dir) {
  const j = i + dir
  if (j < 0 || j >= draft.value.length) return
  const arr = draft.value
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
}
async function saveGroupPrefs() {
  savingPrefs.value = true
  const order = draft.value.map(g => g.chat_id)
  const summarySel = draft.value.filter(g => g.in_summary).map(g => g.chat_id)
  const markers = {}
  for (const g of draft.value) {
    const list = (g.markersStr || '').split(/[,，;；\s]+/).map(s => s.trim()).filter(Boolean)
    if (list.length) markers[g.chat_id] = list
  }
  try {
    const { data } = await axios.put('/api/feishu/groups/prefs', { order, summary: summarySel, markers })
    groups.value = data.groups || []
    showSettings.value = false
    await loadMessages(1)
  } catch (e) { /* ignore */ } finally { savingPrefs.value = false }
}

// ── 每日汇总 ────────────────────────────────────────────────
async function loadSummary() {
  try {
    const { data } = await axios.get('/api/feishu/summary', {
      params: { date: summaryDay.value || undefined, groups: summaryParam.value },
    })
    Object.assign(summary, data)
  } catch (e) { /* ignore */ }
}
async function loadSummaryDates() {
  try { summaryDates.value = (await axios.get('/api/feishu/summary/list')).data.items || [] }
  catch (e) { summaryDates.value = [] }
}
async function refreshSummary() {
  summaryLoading.value = true
  try {
    const { data } = await axios.post('/api/feishu/summary/refresh', null, {
      params: { groups: summaryParam.value },
    })
    summaryDay.value = ''
    Object.assign(summary, data)
    await loadSummaryDates()
  } catch (e) {
    summary.summary = '汇总生成失败：' + (e.response?.data?.detail || e.message)
  } finally { summaryLoading.value = false }
}
async function switchSummary() {
  mode.value = 'summary'
  if (!summaryDates.value.length) await loadSummaryDates()
  await loadSummary()
}

onMounted(async () => {
  await Promise.all([loadStatus(), loadGroups()])
  await loadMessages(1)
})
</script>

<style scoped>
.fs-view { padding: 16px 20px; max-width: 820px; margin: 0 auto; }

/* 模式切换 */
.mode-tabs { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
.mode-tab {
  padding: 6px 16px; border-radius: var(--radius-md); cursor: pointer;
  font-size: 13px; font-weight: 600; border: 1px solid var(--border);
  background: var(--bg-base); color: var(--text-2);
}
.mode-tab.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.mode-tab:hover:not(.active) { color: var(--text-1); background: var(--bg-hover); }
.mode-tab.gear { margin-left: auto; }

/* 群标签设置面板 */
.settings-panel {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 14px 16px; margin-bottom: 16px;
}
.set-head { margin-bottom: 12px; }
.set-head h3 { font-size: 14px; font-weight: 700; color: var(--text-1); margin: 0 0 4px; }
.set-note { font-size: 11px; color: var(--text-3); line-height: 1.6; }
.set-note code { background: var(--bg-hover); padding: 0 4px; border-radius: 4px; }
.set-list { display: flex; flex-direction: column; gap: 8px; }
.set-row { display: flex; align-items: center; gap: 10px; }
.set-order { display: flex; flex-direction: column; gap: 2px; }
.ord-btn {
  width: 22px; height: 16px; line-height: 14px; font-size: 10px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-base); color: var(--text-2);
  border-radius: 4px; padding: 0;
}
.ord-btn:hover:not(:disabled) { color: var(--text-1); background: var(--bg-hover); }
.ord-btn:disabled { opacity: .35; cursor: not-allowed; }
.set-name { width: 120px; font-size: 12.5px; font-weight: 600; color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 0; }
.set-marker {
  flex: 1; min-width: 0; background: var(--bg-elev, var(--bg-base));
  border: 1px solid var(--border); border-radius: var(--radius-md); color: var(--text-1);
  padding: 5px 9px; font-size: 12px; outline: none;
}
.set-marker:focus { border-color: var(--accent); }
.set-sum { display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  color: var(--text-2); white-space: nowrap; cursor: pointer; }
.set-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }

/* 群标签 */
.quick-chips { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px; cursor: pointer; font-size: 12.5px;
  border: 1px solid var(--border); background: var(--bg-base); color: var(--text-2);
}
.chip:hover:not(:disabled) { color: var(--text-1); background: var(--bg-hover); }
.chip.on { background: var(--accent); color: #fff; border-color: var(--accent); }
.chip-mark { font-size: 10px; padding: 0 5px; border-radius: 8px;
  background: rgba(255,255,255,.18); }
.chip:not(.on) .chip-mark { background: var(--bg-hover); color: var(--text-3); }
.chip.add { border-style: dashed; color: var(--text-3); }
.chip.add.on { background: var(--bg-hover); color: var(--text-1); border-style: solid; }

/* 置顶挑选 */
.pin-picker {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 12px 14px; margin-bottom: 12px;
}
.pin-tip { font-size: 11.5px; color: var(--text-3); line-height: 1.6; margin-bottom: 10px; }
.pin-tip b { color: var(--warning); }
.pin-list { display: flex; gap: 8px; flex-wrap: wrap; }
.pin-item {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 5px 11px; border-radius: 20px; cursor: pointer; font-size: 12.5px;
  border: 1px solid var(--border); background: var(--bg-base); color: var(--text-2);
}
.pin-item:hover { background: var(--bg-hover); color: var(--text-1); }
.pin-item.pinned { border-color: var(--accent); color: var(--text-1); }
.pin-item .star { font-size: 13px; color: var(--text-3); }
.pin-item.pinned .star { color: #f59e0b; }

/* 自选汇总群 */
.sum-groups {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 12px 14px; margin-bottom: 14px;
}
.sg-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.sg-label { font-size: 12.5px; font-weight: 700; color: var(--text-1); }
.sg-count { font-size: 11.5px; color: var(--text-3); }
.link-btn {
  margin-left: auto; background: none; border: none; cursor: pointer;
  font-size: 12px; color: var(--accent); padding: 0;
}
.link-btn:disabled { color: var(--text-3); cursor: default; }
.sg-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.sg-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 5px 11px; border-radius: 20px; cursor: pointer; font-size: 12.5px;
  border: 1px solid var(--border); background: var(--bg-base); color: var(--text-3);
}
.sg-chip:hover { background: var(--bg-hover); }
.sg-chip.on { border-color: var(--accent); color: var(--text-1); background: rgba(37,99,235,.08); }
.sg-tick { font-size: 11px; color: var(--accent); width: 10px; }

.btn.sm { padding: 4px 10px; font-size: 11px; }

.dedup-toggle { display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  color: var(--text-2); white-space: nowrap; cursor: pointer; }

/* 汇总 */
.summary-wrap { }
.sum-header { display: flex; align-items: center; justify-content: space-between;
  gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }
.sum-note { font-size: 11.5px; color: var(--text-3); margin: 0 0 14px; line-height: 1.6; }
.sum-meta { font-size: 11px; color: var(--text-3); margin-bottom: 10px; }
.sum-body { background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 16px 18px; }
.md { font-size: 13.5px; color: var(--text-1); line-height: 1.75; word-break: break-word; }
.md :deep(h2) { font-size: 15px; font-weight: 700; margin: 18px 0 8px; color: var(--text-1);
  border-bottom: 1px solid var(--border); padding-bottom: 5px; }
.md :deep(h2:first-child) { margin-top: 0; }
.md :deep(h3) { font-size: 13.5px; font-weight: 700; margin: 12px 0 6px; }
.md :deep(ul), .md :deep(ol) { padding-left: 20px; margin: 6px 0; }
.md :deep(li) { margin: 3px 0; }
.md :deep(p) { margin: 6px 0; }
.md :deep(strong) { color: var(--accent); }
.md :deep(table) { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 12.5px; }
.md :deep(th), .md :deep(td) { border: 1px solid var(--border); padding: 5px 8px; text-align: left; }
.md :deep(code) { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; font-size: 12px; }

/* 顶栏 */
.fs-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 14px; flex-wrap: wrap; margin-bottom: 16px;
}
.header-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.fs-title { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 0; }
.status-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.pill {
  font-size: 11px; padding: 3px 8px; border-radius: 20px;
  background: var(--bg-hover); color: var(--text-3); border: 1px solid var(--border);
  white-space: nowrap;
}
.pill.ok { color: var(--success); border-color: rgba(22,163,74,.3); background: rgba(22,163,74,.08); }
.pill.warn { color: var(--warning); border-color: rgba(240,180,40,.3); background: rgba(240,180,40,.08); }

.header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.search-box, .chat-select {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1);
  padding: 6px 10px; font-size: 12px; outline: none;
}
.search-box { width: 150px; }
.chat-select { max-width: 170px; }
.search-box:focus, .chat-select:focus { border-color: var(--accent); }

.btn {
  padding: 6px 14px; border-radius: var(--radius-md); border: 1px solid var(--accent);
  background: var(--accent); color: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn:hover:not(:disabled) { filter: brightness(1.1); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--text-2); border-color: var(--border); }
.btn.ghost:hover:not(:disabled) { color: var(--text-1); background: var(--bg-hover); }

.info-banner {
  background: rgba(37,99,235,.08); border: 1px solid rgba(37,99,235,.3);
  color: var(--text-2); padding: 10px 14px; border-radius: var(--radius-md);
  font-size: 12.5px; margin-bottom: 14px; line-height: 1.6;
}
.info-banner.warn { background: rgba(240,180,40,.08); border-color: rgba(240,180,40,.3); }
.banner-link { color: var(--accent); text-decoration: none; font-weight: 600; }
.banner-link:hover { text-decoration: underline; }

.state { text-align: center; color: var(--text-3); padding: 48px 0; font-size: 13px; }
.state.sm { padding: 18px 0; font-size: 12px; }
.hint { font-size: 11px; color: var(--text-3); margin-top: 6px; }

/* 日期分隔 */
.date-divider { display: flex; align-items: center; gap: 10px; margin: 18px 0 10px; }
.date-divider::before, .date-divider::after {
  content: ''; flex: 1; height: 1px; background: var(--border);
}
.date-divider span { font-size: 11px; color: var(--text-3); font-weight: 600; white-space: nowrap; }

/* 消息流 */
.msg-feed { display: flex; flex-direction: column; }
.msg-card {
  display: flex; gap: 10px; padding: 10px 4px;
  border-bottom: 1px solid var(--border);
}
.msg-card:last-child { border-bottom: none; }
.msg-card.system { opacity: .65; }
.msg-card.system .msg-text { font-style: italic; color: var(--text-3); }

.msg-avatar {
  flex-shrink: 0; width: 34px; height: 34px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 15px; font-weight: 700; user-select: none;
}
.msg-main { flex: 1; min-width: 0; }
.msg-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 3px; flex-wrap: wrap; }
.msg-chat { font-size: 13px; font-weight: 600; color: var(--text-1); }
.msg-time { font-size: 11px; color: var(--text-3); }
.msg-type {
  font-size: 10px; padding: 0 6px; border-radius: 10px; line-height: 16px;
  background: var(--bg-hover); color: var(--text-3); border: 1px solid var(--border);
}

.msg-body { display: flex; flex-direction: column; gap: 8px; }
.msg-text {
  margin: 0; font-size: 13.5px; color: var(--text-1); line-height: 1.75;
  word-break: break-word; white-space: normal;
}
.msg-text :deep(.tag) {
  color: var(--accent); font-weight: 600;
  background: rgba(37,99,235,.08); padding: 0 4px; border-radius: 4px;
}
.msg-text :deep(a) { color: var(--accent); text-decoration: none; word-break: break-all; }
.msg-text :deep(a:hover) { text-decoration: underline; }
.msg-text :deep(.muted) { color: var(--text-3); font-style: italic; }

.msg-img {
  max-width: min(320px, 100%); max-height: 360px; border-radius: var(--radius-md);
  border: 1px solid var(--border); cursor: zoom-in; object-fit: contain; display: block;
  transition: filter .15s;
}
.msg-img:hover { filter: brightness(1.04); }

.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 22px; }
.pager-info { font-size: 12px; color: var(--text-3); }

/* lightbox */
.lightbox {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,.82); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center; cursor: zoom-out;
}
.lb-img {
  max-width: 92vw; max-height: 88vh; object-fit: contain;
  border-radius: var(--radius-md); box-shadow: 0 8px 40px rgba(0,0,0,.5); cursor: default;
}
.lb-close {
  position: fixed; top: 18px; right: 22px; width: 38px; height: 38px;
  border-radius: 50%; border: none; cursor: pointer; font-size: 18px;
  background: rgba(255,255,255,.12); color: #fff; line-height: 1;
}
.lb-close:hover { background: rgba(255,255,255,.24); }
.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .fs-view { padding: 12px; }
  .fs-header { gap: 10px; }
  .search-box { flex: 1; min-width: 120px; width: auto; }
  .chat-select { flex: 1; min-width: 110px; max-width: none; }
  .msg-img { max-width: 100%; }
  .set-row { flex-wrap: wrap; }
  .set-name { width: auto; flex: 1; }
  .set-marker { flex-basis: 100%; order: 5; }
}
</style>
