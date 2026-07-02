<template>
  <el-row :gutter="16">
    <el-col :span="14">
      <el-card>
        <template #header>上傳新版語意模型</template>
        <el-form label-position="top">
          <el-form-item label="Relationships JSON">
            <el-input
              v-model="relationships"
              type="textarea"
              :rows="10"
              placeholder='{"tables": {...}}'
              @input="parseError = ''"
            />
          </el-form-item>
          <el-form-item label="Tables JSON（陣列）">
            <el-input
              v-model="tables"
              type="textarea"
              :rows="10"
              placeholder='[{"name": "TableA", ...}]'
              @input="parseError = ''"
            />
          </el-form-item>
          <el-alert v-if="parseError" :title="parseError" type="error" show-icon :closable="false" style="margin-bottom: 12px" />
          <el-button type="primary" :loading="uploading" @click="handleUpload">上傳</el-button>
        </el-form>
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
import http from '@/api/http'

interface Version { model_version: number; uploaded_at: string }

const relationships = ref('')
const tables = ref('')
const parseError = ref('')
const uploading = ref(false)
const versions = ref<Version[]>([])
const loadingVersions = ref(false)

function fmtDate(d: string) {
  return new Date(d).toLocaleString()
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

async function handleUpload() {
  let parsedRel: object, parsedTables: unknown[]
  try {
    parsedRel = JSON.parse(relationships.value)
  } catch {
    parseError.value = 'Relationships JSON 格式錯誤'
    return
  }
  try {
    parsedTables = JSON.parse(tables.value)
    if (!Array.isArray(parsedTables)) throw new Error()
  } catch {
    parseError.value = 'Tables JSON 格式錯誤（需為陣列）'
    return
  }

  uploading.value = true
  try {
    const res = await http.post('/model/upload', { relationships: parsedRel, tables: parsedTables })
    ElMessage.success(`上傳成功，版本 ${res.data.model_version}`)
    relationships.value = ''
    tables.value = ''
    await loadVersions()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail ?? '上傳失敗')
  } finally {
    uploading.value = false
  }
}

onMounted(loadVersions)
</script>
