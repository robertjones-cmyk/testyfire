<script setup lang="ts">
/**
 * Event status chip.
 *
 * Never colour alone: every chip carries an icon AND a text label, because red
 * and orange are hard to tell apart for many colour-blind users. Chip text uses
 * the dark 600/700 token shades so it clears 4.5:1 on the tinted background
 * (verified by scripts/check_contrast.py).
 */
import { computed } from 'vue'
import TorchIcon from './TorchIcon.vue'
import type { EventStatus } from '@/api'
import type { IconName } from '@/icons'

const props = defineProps<{ status: EventStatus; demo?: boolean | number }>()

const config = computed<{ cls: string; icon: IconName; label: string }>(() => {
  switch (props.status) {
    case 'verified':
      return { cls: 'chip--verified', icon: 'check-shield', label: 'Verified' }
    case 'sensor_only':
      return { cls: 'chip--sensor', icon: 'sensor-color', label: 'Sensor only' }
    default:
      return { cls: 'chip--possible', icon: 'question-circle', label: 'Possible smoke' }
  }
})
</script>

<template>
  <span class="chips">
    <span class="chip" :class="config.cls">
      <TorchIcon :name="config.icon" :size="14" />
      <span>{{ config.label }}</span>
    </span>
    <span v-if="demo" class="chip chip--demo" title="Created by the demo fire scenario">
      <TorchIcon name="alert-triangle" :size="14" />
      <span>DEMO</span>
    </span>
  </span>
</template>

<style scoped>
.chips { display: inline-flex; gap: 6px; flex-wrap: wrap; }
</style>
