import { prepareFaceImage } from './face-image';
export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  classId?: string | null;
  signal?: AbortSignal;
  /** Set false only for public endpoints that do not authenticate a cookie session. */
  csrf?: boolean;
};

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  fields?: Array<{ field?: string; message?: string }>;

  constructor(message: string, status: number, code?: string, requestId?: string, fields?: ApiError['fields']) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
const MUTATING = new Set(['POST', 'PATCH', 'DELETE']);

export function readCsrfCookie(): string | null {
  const part = document.cookie.split('; ').find((cookie) => cookie.startsWith('smartattend_csrf='));
  if (!part) return null;
  const value = part.slice('smartattend_csrf='.length);
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  if (options.body !== undefined && !isForm) headers['Content-Type'] = 'application/json';
  if (options.classId) headers['X-Class-ID'] = options.classId;
  if (MUTATING.has(method) && options.csrf !== false) {
    const csrf = readCsrfCookie();
    if (csrf) headers['X-CSRF-Token'] = csrf;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers,
    body: options.body === undefined ? undefined : isForm ? (options.body as FormData) : JSON.stringify(options.body),
    signal: options.signal,
  });
  const requestId = response.headers.get('X-Request-ID') ?? undefined;
  const contentType = response.headers.get('content-type') ?? '';
  let payload: unknown = null;
  if (response.status !== 204) {
    if (contentType.includes('application/json')) {
      payload = await response.json().catch(() => null);
    } else {
      payload = await response.text().catch(() => null);
    }
  }
  if (!response.ok) {
    const body = payload as { error?: { code?: string; message?: string; fields?: ApiError['fields']; request_id?: string }; detail?: string } | null;
    const message = body?.error?.message ?? body?.detail ?? `Request failed (${response.status})`;
    throw new ApiError(String(message), response.status, body?.error?.code, body?.error?.request_id ?? requestId, body?.error?.fields);
  }
  return payload as T;
}

const query = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const result = search.toString();
  return result ? `?${result}` : '';
};

export const api = {
  publicBranding: () => apiRequest<import('./types').SchoolBranding>('/public/school-branding'),
  admin: {
    bootstrapStatus: () => apiRequest<{ available: boolean; principal_exists: boolean }>('/admin/bootstrap/status'),
    bootstrap: (body: { setup_token: string; full_name: string; email: string; password: string }) => apiRequest<{ csrf_token: string; message: string }>('/admin/bootstrap', { method: 'POST', body, csrf: false }),
    login: (body: { email: string; password: string }) => apiRequest<{ csrf_token: string; message: string }>('/admin/auth/login', { method: 'POST', body, csrf: false }),
    logout: () => apiRequest<{ message: string }>('/admin/auth/logout', { method: 'POST' }),
    me: () => apiRequest<import('./types').Principal>('/admin/me'),
    changePassword: (body: { current_password: string; new_password: string }) => apiRequest<{ csrf_token: string; message: string }>('/admin/auth/password', { method: 'POST', body }),
    resetSchoolData: (body: { current_password: string; confirmation: 'RESET SCHOOL DATA' }) => apiRequest<{ message: string; deleted_counts: Record<string, number>; preserved: string[] }>('/admin/system/reset-school-data', { method: 'POST', body }),
    dashboard: () => apiRequest<import('./types').AdminDashboard>('/admin/dashboard'),
    requests: (status = 'PENDING', page = 1) => apiRequest<import('./types').PageResult<import('./types').TeacherRequest>>(`/admin/teacher-requests${query({ status, page, page_size: 50 })}`),
    approveRequest: (id: string, review_note: string) => apiRequest<{ request_id: string; teacher_id: string; status: string; activation_code: string; activation_expires_at: string; one_time_notice: string }>(`/admin/teacher-requests/${id}/approve`, { method: 'POST', body: { review_note } }),
    rejectRequest: (id: string, review_note: string) => apiRequest<{ request_id: string; status: string }>(`/admin/teacher-requests/${id}/reject`, { method: 'POST', body: { review_note } }),
    teachers: (page = 1, pageSize = 50) => apiRequest<import('./types').PageResult<import('./types').Teacher>>(`/admin/teachers${query({ page, page_size: pageSize })}`),
    teacher: (id: string) => apiRequest<import('./types').Teacher & { assignments: Array<{ assignment_id: string; class_id: string; grade: string; section: string; academic_year: string; status: string }> }>(`/admin/teachers/${id}`),
    setTeacherStatus: (id: string, status: 'ACTIVE' | 'SUSPENDED' | 'REVOKED', reason: string) => apiRequest(`/admin/teachers/${id}/status`, { method: 'PATCH', body: { status, reason } }),
    setTeacherConsentPermission: (id: string, enabled: boolean, reason: string) => apiRequest<{ teacher_id: string; can_record_guardian_consent: boolean }>(`/admin/teachers/${id}/consent-permission`, { method: 'PATCH', body: { can_record_guardian_consent: enabled, reason } }),
    revokeTeacherPasskeys: (id: string) => apiRequest<{ recovery_activation_code: string; expires_at: string; one_time_notice: string }>(`/admin/teachers/${id}/revoke-passkeys`, { method: 'POST' }),
    classes: () => apiRequest<import('./types').ClassRecord[]>('/admin/classes'),
    assignTeacher: (classId: string, teacherId: string) => apiRequest(`/admin/classes/${classId}/assignments/${teacherId}`, { method: 'POST' }),
    unassignTeacher: (classId: string, teacherId: string) => apiRequest(`/admin/classes/${classId}/assignments/${teacherId}`, { method: 'DELETE' }),
    students: (search = '', page = 1) => apiRequest<import('./types').PageResult<import('./types').Student>>(`/admin/students${query({ q: search, page, page_size: 50 })}`),
    consent: (studentId: string, body: { consent_status: 'GRANTED' | 'WITHDRAWN'; consent_method: string; consent_record_reference: string }) => apiRequest(`/admin/students/${studentId}/consent`, { method: 'POST', body }),
    liveAttendance: () => apiRequest<import('./types').LiveAttendance[]>('/admin/attendance/live'),
    reports: (params: { from_date?: string; to_date?: string; class_id?: string; page?: number }) => apiRequest<import('./types').PageResult<import('./types').AttendanceReport>>(`/admin/attendance/reports${query({ ...params, page_size: 50 })}`),
    reopen: (sessionId: string, reason: string) => apiRequest(`/admin/attendance/sessions/${sessionId}/reopen`, { method: 'POST', body: { reason } }),
    profile: () => apiRequest<import('./types').SchoolProfile>('/admin/settings/profile'),
    updateProfile: (body: Partial<import('./types').SchoolProfile>) => apiRequest<import('./types').SchoolProfile>('/admin/settings/profile', { method: 'PATCH', body }),
    audit: (page = 1) => apiRequest<import('./types').AuditEvent[]>(`/admin/audit-log${query({ page, page_size: 100 })}`),
  },
  teacher: {
    requestAccess: (body: { full_name: string; phone: string; email?: string; staff_identifier?: string }) => apiRequest<{ message: string; public_reference: string; status: string }>('/teacher-requests', { method: 'POST', body, csrf: false }),
    requestStatus: (reference: string) => apiRequest<{ status: string; requested_at: string; reviewed_at: string | null }>(`/teacher-requests/${encodeURIComponent(reference)}/status`),
    redeem: (activation_code: string) => apiRequest<{ message: string; csrf_token: string; registration_required: boolean }>('/teacher/activation/redeem', { method: 'POST', body: { activation_code }, csrf: false }),
    activationStatus: () => apiRequest<{ id: string; full_name: string; role: string; registration_required: boolean }>('/teacher/activation/status'),
    registrationOptions: () => apiRequest<Record<string, unknown>>('/teacher/passkeys/register/options', { method: 'POST' }),
    registrationVerify: (credential: unknown) => apiRequest<{ message: string; csrf_token: string }>('/teacher/passkeys/register/verify', { method: 'POST', body: { credential } }),
    loginOptions: (identifier: string) => apiRequest<Record<string, unknown>>('/teacher/passkeys/login/options', { method: 'POST', body: { identifier }, csrf: false }),
    loginVerify: (identifier: string, credential: unknown) => apiRequest<{ message: string; csrf_token: string }>('/teacher/passkeys/login/verify', { method: 'POST', body: { identifier, credential }, csrf: false }),
    me: () => apiRequest<import('./types').TeacherIdentity>('/teacher/me'),
    logout: () => apiRequest<{ message: string }>('/teacher/logout', { method: 'POST' }),
    passkeys: () => apiRequest<Array<{ id: string; created_at: string; last_used_at: string | null; device_type: string | null; backed_up: boolean | null; transports: string[] | null }>>('/teacher/passkeys'),
    revokePasskey: (id: string) => apiRequest(`/teacher/passkeys/${id}`, { method: 'DELETE' }),
    classes: () => apiRequest<import('./types').TeacherClass[]>('/teacher/classes'),
    currentClass: (classId?: string | null) => apiRequest<{ class_id: string; grade: string; section: string; academic_year: string; total_enrolled_students: number }>('/teacher/class', { classId }),
    setupClass: (body: { grade_label: string; section_label: string; academic_year: string }) => apiRequest('/teacher/class-setup', { method: 'POST', body }),
    students: (search = '', page = 1, classId?: string | null) => apiRequest<import('./types').PageResult<import('./types').Student>>(`/teacher/students${query({ q: search, page, page_size: 50 })}`, { classId }),
    student: (id: string, classId?: string | null) => apiRequest<import('./types').Student & { enrollment_id: string; consent_status: 'PENDING' | 'GRANTED' | 'WITHDRAWN' }>(`/teacher/students/${id}`, { classId }),
    createStudent: (body: { full_name: string; roll_number: string; school_student_code?: string | null }, classId?: string | null) => apiRequest('/teacher/students', { method: 'POST', body: { ...body, consent_status: 'PENDING' }, classId }),
    updateStudent: (id: string, body: { full_name?: string; roll_number?: string; status?: string }, classId?: string | null) => apiRequest(`/teacher/students/${id}`, { method: 'PATCH', body, classId }),
    recordGuardianConsent: (id: string, body: { consent_status: 'GRANTED' | 'WITHDRAWN'; consent_method: string; consent_record_reference: string }, classId?: string | null) => apiRequest(`/teacher/students/${id}/consent`, { method: 'POST', body, classId }),
    
    faceCaptureGuidance: async (file: File, classId?: string | null) => {
      const preparedFile = await prepareFaceImage(file);
      const form = new FormData();
    
      form.append('file', preparedFile);
    
      return apiRequest<{
        face_detected: boolean;
        pose_bucket: string;
        quality_grade: string;
        capture_ready: boolean;
        guidance: string[];
        metrics: Record<string, number | number[] | null>;
      }>('/teacher/face-capture-guidance', {
        method: 'POST',
        body: form,
        classId,
      });
    },

    faceEnrollment: async (id: string, files: File[], classId?: string | null) => {
      const form = new FormData();
    
      const preparedFiles: File[] = await Promise.all(
        files.map((file) => prepareFaceImage(file))
      );
    
      preparedFiles.forEach((file) => form.append('files', file));
    
      return apiRequest(
        `/teacher/students/${id}/face-enrollment`,
        { method: 'POST', body: form, classId }
      );
    },
    
    openAttendance: (classId?: string | null) => apiRequest<import('./types').AttendanceSession>('/teacher/attendance/sessions', { method: 'POST', classId }),
    attendanceSession: (sessionId: string) => apiRequest<import('./types').AttendanceSession>(`/teacher/attendance/sessions/${sessionId}`),
    attendanceReview: (sessionId: string) => apiRequest<import('./types').AttendanceReview>(`/teacher/attendance/sessions/${sessionId}/review`),
    identify: async (
      sessionId: string,
      files: File | File[],
      classId?: string | null
    ) => {
      const form = new FormData();
      const fileList = Array.isArray(files) ? files : [files];
    
      if (fileList.length === 0) {
        throw new Error('At least one face image is required.');
      }
    
      const preparedFiles = await Promise.all(
        fileList.map((file) => prepareFaceImage(file))
      );
    
      if (preparedFiles.length === 1) {
        form.append('file', preparedFiles[0]);
      } else {
        preparedFiles.forEach((file) => {
          form.append('files', file);
        });
      }
    
      return apiRequest<import('./types').FaceIdentifyResult>(
        `/teacher/attendance/sessions/${sessionId}/identify`,
        {
          method: 'POST',
          body: form,
          classId,
        }
      );
    },
    
    resumeScanning: (sessionId: string) => apiRequest(`/teacher/attendance/sessions/${sessionId}/resume-scanning`, { method: 'POST' }),
    markAttendance: (sessionId: string, enrollmentId: string, status: 'PRESENT' | 'ABSENT' | 'LATE' | 'EXCUSED', notes: string | null) => apiRequest(`/teacher/attendance/sessions/${sessionId}/marks/${enrollmentId}`, { method: 'PATCH', body: { status, notes } }),
    finalizeAttendance: (sessionId: string) => apiRequest(`/teacher/attendance/sessions/${sessionId}/finalize`, { method: 'POST', body: { confirmation: 'CONFIRM_ALL_STATUSES' } }),
    history: (page = 1, classId?: string | null) => apiRequest<import('./types').PageResult<{ session_id: string; date: string; present_count: number; absent_count: number; finalized_at: string }>>(`/teacher/attendance/history${query({ page, page_size: 50 })}`, { classId }),
  },
};
