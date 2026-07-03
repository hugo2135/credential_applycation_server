import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useUserAuthStore = defineStore('userAuth', () => {
  const token = ref<string | null>(sessionStorage.getItem('user_token'))
  const email = ref<string>(sessionStorage.getItem('user_email') ?? '')

  const isAuthenticated = computed(() => !!token.value)

  async function login(emailInput: string, password: string) {
    const res = await axios.post('/auth/login', { email: emailInput, password })
    token.value = res.data.access_token
    email.value = emailInput
    sessionStorage.setItem('user_token', token.value!)
    sessionStorage.setItem('user_email', emailInput)
  }

  function logout() {
    token.value = null
    email.value = ''
    sessionStorage.removeItem('user_token')
    sessionStorage.removeItem('user_email')
  }

  return { token, email, isAuthenticated, login, logout }
})
