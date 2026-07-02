import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(sessionStorage.getItem('admin_token'))

  const isAuthenticated = computed(() => !!token.value)

  async function login(secret: string) {
    const res = await axios.post('/admin/login', { secret })
    token.value = res.data.access_token
    sessionStorage.setItem('admin_token', token.value!)
  }

  function logout() {
    token.value = null
    sessionStorage.removeItem('admin_token')
  }

  return { token, isAuthenticated, login, logout }
})
