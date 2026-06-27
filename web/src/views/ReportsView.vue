<template>
  <div class="reports-view">
    <!-- ══ 顶栏 ══════════════════════════════════════════════ -->
    <div class="rpt-header">
      <div class="header-left">
        <h2 class="rpt-title">研报</h2>
        <div class="status-pills">
          <span class="pill">个股 {{ status.stock_count?.toLocaleString?.() ?? '—' }} 篇</span>
          <span class="pill">行业 {{ status.industry_count?.toLocaleString?.() ?? '—' }} 篇</span>
          <span class="pill" v-if="latestDate">最新 {{ latestDate }}</span>
          <span class="pill ok">整点每小时更新</span>
        </div>
      </div>
      <div class="header-right">
        <input
          v-model="search" class="search-box"
          :placeholder="tab === 'stock' ? '搜索标题/机构/代码…' : '搜索标题/机构/行业…'"
          @keyup.enter="reload()"
        />
        <button class="btn" @click="reload()" :disabled="loading">
          {{ loading ? '加载中…' : '搜索' }}
        </button>
      </div>
    </div>

    <!-- ══ 类型切换 ══════════════════════════════════════════ -->
    <div class="view-tabs">
      <button class="vtab" :class="{ active: tab === 'stock' }" @click="switchTab('stock')">
        个股研报
      </button>
      <button class="vtab" :class="{ active: tab === 'industry' }" @click="switchTab('industry')">
        行业策略
      </button>
    </div>

    <!-- ══ 过滤条 ════════════════════════════════════════════ -->
    <div class="filter-bar">
      <div class="filter-group">
        <span class="filter-label">时间</span>
        <button v-for="d in dayOptions" :key="d.value" class="chip"
                :class="{ active: days === d.value }" @click="setDays(d.value)">
          {{ d.label }}
        </button>
      </div>
      <div class="filter-group" v-if="tab === 'stock'">
        <span class="filter-label">评级</span>
        <button v-for="r in ratingOptions" :key="r" class="chip"
                :class="{ active: rating === r }" @click="setRating(r)">
          {{ r || '全部' }}
        </button>
      </div>
    </div>

    <!-- ══ 列表 ══════════════════════════════════════════════ -->
    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="!items.length" class="state">
      <p>暂无研报。</p>
      <p class="hint">研报库每小时增量更新，若长期为空请确认后端已开启同步。</p>
    </div>

    <div v-else class="report-list">
      <article v-for="r in items" :key="r.info_code" class="report-card">
        <div class="card-main">
          <div class="card-line1">
            <span class="rating-badge" v-if="r.rating" :class="ratingClass(r.rating)">{{ r.rating }}</span>
            <span v-if="r.rating_change && r.rating_change !== '维持'" class="rating-change">{{ r.rating_change }}</span>
            <h3 class="card-title">{{ r.title || '（无标题）' }}</h3>
          </div>
          <div class="card-line2">
            <router-link v-if="tab === 'stock' && r.code" class="code-link" :to="`/stock/${r.code}`" target="_blank" rel="noopener">
              {{ r.code }}
            </router-link>
            <span v-if="tab === 'industry' && r.industry_name" class="industry-tag">{{ r.industry_name }}</span>
            <span class="org">{{ r.org || '—' }}</span>
            <span class="date">{{ r.publish_date }}</span>
            <span v-if="r.target_price" class="target">目标价 {{ r.target_price }}</span>
            <span v-if="r.eps_this != null" class="eps">EPS {{ r.eps_this }}<span v-if="r.pe_this"> / PE {{ r.pe_this }}</span></span>
          </div>
        </div>
        <button v-if="r.info_code" class="pdf-btn" @click="openReader(r)" title="阅读研报正文">
          阅读
        </button>
      </article>
    </div>

    <!-- ══ 分页 ══════════════════════════════════════════════ -->
    <div v-if="totalPages > 1" class="pager">
      <button class="btn ghost" :disabled="page <= 1 || loading" @click="goPage(page - 1)">上一页</button>
      <span class="pager-info">{{ page }} / {{ totalPages }} 页 · 共 {{ total.toLocaleString() }} 篇</span>
      <button class="btn ghost" :disabled="page >= totalPages || loading" @click="goPage(page + 1)">下一页</button>
    </div>

    <!-- ══ 研报正文阅读弹窗 ════════════════════════════════════ -->
    <div v-if="reader.open" class="reader-mask" @click.self="closeReader">
      <div class="reader-panel">
        <div class="reader-head">
          <div class="reader-titles">
            <h3 class="reader-title">{{ reader.report?.title || '研报' }}</h3>
            <div class="reader-meta">
              <span v-if="reader.report?.org">{{ reader.report.org }}</span>
              <span v-if="reader.report?.publish_date">{{ reader.report.publish_date }}</span>
              <span v-if="reader.report?.code" class="mono">{{ reader.report.code }}</span>
            </div>
          </div>
          <div class="reader-modes">
            <button class="mode-btn" :class="{ active: reader.mode === 'pdf' }" @click="setMode('pdf')">PDF 原文</button>
            <button class="mode-btn" :class="{ active: reader.mode === 'text' }" @click="setMode('text')">文本</button>
          </div>
          <button class="reader-close" @click="closeReader" title="关闭">×</button>
        </div>

        <!-- PDF 原文：经后端同源代理内嵌，绕开东财防盗链 -->
        <div v-if="reader.mode === 'pdf'" class="reader-body pdf">
          <iframe :src="pdfProxyUrl" class="pdf-frame" title="研报 PDF"></iframe>
        </div>

        <!-- 文本：抽取正文清洗成段落 -->
        <div v-else class="reader-body">
          <div v-if="reader.loading" class="reader-state">正在抽取正文…（首次需下载 PDF，稍候）</div>
          <div v-else-if="reader.error" class="reader-state">
            <p>正文获取失败。</p>
            <button class="reader-link as-btn" @click="setMode('pdf')">改看 PDF 原文 →</button>
          </div>
          <div v-else-if="readerParas.length" class="reader-doc">
            <template v-for="(p, i) in readerParas" :key="i">
              <h4 v-if="p.type === 'h'" class="rd-h">{{ p.text }}</h4>
              <p v-else class="rd-p">{{ p.text }}</p>
            </template>
          </div>
          <div v-else class="reader-state">
            <p>未能解析到文本（PDF 多为扫描/水印件）。</p>
            <button class="reader-link as-btn" @click="setMode('pdf')">改看 PDF 原文 →</button>
          </div>
        </div>

        <div class="reader-foot" v-if="reader.pdfUrl">
          <a :href="reader.pdfUrl" target="_blank" rel="noopener" class="reader-link">在新标签打开 PDF ↗</a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { usePersistentRef } from '../composables/usePersistentRef'
import { cleanReportText } from '../utils/reportText'

// 筛选/翻页状态持久化：刷新或后端崩溃恢复后，自动还原上次的浏览位置
const tab = usePersistentRef('reports:tab', 'stock')
const search = usePersistentRef('reports:search', '')
const days = usePersistentRef('reports:days', null)        // null=全部
const rating = usePersistentRef('reports:rating', '')      // ''=全部
const page = usePersistentRef('reports:page', 1)
const pageSize = 30

const items = ref([])
const total = ref(0)
const loading = ref(false)
const status = ref({})

const reader = ref({ open: false, mode: 'pdf', loaded: false, loading: false, error: false, text: '', pdfUrl: '', report: null })

// 抽取正文清洗成段落（去水印/页眉页脚、合并硬换行、识别小标题）
const readerParas = computed(() => cleanReportText(reader.value.text))
// 同源 PDF 代理地址（绕东财防盗链）
const pdfProxyUrl = computed(() =>
  reader.value.report?.info_code
    ? `/api/research/report-pdf/${encodeURIComponent(reader.value.report.info_code)}`
    : '')

const dayOptions = [
  { label: '近7天', value: 7 },
  { label: '近30天', value: 30 },
  { label: '近90天', value: 90 },
  { label: '全部', value: null },
]
const ratingOptions = ['', '买入', '增持', '中性', '推荐', '谨慎推荐']

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const latestDate = computed(() =>
  tab.value === 'stock' ? status.value.stock_latest : status.value.industry_latest)

function ratingClass(r) {
  if (/买入|强烈|推荐/.test(r)) return 'buy'
  if (/增持|跑赢|outperform/i.test(r)) return 'add'
  if (/中性|持有|hold/i.test(r)) return 'hold'
  if (/减持|卖出|回避/.test(r)) return 'sell'
  return 'add'
}

async function loadStatus() {
  try {
    const { data } = await axios.get('/api/research/sync-status')
    status.value = data
  } catch { /* 状态不可用不影响列表 */ }
}

async function load() {
  loading.value = true
  try {
    const { data } = await axios.get('/api/research/all-reports', {
      params: {
        kind: tab.value, page: page.value, page_size: pageSize,
        search: search.value || undefined,
        days: days.value || undefined,
        rating: tab.value === 'stock' && rating.value ? rating.value : undefined,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function reload() { page.value = 1; load() }
function goPage(p) { page.value = p; load(); window.scrollTo({ top: 0, behavior: 'smooth' }) }
function switchTab(t) {
  if (tab.value === t) return
  tab.value = t
  rating.value = ''
  reload()
}
function setDays(v) { days.value = v; reload() }
function setRating(v) { rating.value = v; reload() }

function openReader(r) {
  // 默认直接看 PDF 原文（内嵌）；文本视图按需懒加载，避免每次都等抽取
  reader.value = { open: true, mode: 'pdf', loaded: false, loading: false, error: false, text: '', pdfUrl: r.pdf_url || '', report: r }
}

function setMode(m) {
  reader.value.mode = m
  if (m === 'text' && !reader.value.loaded) loadReaderText()
}

async function loadReaderText() {
  const r = reader.value.report
  if (!r?.info_code) return
  reader.value.loading = true
  reader.value.error = false
  try {
    const { data } = await axios.get(`/api/research/report-text/${encodeURIComponent(r.info_code)}`)
    reader.value.text = data.text || ''
    reader.value.pdfUrl = data.pdf_url || reader.value.pdfUrl
    reader.value.loaded = true
  } catch (e) {
    reader.value.error = true
  } finally {
    reader.value.loading = false
  }
}
function closeReader() { reader.value.open = false }

onMounted(() => { loadStatus(); load() })
</script>

<style scoped>
.reports-view { padding: 18px 22px 40px; max-width: 1100px; margin: 0 auto; }

/* 顶栏 */
.rpt-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin-bottom: 14px;
}
.header-left { display: flex; flex-direction: column; gap: 8px; }
.rpt-title { font-size: 18px; font-weight: 700; color: var(--text-1); margin: 0; }
.status-pills { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
  font-size: 11px; color: var(--text-3); background: var(--bg-base);
  border: 1px solid var(--border); border-radius: 20px; padding: 2px 10px;
}
.pill.ok { color: var(--success); border-color: rgba(22,163,74,0.3); }

.header-right { display: flex; gap: 8px; align-items: center; }
.search-box {
  width: 240px; max-width: 50vw; height: 32px; padding: 0 12px;
  background: var(--bg-base); border: 1px solid var(--border);
  border-radius: var(--radius-md); color: var(--text-1); font-size: 13px;
}
.search-box:focus { outline: none; border-color: var(--accent); }
.btn {
  height: 32px; padding: 0 14px; border: none; border-radius: var(--radius-md);
  background: var(--accent); color: #fff; font-size: 13px; font-weight: 600;
  cursor: pointer; white-space: nowrap;
}
.btn:disabled { opacity: 0.55; cursor: default; }
.btn.ghost { background: var(--bg-base); color: var(--text-2); border: 1px solid var(--border); }

/* 类型切换 */
.view-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); margin-bottom: 12px; }
.vtab {
  padding: 8px 16px; background: none; border: none; cursor: pointer;
  font-size: 13px; font-weight: 600; color: var(--text-3);
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.vtab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* 过滤条 */
.filter-bar { display: flex; gap: 22px; flex-wrap: wrap; margin-bottom: 14px; }
.filter-group { display: flex; align-items: center; gap: 6px; }
.filter-label { font-size: 11px; color: var(--text-3); margin-right: 2px; }
.chip {
  font-size: 12px; padding: 3px 11px; border-radius: 16px; cursor: pointer;
  background: var(--bg-base); border: 1px solid var(--border); color: var(--text-2);
}
.chip.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }

/* 列表 */
.report-list { display: flex; flex-direction: column; gap: 8px; }
.report-card {
  display: flex; align-items: center; gap: 14px;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 12px 14px;
  transition: border-color var(--trans-fast);
}
.report-card:hover { border-color: var(--border-light); }
.card-main { flex: 1; min-width: 0; }
.card-line1 { display: flex; align-items: baseline; gap: 8px; }
.card-title {
  font-size: 14px; font-weight: 600; color: var(--text-1); margin: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.card-line2 {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  margin-top: 6px; font-size: 12px; color: var(--text-3);
}
.code-link { color: var(--accent); font-family: var(--font-mono); text-decoration: none; font-weight: 600; }
.code-link:hover { text-decoration: underline; }
.industry-tag { color: var(--text-2); background: var(--bg-base); border-radius: 4px; padding: 1px 7px; }
.org { color: var(--text-2); }
.target { color: var(--success); font-weight: 600; }
.eps { color: var(--text-3); }

.rating-badge {
  font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: 4px; flex-shrink: 0;
}
.rating-badge.buy  { background: rgba(225,29,42,0.12); color: #e11d2a; }
.rating-badge.add  { background: rgba(245,158,11,0.14); color: #d97706; }
.rating-badge.hold { background: rgba(100,130,160,0.12); color: var(--text-2); }
.rating-badge.sell { background: rgba(22,163,74,0.12); color: var(--success); }
.rating-change { font-size: 11px; color: var(--text-3); flex-shrink: 0; }

.pdf-btn {
  flex-shrink: 0; font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
  color: var(--text-2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 5px 10px; text-decoration: none; background: none; cursor: pointer;
}
.pdf-btn:hover { border-color: var(--accent); color: var(--accent); }

/* 阅读弹窗 */
.reader-mask {
  position: fixed; inset: 0; z-index: 1000; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; padding: 24px;
}
.reader-panel {
  width: 100%; max-width: 860px; height: 88vh; display: flex; flex-direction: column;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-md); box-shadow: 0 12px 40px rgba(0,0,0,0.4);
}
.reader-head {
  display: flex; align-items: flex-start; gap: 12px; padding: 16px 18px;
  border-bottom: 1px solid var(--border);
}
.reader-titles { flex: 1; min-width: 0; }
.reader-title { font-size: 15px; font-weight: 700; color: var(--text-1); margin: 0; }
.reader-meta { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; color: var(--text-3); }
.reader-meta .mono { font-family: var(--font-mono); color: var(--accent); }
.reader-close {
  flex-shrink: 0; width: 28px; height: 28px; border: none; background: none;
  color: var(--text-3); font-size: 22px; line-height: 1; cursor: pointer; border-radius: var(--radius-sm);
}
.reader-close:hover { background: var(--bg-base); color: var(--text-1); }
.reader-modes { display: flex; gap: 4px; margin-left: auto; align-self: center; }
.mode-btn {
  font-size: 12px; padding: 4px 12px; border-radius: 14px; cursor: pointer;
  background: var(--bg-base); border: 1px solid var(--border); color: var(--text-3);
}
.mode-btn.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }

.reader-body { flex: 1; overflow-y: auto; padding: 22px 26px; }
.reader-body.pdf { padding: 0; overflow: hidden; display: flex; min-height: 0; }
.pdf-frame { flex: 1; width: 100%; border: none; background: var(--bg-base); }
.reader-link.as-btn { background: none; border: none; cursor: pointer; padding: 0; }
.reader-doc { max-width: 680px; margin: 0 auto; }
.rd-p {
  margin: 0 0 14px; font-size: 14.5px; line-height: 1.95; color: var(--text-1);
  text-align: justify; word-break: break-word; text-indent: 2em;
}
.rd-h {
  margin: 22px 0 10px; font-size: 15px; font-weight: 700; color: var(--text-1);
  padding-left: 10px; border-left: 3px solid var(--accent); line-height: 1.5;
}
.rd-h:first-child { margin-top: 0; }
.reader-state { text-align: center; padding: 50px 20px; color: var(--text-3); font-size: 14px; }
.reader-foot { padding: 12px 18px; border-top: 1px solid var(--border); text-align: right; }
.reader-link { font-size: 12px; color: var(--accent); text-decoration: none; }
.reader-link:hover { text-decoration: underline; }

/* 状态 / 分页 */
.state { text-align: center; padding: 60px 20px; color: var(--text-3); font-size: 14px; }
.state .hint { font-size: 12px; margin-top: 6px; }
.pager { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 22px; }
.pager-info { font-size: 12px; color: var(--text-3); }

@media (max-width: 768px) {
  .reports-view { padding: 14px 12px 32px; }
  .header-right { width: 100%; }
  .search-box { flex: 1; max-width: none; }
  .card-title { white-space: normal; }
}
</style>
