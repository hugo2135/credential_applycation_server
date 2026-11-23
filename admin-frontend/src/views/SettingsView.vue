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

      <el-tab-pane label="登入與註冊" name="login">
        <el-form label-width="180px" style="max-width: 720px">
          <el-form-item label="允許的 email 網域">
            <TagInput v-model="form.allowed_email_domains" placeholder="例如 company.com，輸入後按 Enter" />
            <div class="hint">
              帳密註冊與 Google 登入共用。留空時帳密註冊不限網域，但 Google 登入會停用
              （Google 登入會自動開通帳號，不能對所有 Google 帳號開放）。
            </div>
          </el-form-item>

          <el-divider content-position="left">Google 登入</el-divider>

          <el-alert type="info" :closable="false" style="margin-bottom: 20px">
            <template #title>
              在 Google Cloud Console 建立「網頁應用程式」類型的 OAuth 用戶端（同意畫面選 Internal、scope 只需 openid 與
              email），把下面的重新導向 URI 填進「已授權的重新導向 URI」，再把拿到的用戶端 ID 與密鑰填在這裡。
            </template>
          </el-alert>

          <el-form-item label="重新導向 URI">
            <el-input :model-value="googleRedirectUri" readonly>
              <template #append>
                <el-button @click="copyRedirectUri">複製</el-button>
              </template>
            </el-input>
            <div class="hint">跟 SITE_DOMAIN 綁在一起；換網域時要到 Google Cloud Console 加上新的 URI。</div>
          </el-form-item>
          <el-form-item label="啟用 Google 登入">
            <el-switch v-model="form.google_login_enabled" />
            <div v-if="form.google_login_enabled && missingGoogleFields.length" class="hint warn">
              尚未設定：{{ missingGoogleFields.join('、') }}，登入頁不會出現 Google 按鈕。
            </div>
          </el-form-item>
          <el-form-item label="用戶端 ID">
            <el-input v-model="form.google_client_id" placeholder="xxxx.apps.googleusercontent.com" />
          </el-form-item>
          <el-form-item label="用戶端密鑰">
            <el-input
              v-model="googleSecretInput"
              type="password"
              show-password
              autocomplete="new-password"
              :placeholder="secrets.google_client_secret ? '已設定（留空表示不變）' : '尚未設定'"
            />
            <div class="hint">加密儲存，儲存後無法再查看。</div>
          </el-form-item>
          <el-form-item label="新帳號自動開通">
            <el-switch v-model="form.google_auto_activate" />
            <div class="hint">
              第一次用 Google 登入時建立的帳號直接開通，在 MCP 授權頁就能一次完成建帳號與連線。其他設定照預設，
              沒指派模型、沒填 Azure AD 憑證照樣查不了。只在建立當下生效，管理員停用後再登入不會恢復。
            </div>
          </el-form-item>
          <el-form-item label="自動綁定同 email 帳號">
            <el-switch v-model="form.google_auto_link" />
            <div class="hint">
              已用帳密註冊的人第一次用 Google 登入時，自動綁定到原帳號（只綁定，不改原帳號其他設定），之後只能用
              Google 登入。關閉時這種人會被擋下，請他繼續用帳密登入。
            </div>
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
import TagInput from '@/components/pbi/TagInput.vue'

type QueryExecution = 'edge' | 'server'
interface Settings {
  server_query_max_concurrency: number
  server_query_max_rows: number
  server_query_timeout_seconds: number
  default_query_execution: QueryExecution
  allowed_email_domains: string[]
  google_login_enabled: boolean
  google_client_id: string
  google_auto_activate: boolean
  google_auto_link: boolean
}
interface SettingsResponse {
  values: Settings
  secrets: { google_client_secret: boolean }
  query_execution_counts: Record<QueryExecution, number>
  google_redirect_uri: string
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
  allowed_email_domains: [],
  google_login_enabled: false,
  google_client_id: '',
  google_auto_activate: true,
  google_auto_link: true,
})
const counts = ref<Record<QueryExecution, number>>({ edge: 0, server: 0 })
const secrets = ref({ google_client_secret: false })
const googleRedirectUri = ref('')
// 密鑰只能寫入：輸入框永遠從空白開始，有輸入才會送出
const googleSecretInput = ref('')

const dirty = computed(
  () => !!saved.value && (JSON.stringify(form.value) !== JSON.stringify(saved.value) || !!googleSecretInput.value),
)

const missingGoogleFields = computed(() => {
  const missing = []
  if (!form.value.google_client_id) missing.push('用戶端 ID')
  if (!secrets.value.google_client_secret && !googleSecretInput.value) missing.push('用戶端密鑰')
  if (!form.value.allowed_email_domains.length) missing.push('允許的 email 網域')
  return missing
})

function clone(values: Settings): Settings {
  return JSON.parse(JSON.stringify(values))
}

function apply(data: SettingsResponse) {
  saved.value = clone(data.values)
  form.value = clone(data.values)
  counts.value = data.query_execution_counts
  secrets.value = data.secrets
  googleRedirectUri.value = data.google_redirect_uri
  googleSecretInput.value = ''
}

function reset() {
  if (saved.value) form.value = clone(saved.value)
  googleSecretInput.value = ''
}

async function copyRedirectUri() {
  try {
    await navigator.clipboard.writeText(googleRedirectUri.value)
    ElMessage.success('已複製')
  } catch {
    ElMessage.warning('無法存取剪貼簿，請手動複製')
  }
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
    const body: Record<string, unknown> = { ...form.value }
    if (googleSecretInput.value) body.google_client_secret = googleSecretInput.value
    const { data } = await http.put<SettingsResponse>('/settings', body)
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
.hint.warn {
  color: #e6a23c;
}
</style>
