import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { canWriteCustomers } from '@/auth/permissions'
import { CustomerCreateModal } from '@/components/CustomerCreateModal'
import { useCustomers } from '@/hooks/useCustomers'

const PAGE_SIZE = 25

export function CustomersListPage() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [searchInput, setSearchInput] = useState('')
  const [q, setQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [showCreate, setShowCreate] = useState(false)

  // Debounce the search box; reset to the first page on a new query.
  useEffect(() => {
    const handle = setTimeout(() => {
      setQ(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [searchInput])

  const { data, isLoading, isError, isFetching } = useCustomers({
    q: q || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const total = data?.total ?? 0
  const items = data?.items ?? []
  const pageInfo = useMemo(() => {
    if (total === 0) return '0 customers'
    const start = offset + 1
    const end = Math.min(offset + PAGE_SIZE, total)
    return `${start}–${end} of ${total}`
  }, [offset, total])

  const canCreate = canWriteCustomers(user?.role.name)

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold text-slate-800">Customers</h1>
        {canCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-md bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
          >
            New customer
          </button>
        )}
      </div>

      <input
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Search name, email, phone, suburb, postcode…"
        className="mb-4 w-full rounded-md border border-slate-300 px-3 py-2 focus:outline-none focus:ring-1 focus:ring-slate-400"
      />

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Phone</th>
              <th className="px-4 py-2 font-medium">Suburb</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <RowMessage>Loading customers…</RowMessage>
            ) : isError ? (
              <RowMessage className="text-red-600">Failed to load customers.</RowMessage>
            ) : items.length === 0 ? (
              <RowMessage>
                {q ? `No customers match “${q}”.` : 'No customers yet.'}
              </RowMessage>
            ) : (
              items.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => navigate(`/customers/${c.id}`)}
                  className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50"
                >
                  <td className="px-4 py-2 font-medium text-slate-800">{c.full_name}</td>
                  <td className="px-4 py-2 text-slate-600">{c.email ?? '—'}</td>
                  <td className="px-4 py-2 text-slate-600">{c.phone ?? '—'}</td>
                  <td className="px-4 py-2 text-slate-600">{c.suburb ?? '—'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-sm text-slate-500">
        <span>
          {pageInfo}
          {isFetching && !isLoading ? ' · updating…' : ''}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className="rounded-md border border-slate-300 px-3 py-1 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>

      {showCreate && (
        <CustomerCreateModal
          onClose={() => setShowCreate(false)}
          onCreated={(id) => {
            setShowCreate(false)
            navigate(`/customers/${id}`)
          }}
        />
      )}
    </div>
  )
}

function RowMessage({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <tr>
      <td colSpan={4} className={`px-4 py-8 text-center text-slate-500 ${className ?? ''}`}>
        {children}
      </td>
    </tr>
  )
}
