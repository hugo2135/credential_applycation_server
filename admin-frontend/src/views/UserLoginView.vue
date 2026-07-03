<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <template #header>
        <span style="font-size: 18px; font-weight: bold">PBI Credential 使用者登入</span>
      </template>
      <el-form @submit.prevent="handleLogin" label-width="70px">
        <el-form-item label="Email">
          <el-input v-model="form.email" type="email" placeholder="your@email.com" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密碼">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
            登入
          </el-button>
        </el-form-item>
        <div style="text-align: center; font-size: 13px; color: #666">
          還沒有帳號？<router-link to="/register">立即註冊</router-link>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserAuthStore } from '@/stores/userAuth'

const router = useRouter()
const auth = useUserAuthStore()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

async function handleLogin() {
  if (!form.email || !form.password) return
  loading.value = true
  try {
    await auth.login(form.email, form.password)
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '登入失敗')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-wrap {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #001529 0%, #003a70 100%);
}
.auth-card {
  width: 400px;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
</style>
