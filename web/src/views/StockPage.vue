<template>
  <div class="stock-page">
    <div class="sp-bar">
      <button class="sp-back" @click="goBack">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
        </svg>
        <span>返回</span>
      </button>
    </div>
    <StockAnalysisDetail :key="code" :symbol="code" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import StockAnalysisDetail from '../components/StockAnalysisDetail.vue'

const route = useRoute()
const router = useRouter()
const code = computed(() => String(route.params.code || '').trim())

function goBack() {
  // 有上一页则返回，否则回首页
  if (window.history.length > 1) router.back()
  else router.push('/')
}
</script>

<style scoped>
.stock-page { padding: 0; }
.sp-bar { padding: 10px 16px 0; }
.sp-back {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text-2);
  padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.15s;
}
.sp-back:hover { color: var(--text-1); border-color: var(--text-3); }

@media (max-width: 768px) {
  .sp-bar { padding: 10px 12px 0; }
  .sp-back { padding: 8px 14px; min-height: 40px; }
}
</style>
