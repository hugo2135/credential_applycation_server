import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { requiresAuth: false } },
    {
      path: '/users',
      name: 'users',
      component: () => import('@/views/UsersView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/pbi-configs',
      name: 'pbi-configs',
      component: () => import('@/views/PbiConfigsView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/model',
      name: 'model',
      component: () => import('@/views/ModelView.vue'),
      meta: { requiresAuth: true },
    },
    { path: '/', redirect: '/users' },
    { path: '/:pathMatch(.*)*', redirect: '/users' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) return '/login'
  if (to.name === 'login' && auth.isAuthenticated) return '/users'
})

export default router
