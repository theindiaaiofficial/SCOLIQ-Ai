import { useQuery } from '@tanstack/react-query';
import { Navigate, Route, Routes } from 'react-router-dom';
import { api, ApiError } from './api/client';
import { AdminLayout, TeacherLayout } from './components/PortalShells';
import { ErrorState, LoadingState } from './components/ui';
import { AdminLoginPage, TeacherActivationPage, TeacherLoginPage, TeacherRequestPage } from './features/auth/PublicAuthPages';
import {
  AdminDashboardPage, AdminSchoolSettingsPage, AdminSecurityPage, AuditPage, BrandStudioPage, ClassesPage,
  LiveAttendancePage, ReportsPage, StudentsPage, TeacherRequestsPage, TeachersPage,
} from './features/admin/AdminPages';
import {
  ClassSetupPage, TeacherAttendancePage, TeacherDashboardPage, TeacherHistoryPage,
  TeacherSecurityPage, TeacherStudentsPage,
} from './features/teacher/TeacherPages';

function AdminGate() {
  const query = useQuery({ queryKey: ['admin-me'], queryFn: api.admin.me, retry: false, staleTime: 15_000 });
  if (query.isLoading) return <LoadingState label="Securing Principal workspace…" />;
  if (query.isError && query.error instanceof ApiError && [401, 403].includes(query.error.status)) return <Navigate to="/admin/login" replace />;
  if (query.isError) return <ErrorState message={query.error instanceof Error ? query.error.message : 'Principal session could not be checked.'} requestId={query.error instanceof ApiError ? query.error.requestId : undefined} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Navigate to="/admin/login" replace />;
  return <AdminLayout user={query.data} />;
}

function TeacherGate() {
  const teacher = useQuery({ queryKey: ['teacher-me'], queryFn: api.teacher.me, retry: false, staleTime: 15_000 });
  const activation = useQuery({ queryKey: ['teacher-activation-status'], queryFn: api.teacher.activationStatus, retry: false, enabled: teacher.isError, staleTime: 0 });
  if (teacher.isLoading || (teacher.isError && activation.isLoading)) return <LoadingState label="Loading your Teacher workspace…" />;
  if (teacher.isError && !(teacher.error instanceof ApiError && [401, 403].includes(teacher.error.status))) return <ErrorState message={teacher.error instanceof Error ? teacher.error.message : 'Teacher session could not be checked.'} requestId={teacher.error instanceof ApiError ? teacher.error.requestId : undefined} onRetry={() => void teacher.refetch()} />;
  if (teacher.data) return <TeacherLayout user={teacher.data} />;
  if (activation.data) return <Navigate to="/teacher/activate" replace />;
  if (activation.isError && !(activation.error instanceof ApiError && [401, 403].includes(activation.error.status))) return <ErrorState message={activation.error instanceof Error ? activation.error.message : 'Activation state could not be checked.'} requestId={activation.error instanceof ApiError ? activation.error.requestId : undefined} onRetry={() => void activation.refetch()} />;
  return <Navigate to="/teacher/login" replace />;
}

export default function App() {
  return <Routes>
    <Route path="/admin/login" element={<AdminLoginPage />} />
    <Route path="/admin" element={<AdminGate />}>
      <Route index element={<Navigate to="dashboard" replace />} />
      <Route path="dashboard" element={<AdminDashboardPage />} />
      <Route path="requests" element={<TeacherRequestsPage />} />
      <Route path="teachers" element={<TeachersPage />} />
      <Route path="classes" element={<ClassesPage />} />
      <Route path="students" element={<StudentsPage />} />
      <Route path="live-attendance" element={<LiveAttendancePage />} />
      <Route path="reports" element={<ReportsPage />} />
      <Route path="settings" element={<BrandStudioPage />} />
      <Route path="school-settings" element={<AdminSchoolSettingsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="security" element={<AdminSecurityPage />} />
      <Route path="*" element={<Navigate to="dashboard" replace />} />
    </Route>

    <Route path="/teacher/login" element={<TeacherLoginPage />} />
    <Route path="/teacher/request-access" element={<TeacherRequestPage />} />
    <Route path="/teacher/activate" element={<TeacherActivationPage />} />
    <Route path="/teacher" element={<TeacherGate />}>
      <Route index element={<Navigate to="dashboard" replace />} />
      <Route path="dashboard" element={<TeacherDashboardPage />} />
      <Route path="class-setup" element={<ClassSetupPage />} />
      <Route path="students" element={<TeacherStudentsPage />} />
      <Route path="attendance" element={<TeacherAttendancePage />} />
      <Route path="history" element={<TeacherHistoryPage />} />
      <Route path="security" element={<TeacherSecurityPage />} />
      <Route path="*" element={<Navigate to="dashboard" replace />} />
    </Route>

    <Route path="/" element={<Navigate to="/admin" replace />} />
    <Route path="*" element={<Navigate to="/admin" replace />} />
  </Routes>;
}
