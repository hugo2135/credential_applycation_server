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
    token.value = res.data.access_token
    sessionStorage.setItem('admin_token', token.value!)
  }

  function logout() {
    token.value = null
    sessionStorage.removeItem('admin_token')
  }

  return { token, isAuthenticated, login, logout }
})
