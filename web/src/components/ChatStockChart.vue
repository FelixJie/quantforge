<template>
  <div class="cs-chart" v-if="bars.length">
    <div class="cs-head">
      <span class="cs-code">{{ code }}<span v-if="name" class="cs-name">{{ name }}</span></span>
      <span class="cs-meta">
        <span class="cs-last">{{ last }}</span>
        <span class="cs-pct" :class="up ? 'up' : 'down'">{{ pctText }}</span>
        <span class="cs-tag">近{{ bars.length }}日</span>
      </span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" class="cs-svg" preserveAspectRatio="none">
      <polyline :points="points" :stroke="up ? '#ef4444' : '#22c55e'" fill="none" stroke-width="1.4" />
    </svg>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const props = defineProps({
  code: { type: String, required: true },
})

const W = 280
const H = 56
const bars = ref([])
const name = ref('')

onMounted(async () => {
  try {
    const r = await fetch(`/api/market/kline/${props.code}?period=day&count=60`)
    if (!r.ok) return
    const d = await r.json()
    bars.value = (d.bars || []).filter(b => b && b.close != null)
  } catch { /* 静默：出图失败不影响对话 */ }
  try {
    const q = await fetch(`/api/market/quote/${props.code}`)
    if (q.ok) { const qd = await q.json(); name.value = qd.name || qd.data?.name || '' }
  } catch { /* ignore */ }
})

const closes = computed(() => bars.value.map(b => Number(b.close)).filter(n => !Number.isNaN(n)))
const last = computed(() => closes.value.length ? closes.value[closes.value.length - 1] : '')
const up = computed(() => {
  const c = closes.value
  return c.length >= 2 ? c[c.length - 1] >= c[0] : true
})
const pctText = computed(() => {
  const c = closes.value
  if (c.length < 2 || !c[0]) return ''
  const p = (c[c.length - 1] / c[0] - 1) * 100
  return `${p >= 0 ? '+' : ''}${p.toFixed(1)}%`
})
const points = computed(() => {
  const c = closes.value
  if (c.length < 2) return ''
  const min = Math.min(...c), max = Math.max(...c)
  const span = max - min || 1
  const n = c.length
  return c.map((v, i) => {
    const x = (i / (n - 1)) * W
    const y = H - 4 - ((v - min) / span) * (H - 8)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
})
</script>

<style scoped>
.cs-chart {
  margin: 8px 0 2px; padding: 8px 10px; border-radius: 8px;
  background: rgba(127, 127, 127, .06); border: 1px solid var(--border, #2a2a35);
}
.cs-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; font-size: 12px; }
.cs-code { font-weight: 600; color: var(--text-1); font-family: var(--font-mono, monospace); }
.cs-name { margin-left: 6px; color: var(--text-2); font-family: inherit; font-weight: 500; }
.cs-meta { display: flex; align-items: baseline; gap: 8px; }
.cs-last { color: var(--text-1); font-weight: 600; }
.cs-pct.up { color: #ef4444; }
.cs-pct.down { color: #22c55e; }
.cs-tag { color: var(--text-3); font-size: 11px; }
.cs-svg { width: 100%; height: 56px; margin-top: 4px; display: block; }
</style>
