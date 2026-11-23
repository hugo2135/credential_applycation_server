import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

export const useUserAuthStore = defineStore('userAuth', () => {
  const token = ref<string | null>(sessionStorage.getItem('user_token'))
  const email = ref<string>(sessionStorage.getItem('user_email') ?? '')

  const isAuthenticated = computed(() => !!token.value)

  async function login(emailInput: string, password: string) {
    const res = await axios.post('/auth/login', { email: emailInput, password })
    setSession(res.data.access_token, emailInput)
  }

  // Google 登入由後端導回時直接帶著 token，不經過 /auth/login
  function setSession(newToken: string, newEmail: string) {
    token.value = newToken
    email.value = newEmail
    sessionStorage.setItem('user_token', newToken)
    sessionStorage.setItem('user_email', newEmail)
  }

  function logout() {
    token.value = null
    email.value = ''
    sessionStorage.removeItem('user_token')
    sessionStorage.removeItem('user_email')
  }

  return { token, email, isAuthenticated, login, setSession, logout }
})
