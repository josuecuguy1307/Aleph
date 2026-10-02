/**
 * Tailwind v4 preset. Apps consume via `@import` of this file's path
 * inside their main CSS, then enable @theme via the standard v4 setup.
 *
 * Re-export of token names so apps can reference `bg-surface` etc.
 */
export const tokens = {
  colors: {
    background: 'var(--color-background)',
    'background-secondary': 'var(--color-background-secondary)',
    surface: 'var(--color-surface)',
    'surface-hover': 'var(--color-surface-hover)',
    'surface-active': 'var(--color-surface-active)',
    'surface-muted': 'var(--color-surface-muted)',
    border: 'var(--color-border)',
    'border-muted': 'var(--color-border-muted)',
    'border-subtle': 'var(--color-border-subtle)',
    accent: 'var(--color-accent)',
    'accent-hover': 'var(--color-accent-hover)',
    'accent-muted': 'var(--color-accent-muted)',
    'text-primary': 'var(--color-text-primary)',
    'text-secondary': 'var(--color-text-secondary)',
    'text-muted': 'var(--color-text-muted)',
    success: 'var(--color-success)',
    warning: 'var(--color-warning)',
    error: 'var(--color-error)',
  },
} as const;
