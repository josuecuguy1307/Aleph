---
schemaVersion: 1
name: app-shell-navigation
description: >
  Designs product app shells with navigation hierarchy, headers, search,
  breadcrumbs, command surfaces, responsive sidebars, and dense but readable
  work areas. Use for SaaS dashboards, admin consoles, CRM/ERP tools,
  developer tools, and internal operations products.
aliases: [app-shell, sidebar, navigation, dashboard-shell, admin-shell, ia]
dependencies: [artifact-composition, responsive-layout, accessibility-states]
validationHints:
  - shell has persistent navigation plus a clear active destination
  - content area includes filters data actions and non-happy states
trigger:
  providers: ['*']
  scope: system
disable_model_invocation: false
user_invocable: true
---

## Shell Anatomy

A serious app shell has five zones:

1. Primary navigation: product areas, grouped and ordered by user workflow.
2. Header: page title, breadcrumbs or context, search, notifications, account.
3. Work area: the main task surface, not a marketing hero.
4. Detail/action area: filters, inspector, drawer, side panel, or action bar.
5. Status layer: loading, empty, error, sync, permission, or connection state.

Do not spend the first viewport on a sales headline when the user asked for a
tool, dashboard, admin console, CRM, or operational product.

## Navigation Rules

- Keep sidebar labels concrete: Overview, Pipeline, Accounts, Reports,
  Settings. Avoid vague labels like Explore or Magic.
- Show one active destination with shape/weight and color.
- Use section headers only when there are 6+ items.
- Put destructive/admin items away from primary task navigation.
- Mobile/tablet shells should collapse navigation into a drawer or top menu,
  while preserving the current page title and primary action.

## Work Area Density

Operational shells should include enough real structure:

- KPI or status strip with units and trend.
- Filters/search/sort where records are shown.
- At least one chart, table, list, kanban, timeline, or inspector.
- Real rows/cards with owner, status, date, amount, severity, or next action.
- Empty/loading/error state for one major panel.

## Implementation Notes

- Use CSS variables or `TWEAK_DEFAULTS` for shell width, accent, density,
  radius, and theme.
- Keep sidebar width stable; hover and active states must not shift layout.
- Buttons and nav items should be at least 40px tall on desktop, 44px on touch.
- If using a scaffolded app shell, adapt the data and page structure before
  previewing; the copied shell is a starting point, not the final artifact.
