<script setup lang="ts">
/** Feed/sensor health. Shape + text, never colour alone. */
import { computed } from 'vue'

const props = defineProps<{ ok: boolean | number | null; labelPrefix?: string }>()
const state = computed(() => (props.ok === null ? 'unknown' : props.ok ? 'ok' : 'bad'))
const text = computed(() =>
  state.value === 'ok' ? 'Reachable' : state.value === 'bad' ? 'Unreachable' : 'Unknown',
)
</script>

<template>
  <span class="health">
    <span class="health-dot" :class="`health-dot--${state}`" aria-hidden="true" />
    <span class="health-text">{{ labelPrefix }}{{ text }}</span>
  </span>
</template>

<style scoped>
.health { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.health-text { color: var(--color-text-muted); font-weight: 600; }
</style>
