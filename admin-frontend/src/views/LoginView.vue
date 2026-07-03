<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <span style="font-size: 18px; font-weight: bold">PBI Admin 登入</span>
      </template>
      <el-form @submit.prevent="handleLogin">
        <el-form-item label="Admin Secret">
          <el-input
            v-model="secret"
            type="password"
            show-password
            placeholder="輸入 ADMIN_SECRET"
            autocomplete="current-password"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
            登入
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const secret = ref('')
const loading = ref(false)

async function handleLogin() {
  if (!secret.value) return
  loading.value = true
  try {
    await auth.login(secret.value)
    router.push('/admin/users')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '登入失敗')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #001529 0%, #003a70 100%);
}
.login-card {
  width: 400px;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
</style>
