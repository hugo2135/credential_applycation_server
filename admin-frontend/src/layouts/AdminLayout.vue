<template>
  <el-container style="height: 100vh">
    <el-aside width="200px" class="admin-aside">
      <div style="color: #fff; padding: 20px 16px; font-weight: bold; font-size: 15px">
        PBI Admin
      </div>
      <el-menu
        class="admin-menu admin-menu--main"
        :default-active="activeMenuIndex"
        router
        background-color="#001529"
        text-color="#ffffffa0"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/admin/users">
          <el-icon><User /></el-icon>
          <span>使用者管理</span>
        </el-menu-item>
        <el-menu-item index="/admin/pbi-configs">
          <el-icon><Setting /></el-icon>
          <span>PBI 設定</span>
        </el-menu-item>
        <el-menu-item index="/admin/access-logs">
          <el-icon><Clock /></el-icon>
          <span>存取歷史</span>
        </el-menu-item>
      </el-menu>

      <!-- 系統層級的設定跟日常管理功能分開，固定在側欄底部、登出鈕上方 -->
      <el-menu
        class="admin-menu"
        :default-active="activeMenuIndex"
        router
        background-color="#001529"
        text-color="#ffffffa0"
        active-text-color="#ffffff"
      >
        <el-menu-item index="/admin/settings">
          <el-icon><Tools /></el-icon>
          <span>系統設定</span>
        </el-menu-item>
      </el-menu>
      <div style="padding: 8px 12px 16px">
        <el-button style="width: 100%" @click="handleLogout">登出</el-button>
      </div>
    </el-aside>

    <el-container>
      <el-header style="background: #fff; border-bottom: 1px solid #e8e8e8; line-height: 60px; font-size: 16px; font-weight: 500">
        {{ pageTitle }}
      </el-header>
      <el-main style="background: #f5f5f5">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const titleMap: Record<string, string> = {
  '/admin/users': '使用者管理',
  '/admin/pbi-configs': 'PBI 設定管理',
  '/admin/access-logs': '存取歷史',
  '/admin/settings': '系統設定',
}
// /admin/pbi-configs/:id 這種巢狀路徑，選單跟標題都比照父層 /admin/pbi-configs 顯示
const activeMenuIndex = computed(() =>
  route.path.startsWith('/admin/pbi-configs/') ? '/admin/pbi-configs' : route.path,
)
const pageTitle = computed(() => titleMap[activeMenuIndex.value] ?? '')

function handleLogout() {
  auth.logout()
  router.push('/admin/login')
}
</script>

<style scoped>
.admin-aside {
  background: #001529;
  display: flex;
  flex-direction: column;
}
.admin-menu {
  border-right: none;
}
/* 主選單吃掉剩餘高度，把系統設定與登出推到底部 */
.admin-menu--main {
  flex: 1;
}
</style>
