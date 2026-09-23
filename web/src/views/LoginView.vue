<script setup lang="ts">
/**
 * Login.
 *
 * Follows the Torch layout (centred white card on the light-grey page, orange
 * logo tile, "Log in to your account", Email/Password, full-width button) but
 * deliberately DIFFERS so it can never be mistaken for, or used as, a copy of
 * the real Torch login:
 *   - a visible "Camera Fusion Prototype · internal" label under the logo
 *   - a different page title
 *   - no Google/Okta buttons (no fake SSO)
 *   - no "Forgot password" link (admins reset with `python -m app create-admin --force`)
 *   - no "Remember for 30 days" (session rules are fixed server-side)
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NInput } from 'naive-ui'
import LogoTile from '@/components/LogoTile.vue'
import { useAuthStore } from '@/stores/auth'
import { ApiError } from '@/api'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const submitting = ref(false)
const errorMessage = ref('')
const fieldErrors = ref<{ email?: string; password?: string }>({})

const hasError = computed(() => errorMessage.value !== '')

async function submit() {
  fieldErrors.value = {}
  errorMessage.value = ''

  if (!email.value.trim()) fieldErrors.value.email = 'Enter your email address'
  if (!password.value) fieldErrors.value.password = 'Enter your password'
  if (Object.keys(fieldErrors.value).length) return

  submitting.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    await router.push(next)
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : 'Could not reach the server. Is it running?'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main id="main-content" class="page" tabindex="-1">
    <div class="card card--float login">
      <div class="login__head">
        <LogoTile :size="48" />
        <p class="login__badge">Camera Fusion Prototype · internal</p>
      </div>

      <h1 class="login__title">Log in to your account</h1>
      <p class="login__sub muted">Torch Camera Fusion (Prototype)</p>

      <!-- role=alert so the failure is announced without moving focus. -->
      <div v-if="hasError" class="login__error" role="alert">{{ errorMessage }}</div>

      <form class="login__form" novalidate @submit.prevent="submit">
        <div class="field">
          <label class="field__label" for="login-email">Email</label>
          <!-- The id MUST go through input-props: Naive UI puts a bare `id`
               on its wrapper div, which leaves <label for> pointing at a
               non-form element and the field effectively unlabelled. -->
          <NInput
            v-model:value="email"
            type="text"
            size="large"
            placeholder=""
            autocomplete="username"
            :input-props="{
              id: 'login-email',
              name: 'email',
              inputmode: 'email',
              'aria-describedby': fieldErrors.email ? 'login-email-error' : undefined,
              'aria-invalid': fieldErrors.email ? 'true' : undefined,
            }"
          />
          <p v-if="fieldErrors.email" id="login-email-error" class="field__error">{{ fieldErrors.email }}</p>
        </div>

        <div class="field">
          <label class="field__label" for="login-password">Password</label>
          <NInput
            v-model:value="password"
            type="password"
            size="large"
            placeholder=""
            show-password-on="click"
            autocomplete="current-password"
            :input-props="{
              id: 'login-password',
              name: 'password',
              'aria-describedby': fieldErrors.password ? 'login-password-error' : undefined,
              'aria-invalid': fieldErrors.password ? 'true' : undefined,
            }"
          />
          <p v-if="fieldErrors.password" id="login-password-error" class="field__error">
            {{ fieldErrors.password }}
          </p>
        </div>

        <NButton attr-type="submit" type="primary" size="large" block :loading="submitting">
          Log in
        </NButton>
      </form>

      <p class="login__note muted">
        Accounts are local to this prototype. An admin creates and resets them from the
        command line.
      </p>
    </div>
  </main>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  background: var(--color-page);
}
.page:focus { outline: none; }

.login { width: 100%; max-width: 420px; padding: 32px; }
.login__head { display: flex; flex-direction: column; align-items: center; gap: 12px; }
.login__badge {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--color-text-muted);
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-pill);
  padding: 4px 12px;
}
.login__title { text-align: center; margin-top: 20px; font-size: 22px; }
.login__sub { text-align: center; margin-bottom: 20px; font-size: 13px; }

.login__error {
  background: oklch(94% .04 28.54);
  color: var(--color-error-text);
  border: 1px solid oklch(80% .1 28.54);
  border-radius: var(--radius-control);
  padding: 10px 12px;
  font-size: 13px;
  margin-bottom: 16px;
}
:global([data-theme='dark']) .login__error {
  background: oklch(30% .07 28.54);
  border-color: oklch(45% .12 28.54);
}

.login__form { display: flex; flex-direction: column; gap: 16px; }
.field__label {
  display: block;
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-strong);
  margin-bottom: 6px;
}
.field__error { margin: 6px 0 0; font-size: 12px; color: var(--color-error-text); font-weight: 600; }
.login__note { margin: 20px 0 0; font-size: 12px; text-align: center; }
</style>
