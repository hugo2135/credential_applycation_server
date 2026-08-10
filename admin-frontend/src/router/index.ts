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
      meta: { layout: 'guest', title: 'PBI 憑證申請 - 登入' },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { layout: 'guest', title: 'PBI 憑證申請 - 註冊' },
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { layout: 'user', requiresAuth: 'user', title: 'PBI 憑證申請 - 我的帳號' },
    },
    {
      path: '/mcp-tokens',
      name: 'mcp-tokens',
      component: () => import('@/views/McpTokenView.vue'),
      meta: { layout: 'user', requiresAuth: 'user', title: 'PBI 憑證申請 - MCP Token' },
    },

    // ── Admin routes ─────────────────────────────────────────
    {
      path: '/admin/login',
      name: 'admin-login',
      component: () => import('@/views/LoginView.vue'),
      meta: { layout: 'guest', title: 'PBI 管理後台 - 登入' },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/UsersView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin', title: 'PBI 管理後台 - 使用者管理' },
    },
    {
      path: '/admin/pbi-configs',
      name: 'admin-pbi-configs',
      component: () => import('@/views/PbiConfigsView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin', title: 'PBI 管理後台 - PBI 設定' },
    },
    {
      path: '/admin/pbi-configs/:id',
      name: 'admin-pbi-config-detail',
      component: () => import('@/views/PbiConfigDetailView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin', title: 'PBI 管理後台 - PBI 設定詳情' },
    },
    {
      path: '/admin/access-logs',
      name: 'admin-access-logs',
      component: () => import('@/views/AccessLogsView.vue'),
      meta: { layout: 'admin', requiresAuth: 'admin', title: 'PBI 管理後台 - 存取歷史' },
    },

    // ── Fallback ──────────────────────────────────────────────
    { path: '/admin', redirect: '/admin/login' },
    { path: '/', redirect: '/login' },
    {
      path: '/:pathMatch(.*)*',
      redirect: (to) => (to.path.startsWith('/admin') ? '/admin/login' : '/login'),
    },
  ],
})

router.beforeEach((to) => {
  const adminAuth = useAuthStore()
  const userAuth = useUserAuthStore()

  document.title = (to.meta.title as string) ?? 'PBI 憑證申請'

  // 任何 /admin/* 路徑（不論是否已定義路由）未授權一律導回 /admin/login
  if (to.path.startsWith('/admin') && to.name !== 'admin-login' && !adminAuth.isAuthenticated) {
    return '/admin/login'
  }
  if (to.meta.requiresAuth === 'user' && !userAuth.isAuthenticated) return '/login'

  if (to.name === 'admin-login' && adminAuth.isAuthenticated) return '/admin/users'
  if ((to.name === 'user-login' || to.name === 'register') && userAuth.isAuthenticated) return '/dashboard'
})

export default router
