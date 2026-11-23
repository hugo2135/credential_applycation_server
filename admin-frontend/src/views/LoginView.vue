<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <template #header>
        <span style="font-size: 18px; font-weight: bold">PBI Admin 登入</span>
      </template>

      <template v-if="mode === 'account'">
        <GoogleLoginButton flow="admin" />
        <el-form @submit.prevent="handleAccountLogin" label-width="50px">
          <el-form-item label="Email">
            <el-input v-model="account.email" type="email" placeholder="your@email.com" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密碼">
            <el-input v-model="account.password" type="password" show-password autocomplete="current-password" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">登入</el-button>
          </el-form-item>
        </el-form>
        <div class="hint">需要使用者管理中具備「管理員」權限的帳號。</div>
      </template>

      <!-- ADMIN_SECRET：新部署還沒有管理員帳號、或 Google 設定壞掉時的備援 -->
      <el-form v-else @submit.prevent="handleSecretLogin">
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
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">登入</el-button>
        </el-form-item>
      </el-form>

      <div class="switch">
        <el-button link type="primary" @click="mode = mode === 'account' ? 'secret' : 'account'">
          {{ mode === 'account' ? '使用 Admin Secret 登入 →' : '← 使用帳號登入' }}
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import GoogleLoginButton from '@/components/GoogleLoginButton.vue'
import { consumeGoogleFragment } from '@/utils/googleLogin'

const router = useRouter()
const auth = useAuthStore()

const mode = ref<'account' | 'secret'>('account')
const account = reactive({ email: '', password: '' })
const secret = ref('')
const loading = ref(false)

onMounted(() => {
  const result = consumeGoogleFragment()
  if (!result) return
  if (result.error || !result.token) {
    ElMessage.error({ message: result.error ?? 'Google 登入失敗', duration: 6000 })
    return
  }
  auth.setToken(result.token)
  router.push('/admin/users')
})

async function submit(login: () => Promise<void>) {
  loading.value = true
  try {
    await login()
    router.push('/admin/users')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '登入失敗')
  } finally {
    loading.value = false
  }
}

function handleAccountLogin() {
  if (!account.email || !account.password) return
  submit(() => auth.loginWithPassword(account.email, account.password))
}

function handleSecretLogin() {
  if (!secret.value) return
  submit(() => auth.login(secret.value))
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
.hint {
  font-size: 12px;
  color: #909399;
  text-align: center;
}
.switch {
  margin-top: 16px;
  text-align: center;
}
</style>
