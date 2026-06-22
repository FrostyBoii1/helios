import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from '@/components/AppLayout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { CustomerDetailPage } from '@/pages/CustomerDetailPage'
import { CustomersListPage } from '@/pages/CustomersListPage'
import { DashboardPage } from '@/pages/DashboardPage'
import { JobDetailPage } from '@/pages/JobDetailPage'
import { JobsListPage } from '@/pages/JobsListPage'
import { TasksListPage } from '@/pages/TasksListPage'
import { SchedulePage } from '@/pages/SchedulePage'
import { ImportsListPage } from '@/pages/ImportsListPage'
import { ImportBatchPage } from '@/pages/ImportBatchPage'
import { SettingsLayout } from '@/components/SettingsLayout'
import { SettingsHardwarePage } from '@/pages/SettingsHardwarePage'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        {/* Authenticated area */}
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/customers" element={<CustomersListPage />} />
            <Route path="/customers/:id" element={<CustomerDetailPage />} />
            <Route path="/jobs" element={<JobsListPage />} />
            <Route path="/jobs/:id" element={<JobDetailPage />} />
            <Route path="/tasks" element={<TasksListPage />} />
            <Route path="/schedule" element={<SchedulePage />} />
            {/* Imports review + Settings are admin-only (backend enforces this too). */}
            <Route element={<ProtectedRoute allowedRoles={['admin']} />}>
              <Route path="/imports" element={<ImportsListPage />} />
              <Route path="/imports/:id" element={<ImportBatchPage />} />
              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<Navigate to="/settings/hardware" replace />} />
                <Route path="hardware" element={<SettingsHardwarePage />} />
              </Route>
            </Route>
          </Route>
        </Route>

        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<Navigate to="/404" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
