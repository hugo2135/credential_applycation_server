<template>
  <el-container style="height: 100vh">
    <el-aside width="200px" style="background: #001529">
      <div style="color: #fff; padding: 20px 16px; font-weight: bold; font-size: 15px">
        PBI Admin
      </div>
      <el-menu
        :default-active="route.path"
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
        <el-menu-item index="/admin/model">
          <el-icon><Upload /></el-icon>
          <span>語意模型</span>
        </el-menu-item>
      </el-menu>

      <div style="position: absolute; bottom: 16px; width: 8%; padding: 0 12px; box-sizing: border-box">
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
  '/admin/model': '語意模型管理',
}
const pageTitle = computed(() => titleMap[route.path] ?? '')

function handleLogout() {
  auth.logout()
  router.push('/admin/login')
}
</script>
