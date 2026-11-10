<template>
  <div>
    <el-empty v-if="!model.length" description="還沒有查詢模式（使用者可以查整個模型）" :image-size="60" />

    <template v-else>
      <div class="toolbar">
        <el-button text size="small" @click="expandAll">全部展開</el-button>
        <el-button text size="small" @click="collapseAll">全部收合</el-button>
      </div>
      <el-collapse v-model="open" class="items">
        <el-collapse-item v-for="(m, i) in model" :key="itemKey(m)" :name="itemKey(m)">
          <template #title>
            <div class="item-title">
              <span>
                <b>{{ m.name || '（未命名模式）' }}</b>
                <span class="summary">
                  {{ m.tables.length ? `${m.tables.length} 張表` : '不限資料表' }}・{{ m.filters.length }} 條額外條件
                </span>
              </span>
              <span @click.stop>
                <el-popconfirm title="確定刪除這個模式？" confirm-button-type="danger" @confirm="model.splice(i, 1)">
                  <template #reference><el-button text type="danger" size="small">刪除</el-button></template>
                </el-popconfirm>
              </span>
            </div>
          </template>

          <el-form label-width="130px" class="item-body">
            <el-form-item label="模式名稱" required>
              <el-input v-model="m.name" placeholder="例：摘要模式" />
              <div class="hint">有多個模式時，AI 會列出名稱和說明請使用者選一個。</div>
            </el-form-item>
            <el-form-item label="說明">
              <el-input v-model="m.description" placeholder="（選填）例：只看高階彙總，不含明細" />
            </el-form-item>
            <el-form-item label="可查詢的資料表">
              <TagInput v-model="m.tables" :options="tables" placeholder="不選 = 不限制，整個模型都能查" />
            </el-form-item>
            <el-form-item label="額外篩選條件">
              <FilterRulesEditor v-model="m.filters" :tables="tables" style="width: 100%" />
              <div class="hint">選這個模式時一律套用，疊加在「篩選規則」分頁的結果之上。</div>
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </template>

    <el-button type="primary" plain @click="add(normalizeMode({}))">＋ 新增查詢模式</el-button>
  </div>
</template>

<script setup lang="ts">
import FilterRulesEditor from './FilterRulesEditor.vue'
import TagInput from './TagInput.vue'
import { normalizeMode, type QueryMode } from './types'
import { useCollapse } from './useCollapse'

const model = defineModel<QueryMode[]>({ required: true })
defineProps<{ tables: string[] }>()
// 識別碼（mode_id）新增時自動產生，表單上不顯示；真的要改請切到 JSON 模式
const { open, add, expandAll, collapseAll, itemKey } = useCollapse(model)
</script>

<style scoped>
@import './editor.css';
</style>
