import { useState } from 'react'
import type { FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { ContourBackground } from '@/components/ContourBackground'
import { ApiError } from '@/lib/api'

interface LocationState {
  from?: { pathname: string }
}

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as LocationState | null)?.from?.pathname ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Incorrect email or password.')
      } else {
        setError('Unable to sign in. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="relative isolate flex min-h-screen items-center justify-center px-4">
      <ContourBackground />
      <form
        onSubmit={handleSubmit}
        className="relative z-10 w-full max-w-sm rounded-lg border border-white/10 bg-surface/70 p-6 shadow-2xl shadow-black/50 ring-1 ring-white/5 backdrop-blur-xl"
      >
        <div className="mb-1 flex items-center gap-2">
          <span className="h-5 w-5 rounded-sm bg-brand-500" aria-hidden />
          <h1 className="text-xl font-semibold tracking-tight text-fg">
            SUN<span className="text-brand-500">CENTRAL</span>
          </h1>
        </div>
        <p className="mb-6 text-sm text-muted">Operations platform — sign in</p>

        {error && (
          <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        <label className="mb-3 block text-sm">
          <span className="mb-1 block font-medium text-fg">Email</span>
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="input"
          />
        </label>

        <label className="mb-6 block text-sm">
          <span className="mb-1 block font-medium text-fg">Password</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="input"
          />
        </label>

        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
