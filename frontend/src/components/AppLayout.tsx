// Authenticated app shell: top bar with user/role + logout, content outlet.
// Navigation will expand as feature pages land (jobs, calendar, tasks, etc.).

import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canManageHardware, canReviewImports } from '@/auth/permissions'
import { ContourBackground } from '@/components/ContourBackground'

interface NavItem {
  to: string
  label: string
  end: boolean
  adminOnly?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/customers', label: 'Customers', end: false },
  { to: '/jobs', label: 'Jobs', end: false },
  { to: '/schedule', label: 'Schedule', end: false },
  { to: '/tasks', label: 'Tasks', end: false },
  { to: '/imports', label: 'Imports', end: false, adminOnly: true },
]

export function AppLayout() {
  const { user, logout } = useAuth()
  const navItems = NAV_ITEMS.filter(
    (item) => !item.adminOnly || canReviewImports(user?.role.name),
  )
  // Settings is admin-only (the gear is hidden for everyone else; the route + every
  // hardware API additionally enforce admin server-side).
  const showSettings = canManageHardware(user?.role.name)

  return (
    <div className="min-h-screen">
      {/* Restrained ambient variant of the /login contour system — one shared
          visual language across the app. Fixed + z-index:-1, so it sits behind
          all content. Mounted once at the shell so it persists across in-app
          navigation (no per-page re-init). */}
      <ContourBackground variant="ambient" />
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Wordmark />
            <nav className="flex flex-wrap items-center gap-1 text-sm">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    `rounded-md px-3 py-1.5 transition-colors ${
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
          </div>
          <div className="flex items-center gap-3 text-sm">
            {showSettings && (
              <NavLink
                to="/settings/hardware"
                aria-label="Settings"
                title="Settings"
                className={({ isActive }) =>
                  `rounded-md p-1.5 transition-colors ${
                    isActive ? 'text-brand-400' : 'text-muted hover:text-fg'
                  }`
                }
              >
                <GearIcon />
              </NavLink>
            )}
            {user && (
              <span className="text-muted">
                {user.full_name}
                <span className="ml-2 rounded bg-elevated px-2 py-0.5 text-xs uppercase tracking-wide text-faint">
                  {user.role.name}
                </span>
              </span>
            )}
            <button
              onClick={logout}
              className="rounded-md border border-line-strong px-3 py-1 text-fg transition-colors hover:bg-elevated"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}

// Text wordmark (no image asset this pass). "SUN" white, "CENTRAL" orange,
// echoing the flyer; a small square mark stands in for the logo.
function Wordmark() {
  return (
    <Link to="/" className="flex items-center gap-2">
      <span className="h-5 w-5 rounded-sm bg-brand-500" aria-hidden />
      <span className="text-lg font-semibold tracking-tight text-fg">
        SUN<span className="text-brand-500">CENTRAL</span>
        <span className="ml-2 text-sm font-normal text-faint">Ops</span>
      </span>
    </Link>
  )
}

// Inline cog (no icon library). Admin-only Settings access point in the top bar.
function GearIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}
