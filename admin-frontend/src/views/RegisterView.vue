<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <template #header>
        <span style="font-size: 18px; font-weight: bold">PBI Credential 帳號申請</span>
      </template>
      <el-form @submit.prevent="handleRegister" label-width="80px">
        <el-form-item label="Email">
          <el-input v-model="form.email" type="email" placeholder="your@email.com" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密碼">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="確認密碼">
          <el-input v-model="form.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
            申請帳號
          </el-button>
        </el-form-item>
        <div style="text-align: center; font-size: 13px; color: #666">
          已有帳號？<router-link to="/login">前往登入</router-link>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', password: '', confirm: '' })

async function handleRegister() {
  if (!form.email || !form.password) return
  if (form.password !== form.confirm) {
    ElMessage.error('兩次輸入的密碼不一致')
    return
  }
  loading.value = true
  try {
    await axios.post('/auth/register', { email: form.email, password: form.password })
    ElMessage.success('申請成功！請等待管理員開通後再登入')
    router.push('/login')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '申請失敗')
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
  width: 420px;
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
</style>
