/**
 * Automated accessibility tests: axe-core on every screen, in BOTH themes.
 *
 * CI fails on any `serious` or `critical` violation. The keyboard and
 * screen-reader checks that automation cannot do are in ACCESSIBILITY.md as a
 * manual checklist.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const EMAIL = process.env.TORCH_TEST_EMAIL ?? 'admin@torchsystems.com'
const PASSWORD = process.env.TORCH_TEST_PASSWORD ?? 'prototype-demo-password'

const SCREENS = [
  { name: 'Map', path: '/' },
  { name: 'Events', path: '/events' },
  { name: 'Sensors', path: '/sensors' },
  { name: 'Cameras', path: '/cameras' },
  { name: 'Dashboard', path: '/dashboard' },
  { name: 'Settings', path: '/settings' },
]

const THEMES = ['light', 'dark'] as const

async function setTheme(page: Page, theme: 'light' | 'dark') {
  await page.evaluate((value) => {
    localStorage.setItem('app-theme', value)
    document.documentElement.setAttribute('data-theme', value)
  }, theme)
}

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Log in' }).click()
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 20_000 })
}

async function scan(page: Page, context: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    // The Mapbox canvas is third-party and unreachable by keyboard by nature;
    // everything in it is duplicated in the synced list panel, which IS scanned.
    .exclude('.mapboxgl-canvas-container')
    .exclude('.mapboxgl-control-container')
    .analyze()

  const blocking = results.violations.filter(
    (violation) => violation.impact === 'serious' || violation.impact === 'critical',
  )
  if (blocking.length) {
    console.error(
      `\n${context} — ${blocking.length} blocking violation(s):\n` +
        blocking
          .map((v) => `  [${v.impact}] ${v.id}: ${v.help}\n    ${v.nodes.map((n) => n.target.join(' ')).join('\n    ')}`)
          .join('\n'),
    )
  }
  expect(blocking, `${context} must have no serious or critical a11y violations`).toEqual([])
}

test.describe('accessibility', () => {
  for (const theme of THEMES) {
    test(`login screen — ${theme}`, async ({ page }) => {
      await page.goto('/login')
      await setTheme(page, theme)
      await page.reload()
      await scan(page, `Login (${theme})`)
    })
  }

  for (const theme of THEMES) {
    for (const screen of SCREENS) {
      test(`${screen.name} — ${theme}`, async ({ page }) => {
        await login(page)
        await setTheme(page, theme)
        await page.goto(screen.path)
        await page.waitForLoadState('networkidle')
        await scan(page, `${screen.name} (${theme})`)
      })
    }
  }

  test('event drawer is accessible and keyboard operable', async ({ page }) => {
    await login(page)
    await page.goto('/events')
    await page.waitForLoadState('networkidle')

    const firstRow = page.locator('tbody tr').first()
    if ((await firstRow.count()) === 0) test.skip(true, 'no events to open yet')

    await firstRow.click()
    await expect(page.getByRole('dialog').or(page.locator('.n-drawer'))).toBeVisible()
    await scan(page, 'Events with drawer open')

    // Esc closes the drawer.
    await page.keyboard.press('Escape')
    await expect(page.locator('.n-drawer')).toBeHidden({ timeout: 5000 })
  })
})

test.describe('structure', () => {
  test('page language is English and zooming is not blocked', async ({ page }) => {
    await page.goto('/login')
    expect(await page.locator('html').getAttribute('lang')).toBe('en')

    const viewport = await page.locator('meta[name="viewport"]').getAttribute('content')
    expect(viewport).not.toContain('user-scalable=no')
    expect(viewport).not.toContain('maximum-scale=1')
  })

  test('skip link is the first focusable element and works', async ({ page }) => {
    await login(page)
    await page.goto('/events')
    await page.keyboard.press('Tab')

    const focused = page.locator(':focus')
    await expect(focused).toHaveText(/skip to main content/i)

    await page.keyboard.press('Enter')
    await expect(page.locator('#main-content')).toBeVisible()
  })

  test('layout survives 320px width without horizontal scrolling', async ({ page }) => {
    await login(page)
    await page.setViewportSize({ width: 320, height: 800 })
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, 'no horizontal page scroll at 320px').toBeLessThanOrEqual(2)
  })

  test('status is never carried by colour alone', async ({ page }) => {
    await login(page)
    await page.goto('/events')
    await page.waitForLoadState('networkidle')

    const chips = page.locator('.chip')
    if ((await chips.count()) === 0) test.skip(true, 'no events yet')

    // Every chip carries readable text as well as its colour.
    for (let index = 0; index < Math.min(await chips.count(), 5); index += 1) {
      await expect(chips.nth(index)).toHaveText(/verified|possible smoke|sensor only|demo/i)
    }
  })

  test('the EMPTY table state is accessible too', async ({ page }) => {
    // Regression guard: an empty table renders Naive UI's empty state, whose
    // default text colour fails AA on our dark surface. Seeded local data hides
    // this, so filter down to nothing and scan that state deliberately.
    // Log in ONCE: a second call would navigate to /login while already
    // authenticated, get redirected away, and never find the email field.
    await login(page)

    for (const theme of THEMES) {
      await setTheme(page, theme)
      await page.goto('/events')
      await page.waitForLoadState('networkidle')

      // Filter Category to Security. Every event this system raises is Fire, so
      // the table is guaranteed empty whatever data happens to be present.
      // Scoped to the filters card: the sidebar has a select too.
      await page.locator('.filters .n-select').nth(2).click()
      await page.getByText('Security', { exact: true }).click()

      await expect(page.locator('.n-empty').first()).toBeVisible()
      await scan(page, `Events empty state (${theme})`)
    }
  })

  test('live updates can be paused so the table does not move', async ({ page }) => {
    await login(page)
    await page.goto('/events')
    const toggle = page.getByLabel('Pause live updates')
    await expect(toggle).toBeVisible()
    await toggle.click()
    await expect(page.getByText(/Paused — the table will not move/i)).toBeVisible()
  })
})
