import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

function isExpired(jwt: string): boolean {
  try {
    const part = jwt.split('.')[1]
    if (!part) return false
    const payload = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.exp === 'number' && payload.exp * 1000 <= Date.now()
  } catch {
    return false
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(sessionStorage.getItem('admin_token'))

  const isAuthenticated = computed(() => !!token.value && !isExpired(token.value))

  async function login(secret: string) {
    const res = await axios.post('/api/admin/login', { secret })
    setToken(res.data.access_token)
  }

  // 管理員帳號（一般使用者帳號 + 管理員權限）
  async function loginWithPassword(email: string, password: string) {
    const res = await axios.post('/api/admin/login/password', { email, password })
    setToken(res.data.access_token)
  }

  // Google 登入由後端導回時直接帶著 token
  function setToken(newToken: string) {
    token.value = newToken
    sessionStorage.setItem('admin_token', newToken)
  }

  function logout() {
    token.value = null
    sessionStorage.removeItem('admin_token')
  }

  return { token, isAuthenticated, login, loginWithPassword, setToken, logout }
})
