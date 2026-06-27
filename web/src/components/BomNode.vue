<template>
  <div class="bnode" :class="'lv' + depth">
    <!-- 节点头：名称 + 本层占比 + 占整体占比 + 展开箭头 -->
    <div class="bn-head" :style="{ borderLeftColor: color }" @click="toggle">
      <span class="bn-caret" v-if="hasChildren">{{ open ? '▾' : '▸' }}</span>
      <span class="bn-caret placeholder" v-else></span>
      <span class="bn-name">{{ node.name }}</span>
      <span class="bn-spacer"></span>
      <!-- 占整体进度条（让深层节点也有统一的“整体视角”参照） -->
      <span class="bn-track">
        <span class="bn-fill" :style="{ width: Math.min(absShare, 100) + '%', background: color }"></span>
      </span>
      <span class="bn-pct">
        <b class="bn-rel">{{ node.percent != null ? node.percent + '%' : '—' }}</b>
        <i class="bn-abs" v-if="node.percent != null">占整体 {{ absShareText }}%</i>
      </span>
    </div>

    <!-- 每个层级名后面挂龙头/弹性票（2-4 只）：紧跟该环节，始终可见 -->
    <div v-if="hasStocks" class="bn-stocks">
      <span
        v-for="s in node.stocks" :key="s.code"
        class="bn-chip" :class="tierKey(s.tier)"
        :title="s.reason || ''"
      >
        <span class="chip-tier" v-if="s.tier">{{ tierLabel(s.tier) }}</span>
        <span class="chip-name">{{ s.name }}</span>
        <span class="chip-code mono">{{ s.code }}</span>
        <span class="chip-q mono" v-if="info(s.code) && info(s.code).price != null">¥{{ info(s.code).price }}</span>
        <span class="chip-q mono" v-if="info(s.code) && info(s.code).change_pct != null" :class="chg(info(s.code).change_pct)">{{ pct(info(s.code).change_pct) }}</span>
        <button class="chip-add" :class="{ added: wl.isInWatchlist(s.code) }" @click.stop="add(s)">
          {{ wl.isInWatchlist(s.code) ? '✓' : '+' }}
        </button>
      </span>
    </div>

    <!-- 展开后：子节点递归 -->
    <div v-if="open && hasChildren" class="bn-body">
      <div class="bn-children">
        <BomNode
          v-for="c in node.children" :key="c.name"
          :node="c" :color="color" :depth="depth + 1"
          :parent-share="absShare" :stock-info="stockInfo"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useWatchlistStore } from '../stores/watchlist'

const props = defineProps({
  node: { type: Object, required: true },
  color: { type: String, default: '#6366f1' },
  depth: { type: Number, default: 1 },
  // 父节点占整体的百分比（顶层传 100），用于换算本节点「占整体」
  parentShare: { type: Number, default: 100 },
  stockInfo: { type: Object, default: () => ({}) },
})

const wl = useWatchlistStore()

// 顶层默认展开，深层默认收起（避免一进来铺满全屏）
const open = ref(props.depth <= 1)
function toggle() { open.value = !open.value }

const hasChildren = computed(() => Array.isArray(props.node.children) && props.node.children.length > 0)
const hasStocks = computed(() => Array.isArray(props.node.stocks) && props.node.stocks.length > 0)

// 占整体 = 父占整体 × 本层占父
const absShare = computed(() => {
  const rel = Number(props.node.percent)
  if (!Number.isFinite(rel)) return 0
  return (props.parentShare * rel) / 100
})
const absShareText = computed(() => {
  const v = absShare.value
  return v >= 10 ? v.toFixed(0) : v.toFixed(1)
})

function info(code) { return props.stockInfo?.[code] || null }
function add(s) { if (!wl.isInWatchlist(s.code)) wl.addToWatchlist({ code: s.code, name: s.name }) }
// 标的定位：龙头 / 弹性
function tierKey(t) {
  if (!t) return ''
  if (t.includes('龙头')) return 'leader'
  if (t.includes('弹性')) return 'elastic'
  return 'other'
}
function tierLabel(t) {
  const k = tierKey(t)
  if (k === 'leader') return '龙头'
  if (k === 'elastic') return '弹性'
  return t
}
function chg(v) { return v == null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : '' }
function pct(v) { return v == null ? '-' : (v > 0 ? '+' : '') + v + '%' }
</script>

<style scoped>
.bnode { margin-bottom: 4px; }
.bnode.lv1 { margin-bottom: 8px; }

.bn-head {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 12px; border-radius: 8px; cursor: pointer;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-left: 3px solid var(--accent); transition: background .15s;
}
.bn-head:hover { background: var(--bg-hover); }
.bnode.lv1 > .bn-head { background: var(--bg-elevated); padding: 11px 14px; }
.bnode.lv1 > .bn-head .bn-name { font-weight: 700; font-size: 15px; }

.bn-caret { width: 14px; flex-shrink: 0; color: var(--text-3); font-size: 11px; text-align: center; }
.bn-caret.placeholder { visibility: hidden; }
.bn-name { font-size: 14px; color: var(--text-1); }
.bnode.lv2 > .bn-head .bn-name { font-size: 13px; color: var(--text-2); }
.bnode.lv3 > .bn-head .bn-name,
.bnode.lv4 > .bn-head .bn-name { font-size: 12px; color: var(--text-2); }
.bn-spacer { flex: 1; }

.bn-track { flex: 0 0 90px; height: 7px; background: var(--bg-1, rgba(255,255,255,.06)); border-radius: 4px; overflow: hidden; }
.bn-fill { display: block; height: 100%; border-radius: 4px; transition: width .5s ease; }

.bn-pct { flex: 0 0 auto; display: flex; flex-direction: column; align-items: flex-end; line-height: 1.25; min-width: 78px; }
.bn-rel { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--text-1); }
.bn-abs { font-style: normal; font-size: 10px; color: var(--text-3); }

/* 逐层缩进，并以左侧虚线串起层级 */
.bn-body { margin-left: 18px; padding-left: 10px; border-left: 1px dashed var(--border); margin-top: 4px; }
.bn-children { display: flex; flex-direction: column; }

/* 每层环节后面的龙头/弹性票 chips */
.bn-stocks { display: flex; flex-wrap: wrap; gap: 6px; padding: 5px 0 7px 22px; }
.bn-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 4px 2px 8px; border-radius: 7px; font-size: 12px;
  background: var(--bg-surface); border: 1px solid var(--border);
}
.bn-chip.leader { border-color: rgba(220,38,38,.4); }
.bn-chip.elastic { border-color: rgba(217,119,6,.4); }
.chip-tier { font-size: 10px; font-weight: 700; padding: 0 5px; border-radius: 4px; }
.bn-chip.leader .chip-tier { background: rgba(220,38,38,.16); color: #dc2626; }
.bn-chip.elastic .chip-tier { background: rgba(217,119,6,.16); color: #d97706; }
.bn-chip.other .chip-tier { background: var(--bg-hover); color: var(--text-3); }
.chip-name { font-weight: 600; color: var(--text-1); }
.chip-code { font-size: 11px; color: var(--text-3); }
.chip-q { font-size: 11px; color: var(--text-2); }
.chip-add {
  width: 20px; height: 20px; line-height: 1; padding: 0;
  border: 1px solid var(--accent); border-radius: 5px; background: transparent;
  color: var(--accent); font-size: 13px; cursor: pointer;
}
.chip-add:hover { background: var(--accent); color: #fff; }
.chip-add.added { border-color: #16a34a; color: #16a34a; cursor: default; }
.up { color: #dc2626; }
.down { color: #16a34a; }
.mono { font-family: var(--font-mono); }

@media (max-width: 768px) {
  .bn-track { display: none; }
  .bn-body { margin-left: 10px; padding-left: 8px; }
  .bn-stocks { padding-left: 12px; }
}
</style>
