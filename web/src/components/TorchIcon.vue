<script setup lang="ts">
/** Thin line icon. Decorative by default (aria-hidden); pass `label` to expose it. */
import { computed } from 'vue'
import { icons, type IconName } from '@/icons'

const props = withDefaults(defineProps<{ name: IconName; size?: number; label?: string }>(), {
  size: 18,
})
const component = computed(() => icons[props.name])
</script>

<template>
  <component
    :is="component"
    :size="size"
    :stroke-width="1.75"
    :aria-hidden="label ? undefined : 'true'"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    focusable="false"
  />
</template>
