import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center text-center">
      <p className="text-4xl font-semibold text-fg">404</p>
      <p className="mt-2 text-muted">This page could not be found.</p>
      <Link to="/" className="mt-4 text-brand-400 underline hover:text-brand-500">
        Back to dashboard
      </Link>
    </div>
  )
}
