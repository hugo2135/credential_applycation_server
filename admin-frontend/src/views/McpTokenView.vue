<template>
  <div style="max-width: 680px; margin: 32px auto">
    <el-page-header content="MCP Personal Access Token" @back="router.push('/dashboard')" style="margin-bottom: 20px" />

    <el-alert type="info" :closable="false" style="margin-bottom: 20px">
      <template #title>
        這裡產生的 token 跟 PBI_MASK_KEY 是不同東西：PBI_MASK_KEY 給支援 OAuth 連線的
        MCP client（例如 Claude）使用；這裡的 token 給不支援 OAuth 流程、需要手動貼上
        固定 Bearer token 的 MCP client（例如 Antigravity）使用，請依照該 client 的說明
        將 token 貼到它的 MCP 設定裡。
      </template>
    </el-alert>

    <!-- 新產生的 token（本次領取後顯示一次） -->
    <el-card v-if="newToken" style="margin-bottom: 20px">
      <template #header>
        <span style="font-size: 16px; font-weight: 600">新 Token 已產生</span>
      </template>
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>請立即複製並妥善保存，此 token 僅顯示一次，關閉頁面後無法再次查看。</template>
      </el-alert>
      <el-input v-model="newToken" readonly :rows="2" type="textarea" style="font-family: monospace; font-size: 13px" />
      <el-button style="margin-top: 12px" type="primary" plain @click="copyToken">複製 Token</el-button>
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
          <template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="最後使用">
          <template #default="{ row }">
            {{ row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '尚未使用' }}
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

async function copyToken() {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(newToken.value)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = newToken.value
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    ElMessage.success('已複製到剪貼簿')
  } catch {
    ElMessage.error('複製失敗，請手動選取 token 複製')
  }
}

onMounted(loadTokens)
</script>
