<template>
  <el-card v-loading="loading">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="伺服器查詢" name="server-query">
        <el-alert type="info" :closable="false" style="margin-bottom: 20px">
          <template #title>
            每位使用者可以各自選擇查詢方式：「腳本查詢」由 AI 端的查詢腳本自行連 Power BI（需要沙盒放行網路）；
            「伺服器查詢」由這台伺服器代查並把結果交給 AI，不需要任何網路設定。
            查詢方式在「使用者管理」逐一或批次切換，這裡調整伺服器查詢的共用參數，儲存後立即生效。
          </template>
        </el-alert>

        <div class="mode-stats">
          <div class="mode-stat">
            <div class="mode-stat__value">{{ counts.edge }}</div>
            <div class="mode-stat__label">腳本查詢</div>
          </div>
          <div class="mode-stat">
            <div class="mode-stat__value">{{ counts.server }}</div>
            <div class="mode-stat__label">伺服器查詢</div>
          </div>
          <el-button link type="primary" @click="router.push('/admin/users')">到使用者管理切換 →</el-button>
        </div>

        <el-form label-width="180px" style="max-width: 640px">
          <el-form-item label="同時查詢上限">
            <el-input-number v-model="form.server_query_max_concurrency" :min="1" :max="32" />
            <div class="hint">同時進行中的伺服器查詢數，超過的會排隊。主機記憶體小時不建議調太高。</div>
          </el-form-item>
          <el-form-item label="每個結果最多回傳列數">
            <el-input-number v-model="form.server_query_max_rows" :min="1" :max="10000" :step="100" />
            <div class="hint">結果會整包交給 AI。超過時只回傳前面幾列並標示不完整，AI 會改成彙總或加篩選再查。</div>
          </el-form-item>
          <el-form-item label="查詢逾時（秒）">
            <el-input-number v-model="form.server_query_timeout_seconds" :min="5" :max="300" />
            <div class="hint">包含排隊等待時間。</div>
          </el-form-item>
          <el-form-item label="新使用者預設查詢方式">
            <el-radio-group v-model="form.default_query_execution">
              <el-radio value="edge">腳本查詢</el-radio>
              <el-radio value="server">伺服器查詢</el-radio>
            </el-radio-group>
            <div class="hint">只影響之後註冊的使用者，既有使用者不會被改動。</div>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">儲存</el-button>
            <el-button :disabled="!dirty" @click="reset">還原</el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '@/api/http'

type QueryExecution = 'edge' | 'server'
interface Settings {
  server_query_max_concurrency: number
  server_query_max_rows: number
  server_query_timeout_seconds: number
  default_query_execution: QueryExecution
}
interface SettingsResponse {
  values: Settings
  query_execution_counts: Record<QueryExecution, number>
  message?: string
}

const router = useRouter()
const activeTab = ref('server-query')
const loading = ref(false)
const saving = ref(false)
const saved = ref<Settings | null>(null)
const form = ref<Settings>({
  server_query_max_concurrency: 4,
  server_query_max_rows: 1000,
  server_query_timeout_seconds: 60,
  default_query_execution: 'edge',
})
const counts = ref<Record<QueryExecution, number>>({ edge: 0, server: 0 })

const dirty = computed(() => !!saved.value && JSON.stringify(form.value) !== JSON.stringify(saved.value))

function apply(data: SettingsResponse) {
  saved.value = { ...data.values }
  form.value = { ...data.values }
  counts.value = data.query_execution_counts
}

function reset() {
  if (saved.value) form.value = { ...saved.value }
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get<SettingsResponse>('/settings')
    apply(data)
  } catch {
    ElMessage.error('無法載入系統設定')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const { data } = await http.put<SettingsResponse>('/settings', form.value)
    apply(data)
    ElMessage.success(data.message ?? '已儲存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '儲存失敗')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mode-stats {
  display: flex;
  align-items: center;
  gap: 24px;
  margin-bottom: 24px;
}
.mode-stat {
  min-width: 96px;
  padding: 12px 16px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  text-align: center;
}
.mode-stat__value {
  font-size: 22px;
  font-weight: 600;
}
.mode-stat__label {
  font-size: 12px;
  color: #909399;
}
.hint {
  width: 100%;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}
</style>
