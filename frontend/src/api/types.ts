export type Branding = {
  design_profile: 'basic' | 'clean' | 'premium';
  appearance: 'light' | 'dark' | 'system';
  primary_color: string;
  accent_color: string;
  sidebar_appearance: 'solid' | 'subtle' | 'brand-tinted';
  sidebar_collapsed: boolean;
  card_appearance: 'flat' | 'outlined' | 'elevated';
  corner_radius: 'sharp' | 'balanced' | 'soft';
  density: 'comfortable' | 'compact';
  heading_style: 'modern' | 'editorial';
  masthead_style: 'prominent' | 'compact';
  motion: 'off' | 'subtle' | 'expressive';
  page_background: 'plain' | 'soft-tint' | 'gradient';
  logo_size: 'small' | 'medium' | 'large';
  logo_placement: 'beside' | 'above';
  logo_with_school_name: boolean;
};

export type SchoolBranding = {
  school_name: string;
  logo_url: string | null;
  branding: Branding;
};

export type SchoolProfile = SchoolBranding & {
  school_code: string | null;
  timezone: string;
  current_academic_year: string;
  settings?: {
    student_information_enabled: boolean;
    face_verification_attempt_limit: 3 | 5;
    [key: string]: unknown;
  };
};

export type Principal = { id: string; full_name: string; email: string; role: 'PRINCIPAL' };
export type Teacher = {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  status: 'ACTIVE' | 'PENDING' | 'SUSPENDED' | 'REVOKED';
  can_record_guardian_consent: boolean;
  created_at: string;
};
export type TeacherIdentity = {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  role: 'TEACHER';
  can_record_guardian_consent: boolean;
  classes: Array<{ id: string; grade: string; section: string; academic_year: string }>;
};
export type TeacherClass = {
  class_id: string;
  grade: string;
  section: string;
  academic_year: string;
};
export type Student = {
  student_id: string;
  enrollment_id?: string;
  full_name: string;
  school_student_code: string | null;
  roll_number: string;
  class?: string;
  section?: string;
  academic_year?: string;
  status: string;
  consent_status: 'PENDING' | 'GRANTED' | 'WITHDRAWN';
  face_enrolled: boolean;
  father_name?: string | null;
  mother_name?: string | null;
  guardian_phone?: string | null;
  alternate_guardian_phone?: string | null;
};
export type PageResult<T> = { items: T[]; page: number; page_size: number; total: number };
export type TeacherRequest = {
  id: string;
  full_name: string;
  phone: string;
  email: string | null;
  staff_identifier: string | null;
  status: string;
  requested_at: string;
};
export type AdminDashboard = {
  school: { name: string; timezone: string; academic_year: string };
  total_students: number;
  total_teachers: number;
  total_classes_sections: number;
  present_today_finalized: number;
  absent_today_finalized: number;
  classes_in_progress: number;
  attendance_completion: { sessions_today: number; finalized: number };
  session_states: Array<{
    session_id: string;
    class_id: string;
    class: string;
    section: string;
    status: string;
    provisional_present_count: number | null;
    final_present_count: number | null;
    final_absent_count: number | null;
  }>;
};
export type ClassRecord = {
  class_id: string;
  grade: string;
  section: string;
  academic_year: string;
  status: string;
  teacher_id: string | null;
  teacher_name: string | null;
};
export type LiveAttendance = {
  session_id: string;
  class_id: string;
  class: string;
  section: string;
  status: string;
  provisional_present_count: number | null;
  final_present_count: number | null;
  final_absent_count: number | null;
  opened_at: string;
  finalized_at: string | null;
};
export type AttendanceReport = {
  session_id: string;
  date: string;
  class_id: string;
  class: string;
  section: string;
  present_count: number;
  absent_count: number;
  submitted_by: string;
  submitted_at: string | null;
};
export type AttendanceSession = {
  session_id: string;
  class_id: string;
  attendance_date: string;
  status: 'OPEN' | 'REVIEW' | 'FINALIZED' | 'CANCELLED' | 'REOPENED';
  total_enrolled?: number;
  provisional_present_count?: number | null;
  final_present_count?: number | null;
  final_absent_count?: number | null;
  identified_unique?: number;
};
export type ReviewMark = {
  enrollment_id: string;
  student_name: string;
  roll_number: string;
  status: 'PRESENT' | 'ABSENT' | 'LATE' | 'EXCUSED' | 'UNCONFIRMED_ABSENT_CANDIDATE';
  source?: string;
  confirmed: boolean;
};
export type AttendanceReview = {
  session_id: string;
  status: string;
  total_enrolled: number;
  provisional_present_count: number;
  marks: ReviewMark[];
  absent_candidates: ReviewMark[];
  message: string;
};
export type AuditEvent = {
  id: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type FaceIdentifyResult = {
  scan_event_id: string;
  status: 'MATCHED' | 'DUPLICATE' | 'NO_MATCH' | 'AMBIGUOUS' | 'POOR_QUALITY' | 'PROVIDER_UNAVAILABLE' | 'ALREADY_REVIEWED' | string;
  candidate: { student_id: string; enrollment_id: string; name: string; roll_number: string } | null;
  score: number | null;
  provisional_present_count: number;
  new_unique_mark: boolean;
  teacher_confirmation_required: boolean;
  message: string;
  attempt_count: number | null;
  attempt_limit: number | null;
  manual_required: boolean;
};

export type AttendanceVerificationStudent = {
  student_id: string;
  enrollment_id: string;
  full_name: string;
  roll_number: string;
  face_enrolled: boolean;
  attempt_count: number;
  attempt_limit: number;
  attendance_status: string | null;
  attendance_confirmed: boolean;
  attendance_source: string | null;
  father_name?: string | null;
  mother_name?: string | null;
  guardian_phone?: string | null;
  alternate_guardian_phone?: string | null;
};

export type AttendanceVerificationProgress = {
  session_id: string;
  attempt_limit: number;
  student_information_enabled: boolean;
  total_students: number;
  confirmed_students: number;
  current_student: AttendanceVerificationStudent | null;
  manual_required: boolean;
  students: AttendanceVerificationStudent[];
};
