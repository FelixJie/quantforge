<template>
  <div class="capital-view">
    <h2>💰 资金面 & 筹码</h2>
    
    <div class="search-bar">
      <input v-model="stockCode" placeholder="输入股票代码 (如 600519)" />
      <button @click="search" class="btn-primary">搜索</button>
    </div>

    <div v-if="summaryData" class="panels">
      <div class="panel">
        <h3>📈 融资融券 (最近 30 条)</h3>
        <table class="small-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>融资余额</th>
              <th>融券余额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in summaryData.margin.slice(0, 30)" :key="idx">
              <td>{{ r.TRADE_DATE?.slice(0, 10) }}</td>
              <td>{{ r.RZ_BALANCE }}</td>
              <td>{{ r.RQ_BALANCE }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h3>🗂️ 股东户数</h3>
        <table class="small-table">
          <thead>
            <tr>
              <th>截止日期</th>
              <th>户数</th>
              <th>变化</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in summaryData.holder_count.slice(0, 10)" :key="idx">
              <td>{{ r.END_DATE?.slice(0, 10) }}</td>
              <td>{{ r.HOLDER_NUM }}</td>
              <td>{{ r.CHANGE_RATE }}%</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h3>🎁 分红送转</h3>
        <table class="small-table">
          <thead>
            <tr>
              <th>除权日</th>
              <th>送股</th>
              <th>转增</th>
              <th>派息</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in summaryData.dividend.slice(0, 10)" :key="idx">
              <td>{{ r.EX_DIVIDEND_DATE }}</td>
              <td>{{ r.BONUS_RATIO }}</td>
              <td>{{ r.TRANSFER_RATIO }}</td>
              <td>{{ r.DIVIDEND_RATIO }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="panel">
        <h3>💼 大宗交易</h3>
        <table class="small-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>价格</th>
              <th>数量</th>
              <th>成交额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in summaryData.block_trade.slice(0, 10)" :key="idx">
              <td>{{ r.TRADE_DATE?.slice(0, 10) }}</td>
              <td>{{ r.PRICE }}</td>
              <td>{{ r.VOLUME }}</td>
              <td>{{ r.AMOUNT }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="loading" class="loading">
      ⏳ 加载中...
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import axios from 'axios'

const stockCode = ref('600519')
const summaryData = ref(null)
const loading = ref(false)

const search = async () => {
  loading.value = true
  summaryData.value = null
  
  try {
    const res = await axios.get(`/api/capital/summary/${stockCode.value}`)
    summaryData.value = res.data
  } catch (err) {
    console.error('Search failed', err)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.capital-view { padding: 20px; max-width: 1400px; margin: 0 auto; }
.search-bar { display: flex; gap: 10px; margin-bottom: 20px; }
.search-bar input { flex: 1; padding: 10px 14px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }
.btn-primary { background: #3b82f6; color: white; border: none; padding: 10px 24px; border-radius: 6px; cursor: pointer; }

.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.panel { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.panel h3 { margin-top: 0; font-size: 16px; margin-bottom: 14px; }

.small-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.small-table thead th { background: #f1f5f9; padding: 8px 6px; text-align: left; border-bottom: 2px solid #e2e8f0; }
.small-table tbody td { padding: 7px 6px; border-bottom: 1px solid #f1f5f9; }

.loading { text-align: center; padding: 30px; color: #64748b; }
</style>
