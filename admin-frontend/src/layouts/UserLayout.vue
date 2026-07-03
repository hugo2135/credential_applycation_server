<template>
  <el-container style="height: 100vh; flex-direction: column">
    <el-header style="background: #001529; display: flex; align-items: center; justify-content: space-between; padding: 0 24px">
      <span style="color: #fff; font-size: 15px; font-weight: bold">PBI Credential 自助服務</span>
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-size: 13px; color: #ffffff80">{{ auth.email }}</span>
        <el-button size="small" @click="handleLogout">登出</el-button>
      </div>
    </el-header>
    <el-main style="background: #f5f7fa; overflow-y: auto">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useUserAuthStore } from '@/stores/userAuth'

const router = useRouter()
const auth = useUserAuthStore()

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>
