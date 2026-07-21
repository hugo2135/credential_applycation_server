<template>
  <div style="max-width: 680px; margin: 32px auto">
    <el-card v-loading="loading">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">帳號狀態</span>
      </template>

      <el-descriptions :column="1" border>
        <el-descriptions-item label="Email">{{ info?.email }}</el-descriptions-item>
        <el-descriptions-item label="帳號狀態">
          <el-tag :type="info?.is_active ? 'success' : 'warning'">
            {{ info?.is_active ? '已開通' : '待開通' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="到期時間">
          {{ info?.expires_at ? new Date(info.expires_at).toLocaleString() : '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="PBI_MASK_KEY">
          <el-tag :type="info?.has_mask_key ? 'info' : 'default'">
            {{ info?.has_mask_key ? '已領取' : '尚未領取' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 領取 key 區塊 -->
    <el-card style="margin-top: 20px">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">PBI_MASK_KEY</span>
      </template>

      <!-- 已顯示過 key（本次領取後） -->
      <template v-if="newKey">
        <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
          <template #title>
            請立即複製並妥善保存，此金鑰僅顯示一次，關閉頁面後無法再次查看。
          </template>
        </el-alert>
        <el-input
          v-model="newKey"
          readonly
          :rows="2"
          type="textarea"
          style="font-family: monospace; font-size: 13px"
        />
        <el-button
          style="margin-top: 12px"
          type="primary"
          plain
          @click="copyKey"
        >
          複製金鑰
        </el-button>
      </template>

      <!-- 未開通 -->
      <template v-else-if="info && !info.is_active">
        <el-empty description="帳號尚未開通，請聯絡管理員" :image-size="80" />
      </template>

      <!-- 已開通但尚未領取 -->
      <template v-else-if="info && info.is_active && !info.has_mask_key">
        <p style="color: #666; margin-bottom: 16px; font-size: 14px">
          領取後金鑰只會顯示一次，請確保已準備好安全保存的地方。
        </p>
        <el-button type="primary" :loading="issuing" @click="issueKey">領取 PBI_MASK_KEY</el-button>
      </template>

      <!-- 已領取過（本次沒有新 key） -->
      <template v-else-if="info && info.has_mask_key">
        <el-empty description="PBI_MASK_KEY 已領取。如需重新領取，請聯絡管理員重設。" :image-size="80" />
      </template>
    </el-card>

    <!-- 不支援 OAuth 連線的 MCP client，跟上面的 PBI_MASK_KEY 是不同機制 -->
    <el-card style="margin-top: 20px">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">MCP Personal Access Token</span>
      </template>
      <p style="color: #666; margin-bottom: 16px; font-size: 14px">
        如果你使用的 MCP client（例如 Antigravity）不支援 OAuth 連線流程、需要手動貼上固定
        Bearer token，請到專屬頁面產生這種 token（跟上方的 PBI_MASK_KEY 用途不同，不要混用）。
      </p>
      <el-button @click="router.push('/mcp-tokens')">前往管理 MCP Token</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import userHttp from '@/api/userHttp'

interface UserInfo {
  user_id: string
  email: string
  is_active: boolean
  has_mask_key: boolean
  expires_at: string | null
}

const router = useRouter()
const loading = ref(false)
const issuing = ref(false)
const info = ref<UserInfo | null>(null)
const newKey = ref('')

async function loadMe() {
  loading.value = true
  try {
    const { data } = await userHttp.get('/me')
    info.value = data
  } catch {
    ElMessage.error('無法載入帳號資訊')
  } finally {
    loading.value = false
  }
}

async function issueKey() {
  issuing.value = true
  try {
    const { data } = await userHttp.post('/mask-key')
    newKey.value = data.mask_key
    if (info.value) info.value.has_mask_key = true
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '領取失敗')
  } finally {
    issuing.value = false
  }
}

async function copyKey() {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(newKey.value)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = newKey.value
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('已複製到剪貼簿')
  } catch {
    ElMessage.error('複製失敗，請手動選取金鑰複製')
  }
}

onMounted(loadMe)
</script>
