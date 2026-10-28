<template>
  <div style="max-width: 960px; margin: 32px auto">
    <el-page-header content="我的書籤" @back="router.push('/dashboard')" style="margin-bottom: 20px" />

    <el-alert type="info" :closable="false" style="margin-bottom: 20px">
      <template #title>
        在 AI 對話中說「把這個查詢存成書籤」就會存到這裡，之後說「執行我的書籤 XXX」即可重跑。
        匯出的檔案可以分享給同事匯入，對方需要有同一個模型的存取權。
      </template>
    </el-alert>

    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap">
          <el-select v-model="filterConfigId" placeholder="全部模型" clearable style="width: 240px">
            <el-option v-for="c in configOptions" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
          <div style="display: flex; gap: 8px">
            <el-button :loading="exporting" @click="exportBookmarks">匯出</el-button>
            <el-button type="primary" @click="fileInput?.click()">匯入</el-button>
            <input ref="fileInput" type="file" accept=".json,application/json" style="display: none" @change="onFilePicked" />
          </div>
        </div>
      </template>

      <el-table :data="filteredBookmarks" v-loading="loading">
        <el-table-column label="模型" min-width="140">
          <template #default="{ row }">{{ row.pbi_config_name }}</template>
        </el-table-column>
        <el-table-column label="標題" min-width="160">
          <template #default="{ row }">
            {{ row.title }}
            <el-tooltip
              v-if="row.possibly_outdated"
              content="存檔後語意模型改過版，這個 DAX 可能已經不適用，AI 執行前會先跟你確認"
              placement="top"
            >
              <el-tag type="warning" size="small" style="margin-left: 4px">可能過時</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="原始問題" min-width="200">
          <template #default="{ row }">
            <span :style="{ color: row.question ? 'inherit' : '#c0c4cc' }">{{ row.question || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="更新時間" width="170">
          <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="viewing = row">查看 DAX</el-button>
            <el-popconfirm title="確定刪除這個書籤？" @confirm="remove(row.id)">
              <template #reference>
                <el-button size="small" link type="danger">刪除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="還沒有書籤" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <!-- 查看 DAX -->
    <el-dialog :model-value="!!viewing" :title="viewing?.title" width="640px" @close="viewing = null">
      <el-input :model-value="viewing?.dax" type="textarea" readonly :rows="12" style="font-family: monospace; font-size: 13px" />
      <template #footer>
        <el-button @click="viewing = null">關閉</el-button>
        <el-button type="primary" plain @click="copyText(viewing?.dax ?? '')">複製 DAX</el-button>
      </template>
    </el-dialog>

    <!-- 匯入：先選同名處理方式，匯入後顯示結果 -->
    <el-dialog v-model="importDialog.visible" title="匯入書籤" width="480px">
      <template v-if="!importDialog.result">
        <p style="margin-bottom: 16px; font-size: 14px">
          檔案：{{ importDialog.fileName }}（{{ importDialog.count }} 筆）
        </p>
        <el-form label-width="110px">
          <el-form-item label="遇到同名書籤">
            <el-radio-group v-model="importDialog.onConflict">
              <el-radio value="skip">略過，保留我的</el-radio>
              <el-radio value="overwrite">覆蓋成檔案裡的</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-form>
      </template>
      <template v-else>
        <p style="font-size: 14px; line-height: 2">
          新增 {{ importDialog.result.created }} 筆、覆蓋 {{ importDialog.result.overwritten }} 筆
        </p>
        <div v-if="importDialog.result.skipped.length || importDialog.result.failed.length" style="font-size: 13px; color: #666">
          <div style="margin-bottom: 4px">以下沒有匯入：</div>
          <ul style="padding-left: 20px; margin: 0; line-height: 1.8">
            <li v-for="(item, i) in [...importDialog.result.skipped, ...importDialog.result.failed]" :key="i">
              {{ item.title || '（無標題）' }}：{{ item.reason }}
            </li>
          </ul>
        </div>
      </template>
      <template #footer>
        <template v-if="!importDialog.result">
          <el-button @click="importDialog.visible = false">取消</el-button>
          <el-button type="primary" :loading="importDialog.loading" @click="submitImport">匯入</el-button>
        </template>
        <el-button v-else type="primary" @click="importDialog.visible = false">完成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import userHttp from '@/api/userHttp'
import { formatDate } from '@/utils/date'

interface Bookmark {
  id: string
  pbi_config_id: string
  pbi_config_name: string
  title: string
  dax: string
  question: string | null
  possibly_outdated: boolean
  updated_at: string
}
interface ImportResult {
  created: number
  overwritten: number
  skipped: { title: string | null; reason: string }[]
  failed: { title: string | null; reason: string }[]
}

const router = useRouter()
const loading = ref(false)
const exporting = ref(false)
const bookmarks = ref<Bookmark[]>([])
const filterConfigId = ref('')
const viewing = ref<Bookmark | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const importDialog = ref({
  visible: false,
  loading: false,
  fileName: '',
  count: 0,
  data: null as unknown,
  onConflict: 'skip' as 'skip' | 'overwrite',
  result: null as ImportResult | null,
})

const configOptions = computed(() => {
  const seen = new Map<string, string>()
  for (const b of bookmarks.value) seen.set(b.pbi_config_id, b.pbi_config_name)
  return [...seen].map(([id, name]) => ({ id, name }))
})

const filteredBookmarks = computed(() =>
  filterConfigId.value ? bookmarks.value.filter((b) => b.pbi_config_id === filterConfigId.value) : bookmarks.value,
)

async function load() {
  loading.value = true
  try {
    const { data } = await userHttp.get('/bookmarks')
    bookmarks.value = data
  } catch {
    ElMessage.error('無法載入書籤')
  } finally {
    loading.value = false
  }
}

async function remove(id: string) {
  try {
    await userHttp.delete(`/bookmarks/${id}`)
    ElMessage.success('已刪除')
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '刪除失敗')
  }
}

async function exportBookmarks() {
  exporting.value = true
  try {
    const { data } = await userHttp.get('/bookmarks/export', { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const a = document.createElement('a')
    a.href = url
    a.download = `nl-to-dax-bookmarks-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('匯出失敗')
  } finally {
    exporting.value = false
  }
}

async function onFilePicked(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 讓同一個檔案可以再選一次
  if (!file) return
  let data: any
  try {
    data = JSON.parse(await file.text())
  } catch {
    ElMessage.error('檔案不是有效的 JSON')
    return
  }
  if (!Array.isArray(data?.bookmarks)) {
    ElMessage.error('這不是書籤匯出檔')
    return
  }
  importDialog.value = {
    visible: true,
    loading: false,
    fileName: file.name,
    count: data.bookmarks.length,
    data,
    onConflict: 'skip',
    result: null,
  }
}

async function submitImport() {
  const d = importDialog.value
  d.loading = true
  try {
    const { data } = await userHttp.post('/bookmarks/import', { data: d.data, on_conflict: d.onConflict })
    d.result = data
    await load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '匯入失敗')
  } finally {
    d.loading = false
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

onMounted(load)
</script>
