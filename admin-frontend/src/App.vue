<template>
  <AdminLayout v-if="route.meta.layout === 'admin'">
    <router-view />
  </AdminLayout>
  <UserLayout v-else-if="route.meta.layout === 'user'">
    <router-view />
  </UserLayout>
  <router-view v-else />
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import AdminLayout from '@/layouts/AdminLayout.vue'
import UserLayout from '@/layouts/UserLayout.vue'

const route = useRoute()
</script>
