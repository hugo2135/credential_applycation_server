import axios from 'axios'
import { useUserAuthStore } from '@/stores/userAuth'
import router from '@/router'

const userHttp = axios.create({ baseURL: '/auth' })

userHttp.interceptors.request.use((config) => {
  const store = useUserAuthStore()
  if (store.token) config.headers.Authorization = `Bearer ${store.token}`
  return config
})

userHttp.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401) {
      useUserAuthStore().logout()
      router.push('/login')
    }
    return Promise.reject(error)
  },
)

export default userHttp
