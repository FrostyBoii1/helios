// Jobs panel embedded in the Customer detail page: lists this customer's jobs
// and offers a create-job modal to write-permitted roles.

import { useState } from 'react'
import { useAuth } from '@/auth/AuthContext'
import { canCreateJobs } from '@/auth/permissions'
import { JobCreateModal } from '@/components/JobCreateModal'
import { JobsTable } from '@/components/JobsTable'
import { useJobs } from '@/hooks/useJobs'
import { useNavigate } from 'react-router-dom'

interface CustomerJobsPanelProps {
  customerId: number
  customerName: string
}

export function CustomerJobsPanel({ customerId, customerName }: CustomerJobsPanelProps) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [showCreate, setShowCreate] = useState(false)

  const { data, isLoading, isError } = useJobs({ customer_id: customerId, limit: 50 })
  const canCreate = canCreateJobs(user?.role.name)

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-medium text-fg">Jobs {data ? `(${data.total})` : ''}</h3>
        {canCreate && (
          <button onClick={() => setShowCreate(true)} className="btn-primary px-3 py-1.5 text-sm">
            New job
          </button>
        )}
      </div>

      <JobsTable
        jobs={data?.items ?? []}
        showCustomer={false}
        showSite
        loading={isLoading}
        error={isError}
        emptyMessage="No jobs for this customer yet."
      />

      {showCreate && (
        <JobCreateModal
          customerId={customerId}
          customerName={customerName}
          onClose={() => setShowCreate(false)}
          onCreated={(jobId) => {
            setShowCreate(false)
            navigate(`/jobs/${jobId}`)
          }}
        />
      )}
    </div>
  )
}
