import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))
  const token = ref(localStorage.getItem('token') || '')

  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => !!user.value?.is_admin)

  const login = async (username, password) => {
    const params = new URLSearchParams()
    params.append('username', username)
    params.append('password', password)
    const response = await axios.post('/api/auth/token', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
    user.value = response.data.user
    token.value = response.data.access_token
    localStorage.setItem('user', JSON.stringify(user.value))
    localStorage.setItem('token', token.value)
    return response.data
  }

  const register = async (username, email, password) => {
    const response = await axios.post('/api/auth/register', {
      username,
      email,
      password
    })
    user.value = response.data.user
    token.value = response.data.access_token
    localStorage.setItem('user', JSON.stringify(user.value))
    localStorage.setItem('token', token.value)
    return response.data
  }

  const logout = () => {
    user.value = null
    token.value = ''
    localStorage.removeItem('user')
    localStorage.removeItem('token')
  }

  const checkAuth = async () => {
    if (!token.value) {
      logout()
      return false
    }
    try {
      const response = await axios.get('/api/auth/me', {
        headers: { Authorization: `Bearer ${token.value}` }
      })
      user.value = response.data
      return true
    } catch (error) {
      logout()
      return false
    }
  }

  return {
    user,
    token,
    isAuthenticated,
    isAdmin,
    login,
    register,
    logout,
    checkAuth
  }
})
