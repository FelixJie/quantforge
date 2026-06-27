<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <div class="auth-logo">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#e11d2a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
            <polyline points="16 7 22 7 22 13"></polyline>
          </svg>
        </div>
        <h1 class="auth-title">{{ isLogin ? '登录' : '注册' }}</h1>
        <p class="auth-subtitle">{{ isLogin ? '欢迎回到 QuantForge' : '创建您的 QuantForge 账户' }}</p>
      </div>

      <div v-if="errorMessage" class="auth-error">{{ errorMessage }}</div>
      <div v-if="successMessage" class="auth-success">{{ successMessage }}</div>

      <form @submit.prevent="handleSubmit" class="auth-form">
        <div class="form-group">
          <label for="username">用户名</label>
          <input
            id="username"
            v-model="form.username"
            type="text"
            required
            placeholder="请输入用户名"
            autocomplete="username"
          />
        </div>

        <div v-if="!isLogin" class="form-group">
          <label for="email">邮箱</label>
          <input
            id="email"
            v-model="form.email"
            type="email"
            required
            placeholder="请输入邮箱"
            autocomplete="email"
          />
        </div>

        <div class="form-group">
          <label for="password">密码</label>
          <input
            id="password"
            v-model="form.password"
            type="password"
            required
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </div>

        <div v-if="!isLogin" class="form-group">
          <label for="confirmPassword">确认密码</label>
          <input
            id="confirmPassword"
            v-model="form.confirmPassword"
            type="password"
            required
            placeholder="请再次输入密码"
            autocomplete="new-password"
          />
        </div>

        <button type="submit" class="auth-button" :disabled="loading">
          {{ loading ? '处理中...' : (isLogin ? '登录' : '注册') }}
        </button>
      </form>

      <div class="auth-footer">
        <span>{{ isLogin ? '还没有账户？' : '已有账户？' }}</span>
        <button @click="toggleMode" class="auth-link">{{ isLogin ? '立即注册' : '立即登录' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const isLogin = ref(true)
const loading = ref(false)
const errorMessage = ref('')
const successMessage = ref('')

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: ''
})

const toggleMode = () => {
  isLogin.value = !isLogin.value
  errorMessage.value = ''
  successMessage.value = ''
  form.username = ''
  form.email = ''
  form.password = ''
  form.confirmPassword = ''
}

const handleSubmit = async () => {
  errorMessage.value = ''
  successMessage.value = ''

  if (!isLogin.value && form.password !== form.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    if (isLogin.value) {
      await authStore.login(form.username, form.password)
    } else {
      await authStore.register(form.username, form.email, form.password)
    }
    successMessage.value = isLogin.value ? '登录成功！' : '注册成功！'
    setTimeout(() => {
      router.push('/')
    }, 500)
  } catch (error) {
    if (error.response && error.response.data && error.response.data.detail) {
      errorMessage.value = error.response.data.detail
    } else {
      errorMessage.value = isLogin.value ? '登录失败，请检查用户名和密码' : '注册失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-container {
  /* 页面级强调色锁定为品牌红(与 logo 一致),不污染全局 --accent */
  --auth-accent: #e11d2a;
  --auth-accent-strong: #c01622;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--bg-base) 0%, var(--bg-surface) 100%);
  padding: 24px;
}

.auth-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border-radius: 16px;
  padding: 40px 32px;
  box-shadow: 0 20px 60px rgba(15,23,42,0.12);
  border: 1px solid var(--border);
}

.auth-header {
  text-align: center;
  margin-bottom: 32px;
}

.auth-logo {
  width: 56px;
  height: 56px;
  background: rgba(225, 29, 42, 0.1);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
}

.auth-title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-1);
  margin: 0 0 4px;
}

.auth-subtitle {
  font-size: 14px;
  color: var(--text-3);
  margin: 0;
}

.auth-error, .auth-success {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 14px;
}

.auth-error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #dc2626;
}

.auth-success {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  color: #16a34a;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-group label {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-2);
}

.form-group input {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 14px;
  background: var(--bg-base);
  color: var(--text-1);
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-group input:focus {
  border-color: var(--auth-accent);
  box-shadow: 0 0 0 3px rgba(225, 29, 42, 0.15);
}

.form-group input::placeholder {
  color: var(--text-3);
}

.auth-button {
  width: 100%;
  padding: 12px 24px;
  margin-top: 8px;
  background: linear-gradient(135deg, var(--auth-accent) 0%, var(--auth-accent-strong) 100%);
  border: none;
  border-radius: 8px;
  color: white;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.auth-button:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 10px 20px rgba(225, 29, 42, 0.3);
}

.auth-button:active:not(:disabled) {
  transform: translateY(0);
}

.auth-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (prefers-reduced-motion: reduce) {
  .auth-button,
  .form-group input {
    transition: none;
  }
  .auth-button:hover:not(:disabled) {
    transform: none;
  }
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 14px;
  color: var(--text-3);
}

.auth-link {
  background: none;
  border: none;
  color: var(--auth-accent);
  font-weight: 600;
  cursor: pointer;
  padding: 0 4px;
  transition: color 0.2s;
}

.auth-link:hover {
  color: var(--auth-accent-strong);
}
</style>
