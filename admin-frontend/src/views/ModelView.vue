<template>
  <el-row :gutter="16">
    <el-col :span="14">
      <el-card>
        <template #header>上傳新版語意模型</template>

        <el-tabs v-model="inputMode">
          <!-- 上傳檔案 -->
          <el-tab-pane label="上傳檔案" name="file">
            <el-upload
              drag
              accept=".json"
              :auto-upload="false"
              :limit="1"
              :on-change="handleFileChange"
              :on-remove="() => { fileContent = ''; fileName = '' }"
              :file-list="fileList"
            >
              <el-icon style="font-size: 48px; color: #c0c4cc"><Upload /></el-icon>
              <div style="margin-top: 8px; font-size: 14px; color: #606266">
                拖曳 <b>.json</b> 檔案至此，或<em>點擊選擇</em>
              </div>
              <template #tip>
                <div style="font-size: 12px; color: #909399; margin-top: 4px">
                  支援原始 Power BI 格式（clientDataModel）或簡化語意格式
                </div>
              </template>
            </el-upload>
            <div v-if="fileName" style="margin-top: 8px; font-size: 13px; color: #67c23a">
              ✓ 已選擇：{{ fileName }}
            </div>
          </el-tab-pane>

          <!-- 貼上 JSON -->
          <el-tab-pane label="貼上 JSON" name="text">
            <el-input
              v-model="rawJson"
              type="textarea"
              :rows="16"
              placeholder="貼上原始 PBI JSON（clientDataModel 格式或簡化語意格式皆可）"
              style="font-family: monospace; font-size: 12px"
            />
          </el-tab-pane>
        </el-tabs>

        <el-alert v-if="parseError" :title="parseError" type="error" show-icon :closable="false" style="margin: 12px 0 0" />

        <el-button
          type="primary"
          :loading="uploading"
          style="margin-top: 16px"
          @click="handleUpload"
        >
          上傳
        </el-button>
      </el-card>
    </el-col>

    <el-col :span="10">
      <el-card>
        <template #header>版本歷史</template>
        <el-table :data="versions" v-loading="loadingVersions" border>
          <el-table-column prop="model_version" label="版本" width="70" align="center" />
          <el-table-column label="上傳時間">
            <template #default="{ row }">{{ fmtDate(row.uploaded_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import http from '@/api/http'

interface Version { model_version: number; uploaded_at: string }

const inputMode = ref<'file' | 'text'>('file')
const fileContent = ref('')
const fileName = ref('')
const fileList = ref<UploadFile[]>([])
const rawJson = ref('')
const parseError = ref('')
const uploading = ref(false)
const versions = ref<Version[]>([])
const loadingVersions = ref(false)

function fmtDate(d: string) {
  return new Date(d).toLocaleString()
}

function handleFileChange(file: UploadFile) {
  const raw = file.raw
  if (!raw) return
  fileName.value = raw.name
  const reader = new FileReader()
  reader.onload = (e) => { fileContent.value = e.target?.result as string ?? '' }
  reader.readAsText(raw, 'utf-8')
}

async function handleUpload() {
  parseError.value = ''
  const source = inputMode.value === 'file' ? fileContent.value : rawJson.value

  if (!source.trim()) {
    parseError.value = inputMode.value === 'file' ? '請先選擇 .json 檔案' : '請貼上 JSON 內容'
    return
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(source)
  } catch {
    parseError.value = 'JSON 格式錯誤，請確認內容'
    return
  }

  uploading.value = true
  try {
    const res = await http.post('/model/upload', parsed)
    ElMessage.success(
      `上傳成功 — 版本 ${res.data.model_version}（${res.data.table_count} 張表，${res.data.relationship_count} 個關聯）`
    )
    fileContent.value = ''
    fileName.value = ''
    fileList.value = []
    rawJson.value = ''
    await loadVersions()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '上傳失敗')
  } finally {
    uploading.value = false
  }
}

async function loadVersions() {
  loadingVersions.value = true
  try {
    const res = await http.get('/model/versions')
    versions.value = res.data
  } finally {
    loadingVersions.value = false
  }
}

onMounted(loadVersions)
</script>
