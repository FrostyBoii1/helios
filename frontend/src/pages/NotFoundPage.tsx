import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center text-center">
      <p className="text-4xl font-semibold text-slate-800">404</p>
      <p className="mt-2 text-slate-500">This page could not be found.</p>
      <Link to="/" className="mt-4 text-slate-700 underline">
        Back to dashboard
      </Link>
    </div>
  )
}
