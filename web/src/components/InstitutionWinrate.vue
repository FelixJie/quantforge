<template>
  <div class="iwr">
    <!-- 控制条 -->
    <div class="iwr-controls">
      <label>回看
        <select v-model.number="lookbackDays" @change="load">
          <option :value="30">30天</option>
          <option :value="60">60天</option>
          <option :value="120">120天</option>
          <option :value="250">近一年</option>
        </select>
      </label>
      <label>最少样本
        <select v-model.number="minSamples" @change="load">
          <option :value="2">2</option>
          <option :value="3">3</option>
          <option :value="4">4</option>
          <option :value="5">5</option>
          <option :value="8">8</option>
        </select>
      </label>
      <label>排序窗口
        <select v-model="sortKey">
          <option value="1">昨日</option>
          <option value="3">3日</option>
          <option value="5">5日</option>
          <option value="30">30日</option>
        </select>
      </label>
      <button class="btn" @click="load" :disabled="loading">
        {{ loading ? '计算中…' : '刷新' }}
      </button>
    </div>

    <!-- 概览 -->
    <div v-if="meta" class="iwr-meta">
      <span class="pill">帖子 {{ meta.posts_total }}</span>
      <span class="pill">识别机构 {{ meta.posts_with_inst }}</span>
      <span class="pill">含个股 {{ meta.posts_with_stock }}</span>
      <span class="pill">机构数 {{ meta.inst_count }}</span>
      <span class="pill">区间 {{ meta.post_start }} ~ {{ meta.post_end }}</span>
      <span class="pill ok">基准 {{ meta.benchmark }}</span>
    </div>
    <p class="iwr-note">
      胜率口径：发帖后 N 个交易日收盘。<b>相对胜率</b>=跑赢沪深300同期的占比（主），
      绝对%=收益为正占比（副）。相对胜率更能区分强弱（大盘普涨时绝对胜率会虚高）。
      <span v-if="meta && meta.note">⚠️ {{ meta.note }}</span>
    </p>

    <!-- 最靠谱机构（按所选窗口） -->
    <div v-if="topPick.length" class="iwr-podium">
      <div class="podium-title">「{{ horizonLabel(sortKey) }}」最靠谱机构（相对胜率排名 · 样本≥{{ minSamples }}）</div>
      <div class="podium-row">
        <div v-for="(p, i) in topPick" :key="p.name" class="podium-card" :class="'rank-'+(i+1)">
          <div class="podium-rank">#{{ i + 1 }}</div>
          <div class="podium-name">{{ p.name }}</div>
          <div class="podium-stat">
            相对胜率 <b>{{ pct(p.s.win_rel) }}</b>
            <span class="sub">超额 {{ signed(p.s.avg_exc) }} · n={{ p.s.n }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="iwr-state">计算中…</div>
    <div v-else-if="!rows.length" class="iwr-state">暂无可用数据。</div>

    <!-- 明细表 -->
    <table v-else class="iwr-table">
      <thead>
        <tr>
          <th class="col-name">机构</th>
          <th v-for="h in horizons" :key="h"
              :class="{ active: String(h) === sortKey }"
              @click="sortKey = String(h)">
            {{ horizonLabel(h) }}
            <span class="sort-caret" v-if="String(h) === sortKey">▾</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.name">
          <td class="col-name">{{ r.name }}</td>
          <td v-for="h in horizons" :key="h" class="cell"
              :class="cellClass(r.horizons[String(h)])">
            <template v-if="r.horizons[String(h)]">
              <div class="cell-main">{{ pct(r.horizons[String(h)].win_rel) }}</div>
              <div class="cell-sub">
                绝{{ pct(r.horizons[String(h)].win_abs) }}
                · {{ signed(r.horizons[String(h)].avg_exc) }}
                · n{{ r.horizons[String(h)].n }}
              </div>
            </template>
            <span v-else class="cell-empty">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const loading = ref(false)
const lookbackDays = ref(120)
const minSamples = ref(3)
const sortKey = ref('3')         // 默认按 3 日相对胜率排
const meta = ref(null)
const institutions = ref([])
const rankings = ref({})
const horizons = [1, 3, 5, 30]

function horizonLabel(h) {
  return String(h) === '1' ? '昨日' : `${h}日`
}
function pct(v) {
  return v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`
}
function signed(v) {
  return v === null || v === undefined ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`
}

// 表格按所选窗口的相对胜率(主)→绝对→样本 排序；该窗口无数据的排末尾
const rows = computed(() => {
  const k = sortKey.value
  const score = (r) => {
    const s = r.horizons[k]
    if (!s) return [-2, -2, -2]
    return [s.win_rel ?? -1, s.win_abs ?? -1, s.n]
  }
  return [...institutions.value].sort((a, b) => {
    const sa = score(a), sb = score(b)
    for (let i = 0; i < sa.length; i++) if (sb[i] !== sa[i]) return sb[i] - sa[i]
    return 0
  })
})

// 「最靠谱」前 3（用后端 rankings，已按样本阈值过滤）
const topPick = computed(() => {
  const names = rankings.value[sortKey.value] || []
  const idx = Object.fromEntries(institutions.value.map((r) => [r.name, r]))
  return names.slice(0, 3)
    .map((n) => ({ name: n, s: idx[n]?.horizons[sortKey.value] }))
    .filter((p) => p.s)
})

function cellClass(s) {
  if (!s || s.win_rel === null || s.win_rel === undefined) return ''
  if (s.win_rel >= 0.6) return 'good'
  if (s.win_rel <= 0.35) return 'bad'
  return 'mid'
}

async function load() {
  loading.value = true
  try {
    const { data } = await axios.get('/api/xingqiu/institution-winrate', {
      params: { lookback_days: lookbackDays.value, min_samples: minSamples.value },
    })
    meta.value = data.meta
    institutions.value = data.institutions || []
    rankings.value = data.rankings || {}
  } catch (e) {
    institutions.value = []
    meta.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.iwr { padding: 4px 0 24px; }

.iwr-controls { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.iwr-controls label { font-size: 12px; color: var(--text-3); display: flex; align-items: center; gap: 6px; }
.iwr-controls select {
  background: var(--bg-hover); color: var(--text-1); border: 1px solid var(--border);
  border-radius: 6px; padding: 4px 8px; font-size: 12px;
}
.btn {
  font-size: 12px; padding: 5px 12px; border-radius: 6px; cursor: pointer;
  background: var(--accent); color: #fff; border: none;
}
.btn:disabled { opacity: .6; cursor: default; }

.iwr-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.pill {
  font-size: 11px; padding: 3px 8px; border-radius: 20px;
  background: var(--bg-hover); color: var(--text-3); border: 1px solid var(--border);
}
.pill.ok { color: var(--accent); border-color: var(--accent); }
.iwr-note { font-size: 12px; color: var(--text-3); line-height: 1.6; margin: 0 0 14px; }
.iwr-note b { color: var(--text-1); }

/* 领奖台 */
.iwr-podium { margin-bottom: 16px; }
.podium-title { font-size: 13px; font-weight: 600; color: var(--text-2); margin-bottom: 8px; }
.podium-row { display: flex; gap: 10px; flex-wrap: wrap; }
.podium-card {
  flex: 1 1 160px; min-width: 150px; border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 12px; background: var(--bg-hover); position: relative;
}
.podium-card.rank-1 { border-color: #d4a017; background: rgba(212,160,23,.08); }
.podium-card.rank-2 { border-color: #9aa3ad; }
.podium-rank { font-size: 12px; font-weight: 700; color: var(--text-3); }
.podium-name { font-size: 15px; font-weight: 700; color: var(--text-1); margin: 2px 0 4px; }
.podium-stat { font-size: 12px; color: var(--text-2); }
.podium-stat b { color: var(--accent); font-size: 14px; }
.podium-stat .sub { display: block; color: var(--text-3); font-size: 11px; margin-top: 2px; }

.iwr-state { text-align: center; color: var(--text-3); padding: 40px 0; }

.iwr-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.iwr-table th, .iwr-table td {
  border-bottom: 1px solid var(--border); padding: 7px 8px; text-align: center;
}
.iwr-table th { color: var(--text-3); font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }
.iwr-table th.active { color: var(--accent); }
.sort-caret { font-size: 10px; }
.col-name { text-align: left; color: var(--text-1); font-weight: 600; white-space: nowrap; }
.cell-main { font-weight: 700; font-size: 13px; }
.cell-sub { font-size: 10px; color: var(--text-3); margin-top: 1px; }
.cell.good .cell-main { color: #e5484d; }   /* A股红涨：胜率高用红 */
.cell.bad .cell-main { color: #30a46c; }    /* 绿跌 */
.cell.mid .cell-main { color: var(--text-2); }
.cell-empty { color: var(--text-4, var(--text-3)); }
</style>
