<template>
  <div class="notif-wrap">
    <div class="notif-header">
      <div class="page-badge">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
        推送通知设置
      </div>
      <div class="header-actions">
        <button class="btn-test" @click="testNotify" :disabled="testing">
          {{ testing ? '发送中...' : '测试推送' }}
        </button>
        <button class="btn-save" @click="save" :disabled="saving">
          {{ saving ? '保存中...' : '保存设置' }}
        </button>
      </div>
    </div>

    <!-- Test result -->
    <div v-if="testResults.length" class="test-results">
      <div v-for="r in testResults" :key="r.channel" :class="['test-item', r.success ? 'ok' : 'fail']">
        <span class="ch-name">{{ r.channel }}</span>
        <span class="ch-status">{{ r.success ? '✓ 发送成功' : '✗ ' + r.message }}</span>
      </div>
    </div>

    <!-- Save status -->
    <div v-if="saveMsg" class="save-msg">{{ saveMsg }}</div>

    <div v-if="cfg" class="notif-body">
      <!-- Master switch -->
      <div class="section-card">
        <div class="section-title">主开关</div>
        <label class="toggle-row">
          <span>启用推送通知</span>
          <input type="checkbox" v-model="cfg.enabled" />
        </label>
      </div>

      <!-- Event triggers -->
      <div class="section-card">
        <div class="section-title">推送事件</div>
        <label class="toggle-row">
          <span>AI每日选股生成后</span>
          <input type="checkbox" v-model="cfg.events.ai_picks" />
        </label>
        <label class="toggle-row">
          <span>风险规则触发告警</span>
          <input type="checkbox" v-model="cfg.events.risk_alert" />
        </label>
        <label class="toggle-row">
          <span>订单成交</span>
          <input type="checkbox" v-model="cfg.events.trade" />
        </label>
      </div>

      <!-- Telegram -->
      <div class="section-card channel-card">
        <div class="channel-header">
          <div class="ch-title">Telegram</div>
          <input type="checkbox" v-model="cfg.channels.telegram.enabled" />
        </div>
        <div v-if="cfg.channels.telegram.enabled" class="ch-fields">
          <div class="field-row">
            <label>Bot Token</label>
            <input type="text" v-model="cfg.channels.telegram.bot_token" placeholder="从 @BotFather 获取" />
          </div>
          <div class="field-row">
            <label>Chat ID</label>
            <input type="text" v-model="cfg.channels.telegram.chat_id" placeholder="频道或用户 ID" />
          </div>
        </div>
      </div>

      <!-- WeCom -->
      <div class="section-card channel-card">
        <div class="channel-header">
          <div class="ch-title">企业微信</div>
          <input type="checkbox" v-model="cfg.channels.wecom.enabled" />
        </div>
        <div v-if="cfg.channels.wecom.enabled" class="ch-fields">
          <div class="field-row">
            <label>Webhook URL</label>
            <input type="text" v-model="cfg.channels.wecom.webhook_url" placeholder="企业微信群机器人 Webhook" />
          </div>
        </div>
      </div>

      <!-- Feishu -->
      <div class="section-card channel-card">
        <div class="channel-header">
          <div class="ch-title">飞书</div>
          <input type="checkbox" v-model="cfg.channels.feishu.enabled" />
        </div>
        <div v-if="cfg.channels.feishu.enabled" class="ch-fields">
          <div class="field-row">
            <label>Webhook URL</label>
            <input type="text" v-model="cfg.channels.feishu.webhook_url" placeholder="飞书群机器人 Webhook" />
          </div>
        </div>
      </div>

      <!-- Email -->
      <div class="section-card channel-card">
        <div class="channel-header">
          <div class="ch-title">邮件 (SMTP)</div>
          <input type="checkbox" v-model="cfg.channels.email.enabled" />
        </div>
        <div v-if="cfg.channels.email.enabled" class="ch-fields">
          <div class="field-row">
            <label>SMTP 服务器</label>
            <input type="text" v-model="cfg.channels.email.smtp_host" placeholder="smtp.gmail.com" />
          </div>
          <div class="field-row">
            <label>端口</label>
            <input type="number" v-model.number="cfg.channels.email.smtp_port" placeholder="587" />
          </div>
          <div class="field-row">
            <label>发件人邮箱</label>
            <input type="email" v-model="cfg.channels.email.smtp_user" />
          </div>
          <div class="field-row">
            <label>密码/应用密码</label>
            <input type="password" v-model="cfg.channels.email.smtp_password" placeholder="留空保持不变" />
          </div>
          <div class="field-row">
            <label>收件人</label>
            <input type="text" v-model="cfg.channels.email.to_addrs" placeholder="多个用逗号分隔" />
          </div>
        </div>
      </div>
    </div>
    <div v-else class="loading-msg">加载中...</div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const cfg = ref(null)
const saving = ref(false)
const testing = ref(false)
const saveMsg = ref('')
const testResults = ref([])

async function load() {
  const res = await axios.get('/api/notification/settings')
  cfg.value = res.data
}

async function save() {
  saving.value = true
  saveMsg.value = ''
  try {
    await axios.put('/api/notification/settings', { settings: cfg.value })
    saveMsg.value = '✓ 设置已保存'
    setTimeout(() => saveMsg.value = '', 3000)
  } finally {
    saving.value = false
  }
}

async function testNotify() {
  testing.value = true
  testResults.value = []
  try {
    const res = await axios.post('/api/notification/test')
    testResults.value = res.data.results || []
    if (res.data.status === 'skipped') {
      saveMsg.value = '没有已启用的渠道，请先启用并保存设置'
    }
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.notif-wrap { padding: 20px; display: flex; flex-direction: column; gap: 16px; max-width: 760px; }
.notif-header { display: flex; justify-content: space-between; align-items: center; }
.page-badge { display: inline-flex; align-items: center; gap: 6px; background: var(--accent-dim); color: var(--accent); padding: 5px 12px; border-radius: 20px; font-size: 13px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; }
.btn-test { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-1); border-radius: var(--radius-md); padding: 7px 14px; font-size: 13px; cursor: pointer; }
.btn-save { background: var(--accent); color: #fff; border: none; border-radius: var(--radius-md); padding: 7px 16px; font-size: 13px; cursor: pointer; }
.btn-save:disabled, .btn-test:disabled { opacity: 0.6; cursor: not-allowed; }

.test-results { display: flex; flex-direction: column; gap: 6px; }
.test-item { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-radius: var(--radius-sm); font-size: 13px; }
.test-item.ok { background: #dcfce7; color: #166534; }
.test-item.fail { background: #fee2e2; color: #991b1b; }
.ch-name { font-weight: 600; min-width: 80px; }
.save-msg { font-size: 13px; color: var(--accent); }

.notif-body { display: flex; flex-direction: column; gap: 14px; }
.section-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px; }
.section-title { font-size: 12px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-1); cursor: pointer; }
.toggle-row:last-child { border-bottom: none; }

.channel-card {}
.channel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ch-title { font-size: 14px; font-weight: 600; color: var(--text-1); }
.ch-fields { display: flex; flex-direction: column; gap: 10px; }
.field-row { display: flex; align-items: center; gap: 12px; }
.field-row label { font-size: 12px; color: var(--text-3); min-width: 100px; }
.field-row input { flex: 1; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-sm); color: var(--text-1); padding: 7px 10px; font-size: 13px; }
.loading-msg { padding: 40px; text-align: center; color: var(--text-3); }
</style>
