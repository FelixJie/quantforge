<template>
  <div class="signal-view">
    <h2>📡 信号 & 龙虎榜</h2>
    
    <div class="tabs">
      <button :class="{ active: activeTab === 'summary' }" @click="activeTab = 'summary'">综合</button>
      <button :class="{ active: activeTab === 'dragon' }" @click="activeTab = 'dragon'">龙虎榜</button>
      <button :class="{ active: activeTab === 'industry' }" @click="activeTab = 'industry'">行业</button>
      <button :class="{ active: activeTab === 'unlock' }" @click="activeTab = 'unlock'">解禁</button>
    </div>

    <div v-if="loading" class="loading">
      ⏳ 加载中...
    </div>

    <!-- 综合 -->
    <div v-if="!loading && activeTab === 'summary'" class="panels">
      <div class="panel">
        <h3>🔥 同花顺强势股 & 题材</h3>
        <div v-if="summaryData.hot_stocks.data?.length > 0" class="list">
          <div v-for="(s, idx) in summaryData.hot_stocks.data.slice(0, 30)" :key="idx" class="item">
            {{ s.name }} ({{ s.code }})
          </div>
        </div>
      </div>

      <div class="panel">
        <h3>🌊 北向资金</h3>
        <pre v-if="summaryData.northbound">{{ JSON.stringify(summaryData.northbound, null, 2) }}</pre>
      </div>
    </div>

    <!-- 龙虎榜 -->
    <div v-if="!loading && activeTab === 'dragon'" class="panels">
      <div class="panel full">
        <h3>📋 全市场上榜股票</h3>
        <table v-if="dragonAllData.data?.length > 0" class="small-table">
          <thead>
            <tr>
              <th>股票</th>
              <th>代码</th>
              <th>净买入</th>
              <th>价格</th>
              <th>涨跌幅</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in dragonAllData.data" :key="idx">
              <td>{{ r.SECURITY_NAME_ABBR }}</td>
              <td>{{ r.SECURITY_CODE }}</td>
              <td>{{ r.BUY_NET_AMOUNT }}</td>
              <td>{{ r.CLOSE_PRICE }}</td>
              <td>{{ r.CHANGE_RATE }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 行业 -->
    <div v-if="!loading && activeTab === 'industry'" class="panels">
      <div class="panel full">
        <h3>📊 东财行业板块涨跌排名</h3>
        <table v-if="industryData.data?.length > 0" class="small-table">
          <thead>
            <tr>
              <th>板块</th>
              <th>涨跌幅</th>
              <th>领涨</th>
              <th>上涨家数</th>
              <th>下跌家数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in industryData.data" :key="idx">
              <td>{{ r.PLATE_NAME }}</td>
              <td>{{ r.CHANGE_RATE }}%</td>
              <td>{{ r.LEADER_STOCK }}</td>
              <td>{{ r.RISE_COUNT }}</td>
              <td>{{ r.FALL_COUNT }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 解禁 -->
    <div v-if="!loading && activeTab === 'unlock'" class="panels">
      <div class="panel full">
        <h3>🔓 未来 90 天限售解禁</h3>
        <table v-if="unlockData.data?.length > 0" class="small-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>股票</th>
              <th>代码</th>
              <th>解禁市值</th>
              <th>解禁比例</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, idx) in unlockData.data" :key="idx">
              <td>{{ r.UNBAN_DATE?.slice(0, 10) }}</td>
              <td>{{ r.SECURITY_NAME_ABBR }}</td>
              <td>{{ r.SECURITY_CODE }}</td>
              <td>{{ r.FREE_MARKET_CAP }}</td>
              <td>{{ r.FREE_SHARES_RATIO }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const activeTab = ref('summary')
const loading = ref(false)

const summaryData = ref({})
const dragonAllData = ref({})
const industryData = ref({})
const unlockData = ref({})

const fetchData = async () => {
  loading.value = true
  try {
    const [sumRes, dragonRes, indRes, unlockRes] = await Promise.all([
      axios.get('/api/signal/summary'),
      axios.get('/api/signal/dragon_board_all'),
      axios.get('/api/signal/industry_rank'),
      axios.get('/api/signal/unlock_upcoming')
    ])
    summaryData.value = sumRes.data
    dragonAllData.value = dragonRes.data
    industryData.value = indRes.data
    unlockData.value = unlockRes.data
  } catch (err) {
    console.error(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.signal-view { padding: 20px; max-width: 1400px; margin: 0 auto; }

.tabs { display: flex; gap: 8px; margin-bottom: 20px; }
.tabs button { padding: 8px 16px; border: 1px solid #ddd; background: white; border-radius: 6px; cursor: pointer; }
.tabs button.active { background: #3b82f6; border-color: #3b82f6; color: white; }

.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.panel { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.panel.full { grid-column: 1 / -1; }
.panel h3 { margin-top: 0; font-size: 16px; margin-bottom: 14px; }

.list { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
.item { padding: 8px 12px; background: #f8fafc; border-radius: 6px; font-size: 13px; }

.small-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.small-table thead th { background: #f1f5f9; padding: 8px 6px; text-align: left; border-bottom: 2px solid #e2e8f0; }
.small-table tbody td { padding: 7px 6px; border-bottom: 1px solid #f1f5f9; }

.loading { text-align: center; padding: 30px; color: #64748b; }
pre { font-size: 11px; white-space: pre-wrap; }
</style>
