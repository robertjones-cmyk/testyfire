<script setup lang="ts">
/**
 * Idle-session warning.
 *
 * Appears `idle_warning_seconds` before the 30-minute idle timeout. It is a
 * real dialog: focus moves in, Esc extends (the safe action, since dismissing
 * should not log you out), and the countdown is announced politely rather than
 * hammering a live region every second.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NModal } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const secondsLeft = ref<number | null>(null)
const extendButton = ref<InstanceType<typeof NButton> | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const visible = computed(() => secondsLeft.value !== null && secondsLeft.value > 0)
/** Announced once a minute rather than every tick. */
const announced = computed(() =>
  secondsLeft.value === null ? '' : `Session expires in about ${Math.ceil(secondsLeft.value / 60)} minute(s).`,
)

function tick() {
  if (!auth.isAuthenticated || !auth.idleExpiresAt) {
    secondsLeft.value = null
    return
  }
  const remaining = (new Date(auth.idleExpiresAt).getTime() - Date.now()) / 1000
  secondsLeft.value = remaining <= auth.idleWarningSeconds ? Math.max(0, Math.round(remaining)) : null
}

async function extend() {
  await auth.extendSession()
  secondsLeft.value = null
}

async function logoutNow() {
  await auth.logout()
  window.location.assign('/login')
}

watch(visible, async (isVisible) => {
  if (isVisible) {
    await Promise.resolve()
    // Move focus into the dialog so a keyboard user lands on the safe action.
    extendButton.value?.$el?.focus?.()
  }
})

onMounted(() => {
  timer = setInterval(tick, 1000)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <NModal
    :show="visible"
    preset="card"
    role="alertdialog"
    :mask-closable="false"
    :closable="false"
    aria-labelledby="idle-title"
    aria-describedby="idle-body"
    style="max-width: 440px"
    @esc="extend"
  >
    <template #header>
      <span id="idle-title">Still there?</span>
    </template>
    <p id="idle-body">
      Your session will end in <strong>{{ secondsLeft }} seconds</strong> because of inactivity.
      Choose “Stay signed in” to continue.
    </p>
    <p class="visually-hidden" role="status" aria-live="polite">{{ announced }}</p>
    <template #footer>
      <div class="idle__actions">
        <NButton @click="logoutNow">Log out now</NButton>
        <NButton ref="extendButton" type="primary" @click="extend">Stay signed in</NButton>
      </div>
    </template>
  </NModal>
</template>

<style scoped>
.idle__actions { display: flex; gap: 12px; justify-content: flex-end; }
</style>
