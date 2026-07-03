import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUserAuthStore } from '@/stores/userAuth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    // ── User routes ──────────────────────────────────────────
    {
      path: '/login',
      name: 'user-login',
      component: () => import('@/views/UserLoginView.vue'),
      meta: { layout: 'guest' },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { layout: 'guest' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { layout: 'user', requiresAuth: 'user' },
    },

    // ── Admin routes ─────────────────────────────────────────
    {
      path: '/admin/login',
      name: 'admin-login',
      component: () => import('@/views/LoginView.vue'),
      meta: { layout: 'guest' },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/UsersView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin' },
    },
    {
      path: '/admin/pbi-configs',
      name: 'admin-pbi-configs',
      component: () => import('@/views/PbiConfigsView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin' },
    },
    {
      path: '/admin/model',
      name: 'admin-model',
      component: () => import('@/views/ModelView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin' },
    },

    // ── Fallback ──────────────────────────────────────────────
    { path: '/admin', redirect: '/admin/login' },
    { path: '/', redirect: '/login' },
    { path: '/:pathMatch(.*)*', redirect: '/login' },
  ],
})

router.beforeEach((to) => {
  const adminAuth = useAuthStore()
  const userAuth = useUserAuthStore()

  if (to.meta.requiresAuth === 'admin' && !adminAuth.isAuthenticated) return '/admin/login'
  if (to.meta.requiresAuth === 'user' && !userAuth.isAuthenticated) return '/login'

  if (to.name === 'admin-login' && adminAuth.isAuthenticated) return '/admin/users'
  if ((to.name === 'user-login' || to.name === 'register') && userAuth.isAuthenticated) return '/dashboard'
})

export default router
