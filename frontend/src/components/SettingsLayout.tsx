// Settings area shell (admin-only). Renders a left sub-nav + the active settings
// page in its outlet. This is the FIRST Settings area in the app — more panels
// (users, labels, …) can be added to SETTINGS_NAV later. Mounted inside AppLayout
// so the main top bar persists; the whole /settings route group is admin-gated in
// App.tsx, and every backed API (hardware) re-checks admin server-side.

import { NavLink, Outlet } from 'react-router-dom'

interface SettingsNavItem {
  to: string
  label: string
}

const SETTINGS_NAV: SettingsNavItem[] = [{ to: '/settings/hardware', label: 'Hardware' }]

export function SettingsLayout() {
  return (
    <div>
      <h1 className="mb-5 text-2xl font-semibold text-fg">Settings</h1>
      <div className="flex flex-col gap-6 sm:flex-row">
        <nav className="flex flex-wrap gap-1 sm:w-44 sm:flex-col">
          {SETTINGS_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm transition-colors ${
                  isActive
                    ? 'bg-elevated font-medium text-brand-400'
                    : 'text-muted hover:text-fg'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
