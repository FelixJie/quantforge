<template>
  <div class="fc-view">
    <!-- ══ 顶栏 ══════════════════════════════════════════════ -->
    <div class="fc-header">
      <div class="header-left">
        <h2 class="fc-title">公众号</h2>
      </div>
      <div class="header-right">
        <div class="status-pills">
          <span class="pill">{{ status.count }} 帖</span>
          <span class="pill" :class="status.token_set ? 'ok' : 'warn'">
            {{ status.token_set ? '已登录' : '未登录' }}
          </span>
          <span class="pill" v-if="status.updated_at">
            更新 {{ fmtTime(status.updated_at) }}
          </span>
          <span class="pill" :class="status.enabled ? 'ok' : 'muted'">
            {{ status.enabled ? '整点每小时' : '已暂停' }}
          </span>
        </div>
        <input
          v-model="search" class="search-box" placeholder="搜索标题/正文…"
          @keyup.enter="loadPosts"
        />
        <button class="btn" @click="refresh" :disabled="refreshing">
          {{ refreshing ? '抓取中…' : '立即刷新' }}
        </button>
        <button class="btn ghost" @click="showSettings = !showSettings">设置</button>
      </div>
    </div>

    <!-- ══ 分类标签（按作者/圈子名分组，如 Henry）═════════════ -->
    <div v-if="categories.length" class="category-bar">
      <button
        class="cat-chip" :class="{ active: !activeCat }"
        @click="selectCat('')"
      >全部 <span class="cat-count">{{ totalCount }}</span></button>
      <button
        v-for="c in categories" :key="c.name"
        class="cat-chip" :class="{ active: activeCat === c.name }"
        @click="selectCat(c.name)"
      >{{ c.name }} <span class="cat-count">{{ c.count }}</span></button>
    </div>

    <!-- 登录失效 / 抓取错误提示 -->
    <div v-if="status.status === 'login_required' || !status.token_set" class="error-banner">
      🔑 公众号内容暂不可用（登录态失效）。
      <span v-if="status.error" class="hint-inline">原因：{{ status.error }}</span>
      <template v-if="isAdmin">
        <button class="btn login-btn" @click="goAuth">去后台扫码授权</button>
        <span class="hint-inline">在管理后台「公众号授权」里用微信扫码即可，任一管理员都能授权。</span>
      </template>
      <span v-else class="hint-inline">请联系管理员在后台重新扫码授权。</span>
    </div>
    <div v-else-if="status.status === 'error' && status.error" class="error-banner">
      ⚠️ 上次抓取失败：{{ status.error }}
    </div>

    <!-- ══ 设置面板 ══════════════════════════════════════════ -->
    <transition name="fade">
      <div v-if="showSettings" class="settings-panel">
        <div class="settings-row">
          <label>fc-token（浏览器 pc.fenchuan8.com Cookie 里的 <code>fc-token</code>，留空表示不修改）</label>
          <textarea v-model="form.token" class="cookie-input" rows="2"
                    placeholder="粘贴 fc-token，或留空沿用 token.txt / 扫码登录" />
        </div>
        <div class="settings-row inline">
          <div>
            <label>圈子 qz_id（URL 里的 forum=）</label>
            <input v-model="form.qz_id" class="text-input" placeholder="105371" />
          </div>
          <label class="switch-label">
            <input type="checkbox" v-model="form.enabled" />
            启用整点每小时自动抓取
          </label>
        </div>
        <div class="settings-actions">
          <button class="btn" @click="saveConfig" :disabled="savingConfig">
            {{ savingConfig ? '保存中…' : '保存配置' }}
          </button>
          <span v-if="configMsg" class="config-msg">{{ configMsg }}</span>
        </div>
      </div>
    </transition>

    <!-- ══ 列表 ══════════════════════════════════════════════ -->
    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="!posts.length" class="empty-box">
      <div class="empty-icon">📭</div>
      <p class="empty-title">暂无公众号内容</p>
      <p class="empty-sub" v-if="status.status === 'login_required' || !status.token_set">
        登录态已失效，重新扫码授权后内容会自动恢复。
      </p>
      <p class="empty-sub" v-else>点「立即刷新」抓取最新帖子。</p>
      <div class="empty-actions">
        <button class="btn" @click="refresh" :disabled="refreshing">
          {{ refreshing ? '抓取中…' : '立即刷新' }}
        </button>
        <button v-if="isAdmin && (status.status === 'login_required' || !status.token_set)"
                class="btn ghost" @click="goAuth">去后台扫码授权</button>
      </div>
    </div>

    <div v-else class="post-list">
      <article v-for="p in posts" :key="p.id" class="post-card">
        <header class="post-head">
          <img v-if="p.avatar" class="post-avatar" :src="p.avatar" alt=""
               loading="lazy" referrerpolicy="no-referrer" />
          <div class="post-meta">
            <span class="post-author">{{ p.author || '匿名' }}</span>
            <span class="post-time">{{ p.time }}</span>
            <span v-if="p.is_top" class="badge-top">置顶</span>
          </div>
        </header>

        <h3 v-if="p.title" class="post-card-title">{{ p.title }}</h3>
        <p v-if="p.text" class="post-text">{{ p.text }}</p>

        <!-- 外链 -->
        <div v-if="p.links && p.links.length" class="post-links">
          <a v-for="(lk, i) in p.links" :key="i" :href="lk.url" target="_blank"
             rel="noopener" class="post-link">🔗 {{ lk.text }}</a>
        </div>

        <!-- 配图 -->
        <div v-if="p.images && p.images.length"
             class="post-images" :class="'n-' + Math.min(p.images.length, 3)">
          <button v-for="(img, i) in p.images" :key="i" type="button"
                  class="img-cell" @click="openLightbox(p.images, i)">
            <img :src="img.thumb" loading="lazy" referrerpolicy="no-referrer"
                 @error="onImgError" />
          </button>
        </div>

        <footer class="post-foot">
          <span class="stat">👍 {{ p.stats.zan }}</span>
          <button v-if="(p.comments && p.comments.length) || p.stats.comment"
                  class="stat stat-btn" @click="toggleComments(p.id)">
            💬 {{ p.stats.comment }}<span v-if="isOpen(p.id)"> 收起</span>
          </button>
          <span v-else class="stat">💬 0</span>
          <span class="stat">👁 {{ p.stats.view }}</span>
          <a v-if="p.url" class="post-src" :href="p.url" target="_blank" rel="noopener">原帖 ↗</a>
        </footer>

        <!-- 评论区 -->
        <div v-if="isOpen(p.id)" class="comments">
          <div v-if="!p.comments || !p.comments.length" class="comments-empty">
            暂无已抓取的评论（下次刷新后显示）。
          </div>
          <template v-else>
            <div class="comments-count">已抓取 {{ p.comments.length }} 条评论</div>
            <div v-for="c in p.comments" :key="c.id" class="comment">
              <img v-if="c.avatar" class="c-avatar" :src="c.avatar" alt=""
                   loading="lazy" referrerpolicy="no-referrer" />
              <div class="c-body">
                <div class="c-meta">
                  <span class="c-user">{{ c.user || '匿名' }}</span>
                  <span v-if="c.is_master" class="c-master">博主</span>
                  <span class="c-time">{{ fmtCmtTime(c.time) }}</span>
                  <span v-if="c.zan" class="c-zan">👍 {{ c.zan }}</span>
                </div>
                <p class="c-text">{{ c.text }}</p>
                <img v-if="c.img" class="c-img" :src="c.img" loading="lazy"
                     referrerpolicy="no-referrer"
                     @click="openLightbox([{ full: c.img, thumb: c.img }], 0)" />
                <!-- 二级回复 -->
                <div v-for="r in (c.replies || [])" :key="r.id" class="reply">
                  <span class="c-user">{{ r.user || '匿名' }}</span>
                  <span v-if="r.is_master" class="c-master">博主</span>
                  <span class="c-time">{{ fmtCmtTime(r.time) }}</span>
                  <span class="r-text">{{ r.text }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </article>
    </div>

    <!-- ══ 图片放大查看（lightbox）═══════════════════════════ -->
    <transition name="fade">
      <div v-if="lightbox.open" class="lightbox" @click="closeLightbox">
        <button class="lb-close" @click.stop="closeLightbox" aria-label="关闭">✕</button>
        <button v-if="lightbox.images.length > 1" class="lb-nav lb-prev"
                @click.stop="lbStep(-1)" aria-label="上一张">‹</button>
        <img class="lb-img" :src="lbCurrent" referrerpolicy="no-referrer"
             @click.stop @error="onImgError" />
        <button v-if="lightbox.images.length > 1" class="lb-nav lb-next"
                @click.stop="lbStep(1)" aria-label="下一张">›</button>
        <div v-if="lightbox.images.length > 1" class="lb-count">
          {{ lightbox.index + 1 }} / {{ lightbox.images.length }}
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const { isAdmin } = storeToRefs(useAuthStore())

function goAuth() {
  window.open(router.resolve({ path: '/admin', query: { tab: 'fenchuan' } }).href, '_blank')
}

const posts = ref([])
const loading = ref(false)
const search = ref('')

const categories = ref([])      // [{name, count}]，按作者/圈子聚合
const activeCat = ref(String(route.query.category || ''))  // 当前选中的分类，空=全部
const totalCount = computed(() =>
  categories.value.reduce((s, c) => s + (c.count || 0), 0))

function selectCat(name) {
  activeCat.value = name
  router.replace({ query: name ? { category: name } : {} })
  loadPosts()
}

// 侧边子菜单切换分类时跟随
watch(() => route.query.category, (c) => {
  const v = String(c || '')
  if (v !== activeCat.value) { activeCat.value = v; loadPosts() }
})

const status = reactive({
  status: 'init', error: '', count: 0, updated_at: 0,
  qz_id: '105371', enabled: true, token_set: false,
  forum_url: 'https://pc.fenchuan8.com/#/index?forum=105371',
})

const showSettings = ref(false)
const form = reactive({ token: '', qz_id: '', enabled: true })
const savingConfig = ref(false)
const configMsg = ref('')
const refreshing = ref(false)

// ── 图片放大查看 ──────────────────────────────────────────
const lightbox = reactive({ open: false, images: [], index: 0 })
const lbCurrent = computed(() => {
  const img = lightbox.images[lightbox.index]
  return img ? (img.full || img.thumb) : ''
})
function openLightbox(images, index) {
  lightbox.images = images || []
  lightbox.index = index || 0
  lightbox.open = true
}
function closeLightbox() { lightbox.open = false }
function lbStep(d) {
  const n = lightbox.images.length
  if (n) lightbox.index = (lightbox.index + d + n) % n
}
function onKeydown(e) {
  if (!lightbox.open) return
  if (e.key === 'Escape') closeLightbox()
  else if (e.key === 'ArrowLeft') lbStep(-1)
  else if (e.key === 'ArrowRight') lbStep(1)
}

// 图片加载失败时隐藏，避免破图占位
function onImgError(e) {
  const el = e?.target
  if (el) el.style.display = 'none'
}

const openIds = ref(new Set())
function isOpen(id) { return openIds.value.has(id) }
function toggleComments(id) {
  const s = new Set(openIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  openIds.value = s
}

function fmtCmtTime(t) {
  if (!t) return ''
  // new_list 的 add_time 多为 unix 秒；也可能已是 "05月28日 14:48" 文本
  if (/^\d{9,11}$/.test(String(t))) return fmtTime(Number(t))
  return String(t)
}

function fmtTime(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts * 1000)
    if (isNaN(d.getTime())) return ''
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function applyStatus(s) {
  if (!s) return
  Object.assign(status, s)
  form.qz_id = s.qz_id
  form.enabled = s.enabled
}

async function loadPosts() {
  loading.value = true
  try {
    const { data } = await axios.get('/api/fenchuan/posts', {
      params: {
        search: search.value || undefined,
        category: activeCat.value || undefined,
      },
    })
    posts.value = data.posts || []
    if (data.categories) categories.value = data.categories
    applyStatus(data.status)
  } catch (e) {
    posts.value = []
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  try {
    const { data } = await axios.post('/api/fenchuan/refresh')
    applyStatus(data)
    await loadPosts()
  } catch (e) {
    /* ignore */
  } finally {
    refreshing.value = false
  }
}

async function saveConfig() {
  savingConfig.value = true
  configMsg.value = ''
  try {
    const payload = { qz_id: form.qz_id, enabled: form.enabled }
    if (form.token.trim()) payload.token = form.token.trim()
    const { data } = await axios.put('/api/fenchuan/config', payload)
    applyStatus(data)
    form.token = ''
    configMsg.value = '已保存'
    await loadPosts()
  } catch (e) {
    configMsg.value = '保存失败'
  } finally {
    savingConfig.value = false
  }
}

onMounted(() => {
  loadPosts()
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.fc-view { padding: 16px 20px; max-width: 880px; margin: 0 auto; }

.fc-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin-bottom: 14px;
}
.header-left { display: flex; align-items: baseline; gap: 12px; }
.fc-title { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 0; }
.forum-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.forum-link:hover { text-decoration: underline; }

.header-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.status-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.pill {
  font-size: 11px; padding: 3px 8px; border-radius: 20px;
  background: var(--bg-hover); color: var(--text-3); border: 1px solid var(--border);
  white-space: nowrap;
}
.pill.ok { color: var(--success); border-color: rgba(22,163,74,.3); background: rgba(22,163,74,.08); }
.pill.warn { color: var(--warning); border-color: rgba(240,180,40,.3); background: rgba(240,180,40,.08); }
.pill.muted { color: var(--text-3); }

.search-box, .text-input {
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1);
  padding: 6px 10px; font-size: 12px; outline: none;
}
.search-box { width: 180px; }
.search-box:focus, .text-input:focus { border-color: var(--accent); }

.btn {
  padding: 6px 14px; border-radius: var(--radius-md); border: 1px solid var(--accent);
  background: var(--accent); color: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn:hover:not(:disabled) { filter: brightness(1.1); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.btn.ghost { background: transparent; color: var(--text-2); border-color: var(--border); }
.btn.ghost:hover:not(:disabled) { color: var(--text-1); background: var(--bg-hover); }

.error-banner {
  background: rgba(240,80,96,.08); border: 1px solid rgba(240,80,96,.3);
  color: #dc2626; padding: 8px 12px; border-radius: var(--radius-md);
  font-size: 12px; margin-bottom: 12px;
}
/* 分类标签栏 */
.category-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.cat-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 5px 12px; border-radius: 20px; cursor: pointer;
  background: var(--bg-surface); border: 1px solid var(--border);
  color: var(--text-2); font-size: 12px; font-weight: 600; transition: all .15s;
}
.cat-chip:hover { color: var(--text-1); border-color: rgba(37,99,235,.4); }
.cat-chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.cat-count {
  font-size: 10px; font-weight: 700; padding: 0 6px; border-radius: 10px;
  background: var(--bg-hover); color: var(--text-3);
}
.cat-chip.active .cat-count { background: rgba(255,255,255,.22); color: #fff; }

.hint-inline { color: var(--text-3); margin-left: 6px; }
.login-btn { margin-left: 10px; padding: 3px 12px; font-size: 11px; vertical-align: middle; }
.hint-inline code, .error-banner code { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; color: var(--accent); }

/* 设置面板 */
.settings-panel {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 16px; margin-bottom: 16px;
}
.settings-row { margin-bottom: 12px; }
.settings-row label { display: block; font-size: 12px; color: var(--text-2); margin-bottom: 5px; font-weight: 600; }
.settings-row label code { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; color: var(--accent); }
.settings-row.inline { display: flex; gap: 24px; align-items: flex-end; flex-wrap: wrap; }
.cookie-input {
  width: 100%; background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1); padding: 8px 10px;
  font-size: 12px; font-family: var(--font-mono); resize: vertical; outline: none;
}
.cookie-input:focus { border-color: var(--accent); }
.switch-label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.settings-actions { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.config-msg { font-size: 12px; color: var(--success); }

/* 列表 */
.state { text-align: center; color: var(--text-3); padding: 48px 0; font-size: 13px; }
.hint { font-size: 11px; color: var(--text-3); margin: 6px 0 0; line-height: 1.6; }

/* 无数据占位框：始终显示一个边框卡片，避免页面整片空白 */
.empty-box {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; text-align: center;
  background: var(--bg-surface); border: 1px dashed var(--border);
  border-radius: var(--radius-lg); padding: 48px 20px;
}
.empty-icon { font-size: 34px; line-height: 1; opacity: .8; }
.empty-title { font-size: 14px; font-weight: 600; color: var(--text-1); margin: 0; }
.empty-sub { font-size: 12px; color: var(--text-3); margin: 0; line-height: 1.6; }
.empty-actions { display: flex; gap: 10px; margin-top: 8px; flex-wrap: wrap; justify-content: center; }
.post-list { display: flex; flex-direction: column; gap: 12px; }
.post-card {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 14px 16px; transition: border-color .15s;
}
.post-card:hover { border-color: rgba(37,99,235,.35); }

.post-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.post-avatar { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
.post-meta { display: flex; align-items: center; gap: 10px; }
.post-author { font-size: 12px; font-weight: 600; color: var(--accent); }
.post-time { font-size: 11px; color: var(--text-3); }
.badge-top {
  font-size: 10px; padding: 1px 7px; border-radius: 20px;
  background: rgba(240,180,40,.12); color: var(--warning); border: 1px solid rgba(240,180,40,.3);
}
.post-card-title { font-size: 15px; font-weight: 600; color: var(--text-1); margin: 0 0 6px; line-height: 1.4; }
.post-text { font-size: 13.5px; color: var(--text-1); line-height: 1.8; margin: 0; white-space: pre-wrap; word-break: break-word; }

.post-links { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
.post-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.post-link:hover { text-decoration: underline; }

/* 配图网格：1 图大图、2/3+ 图等分方格，自适应卡片宽度 */
.post-images { display: grid; gap: 6px; margin-top: 10px; }
.post-images.n-1 { grid-template-columns: minmax(0, 320px); }
.post-images.n-2 { grid-template-columns: repeat(2, 1fr); }
.post-images.n-3 { grid-template-columns: repeat(3, 1fr); }
.img-cell {
  padding: 0; border: 1px solid var(--border); background: var(--bg-base);
  border-radius: var(--radius-md); overflow: hidden; cursor: zoom-in;
  aspect-ratio: 1 / 1; display: block; transition: filter .15s, transform .15s;
}
.post-images.n-1 .img-cell { aspect-ratio: auto; max-height: 360px; }
.img-cell:hover { filter: brightness(1.04); transform: translateY(-1px); }
.img-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.post-images.n-1 .img-cell img { object-fit: contain; max-height: 360px; }

/* 图片放大查看 */
.lightbox {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, .82); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center;
  cursor: zoom-out;
}
.lb-img {
  max-width: 92vw; max-height: 88vh; object-fit: contain;
  border-radius: var(--radius-md); box-shadow: 0 8px 40px rgba(0, 0, 0, .5);
  cursor: default;
}
.lb-close {
  position: fixed; top: 18px; right: 22px; width: 38px; height: 38px;
  border-radius: 50%; border: none; cursor: pointer; font-size: 18px;
  background: rgba(255, 255, 255, .12); color: #fff; line-height: 1;
}
.lb-close:hover { background: rgba(255, 255, 255, .24); }
.lb-nav {
  position: fixed; top: 50%; transform: translateY(-50%);
  width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer;
  background: rgba(255, 255, 255, .12); color: #fff; font-size: 28px; line-height: 1;
}
.lb-nav:hover { background: rgba(255, 255, 255, .24); }
.lb-prev { left: 24px; }
.lb-next { right: 24px; }
.lb-count {
  position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
  font-size: 12px; color: rgba(255, 255, 255, .8); letter-spacing: 1px;
}

.post-foot { display: flex; align-items: center; gap: 14px; margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
.stat { font-size: 11px; color: var(--text-3); }
.stat-btn { background: none; border: none; cursor: pointer; padding: 0; font: inherit; color: var(--text-3); }
.stat-btn:hover { color: var(--accent); }
.post-src { font-size: 11px; color: var(--accent); text-decoration: none; margin-left: auto; }

/* 评论区 */
.comments { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border); display: flex; flex-direction: column; gap: 10px; }
.comments-empty { font-size: 12px; color: var(--text-3); }
.comments-count { font-size: 11px; color: var(--text-3); }
.comment { display: flex; gap: 8px; }
.c-avatar { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; flex-shrink: 0; }
.c-body { flex: 1; min-width: 0; }
.c-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 2px; flex-wrap: wrap; }
.c-user { font-size: 12px; font-weight: 600; color: var(--text-2); }
.c-master { font-size: 10px; padding: 0 6px; border-radius: 20px; background: rgba(37,99,235,.12); color: var(--accent); border: 1px solid rgba(37,99,235,.3); }
.c-time { font-size: 11px; color: var(--text-3); }
.c-zan { font-size: 11px; color: var(--text-3); }
.c-text { font-size: 13px; color: var(--text-1); line-height: 1.6; margin: 0; white-space: pre-wrap; word-break: break-word; }
.c-img { max-width: 140px; max-height: 140px; border-radius: var(--radius-md); margin-top: 6px; display: block; cursor: zoom-in; }
.reply { margin-top: 6px; padding: 6px 8px; background: var(--bg-base); border-radius: var(--radius-md); font-size: 12px; color: var(--text-2); line-height: 1.6; }
.reply .c-user { margin-right: 6px; }
.reply .r-text { color: var(--text-1); }

.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .fc-view { padding: 12px; }
}
</style>
