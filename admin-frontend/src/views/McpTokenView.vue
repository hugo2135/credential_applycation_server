<template>
  <div style="max-width: 680px; margin: 32px auto">
    <el-page-header content="MCP 連線設定" @back="router.push('/dashboard')" style="margin-bottom: 20px" />

    <el-alert type="info" :closable="false" style="margin-bottom: 20px">
      <template #title>先看你的 AI 工具在新增 MCP 伺服器時要你填什麼：</template>
      <div style="line-height: 1.8; margin-top: 4px">
        要你填「<b>OAuth 用戶端 ID</b>」（例如 Gemini）→ 用下方第一個區塊<br />
        要你貼上「<b>Bearer token</b>」或 Authorization 標頭（例如 Antigravity）→ 用下方「我的 Token」<br />
        什麼都不用填、會自動跳出登入頁（例如 Claude）→ 不需要這個頁面
      </div>
    </el-alert>

    <!-- 給不會自己做 Dynamic Client Registration 的 client（例如 Gemini 網頁版） -->
    <el-card style="margin-bottom: 20px">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">取得 OAuth 用戶端 ID</span>
      </template>
      <ol style="padding-left: 20px; margin: 0 0 16px; line-height: 2; font-size: 14px; color: #444">
        <li>
          「MCP 伺服器網址」填入
          <code style="background: #f4f4f5; padding: 2px 6px; border-radius: 4px">{{ mcpUrl }}</code>
          <el-button size="small" link type="primary" @click="copyText(mcpUrl)">複製</el-button>
        </li>
        <li>在該工具的設定畫面找到「<b>複製重新導向 URI</b>」，貼到下面</li>
        <li>按「取得用戶端 ID」，把結果貼到「用戶端 ID」，<b>「用戶端密鑰」留空</b></li>
        <li>按繼續後會跳到本站登入頁，用你在這裡的帳號密碼登入</li>
      </ol>
      <div style="display: flex; gap: 8px">
        <el-input v-model="redirectUri" placeholder="貼上重新導向 URI，例如 https://..." clearable />
        <el-button type="primary" :loading="registering" @click="registerClient">取得用戶端 ID</el-button>
      </div>
      <div v-if="clientId" style="margin-top: 16px">
        <div style="font-size: 13px; color: #666; margin-bottom: 6px">用戶端 ID：</div>
        <div style="display: flex; gap: 8px">
          <el-input :model-value="clientId" readonly style="font-family: monospace" />
          <el-button type="primary" plain @click="copyText(clientId)">複製</el-button>
        </div>
      </div>
    </el-card>

    <!-- 新產生的 token（本次領取後顯示一次） -->
    <el-card v-if="newToken" style="margin-bottom: 20px">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">新 Token 已產生</span>
      </template>
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>請立即複製並妥善保存，此 token 僅顯示一次，關閉頁面後無法再次查看。</template>
      </el-alert>
      <el-input v-model="newToken" readonly :rows="2" type="textarea" style="font-family: monospace; font-size: 13px" />
      <el-button style="margin-top: 12px" type="primary" plain @click="copyText(newToken)">複製 Token</el-button>
    </el-card>

    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-size: 16px; font-weight: 600">我的 Token</span>
          <el-button type="primary" size="small" :loading="creating" @click="createDialogVisible = true">
            新增 Token
          </el-button>
        </div>
      </template>

      <el-table :data="tokens" v-loading="loading">
        <el-table-column prop="name" label="名稱">
          <template #default="{ row }">{{ row.name || '—' }}</template>
        </el-table-column>
        <el-table-column label="建立時間">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最後使用">
          <template #default="{ row }">
            {{ row.last_used_at ? formatDate(row.last_used_at) : '尚未使用' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-popconfirm title="確定要撤銷此 token？撤銷後使用它的 MCP client 會立即失效。" @confirm="revoke(row.id)">
              <template #reference>
                <el-button type="danger" size="small" link>撤銷</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="尚未建立任何 token" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-dialog v-model="createDialogVisible" title="新增 Token" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名稱">
          <el-input v-model="createName" placeholder="例如：Antigravity（選填，方便自己辨識）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createToken">產生</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import userHttp from '@/api/userHttp'
import { formatDate } from '@/utils/date'

interface McpToken {
  id: string
  name: string | null
  created_at: string
  last_used_at: string | null
}

const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const tokens = ref<McpToken[]>([])
const newToken = ref('')
const createDialogVisible = ref(false)
const createName = ref('')

// 前端跟後端同 origin，MCP 網址直接用目前網址組出來
const mcpUrl = `${window.location.origin}/mcp`
const redirectUri = ref('')
const clientId = ref('')
const registering = ref(false)

async function registerClient() {
  if (!redirectUri.value.trim()) {
    ElMessage.warning('請先貼上重新導向 URI')
    return
  }
  registering.value = true
  try {
    const { data } = await userHttp.post('/oauth-clients', { redirect_uri: redirectUri.value.trim() })
    clientId.value = data.client_id
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '取得失敗')
  } finally {
    registering.value = false
  }
}

async function loadTokens() {
  loading.value = true
  try {
    const { data } = await userHttp.get('/mcp-tokens')
    tokens.value = data
  } catch {
    ElMessage.error('無法載入 token 清單')
  } finally {
    loading.value = false
  }
}

async function createToken() {
  creating.value = true
  try {
    const { data } = await userHttp.post('/mcp-tokens', { name: createName.value || null })
    newToken.value = data.token
    createDialogVisible.value = false
    createName.value = ''
    await loadTokens()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '產生失敗')
  } finally {
    creating.value = false
  }
}

async function revoke(id: string) {
  try {
    await userHttp.delete(`/mcp-tokens/${id}`)
    ElMessage.success('已撤銷')
    if (newToken.value) newToken.value = ''
    await loadTokens()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '撤銷失敗')
  }
}

async function copyText(text: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('已複製到剪貼簿')
  } catch {
    ElMessage.error('複製失敗，請手動選取後複製')
  }
}

onMounted(loadTokens)
</script>
