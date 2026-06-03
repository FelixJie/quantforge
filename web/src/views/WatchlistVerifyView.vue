<template>
  <div class="watchlist-verify-page">
    <div class="page-header">
      <div class="header-left">
        <h1>自选股验证</h1>
        <p>验证您自选股的历史表现</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" @click="runVerification" :disabled="verifying || watchlist.length === 0">
          <svg v-if="!verifying" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="2" x2="12" y2="6"></line>
            <line x1="12" y1="18" x2="12" y2="22"></line>
            <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
            <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
            <line x1="2" y1="12" x2="6" y2="12"></line>
            <line x1="18" y1="12" x2="22" y2="12"></line>
            <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
            <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
          </svg>
          {{ verifying ? '验证中...' : '运行验证' }}
        </button>
      </div>
    </div>

    <div class="controls-row">
      <div class="control-group">
        <label>验证周期</label>
        <select v-model="selectedPeriod" class="select-input">
          <option value="7">7 天</option>
          <option value="30">30 天</option>
          <option value="90">90 天</option>
          <option value="180">180 天</option>
          <option value="365">365 天</option>
        </select>
      </div>
    </div>

    <div v-if="watchlist.length === 0" class="empty-state">
      <div class="empty-icon">
        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path>
        </svg>
      </div>
      <h3>还没有自选股</h3>
      <p>先去添加一些股票到自选股吧</p>
      <button class="btn btn-primary" @click="goToWatchlist">
        去添加
      </button>
    </div>

    <div v-else class="verification-results">
      <div v-if="currentVerification" class="result-card active">
        <div class="result-header">
          <div>
            <h3>最近验证结果</h3>
            <p class="result-meta">{{ currentVerification.periodDays }} 天 ({{ currentVerification.startDate }} 至 {{ currentVerification.endDate }})</p>
          </div>
          <div class="total-return">
            <span class="return-label">平均收益</span>
            <span class="return-value" :class="getReturnClass(currentVerification.totalReturn)">
              {{ currentVerification.totalReturn }}%
            </span>
          </div>
        </div>
        <div class="result-table">
          <table>
            <thead>
              <tr>
                <th>股票</th>
                <th>期初价格</th>
                <th>期末价格</th>
                <th>涨跌</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in currentVerification.results" :key="item.code">
                <td>
                  <span class="stock-code">{{ item.code }}</span>
                  <span class="stock-name">{{ item.name }}</span>
                </td>
                <td>{{ item.startPrice.toFixed(2) }}</td>
                <td>{{ item.endPrice.toFixed(2) }}</td>
                <td>
                  <span class="change-value" :class="getReturnClass(item.changePercent)">
                    {{ item.changePercent > 0 ? '+' : '' }}{{ item.changePercent }}%
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-if="verifications.length > 0" class="history-section">
        <h3 class="section-title">历史验证</h3>
        <div class="history-list">
          <div v-for="verification in verifications.slice(1)" :key="verification.id" class="history-item">
            <div class="history-info">
              <span class="history-date">{{ formatDate(verification.createdAt) }}</span>
              <span class="history-period">{{ verification.periodDays }} 天</span>
            </div>
            <div class="history-return">
              <span class="return-label">平均收益</span>
              <span class="return-value" :class="getReturnClass(verification.totalReturn)">
                {{ verification.totalReturn }}%
              </span>
            </div>
            <button class="btn-remove" @click="removeVerification(verification.id)" title="删除">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useWatchlistStore } from '../stores/watchlist'

const router = useRouter()
const watchlistStore = useWatchlistStore()

const watchlist = watchlistStore.watchlist
const verifications = watchlistStore.watchlistVerifications
const verifying = ref(false)
const selectedPeriod = ref(30)

const currentVerification = computed(() => {
  return verifications.value[0] || null
})

function formatDate(dateStr) {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function getReturnClass(value) {
  const num = parseFloat(value)
  if (num > 0) return 'positive'
  if (num < 0) return 'negative'
  return 'neutral'
}

async function runVerification() {
  if (verifying.value || watchlist.value.length === 0) return
  verifying.value = true
  try {
    await watchlistStore.verifyWatchlist(selectedPeriod.value)
  } catch (e) {
    console.error('Verification failed:', e)
    alert('验证失败，请稍后重试')
  } finally {
    verifying.value = false
  }
}

function removeVerification(id) {
  if (confirm('确定要删除这条验证记录吗？')) {
    watchlistStore.removeVerification(id)
  }
}

function goToWatchlist() {
  router.push('/watchlist')
}
</script>

<style scoped>
.watchlist-verify-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.header-left h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-1);
  margin: 0 0 4px;
}

.header-left p {
  font-size: 13px;
  color: var(--text-3);
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.controls-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.control-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.control-group label {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
}

.select-input {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text-1);
  font-size: 13px;
  cursor: pointer;
}

.select-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(61,142,248,0.15);
}

.empty-state {
  text-align: center;
  padding: 80px 24px;
  background: var(--bg-surface);
  border: 1px dashed var(--border);
  border-radius: 12px;
}

.empty-icon {
  color: var(--text-4);
  margin-bottom: 16px;
}

.empty-state h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0 0 8px;
}

.empty-state p {
  font-size: 13px;
  color: var(--text-3);
  margin: 0 0 16px;
}

.result-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 24px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  background: linear-gradient(135deg, rgba(61,142,248,0.04), transparent);
}

.result-header h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-1);
  margin: 0 0 4px;
}

.result-meta {
  font-size: 12px;
  color: var(--text-3);
  margin: 0;
}

.total-return {
  text-align: right;
}

.return-label {
  display: block;
  font-size: 11px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.return-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-mono);
}

.return-value.positive {
  color: var(--success);
}

.return-value.negative {
  color: var(--danger);
}

.return-value.neutral {
  color: var(--text-2);
}

.result-table {
  padding: 0 20px 20px;
}

.result-table table {
  width: 100%;
  border-collapse: collapse;
}

.result-table thead {
  background: var(--bg-base);
}

.result-table th {
  padding: 12px 14px;
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-bottom: 1px solid var(--border);
}

.result-table td {
  padding: 12px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}

.result-table tbody tr:last-child td {
  border-bottom: none;
}

.stock-code {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-1);
  margin-right: 8px;
}

.stock-name {
  color: var(--text-3);
  font-size: 12px;
}

.change-value {
  font-family: var(--font-mono);
  font-weight: 600;
}

.change-value.positive {
  color: var(--success);
}

.change-value.negative {
  color: var(--danger);
}

.history-section {
  margin-top: 24px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0 0 12px;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.history-info {
  display: flex;
  gap: 12px;
  align-items: center;
}

.history-date {
  font-size: 13px;
  color: var(--text-2);
  font-weight: 500;
}

.history-period {
  font-size: 12px;
  color: var(--text-3);
  background: var(--bg-base);
  padding: 2px 8px;
  border-radius: 4px;
}

.history-return {
  display: flex;
  align-items: center;
  gap: 12px;
}

.history-return .return-label {
  margin-bottom: 0;
  font-size: 11px;
}

.history-return .return-value {
  font-size: 16px;
}

.btn-remove {
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  transition: all 0.15s;
}

.btn-remove:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}
</style>
