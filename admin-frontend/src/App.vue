<template>
  <template v-if="route.name === 'login'">
    <router-view />
  </template>
  <AdminLayout v-else>
    <router-view />
  </AdminLayout>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import AdminLayout from '@/layouts/AdminLayout.vue'

const route = useRoute()
</script>

