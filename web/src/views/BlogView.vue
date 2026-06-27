<template>
  <div class="blog-view">
    <!-- ══ 顶栏 ══════════════════════════════════════════════ -->
    <div class="blog-header">
      <div class="header-left">
        <h2 class="blog-title">机构荐股</h2>
      </div>
      <div class="header-right">
        <div class="status-pills">
          <span class="pill">{{ status.count }} 篇</span>
          <span class="pill" :class="status.cookie_set ? 'ok' : 'warn'">
            {{ status.cookie_set ? '凭证已设' : '未设凭证' }}
          </span>
          <span class="pill" v-if="status.last_fetch">
            更新 {{ fmtTime(status.last_fetch) }}
          </span>
          <span class="pill" :class="status.enabled ? 'ok' : 'muted'">
            {{ status.enabled ? '整点每小时' : '已暂停' }}
          </span>
        </div>
        <input
          v-model="search" class="search-box" placeholder="搜索标题/正文…"
          @keyup.enter="loadPosts(1)"
        />
        <button class="btn" @click="refresh" :disabled="refreshing">
          {{ refreshing ? '抓取中…' : '立即刷新' }}
        </button>
        <button class="btn ghost" @click="backfill" :disabled="backfilling"
          title="拉取近半年历史帖子入库并生成 AI 标题（耗时较长）">
          {{ backfilling ? '回填中…' : '回填半年' }}
        </button>
        <button class="btn ghost" @click="showSettings = !showSettings">设置</button>
      </div>
    </div>

    <!-- ══ 视图切换 tab：帖子 / 机构胜率榜 ═══════════════════ -->
    <div class="view-tabs">
      <button class="vtab" :class="{ active: viewTab === 'posts' }" @click="viewTab = 'posts'">
        帖子
      </button>
      <button class="vtab" :class="{ active: viewTab === 'winrate' }" @click="viewTab = 'winrate'">
        机构胜率榜
      </button>
    </div>

    <!-- ══ 机构胜率榜 ════════════════════════════════════════ -->
    <InstitutionWinrate v-if="viewTab === 'winrate'" />

    <template v-else>
    <!-- ══ 分类标签（按作者分组，如 芒种/小满）═════════════ -->
    <div v-if="categories.length" class="category-bar">
      <button class="cat-chip" :class="{ active: !activeCat }" @click="selectCat('')">
        全部 <span class="cat-count">{{ totalCatCount }}</span>
      </button>
      <button
        v-for="c in categories" :key="c.group_id || c.name"
        class="cat-chip" :class="{ active: activeCat === (c.group_id || c.name) }"
        @click="selectCat(c.group_id || c.name)"
      >{{ c.name }} <span class="cat-count">{{ c.count }}</span></button>
    </div>

    <!-- 上次抓取错误提示 -->
    <div v-if="status.last_run && status.last_run.ok === false && status.last_run.error"
         class="error-banner">
      ⚠️ 上次抓取失败：{{ status.last_run.error }}
    </div>

    <!-- ══ 设置面板 ══════════════════════════════════════════ -->
    <transition name="fade">
      <div v-if="showSettings" class="settings-panel">
        <div class="settings-row inline">
          <div>
            <label>星球 Group ID</label>
            <input v-model="form.group_id" class="text-input" placeholder="28855458518111" />
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
    <div v-else-if="!posts.length" class="state">
      <p>暂无博客内容。</p>
      <p class="hint">点「立即刷新」抓取最新主题。</p>
    </div>

    <div v-else class="post-list">
      <article v-for="p in posts" :key="p.post_id" class="post-card expanded"
               :ref="(el) => observeCard(el, p.post_id)">
        <header class="post-head">
          <div class="post-meta">
            <span class="post-author">{{ p.author || '匿名' }}</span>
            <span class="post-time">{{ fmtTime(p.created_at) }}</span>
            <span v-if="p.has_youdao" class="badge-youdao">有道笔记</span>
          </div>
          <h3 class="post-card-title">{{ p.ai_title || p.title }}</h3>
        </header>

        <!-- 正文：默认全展开 -->
        <div class="post-body">
          <div v-if="!details[p.post_id]" class="state small">载入正文…</div>
          <template v-else>
            <div class="content-html" v-html="details[p.post_id].content_html"
                 @click="onHtmlImgClick"></div>

            <div v-if="details[p.post_id].images && details[p.post_id].images.length"
                 class="post-images" :class="'n-' + Math.min(details[p.post_id].images.length, 3)">
              <button v-for="(img, i) in details[p.post_id].images" :key="i" type="button"
                      class="img-cell" @click="openLightbox(details[p.post_id].images, i)">
                <img :src="img" loading="lazy" @error="onImgError" />
              </button>
            </div>

            <!-- 有道笔记：折叠，点按钮才展开（内容已后台抓好，仅控制展示） -->
            <section v-for="(yd, i) in (details[p.post_id].youdao || [])"
                     :key="i" class="youdao-block">
              <button class="youdao-head youdao-toggle" type="button"
                      @click="toggleYoudao(p.post_id, i)">
                <span class="youdao-icon">📓</span>
                <span class="youdao-title">{{ yd.title || '有道笔记' }}</span>
                <span class="youdao-caret">{{ isYoudaoOpen(p.post_id, i) ? '收起 ▲' : '展开 ▼' }}</span>
              </button>
              <template v-if="isYoudaoOpen(p.post_id, i)">
                <div class="youdao-sub">
                  <a class="youdao-src" :href="yd.url" target="_blank" rel="noopener">原链接 ↗</a>
                </div>
                <div v-if="yd.ok" class="youdao-content content-html" v-html="yd.html"
                     @click="onHtmlImgClick"></div>
                <div v-else class="youdao-failed">
                  未能抓取笔记正文（{{ yd.error || '可能需要登录/为私有笔记' }}）。
                  <a :href="yd.url" target="_blank" rel="noopener">点此在有道打开 ↗</a>
                </div>
              </template>
            </section>
          </template>
        </div>
      </article>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="pager">
      <button class="btn ghost" :disabled="page <= 1" @click="loadPosts(page - 1)">上一页</button>
      <span class="pager-info">{{ page }} / {{ totalPages }}</span>
      <button class="btn ghost" :disabled="page >= totalPages" @click="loadPosts(page + 1)">下一页</button>
    </div>
    </template>

    <!-- ══ 图片放大查看（lightbox）═══════════════════════════ -->
    <transition name="fade">
      <div v-if="lightbox.open" class="lightbox" @click="closeLightbox">
        <button class="lb-close" @click.stop="closeLightbox" aria-label="关闭">✕</button>
        <button v-if="lightbox.images.length > 1" class="lb-nav lb-prev"
                @click.stop="lbStep(-1)" aria-label="上一张">‹</button>
        <img class="lb-img" :src="lbCurrent" @click.stop @error="onImgError" />
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
import axios from 'axios'
import InstitutionWinrate from '../components/InstitutionWinrate.vue'

const route = useRoute()
const router = useRouter()

// 视图切换：帖子列表 / 机构胜率榜
const viewTab = ref(route.query.tab === 'winrate' ? 'winrate' : 'posts')

const posts = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const search = ref('')

// 分类（按作者聚合，如 芒种/小满）
const categories = ref([])
const activeCat = ref(String(route.query.category || ''))
const totalCatCount = computed(() => categories.value.reduce((s, c) => s + (c.count || 0), 0))

function selectCat(name) {
  activeCat.value = name
  // 同步到 URL，便于从侧边子菜单深链 / 刷新保持
  router.replace({ query: name ? { category: name } : {} })
  loadPosts(1)
}

// 侧边子菜单切换分类时（同一路由 query 变化）跟随
watch(() => route.query.category, (c) => {
  const v = String(c || '')
  if (v !== activeCat.value) { activeCat.value = v; loadPosts(1) }
})

const status = reactive({
  count: 0, last_fetch: null, enabled: true, cookie_set: false,
  group_id: '28855458518111', group_name: '',
  group_url: 'https://wx.zsxq.com/group/28855458518111',
  last_run: null,
})

const showSettings = ref(false)
const form = reactive({ group_id: '', enabled: true })
const savingConfig = ref(false)
const configMsg = ref('')
const refreshing = ref(false)
const backfilling = ref(false)

// 每篇正文详情：{ [post_id]: detail }，进页面后并发（限流）加载当前页全部
const details = reactive({})
// 有道笔记展开状态：Set('<post_id>:<index>')
const openYoudao = ref(new Set())

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

// ── 图片放大查看 ──────────────────────────────────────────
const lightbox = reactive({ open: false, images: [], index: 0 })
const lbCurrent = computed(() => lightbox.images[lightbox.index] || '')
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
// 正文/有道笔记 v-html 内的事件委托：点图放大；点个股链接走前端路由跳详情。
function onHtmlImgClick(e) {
  const el = e?.target
  if (!el) return
  // 个股链接（后端注入的 a.stock-ref）：拦截默认整页跳转，用路由内部跳。
  const ref = el.closest?.('a.stock-ref')
  if (ref) {
    const code = ref.getAttribute('data-code')
    if (code) { e.preventDefault(); window.open(router.resolve(`/stock/${code}`).href, '_blank') }
    return
  }
  if (el.tagName === 'IMG' && el.src) openLightbox([el.src], 0)
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

// 有道笔记折叠/展开（内容已随 detail 抓好，仅控制展示）
function youdaoKey(pid, i) { return `${pid}:${i}` }
function isYoudaoOpen(pid, i) { return openYoudao.value.has(youdaoKey(pid, i)) }
function toggleYoudao(pid, i) {
  const k = youdaoKey(pid, i)
  const s = new Set(openYoudao.value)
  s.has(k) ? s.delete(k) : s.add(k)
  openYoudao.value = s
}

function fmtTime(s) {
  if (!s) return ''
  try {
    const d = new Date(s)
    if (isNaN(d.getTime())) return s
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch { return s }
}

async function loadStatus() {
  try {
    const { data } = await axios.get('/api/xingqiu/status')
    Object.assign(status, data)
    form.group_id = data.group_id
    form.enabled = data.enabled
  } catch (e) { /* ignore */ }
}

async function loadPosts(p = 1) {
  loading.value = true
  page.value = p
  try {
    const { data } = await axios.get('/api/xingqiu/posts', {
      params: {
        page: p, page_size: pageSize,
        search: search.value || undefined,
        category: activeCat.value || undefined,
      },
    })
    posts.value = data.posts || []
    total.value = data.total || 0
    status.count = data.count
    status.last_fetch = data.fetched_at
    if (data.categories) categories.value = data.categories
    // 换页/筛选后清空旧正文与观察登记，懒加载按视口重新触发
    for (const k of Object.keys(details)) delete details[k]
    openYoudao.value = new Set()
    _observed.clear()
    if (_io) _io.disconnect()   // 旧元素的观察作废；新卡片由 :ref 重新登记
  } catch (e) {
    posts.value = []
  } finally {
    loading.value = false
  }
}

// ── 懒加载：滚动到视口才拉该篇正文 ─────────────────────────
let _io = null                       // IntersectionObserver
const _observed = new Set()          // 已登记观察的 post_id，避免重复
const _elToId = new WeakMap()        // DOM 元素 → post_id

function ensureObserver() {
  if (_io) return _io
  _io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue
      const pid = _elToId.get(e.target)
      _io.unobserve(e.target)        // 加载一次即停止观察
      if (pid) loadDetail(pid)
    }
  }, { rootMargin: '300px 0px' })    // 提前 300px 预加载，滚动更顺
  return _io
}

// 卡片 :ref 回调：元素挂载时登记到 observer，卸载时解绑
function observeCard(el, pid) {
  if (!el) return
  _elToId.set(el, pid)
  if (_observed.has(pid) || details[pid]) return
  _observed.add(pid)
  ensureObserver().observe(el)
}

async function loadDetail(pid) {
  if (details[pid]) return
  try {
    const { data } = await axios.get(`/api/xingqiu/posts/${pid}`)
    details[pid] = data
  } catch (e) { /* 失败保留“载入正文…”占位，下次滚动不会重试 */ }
}

async function refresh() {
  refreshing.value = true
  configMsg.value = ''
  try {
    const { data } = await axios.post('/api/xingqiu/refresh')
    status.last_run = data
    await Promise.all([loadStatus(), loadPosts(1)])
  } catch (e) {
    /* ignore */
  } finally {
    refreshing.value = false
  }
}

async function backfill() {
  if (backfilling.value) return
  backfilling.value = true
  try {
    const { data } = await axios.post('/api/xingqiu/backfill')
    if (data && data.ok) {
      await Promise.all([loadStatus(), loadPosts(1)])
    }
  } catch (e) {
    /* ignore */
  } finally {
    backfilling.value = false
  }
}

async function saveConfig() {
  savingConfig.value = true
  configMsg.value = ''
  try {
    const payload = { group_id: form.group_id, enabled: form.enabled }
    await axios.put('/api/xingqiu/config', payload)
    configMsg.value = '已保存'
    await loadStatus()
  } catch (e) {
    configMsg.value = '保存失败'
  } finally {
    savingConfig.value = false
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKeydown)
  await loadStatus()
  await loadPosts(1)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (_io) _io.disconnect()
})
</script>

<style scoped>
.blog-view { padding: 16px 20px; max-width: 880px; margin: 0 auto; }

/* 视图切换 tab */
.view-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 14px; }
.vtab {
  background: none; border: none; cursor: pointer; padding: 8px 16px;
  font-size: 14px; color: var(--text-3); border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.vtab.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

.blog-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin-bottom: 14px;
}
.header-left { display: flex; align-items: baseline; gap: 12px; }
.blog-title { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 0; }
.group-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.group-link:hover { text-decoration: underline; }

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

/* 设置面板 */
.settings-panel {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 16px; margin-bottom: 16px;
}
.settings-row { margin-bottom: 12px; }
.settings-row label { display: block; font-size: 12px; color: var(--text-2); margin-bottom: 5px; font-weight: 600; }
.settings-row.inline { display: flex; gap: 24px; align-items: flex-end; flex-wrap: wrap; }
.cookie-input {
  width: 100%; background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1); padding: 8px 10px;
  font-size: 12px; font-family: var(--font-mono); resize: vertical; outline: none;
}
.cookie-input:focus { border-color: var(--accent); }
.hint { font-size: 11px; color: var(--text-3); margin: 6px 0 0; line-height: 1.6; }
.hint code { background: var(--bg-hover); padding: 1px 5px; border-radius: 4px; color: var(--accent); }
.switch-label { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); cursor: pointer; }
.settings-actions { display: flex; align-items: center; gap: 12px; margin-top: 6px; }
.config-msg { font-size: 12px; color: var(--success); }

/* 列表 */
.state { text-align: center; color: var(--text-3); padding: 48px 0; font-size: 13px; }
.state.small { padding: 18px 0; }
.post-list { display: flex; flex-direction: column; gap: 12px; }
.post-card {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); overflow: hidden; transition: border-color .15s;
}
.post-card:hover { border-color: rgba(37,99,235,.35); }
.post-head { padding: 14px 16px 10px; }
.post-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.post-author { font-size: 12px; font-weight: 600; color: var(--accent); }
.post-time { font-size: 11px; color: var(--text-3); }
.badge-youdao {
  font-size: 10px; padding: 1px 7px; border-radius: 20px;
  background: rgba(22,163,74,.1); color: var(--success); border: 1px solid rgba(22,163,74,.3);
}
.post-card-title { font-size: 15px; font-weight: 600; color: var(--text-1); margin: 0 0 6px; line-height: 1.4; }
.post-preview { font-size: 12.5px; color: var(--text-3); margin: 0; line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

.post-body { padding: 0 16px 16px; border-top: 1px solid var(--border); }
.content-html { font-size: 13.5px; color: var(--text-1); line-height: 1.8; word-break: break-word; }
.content-html :deep(p) { margin: 8px 0; }
.content-html :deep(a) { color: var(--accent); }
.content-html :deep(img) { max-width: 100%; border-radius: var(--radius-md); margin: 8px 0; cursor: zoom-in; }
.content-html :deep(.zsxq-tag) { color: var(--accent); }
.content-html :deep(.zsxq-at) { color: #2563eb; }
.content-html :deep(.zsxq-label) { font-weight: 700; color: var(--text-2); margin-top: 12px; }
/* 个股链接：加黑 + A股红 + 可点击跳详情 */
.content-html :deep(a.stock-ref) {
  color: #e5484d; text-decoration: none; cursor: pointer;
  border-bottom: 1px dashed rgba(229,72,77,.4); white-space: nowrap;
}
.content-html :deep(a.stock-ref:hover) { border-bottom-style: solid; }
.content-html :deep(a.stock-ref b) { font-weight: 700; }

/* 配图网格：1 图大图、2/3+ 图等分方格，自适应卡片宽度 */
.post-images { display: grid; gap: 6px; margin-top: 10px; }
.post-images.n-1 { grid-template-columns: minmax(0, 360px); }
.post-images.n-2 { grid-template-columns: repeat(2, 1fr); }
.post-images.n-3 { grid-template-columns: repeat(3, 1fr); }
.img-cell {
  padding: 0; border: 1px solid var(--border); background: var(--bg-base);
  border-radius: var(--radius-md); overflow: hidden; cursor: zoom-in;
  aspect-ratio: 1 / 1; display: block; transition: filter .15s, transform .15s;
}
.post-images.n-1 .img-cell { aspect-ratio: auto; max-height: 420px; }
.img-cell:hover { filter: brightness(1.04); transform: translateY(-1px); }
.img-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.post-images.n-1 .img-cell img { object-fit: contain; max-height: 420px; }

/* 图片放大查看 */
.lightbox {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0, 0, 0, .82); backdrop-filter: blur(2px);
  display: flex; align-items: center; justify-content: center; cursor: zoom-out;
}
.lb-img {
  max-width: 92vw; max-height: 88vh; object-fit: contain;
  border-radius: var(--radius-md); box-shadow: 0 8px 40px rgba(0, 0, 0, .5); cursor: default;
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

.youdao-block {
  margin-top: 16px; border: 1px solid rgba(22,163,74,0.3);
  border-radius: var(--radius-md); background: rgba(22,163,74,0.04); padding: 12px 14px;
}
.youdao-head { display: flex; align-items: center; gap: 8px; }
.youdao-toggle {
  width: 100%; padding: 2px 0; background: none; border: none; cursor: pointer;
  text-align: left; font: inherit;
}
.youdao-icon { font-size: 15px; }
.youdao-title { font-size: 13px; font-weight: 700; color: var(--text-1); flex: 1; }
.youdao-caret { font-size: 11px; color: var(--text-3); white-space: nowrap; }
.youdao-toggle:hover .youdao-caret { color: var(--accent); }
.youdao-sub { margin: 6px 0 2px; }
.youdao-src { font-size: 11px; color: var(--accent); text-decoration: none; }
.youdao-content { margin-top: 6px; }
.youdao-failed { font-size: 12px; color: var(--text-3); margin-top: 6px; }
.youdao-failed a { color: var(--accent); }

.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 20px; }
.pager-info { font-size: 12px; color: var(--text-3); }

.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 768px) {
  .blog-view { padding: 12px; }
  .blog-header { flex-wrap: wrap; gap: 10px; }
  .settings-row.inline { gap: 14px; }
}

/* 分类标签栏（按作者，如 芒种/小满）*/
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
</style>
