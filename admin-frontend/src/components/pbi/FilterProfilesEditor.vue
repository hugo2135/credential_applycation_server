<template>
  <div>
    <el-empty v-if="!model.length" description="還沒有篩選規則" :image-size="60" />

    <template v-else>
      <div class="toolbar">
        <el-button text size="small" @click="expandAll">全部展開</el-button>
        <el-button text size="small" @click="collapseAll">全部收合</el-button>
      </div>
      <el-collapse v-model="open" class="items">
        <el-collapse-item v-for="(p, i) in model" :key="itemKey(p)" :name="itemKey(p)">
          <template #title>
            <div class="item-title">
              <span>
                <b>{{ p.name || '（未命名規則）' }}</b>
                <el-tag size="small" :type="p.alwaysApply ? 'warning' : 'info'" style="margin-left: 8px">
                  {{ p.alwaysApply ? '每次查詢都套用' : '提到關鍵字才套用' }}
                </el-tag>
                <span class="summary">
                  {{ p.filters.length }} 條條件<template v-if="!p.alwaysApply && p.contextKeywords.length">
                    ・關鍵字：{{ p.contextKeywords.join('、') }}</template>
                </span>
              </span>
              <span @click.stop>
                <el-popconfirm title="確定刪除這組規則？" confirm-button-type="danger" @confirm="model.splice(i, 1)">
                  <template #reference><el-button text type="danger" size="small">刪除</el-button></template>
                </el-popconfirm>
              </span>
            </div>
          </template>

          <el-form label-width="130px" class="item-body">
            <el-form-item label="規則名稱" required>
              <el-input v-model="p.name" placeholder="例：排除退貨單" />
            </el-form-item>
            <el-form-item label="說明">
              <el-input v-model="p.description" placeholder="（選填）給其他管理員看的備註" />
            </el-form-item>

            <el-form-item label="什麼時候套用">
              <el-radio-group v-model="p.alwaysApply">
                <el-radio :value="true">每次查詢都套用（預設篩選）</el-radio>
                <el-radio :value="false">使用者的問題提到特定關鍵字時才套用</el-radio>
              </el-radio-group>
            </el-form-item>

            <template v-if="!p.alwaysApply">
              <el-form-item label="觸發關鍵字">
                <TagInput v-model="p.contextKeywords" placeholder="例：退貨、退款，輸入後按 Enter" />
                <div class="hint">使用者的問題裡出現任一個詞，就套用這組規則。</div>
              </el-form-item>
              <el-form-item label="跟預設篩選的關係">
                <el-radio-group v-model="p.overrideDefaults">
                  <el-radio :value="false">疊加在預設篩選上</el-radio>
                  <el-radio :value="true">取代所有預設篩選</el-radio>
                </el-radio-group>
                <div class="hint">
                  例：預設「排除退貨單」，但使用者問「退貨有幾筆」時要取消那條，就把這組設成「取代」。
                </div>
              </el-form-item>
            </template>

            <el-form-item label="篩選條件">
              <FilterRulesEditor v-model="p.filters" :tables="tables" style="width: 100%" />
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </template>

    <el-button type="primary" plain @click="add(normalizeProfile({}))">＋ 新增一組篩選規則</el-button>
  </div>
</template>

<script setup lang="ts">
import FilterRulesEditor from './FilterRulesEditor.vue'
import TagInput from './TagInput.vue'
import { normalizeProfile, type FilterProfile } from './types'
import { useCollapse } from './useCollapse'

const model = defineModel<FilterProfile[]>({ required: true })
defineProps<{ tables: string[] }>()
// 識別碼（filterId）新增時自動產生，表單上不顯示；真的要改請切到 JSON 模式
const { open, add, expandAll, collapseAll, itemKey } = useCollapse(model)
</script>

<style scoped>
@import './editor.css';
</style>
