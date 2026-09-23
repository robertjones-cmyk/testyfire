/**
 * Naive UI theme overrides driven by the Torch CSS variables.
 *
 * Naive UI cannot read `var(--x)` for every property, so the tokens are read
 * off the document at runtime and fed in as concrete colours. That keeps one
 * source of truth (theme.css) while still theming Naive components.
 */
import type { GlobalThemeOverrides } from 'naive-ui'

function token(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

export function buildThemeOverrides(): GlobalThemeOverrides {
  const brand = token('--color-brand', '#FF5B24')
  const brand600 = token('--color-brand-600', brand)
  const primary = token('--color-primary', '#101828')
  const textBody = token('--color-text-body', '#2e3638')
  const textMuted = token('--color-text-muted', '#5c6d70')
  const surface = token('--color-surface', '#ffffff')
  const page = token('--color-page', '#f8fafa')
  const sunken = token('--color-surface-sunken', '#f2f5f5')
  const border = token('--color-border', '#d5dcdd')
  const borderStrong = token('--color-border-strong', '#7c8d90')
  const divider = token('--color-divider', '#e3e7e8')
  const success = token('--color-success', '#1fa463')
  const warning = token('--color-warning', '#f2a33c')
  const error = token('--color-error', '#e5484d')
  const info = token('--color-blue', '#5b8def')

  return {
    common: {
      fontFamily: token('--font-sans', 'Manrope, sans-serif'),
      fontWeight: '500',
      fontWeightStrong: '700',
      primaryColor: primary,
      primaryColorHover: primary,
      primaryColorPressed: primary,
      primaryColorSuppl: primary,
      infoColor: info,
      successColor: success,
      warningColor: warning,
      errorColor: error,
      textColorBase: textBody,
      textColor1: token('--color-text-strong', primary),
      textColor2: textBody,
      textColor3: textMuted,
      baseColor: surface,
      bodyColor: page,
      cardColor: surface,
      modalColor: surface,
      popoverColor: surface,
      tableColor: surface,
      inputColor: surface,
      borderColor: border,
      dividerColor: divider,
      // Shape
      borderRadius: token('--radius-control', '8px'),
      borderRadiusSmall: token('--radius-tag', '4px'),
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      boxShadow2: token('--shadow-float', '0 12px 16px -4px rgba(0,0,0,.08)'),
    },
    Button: {
      // Primary button: navy in light, light in dark. Orange is an accent only.
      colorPrimary: token('--color-btn-primary-bg', primary),
      colorHoverPrimary: token('--color-btn-primary-bg', primary),
      colorPressedPrimary: token('--color-btn-primary-bg', primary),
      colorFocusPrimary: token('--color-btn-primary-bg', primary),
      textColorPrimary: token('--color-btn-primary-text', '#fff'),
      textColorHoverPrimary: token('--color-btn-primary-text', '#fff'),
      textColorPressedPrimary: token('--color-btn-primary-text', '#fff'),
      textColorFocusPrimary: token('--color-btn-primary-text', '#fff'),
      borderPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderHoverPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderFocusPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      borderPressedPrimary: `1px solid ${token('--color-btn-primary-bg', primary)}`,
      border: `1px solid ${borderStrong}`,
      textColor: textBody,
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      fontWeight: '600',
      borderRadiusMedium: token('--radius-control', '8px'),
    },
    Input: {
      border: `1px solid ${borderStrong}`,
      borderHover: `1px solid ${borderStrong}`,
      borderFocus: `1px solid ${brand600}`,
      boxShadowFocus: `0 0 0 2px ${brand600}40`,
      heightMedium: token('--control-height', '44px'),
      heightLarge: token('--control-height-lg', '48px'),
      borderRadius: token('--radius-control', '8px'),
      color: surface,
      textColor: textBody,
      placeholderColor: textMuted,
    },
    Card: {
      borderRadius: token('--radius-card', '12px'),
      color: surface,
      borderColor: border,
      titleFontWeight: '700',
    },
    DataTable: {
      thColor: sunken,
      thTextColor: token('--color-text-strong', primary),
      thFontWeight: '700',
      tdColor: surface,
      tdTextColor: textBody,
      borderColor: divider,
      borderRadius: token('--radius-card', '12px'),
      thPaddingMedium: '12px 16px',
      tdPaddingMedium: '12px 16px',
    },
    Drawer: { color: surface, textColor: textBody },
    Tabs: {
      tabTextColorActiveLine: token('--color-text-strong', primary),
      tabTextColorLine: textMuted,
      barColor: brand,
      tabFontWeightActive: '700',
    },
    Select: { peers: { InternalSelection: { border: `1px solid ${borderStrong}` } } },
    Tag: { borderRadius: token('--radius-tag', '4px'), heightMedium: '24px' },
    Switch: { railColorActive: brand, loadingColor: brand },
    Progress: { fillColor: brand, fillColorInfo: info },
    Dialog: { borderRadius: token('--radius-card', '12px') },
    Alert: { borderRadius: token('--radius-card', '12px') },
    Message: { borderRadius: token('--radius-control', '8px') },
  }
}
