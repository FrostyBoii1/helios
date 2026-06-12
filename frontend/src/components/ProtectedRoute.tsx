// Route guard: redirects unauthenticated users to /login and optionally
// enforces role-based access for a route subtree.

import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import type { RoleName } from '@/types'

interface ProtectedRouteProps {
  /** If provided, the user's role must be in this list. */
  allowedRoles?: RoleName[]
}

export function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center text-slate-500">
        Loading…
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  if (allowedRoles && !allowedRoles.includes(user.role.name)) {
    return <Navigate to="/" replace />
  }

  return <Outlet />
}
