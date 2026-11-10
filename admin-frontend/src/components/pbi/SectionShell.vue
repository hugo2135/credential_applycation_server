<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px">
      <span v-if="schemaHint && !section.state.jsonMode" style="font-size: 12px; color: var(--el-color-warning)">
        {{ schemaHint }}
      </span>
      <span v-else />
      <el-switch
        :model-value="section.state.jsonMode"
        active-text="以 JSON 編輯（進階）"
        @change="(on: string | number | boolean) => section.setJsonMode(Boolean(on))"
      />
    </div>

    <el-input
      v-if="section.state.jsonMode"
      v-model="section.state.text"
      type="textarea"
      :rows="18"
      class="json-input"
      placeholder="[]"
    />
    <slot v-else />

    <el-alert
      v-if="section.state.errors.length"
      type="error"
      :closable="false"
      show-icon
      style="margin-top: 12px"
    >
      <template #title>
        <div v-for="(e, i) in section.state.errors" :key="i">{{ e }}</div>
      </template>
    </el-alert>

    <el-button type="primary" :loading="section.state.saving" style="margin-top: 16px" @click="section.save()">
      儲存
    </el-button>
  </div>
</template>

<script setup lang="ts">
import type { useConfigSection } from './useConfigSection'

defineProps<{
  section: ReturnType<typeof useConfigSection<any>>
  schemaHint?: string
}>()
</script>

<style scoped>
.json-input :deep(textarea) {
  font-family: monospace;
  font-size: 12px;
}
</style>
