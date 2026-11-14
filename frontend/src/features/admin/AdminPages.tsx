import { useEffect, useState } from 'react';
import type * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  Activity, ArrowRight, BookOpen, Building2, CalendarCheck, CheckCircle2,
  ClipboardList, Copy, GraduationCap, KeyRound, Palette, RefreshCw, ShieldCheck,
  Sparkles, Users, UserRoundCheck,
} from 'lucide-react';
import { api, ApiError } from '../../api/client';
import type { Branding, SchoolProfile } from '../../api/types';
import { DEFAULT_BRANDING, readableText } from '../branding/defaults';
import {
  BrandMark, Button, Card, ConfirmButton, EmptyState, ErrorState, LoadingState, Modal, Notice,
  PageHeader, Pagination, SearchField, SelectField, StatusPill, Table, TextField,
} from '../../components/ui';

function useRefresh(keys: ReadonlyArray<ReadonlyArray<unknown>>) {
  const queryClient = useQueryClient();
  return () => { keys.forEach((queryKey) => void queryClient.invalidateQueries({ queryKey })); };
}

function QueryPanel({ isLoading, isError, error, retry, children }: { isLoading: boolean; isError: boolean; error: unknown; retry: () => void; children: React.ReactNode }) {
  if (isLoading) return <LoadingState />;
  if (isError) return <ErrorState message={error instanceof Error ? error.message : 'A service error occurred.'} requestId={error instanceof ApiError ? error.requestId : undefined} onRetry={retry} />;
  return <>{children}</>;
}

function MetricCard({ label, value, detail, icon, tone = 'blue' }: { label: string; value: number | string; detail: string; icon: React.ReactNode; tone?: string }) {
  return <Card className="metric-card"><div className={`metric-icon metric-${tone}`}>{icon}</div><span className="metric-label">{label}</span><strong className="metric-value">{value}</strong><span className="metric-detail">{detail}</span></Card>;
}

export function AdminDashboardPage() {
  const query = useQuery({ queryKey: ['admin-dashboard'], queryFn: api.admin.dashboard, refetchInterval: 30_000 });
  const pending = useQuery({ queryKey: ['admin-requests-pending-count'], queryFn: () => api.admin.requests('PENDING', 1) });
  const data = query.data;
  return <>
    <PageHeader title="Overview" description="Your school's daily pulse, with a clear separation between live progress and finalized attendance." actions={<Button variant="secondary" onClick={() => { void query.refetch(); void pending.refetch(); }}><RefreshCw size={15} /> Refresh data</Button>} />
    <QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
      {data ? <>
        <div className="metrics-grid">
          <MetricCard label="Students enrolled" value={data.total_students} detail="Active school enrollments" icon={<GraduationCap size={19} />} />
          <MetricCard label="Active teachers" value={data.total_teachers} detail="Approved teacher accounts" icon={<Users size={19} />} tone="green" />
          <MetricCard label="Classes & sections" value={data.total_classes_sections} detail="Active teaching groups" icon={<BookOpen size={19} />} tone="violet" />
          <MetricCard label="Pending requests" value={pending.data?.total ?? '—'} detail="Awaiting Principal review" icon={<ClipboardList size={19} />} tone="amber" />
        </div>
        <div className="dashboard-grid">
          <Card className="panel-card">
            <div className="section-heading"><div><h2>Today's attendance</h2><p>Finalized totals only. In-progress scans are shown separately below.</p></div><CalendarCheck size={19} /></div>
            <div className="attendance-summary">
              <div><span className="summary-number text-success">{data.present_today_finalized}</span><span>Present</span></div>
              <div><span className="summary-number">{data.absent_today_finalized}</span><span>Absent</span></div>
              <div><span className="summary-number text-info">{data.classes_in_progress}</span><span>In progress</span></div>
            </div>
            <div className="progress-meta"><span>Class sessions finalized</span><strong>{data.attendance_completion.finalized} / {data.attendance_completion.sessions_today}</strong></div>
            <div className="progress-track"><span style={{ width: `${data.attendance_completion.sessions_today ? 100 * data.attendance_completion.finalized / data.attendance_completion.sessions_today : 0}%` }} /></div>
          </Card>
          <Card className="panel-card quick-actions">
            <div className="section-heading"><div><h2>Quick actions</h2><p>Common school administration tasks</p></div><Sparkles size={19} /></div>
            <a href="/admin/requests" className="quick-action"><span className="quick-action-icon"><UserRoundCheck size={17} /></span><span><strong>Review teacher requests</strong><small>Verify and approve school staff</small></span><ArrowRight size={16} /></a>
            <a href="/admin/students" className="quick-action"><span className="quick-action-icon"><GraduationCap size={17} /></span><span><strong>Review guardian consent</strong><small>Manage student consent records</small></span><ArrowRight size={16} /></a>
            <a href="/admin/settings" className="quick-action"><span className="quick-action-icon"><Palette size={17} /></span><span><strong>Update school identity</strong><small>Set your shared Admin and Teacher brand</small></span><ArrowRight size={16} /></a>
          </Card>
        </div>
        <Card className="panel-card table-card">
          <div className="section-heading"><div><h2>Class attendance activity</h2><p>Live session counts are provisional until each teacher submits final attendance.</p></div><a className="text-link" href="/admin/live-attendance">View live attendance <ArrowRight size={14} /></a></div>
          {data.session_states.length ? <Table><thead><tr><th>Class</th><th>Session state</th><th>Present count</th><th>Absent count</th><th>Type</th></tr></thead><tbody>{data.session_states.map((item) => <tr key={item.session_id}><td><strong>Grade {item.class} · {item.section}</strong></td><td><StatusPill value={item.status} /></td><td>{item.status === 'FINALIZED' ? item.final_present_count : item.provisional_present_count ?? '—'}</td><td>{item.status === 'FINALIZED' ? item.final_absent_count : '—'}</td><td><span className="muted-text">{item.status === 'FINALIZED' ? 'Final' : 'Provisional'}</span></td></tr>)}</tbody></Table> : <EmptyState icon={<Activity size={23} />} title="No attendance sessions yet" description="When a teacher opens today's attendance, the session will appear here." />}
        </Card>
      </> : null}
    </QueryPanel>
  </>;
}

export function TeacherRequestsPage() {
  const [status, setStatus] = useState('PENDING');
  const [page, setPage] = useState(1);
  const [activation, setActivation] = useState<{ code: string; expires: string; message: string } | null>(null);
  const [reviewNote, setReviewNote] = useState('Verified against school staff records');
  const query = useQuery({ queryKey: ['admin-requests', status, page], queryFn: () => api.admin.requests(status, page) });
  const refresh = useRefresh([['admin-requests', status, page], ['admin-requests-pending-count'], ['admin-dashboard']]);
  const approve = useMutation({ mutationFn: (id: string) => api.admin.approveRequest(id, reviewNote), onSuccess: (result) => { setActivation({ code: result.activation_code, expires: result.activation_expires_at, message: result.one_time_notice }); refresh(); toast.success('Teacher request approved'); }, onError: (error) => toast.error(error instanceof Error ? error.message : 'Approval failed') });
  const reject = useMutation({ mutationFn: (id: string) => api.admin.rejectRequest(id, reviewNote), onSuccess: () => { refresh(); toast.success('Request rejected'); }, onError: (error) => toast.error(error instanceof Error ? error.message : 'Rejection failed') });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return <>
    <PageHeader title="Teacher requests" description="Check each request against your school's staff records before granting access." />
    <Card className="panel-card">
      <div className="toolbar"><SelectField label="Request status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="PENDING">Pending</option><option value="APPROVED_PENDING_PASSKEY">Approved · awaiting passkey</option><option value="ACTIVE">Active</option><option value="REJECTED">Rejected</option><option value="EXPIRED">Expired</option><option value="">All requests</option></SelectField><span className="toolbar-count">{query.data?.total ?? 0} records</span></div>
      <QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
        {query.data?.items.length ? <Table><thead><tr><th>Applicant</th><th>Contact</th><th>Staff ID</th><th>Requested</th><th>Status</th><th>Actions</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.id}><td><strong>{item.full_name}</strong><small className="table-subtext">{item.email ?? 'No email provided'}</small></td><td>{item.phone}</td><td>{item.staff_identifier || '—'}</td><td>{new Date(item.requested_at).toLocaleDateString()}</td><td><StatusPill value={item.status} /></td><td>{item.status === 'PENDING' ? <div className="row-actions"><Button size="sm" onClick={() => { setSelectedId(item.id); setReviewNote('Verified against school staff records'); }}>Review</Button></div> : '—'}</td></tr>)}</tbody></Table> : <EmptyState icon={<ClipboardList size={23} />} title="No requests in this view" description="New teacher access requests will appear here for verification." />}
      </QueryPanel>
      {query.data ? <Pagination page={query.data.page} pageSize={query.data.page_size} total={query.data.total} onPageChange={setPage} /> : null}
    </Card>
    {selectedId ? <Modal title="Review teacher access" description="Approve only after you have independently confirmed the applicant is a member of school staff." onClose={() => setSelectedId(null)}>
      <label className="field"><span className="field-label">Review note</span><textarea className="input textarea" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} maxLength={500} /></label>
      <div className="modal-actions"><Button variant="ghost" onClick={() => setSelectedId(null)}>Cancel</Button><Button variant="danger" loading={reject.isPending} onClick={() => reject.mutate(selectedId)}>Reject request</Button><Button loading={approve.isPending} onClick={() => approve.mutate(selectedId)}>Approve & issue code</Button></div>
    </Modal> : null}
    {activation ? <Modal title="One-time teacher activation code" description="This code is shown only once. Deliver it to the verified teacher using a trusted private/offline channel." onClose={() => setActivation(null)}>
      <Notice tone="warning">Do not send this code through a public channel or save it in a shared document. It expires at {new Date(activation.expires).toLocaleString()}.</Notice>
      <div className="secret-code"><code>{activation.code}</code><Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(activation.code); toast.success('Copied to clipboard'); }}><Copy size={15} /> Copy code</Button></div>
      <p className="muted-text">{activation.message}</p>
      <div className="modal-actions"><Button onClick={() => setActivation(null)}>I have delivered the code</Button></div>
    </Modal> : null}
  </>;
}

export function TeachersPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [recovery, setRecovery] = useState<{ code: string; expires: string; message: string } | null>(null);
  const [selectedTeacher, setSelectedTeacher] = useState<string | null>(null);
  const query = useQuery({ queryKey: ['admin-teachers', page], queryFn: () => api.admin.teachers(page) });
  const refresh = useRefresh([['admin-teachers', page]]);
  const revoke = useMutation({ mutationFn: (id: string) => api.admin.revokeTeacherPasskeys(id), onSuccess: (result) => { setRecovery({ code: result.recovery_activation_code, expires: result.expires_at, message: result.one_time_notice }); toast.success('Passkeys revoked; recovery code created'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Recovery failed') });
  const status = useMutation({ mutationFn: ({ id, value }: { id: string; value: 'ACTIVE' | 'SUSPENDED' | 'REVOKED' }) => api.admin.setTeacherStatus(id, value, `Changed by Principal to ${value}`), onSuccess: () => { refresh(); toast.success('Teacher status updated'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Status update failed') });
  const consentPermission = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.admin.setTeacherConsentPermission(id, enabled, enabled ? 'Principal delegated verified guardian-consent recording authority.' : 'Principal revoked guardian-consent recording authority.'), onSuccess: () => { refresh(); if (selectedTeacher) void queryClient.invalidateQueries({ queryKey: ['admin-teacher-detail', selectedTeacher] }); toast.success('Teacher consent-recording permission updated'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Permission update failed') });
  const detail = useQuery({ queryKey: ['admin-teacher-detail', selectedTeacher], queryFn: () => api.admin.teacher(selectedTeacher!), enabled: Boolean(selectedTeacher) });
  return <>
    <PageHeader title="Teachers" description="Manage approved teacher accounts, access status and class assignments." />
    <Notice tone="info">Consent-recording permission lets an authorized teacher document guardian permission they have actually received. It does not automatically grant consent or bypass the requirement to enter the real consent method and record reference. All entries are audited.</Notice>
    <Card className="panel-card"><QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
      {query.data?.items.length ? <Table><thead><tr><th>Teacher</th><th>Contact</th><th>Account status</th><th>Consent recording</th><th>Joined</th><th>Manage</th></tr></thead><tbody>{query.data.items.map((teacher) => <tr key={teacher.id}><td><button className="table-link" onClick={() => setSelectedTeacher(teacher.id)}><strong>{teacher.full_name}</strong><small className="table-subtext">View assigned classes</small></button></td><td>{teacher.email || teacher.phone || '—'}</td><td><StatusPill value={teacher.status} /></td><td><div className="consent-permission-cell"><StatusPill value={teacher.can_record_guardian_consent ? 'ENABLED' : 'DISABLED'} /><Button size="sm" variant="outline" disabled={teacher.status !== 'ACTIVE' && !teacher.can_record_guardian_consent} loading={consentPermission.isPending && consentPermission.variables?.id === teacher.id} onClick={() => { const enabled = !teacher.can_record_guardian_consent; const message = enabled ? `Allow ${teacher.full_name} to record actual, verified guardian consent for students in assigned classes?` : `Revoke ${teacher.full_name}'s guardian-consent recording permission?`; if (window.confirm(message)) consentPermission.mutate({ id: teacher.id, enabled }); }}>{teacher.can_record_guardian_consent ? 'Disable' : 'Enable'}</Button></div></td><td>{new Date(teacher.created_at).toLocaleDateString()}</td><td><div className="row-actions"><SelectField label="Set status" aria-label={`Set status for ${teacher.full_name}`} value={teacher.status} onChange={(e) => { const value = e.target.value as 'ACTIVE' | 'SUSPENDED' | 'REVOKED'; if (window.confirm(`Change ${teacher.full_name}'s status to ${value}?`)) status.mutate({ id: teacher.id, value }); }}><option value="ACTIVE">Active</option><option value="SUSPENDED">Suspended</option><option value="REVOKED">Revoked</option></SelectField><Button size="sm" variant="outline" onClick={() => revoke.mutate(teacher.id)} loading={revoke.isPending && revoke.variables === teacher.id}>Recover passkey</Button></div></td></tr>)}</tbody></Table> : <EmptyState icon={<Users size={23} />} title="No teacher accounts yet" description="Approved teachers appear here after they complete passkey registration." />}
    </QueryPanel>{query.data ? <Pagination page={query.data.page} pageSize={query.data.page_size} total={query.data.total} onPageChange={setPage} /> : null}</Card>
    {selectedTeacher ? <Modal title="Teacher details" onClose={() => setSelectedTeacher(null)}>
      <QueryPanel isLoading={detail.isLoading} isError={detail.isError} error={detail.error} retry={() => void detail.refetch()}>
        {detail.data ? <><div className="detail-hero"><span className="avatar avatar-primary">{detail.data.full_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join('')}</span><div><h3>{detail.data.full_name}</h3><p>{detail.data.email || detail.data.phone}</p></div><StatusPill value={detail.data.status} /></div><h4>Class assignments</h4>{detail.data.assignments.length ? detail.data.assignments.map((item) => <div className="assignment-row" key={item.assignment_id}><BookOpen size={16} /><span>Grade {item.grade} · {item.section}</span><small>{item.academic_year}</small><StatusPill value={item.status} /></div>) : <p className="muted-text">No class assignment yet.</p>}<div className="teacher-consent-authority"><div><strong>Guardian consent recording</strong><small>{detail.data.can_record_guardian_consent ? "Enabled: may document verified consent for assigned students." : "Disabled: Principal records consent."}</small></div><StatusPill value={detail.data.can_record_guardian_consent ? "ENABLED" : "DISABLED"} /><Button size="sm" variant="outline" disabled={detail.data.status !== "ACTIVE" && !detail.data.can_record_guardian_consent} loading={consentPermission.isPending} onClick={() => { const enabled = !detail.data!.can_record_guardian_consent; if (window.confirm(enabled ? "Delegate guardian-consent recording to this teacher?" : "Revoke this teacher’s guardian-consent recording permission?")) consentPermission.mutate({ id: detail.data!.id, enabled }); }}> {detail.data.can_record_guardian_consent ? "Disable permission" : "Enable permission"} </Button></div></> : null}
      </QueryPanel>
    </Modal> : null}
    {recovery ? <Modal title="Principal-assisted passkey recovery" description="The old credentials have been revoked. Give this one-time activation code directly to the verified teacher." onClose={() => setRecovery(null)}><Notice tone="warning">The code expires at {new Date(recovery.expires).toLocaleString()} and will not be shown again.</Notice><div className="secret-code"><code>{recovery.code}</code><Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(recovery.code); toast.success('Copied to clipboard'); }}><Copy size={15} /> Copy code</Button></div><p className="muted-text">{recovery.message}</p></Modal> : null}
  </>;
}

export function ClassesPage() {
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const classes = useQuery({ queryKey: ['admin-classes'], queryFn: api.admin.classes });
  const teachers = useQuery({ queryKey: ['admin-teachers-active'], queryFn: () => api.admin.teachers(1, 200) });
  const refresh = useRefresh([['admin-classes'], ['admin-teachers-active']]);
  const assign = useMutation({ mutationFn: ({ classId, teacherId }: { classId: string; teacherId: string }) => api.admin.assignTeacher(classId, teacherId), onSuccess: () => { refresh(); toast.success('Teacher assigned'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Assignment failed') });
  const unassign = useMutation({ mutationFn: ({ classId, teacherId }: { classId: string; teacherId: string }) => api.admin.unassignTeacher(classId, teacherId), onSuccess: () => { refresh(); toast.success('Assignment ended'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not end assignment') });
  const available = teachers.data?.items.filter((item) => item.status === 'ACTIVE') ?? [];
  return <><PageHeader title="Classes & assignments" description="Review class ownership and resolve assignment conflicts centrally." />
    <Card className="panel-card"><QueryPanel isLoading={classes.isLoading || teachers.isLoading} isError={classes.isError || teachers.isError} error={classes.error ?? teachers.error} retry={() => { void classes.refetch(); void teachers.refetch(); }}>
      {classes.data?.length ? <Table><thead><tr><th>Class / section</th><th>Academic year</th><th>Class teacher</th><th>Status</th><th>Assignment</th></tr></thead><tbody>{classes.data.map((item) => <tr key={item.class_id}><td><strong>Grade {item.grade} · {item.section}</strong></td><td>{item.academic_year}</td><td>{item.teacher_name || <span className="muted-text">Unassigned</span>}</td><td><StatusPill value={item.status} /></td><td>{item.teacher_id ? <ConfirmButton confirmText="End this assignment?" onConfirm={() => unassign.mutate({ classId: item.class_id, teacherId: item.teacher_id! })}>Unassign</ConfirmButton> : <div className="assign-control"><select aria-label={`Choose teacher for grade ${item.grade} ${item.section}`} value={assignments[item.class_id] ?? ''} onChange={(e) => setAssignments((old) => ({ ...old, [item.class_id]: e.target.value }))}><option value="">Select active teacher</option>{available.map((teacher) => <option key={teacher.id} value={teacher.id}>{teacher.full_name}</option>)}</select><Button size="sm" disabled={!assignments[item.class_id]} loading={assign.isPending} onClick={() => assign.mutate({ classId: item.class_id, teacherId: assignments[item.class_id]! })}>Assign</Button></div>}</td></tr>)}</tbody></Table> : <EmptyState icon={<BookOpen size={23} />} title="No classes created" description="Classes are created by a teacher through class setup, then can be reviewed and assigned here." />}
    </QueryPanel></Card>
  </>;
}

export function StudentsPage() {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [consent, setConsent] = useState<{ studentId: string; name: string; status: 'GRANTED' | 'WITHDRAWN' } | null>(null);
  const [method, setMethod] = useState('Guardian consent form');
  const [reference, setReference] = useState('');
  const query = useQuery({ queryKey: ['admin-students', search, page], queryFn: () => api.admin.students(search, page) });
  const refresh = useRefresh([['admin-students', search, page]]);
  const mutation = useMutation({ mutationFn: () => api.admin.consent(consent!.studentId, { consent_status: consent!.status, consent_method: method, consent_record_reference: reference }), onSuccess: () => { refresh(); setConsent(null); setReference(''); toast.success('Guardian consent record saved'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Consent update failed') });
  return <><PageHeader title="Students & consent" description="Review school enrollments and record Principal-verified guardian consent before any face enrollment." />
    <Card className="panel-card"><div className="toolbar"><SearchField value={search} onChange={(value) => { setSearch(value); setPage(1); }} placeholder="Search name, roll number or school code" /><span className="toolbar-count">{query.data?.total ?? 0} students</span></div>
      <QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
        {query.data?.items.length ? <Table><thead><tr><th>Student</th><th>Class</th><th>Roll no.</th><th>Consent</th><th>Face template</th><th>Action</th></tr></thead><tbody>{query.data.items.map((student) => <tr key={`${student.student_id}-${student.academic_year}`}><td><strong>{student.full_name}</strong><small className="table-subtext">{student.school_student_code || 'No school code'}</small></td><td>Grade {student.class} · {student.section}<small className="table-subtext">{student.academic_year}</small></td><td>{student.roll_number}</td><td><StatusPill value={student.consent_status} /></td><td>{student.face_enrolled ? <StatusPill value="ENROLLED" /> : <span className="muted-text">Not enrolled</span>}</td><td><Button size="sm" variant="outline" onClick={() => { setConsent({ studentId: student.student_id, name: student.full_name, status: 'GRANTED' }); setMethod('Guardian consent form'); setReference(''); }}>Record consent</Button></td></tr>)}</tbody></Table> : <EmptyState icon={<GraduationCap size={23} />} title="No student records found" description={search ? 'Try a different name or roll number.' : 'Student enrollments will appear here when teachers add their class rosters.'} />}
      </QueryPanel>{query.data ? <Pagination page={query.data.page} pageSize={query.data.page_size} total={query.data.total} onPageChange={setPage} /> : null}
    </Card>
    {consent ? <Modal title="Guardian consent record" description={`Record verified permission for ${consent.name}. Only the Principal can change this record.`} onClose={() => setConsent(null)}>
      <div className="field"><span className="field-label">Consent action</span><div className="segmented"><button type="button" className={consent.status === 'GRANTED' ? 'selected' : ''} onClick={() => setConsent({ ...consent, status: 'GRANTED' })}>Grant</button><button type="button" className={consent.status === 'WITHDRAWN' ? 'selected' : ''} onClick={() => setConsent({ ...consent, status: 'WITHDRAWN' })}>Withdraw</button></div></div>
      <TextField label="Consent method" value={method} onChange={(e) => setMethod(e.target.value)} hint="Example: signed paper form, school portal record" />
      <TextField label="Evidence reference" value={reference} onChange={(e) => setReference(e.target.value)} hint="Reference only; do not upload a guardian document here." />
      {consent.status === 'WITHDRAWN' ? <Notice tone="warning">Withdrawing consent deletes the active stored face template. Manual attendance remains available.</Notice> : <Notice tone="info">Face enrollment remains unavailable until this latest consent status is GRANTED.</Notice>}
      <div className="modal-actions"><Button variant="ghost" onClick={() => setConsent(null)}>Cancel</Button><Button disabled={method.trim().length < 3 || reference.trim().length < 3} loading={mutation.isPending} onClick={() => mutation.mutate()}>Save consent record</Button></div>
    </Modal> : null}
  </>;
}

export function LiveAttendancePage() {
  const query = useQuery({ queryKey: ['admin-live-attendance'], queryFn: api.admin.liveAttendance, refetchInterval: 15_000 });
  const refresh = useRefresh([['admin-live-attendance']]);
  return <><PageHeader title="Live attendance" description="Follow session progress across the school. Provisional counts are not finalized attendance." actions={<Button variant="secondary" onClick={refresh}><RefreshCw size={15} /> Refresh</Button>} />
    <Card className="panel-card"><QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
      {query.data?.length ? <Table><thead><tr><th>Class / section</th><th>Session status</th><th>Present count</th><th>Absent count</th><th>Opened</th><th>Finalized</th></tr></thead><tbody>{query.data.map((item) => <tr key={item.session_id}><td><strong>Grade {item.class} · {item.section}</strong></td><td><StatusPill value={item.status} /></td><td>{item.status === 'FINALIZED' ? item.final_present_count : item.provisional_present_count ?? '—'}</td><td>{item.status === 'FINALIZED' ? item.final_absent_count : <span className="muted-text">Awaiting review</span>}</td><td>{new Date(item.opened_at).toLocaleTimeString()}</td><td>{item.finalized_at ? new Date(item.finalized_at).toLocaleString() : '—'}</td></tr>)}</tbody></Table> : <EmptyState icon={<Activity size={23} />} title="No classes in session" description="When teachers start attendance, their provisional progress will appear in this view." />}
    </QueryPanel></Card>
  </>;
}

export function ReportsPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [classId, setClassId] = useState('');
  const [reopenTarget, setReopenTarget] = useState<{ sessionId: string; label: string; date: string } | null>(null);
  const [reopenReason, setReopenReason] = useState('');
  const classes = useQuery({ queryKey: ['admin-classes'], queryFn: api.admin.classes });
  const query = useQuery({ queryKey: ['admin-reports', fromDate, toDate, classId, page], queryFn: () => api.admin.reports({ from_date: fromDate || undefined, to_date: toDate || undefined, class_id: classId || undefined, page }) });
  const reopen = useMutation({
    mutationFn: () => {
      if (!reopenTarget || reopenReason.trim().length < 5) throw new Error('Enter an audit reason of at least five characters.');
      return api.admin.reopen(reopenTarget.sessionId, reopenReason.trim());
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['admin-reports'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-live-attendance'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-dashboard'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-audit'] }),
      ]);
      setReopenTarget(null);
      setReopenReason('');
      toast.success('Attendance session reopened and recorded in the audit log');
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : 'Could not reopen attendance session'),
  });
  return <><PageHeader title="Attendance reports" description="Historical, finalized attendance records. Reopening is a controlled Principal action and requires an audit reason." />
    <Card className="panel-card"><div className="filter-grid"><TextField label="From date" type="date" value={fromDate} onChange={(e) => { setFromDate(e.target.value); setPage(1); }} /><TextField label="To date" type="date" value={toDate} onChange={(e) => { setToDate(e.target.value); setPage(1); }} /><SelectField label="Class filter" value={classId} onChange={(e) => { setClassId(e.target.value); setPage(1); }}><option value="">All classes</option>{classes.data?.map((item) => <option key={item.class_id} value={item.class_id}>Grade {item.grade} · {item.section}</option>)}</SelectField><div className="filter-submit"><Button variant="secondary" onClick={() => { setFromDate(''); setToDate(''); setClassId(''); setPage(1); }}>Clear filters</Button></div></div>
      <QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
        {query.data?.items.length ? <Table><thead><tr><th>Date</th><th>Class</th><th>Present</th><th>Absent</th><th>Submitted</th><th>Principal action</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.session_id}><td>{new Date(`${item.date}T00:00:00`).toLocaleDateString()}</td><td><strong>Grade {item.class} · {item.section}</strong></td><td className="text-success"><strong>{item.present_count}</strong></td><td><strong>{item.absent_count}</strong></td><td>{item.submitted_at ? new Date(item.submitted_at).toLocaleString() : '—'}</td><td><Button size="sm" variant="outline" onClick={() => { setReopenTarget({ sessionId: item.session_id, label: `Grade ${item.class} · ${item.section}`, date: item.date }); setReopenReason(''); }}>Reopen session</Button></td></tr>)}</tbody></Table> : <EmptyState icon={<CalendarCheck size={23} />} title="No finalized reports" description="Choose a different date range or wait for teachers to submit attendance." />}
      </QueryPanel>{query.data ? <Pagination page={query.data.page} pageSize={query.data.page_size} total={query.data.total} onPageChange={setPage} /> : null}
    </Card>
    {reopenTarget ? <Modal title="Reopen finalized attendance" description="This controlled action unlocks the session for corrections. The reason is stored in the school audit log." onClose={() => { if (!reopen.isPending) { setReopenTarget(null); setReopenReason(''); } }}>
      <Notice tone="warning">You are reopening {reopenTarget.label} for {new Date(`${reopenTarget.date}T00:00:00`).toLocaleDateString()}. Previously finalized records will enter the reopened workflow and must be reviewed and submitted again.</Notice>
      <TextField label="Reason for reopening" value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} minLength={5} maxLength={500} placeholder="Explain the correction required" hint="Required for the audit trail. Do not include unnecessary personal information." />
      <div className="modal-actions"><Button variant="ghost" disabled={reopen.isPending} onClick={() => { setReopenTarget(null); setReopenReason(''); }}>Cancel</Button><Button variant="danger" loading={reopen.isPending} disabled={reopenReason.trim().length < 5} onClick={() => reopen.mutate()}>Reopen and record reason</Button></div>
    </Modal> : null}
  </>;
}

export function AuditPage() {
  const query = useQuery({ queryKey: ['admin-audit'], queryFn: () => api.admin.audit() });
  return <><PageHeader title="Audit log" description="A trace of important school, security and attendance actions." />
    <Card className="panel-card"><QueryPanel isLoading={query.isLoading} isError={query.isError} error={query.error} retry={() => void query.refetch()}>
      {query.data?.length ? <Table><thead><tr><th>When</th><th>Action</th><th>Entity</th><th>Actor</th><th>Details</th></tr></thead><tbody>{query.data.map((event) => <tr key={event.id}><td>{new Date(event.created_at).toLocaleString()}</td><td><strong>{event.action.replaceAll('_', ' ')}</strong></td><td>{event.entity_type} · {event.entity_id?.slice(0, 8) ?? '—'}</td><td>{event.actor_user_id?.slice(0, 8) ?? 'System'}</td><td><code className="small-code">{JSON.stringify(event.metadata)}</code></td></tr>)}</tbody></Table> : <EmptyState icon={<ShieldCheck size={23} />} title="No audit events yet" description="Important actions will be recorded here as the system is used." />}
    </QueryPanel></Card>
  </>;
}

export function BrandStudioPage() {
  const queryClient = useQueryClient();
  const profileQuery = useQuery({ queryKey: ['admin-profile'], queryFn: api.admin.profile });
  const [draft, setDraft] = useState<SchoolProfile | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (profileQuery.data && !dirty) setDraft(profileQuery.data);
  }, [profileQuery.data, dirty]);
  const save = useMutation({ mutationFn: (profile: SchoolProfile) => api.admin.updateProfile({
    school_name: profile.school_name,
    school_code: profile.school_code,
    timezone: profile.timezone,
    current_academic_year: profile.current_academic_year,
    logo_url: profile.logo_url,
    branding: profile.branding,
  }), onSuccess: async (saved) => {
    setDraft(saved); setDirty(false);
    queryClient.setQueryData(['admin-profile'], saved);
    await queryClient.invalidateQueries({ queryKey: ['public-school-branding'] });
    toast.success('School identity saved across both portals');
  }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save branding') });
  const setField = <K extends keyof SchoolProfile>(key: K, value: SchoolProfile[K]) => { setDraft((old) => old ? { ...old, [key]: value } : old); setDirty(true); };
  const setBrand = <K extends keyof Branding>(key: K, value: Branding[K]) => { setDraft((old) => old ? { ...old, branding: { ...old.branding, [key]: value } } : old); setDirty(true); };
  const defaults = () => { if (!draft) return; setDraft({ ...draft, branding: DEFAULT_BRANDING }); setDirty(true); };
  const discard = () => { if (profileQuery.data) setDraft(profileQuery.data); setDirty(false); };
  const preview = draft ?? profileQuery.data;
  return <><PageHeader title="School identity & brand studio" description="One saved identity and visual system, shared automatically by the Principal and every teacher." actions={<><Button variant="ghost" disabled={!dirty} onClick={discard}>Discard</Button><Button disabled={!dirty || !draft} loading={save.isPending} onClick={() => draft && save.mutate(draft)}>Save changes</Button></>} />
    <QueryPanel isLoading={profileQuery.isLoading} isError={profileQuery.isError} error={profileQuery.error} retry={() => void profileQuery.refetch()}>
      {draft && preview ? <div className="brand-studio-grid">
        <div className="brand-controls">
          <Card className="panel-card"><div className="section-heading"><div><h2>School identity</h2><p>These details appear on both portals and public sign-in screens.</p></div><Building2 size={19} /></div>
            <div className="form-grid"><TextField label="School name" value={draft.school_name} maxLength={180} onChange={(e) => setField('school_name', e.target.value)} /><TextField label="School code" value={draft.school_code ?? ''} onChange={(e) => setField('school_code', e.target.value || null)} placeholder="Optional" /><TextField label="Logo URL" value={draft.logo_url ?? ''} onChange={(e) => setField('logo_url', e.target.value || null)} placeholder="https://school.example/logo.png" hint="HTTPS hosted image URL. The logo is not uploaded to this application." /><TextField label="Academic year" value={draft.current_academic_year} onChange={(e) => setField('current_academic_year', e.target.value)} /><TextField label="Timezone" value={draft.timezone} onChange={(e) => setField('timezone', e.target.value)} hint="Use an IANA timezone such as Asia/Kolkata." /></div>
          </Card>
          <Card className="panel-card"><div className="section-heading"><div><h2>Visual appearance</h2><p>Choose a profile, then fine-tune the design tokens.</p></div><Palette size={19} /></div>
            <div className="form-grid">
              <SelectField label="Design profile" value={draft.branding.design_profile} onChange={(e) => setBrand('design_profile', e.target.value as Branding['design_profile'])}><option value="basic">Basic · Minimal</option><option value="clean">Clean · Balanced</option><option value="premium">Premium · Expressive</option></SelectField>
              <SelectField label="Appearance" value={draft.branding.appearance} onChange={(e) => setBrand('appearance', e.target.value as Branding['appearance'])}><option value="light">Light</option><option value="dark">Dark</option><option value="system">Follow device</option></SelectField>
              <label className="field"><span className="field-label">Primary brand color</span><span className="color-field"><input type="color" value={draft.branding.primary_color} onChange={(e) => setBrand('primary_color', e.target.value.toUpperCase())} /><code>{draft.branding.primary_color}</code></span></label>
              <label className="field"><span className="field-label">Accent color</span><span className="color-field"><input type="color" value={draft.branding.accent_color} onChange={(e) => setBrand('accent_color', e.target.value.toUpperCase())} /><code>{draft.branding.accent_color}</code></span></label>
              <SelectField label="Sidebar appearance" value={draft.branding.sidebar_appearance} onChange={(e) => setBrand('sidebar_appearance', e.target.value as Branding['sidebar_appearance'])}><option value="solid">Solid</option><option value="subtle">Subtle</option><option value="brand-tinted">Brand tinted</option></SelectField>
              <SelectField label="Card appearance" value={draft.branding.card_appearance} onChange={(e) => setBrand('card_appearance', e.target.value as Branding['card_appearance'])}><option value="flat">Flat</option><option value="outlined">Outlined</option><option value="elevated">Elevated</option></SelectField>
              <SelectField label="Corner radius" value={draft.branding.corner_radius} onChange={(e) => setBrand('corner_radius', e.target.value as Branding['corner_radius'])}><option value="sharp">Sharp</option><option value="balanced">Balanced</option><option value="soft">Soft</option></SelectField>
              <SelectField label="Density" value={draft.branding.density} onChange={(e) => setBrand('density', e.target.value as Branding['density'])}><option value="comfortable">Comfortable</option><option value="compact">Compact</option></SelectField>
              <SelectField label="Heading style" value={draft.branding.heading_style} onChange={(e) => setBrand('heading_style', e.target.value as Branding['heading_style'])}><option value="modern">Modern</option><option value="editorial">Editorial</option></SelectField>
              <SelectField label="School-name masthead" value={draft.branding.masthead_style} onChange={(e) => setBrand('masthead_style', e.target.value as Branding['masthead_style'])}><option value="prominent">Prominent</option><option value="compact">Compact</option></SelectField>
              <SelectField label="Motion" value={draft.branding.motion} onChange={(e) => setBrand('motion', e.target.value as Branding['motion'])}><option value="off">Off</option><option value="subtle">Subtle</option><option value="expressive">Expressive</option></SelectField>
              <SelectField label="Page background" value={draft.branding.page_background} onChange={(e) => setBrand('page_background', e.target.value as Branding['page_background'])}><option value="plain">Plain</option><option value="soft-tint">Soft tint</option><option value="gradient">Subtle gradient accent</option></SelectField>
              <SelectField label="Logo size" value={draft.branding.logo_size} onChange={(e) => setBrand('logo_size', e.target.value as Branding['logo_size'])}><option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option></SelectField>
              <SelectField label="Logo placement" value={draft.branding.logo_placement} onChange={(e) => setBrand('logo_placement', e.target.value as Branding['logo_placement'])}><option value="beside">Beside school name</option><option value="above">Above school name</option></SelectField>
              <label className="switch-field"><input type="checkbox" checked={draft.branding.sidebar_collapsed} onChange={(e) => setBrand('sidebar_collapsed', e.target.checked)} /><span><strong>Compact sidebar preference</strong><small>Use a narrower navigation rail on wide screens.</small></span></label>
              <label className="switch-field"><input type="checkbox" checked={draft.branding.logo_with_school_name} onChange={(e) => setBrand('logo_with_school_name', e.target.checked)} /><span><strong>Show school name beside logo</strong><small>Keep the text identity visible with the mark.</small></span></label>
            </div>
            <div className="brand-form-footer"><Button variant="secondary" onClick={defaults}><RefreshCw size={15} /> Reset visual profile</Button><span className="muted-text">Reset changes the draft only. Save to publish.</span></div>
          </Card>
        </div>
        <aside className="brand-preview-column"><Card className="preview-card"><div className="section-heading"><div><h2>Live preview</h2><p>Unsaved draft · shared identity</p></div><Sparkles size={19} /></div>
          <div className="preview-surface" data-theme-preview={preview.branding.appearance === 'dark' ? 'dark' : 'light'} data-preview-logo-size={preview.branding.logo_size} style={{ '--preview-primary': preview.branding.primary_color, '--preview-accent': preview.branding.accent_color, '--brand-primary': preview.branding.primary_color, '--brand-accent': preview.branding.accent_color, '--brand-primary-contrast': readableText(preview.branding.primary_color) } as React.CSSProperties}>
            <div className="preview-header"><div className="preview-brand" style={{ flexDirection: preview.branding.logo_placement === 'above' ? 'column' : 'row', alignItems: 'flex-start' }}><BrandMark name={preview.school_name} logoUrl={preview.logo_url} size="lg" />{preview.branding.logo_with_school_name ? <div><small>PRINCIPAL PORTAL</small><strong>{preview.school_name || 'Your school name'}</strong></div> : <small>PRINCIPAL PORTAL</small>}</div><span className="preview-user">Principal</span></div>
            <div className="preview-body"><span className="preview-kicker">SCHOOL OVERVIEW</span><h3>{preview.school_name || 'Your school name'}</h3><p>Clear school operations, one shared identity.</p><div className="preview-metrics"><span><b>—</b><small>Students</small></span><span><b>—</b><small>Classes</small></span><span><b>—</b><small>Attendance</small></span></div><span className="preview-button">Primary action preview</span></div>
          </div>
          <div className="preview-divider" />
          <div className="preview-label">Teacher portal</div>
          <div className="teacher-preview" data-preview-logo-size={preview.branding.logo_size} style={{ flexDirection: preview.branding.logo_placement === 'above' ? 'column' : 'row', alignItems: 'flex-start', '--brand-primary': preview.branding.primary_color, '--brand-accent': preview.branding.accent_color, '--brand-primary-contrast': readableText(preview.branding.primary_color) } as React.CSSProperties}><BrandMark name={preview.school_name} logoUrl={preview.logo_url} size="lg" />{preview.branding.logo_with_school_name ? <div><strong>{preview.school_name || 'Your school name'}</strong><small>Teacher workspace · Shared identity</small></div> : <small>Teacher workspace · Shared identity</small>}<span className="preview-chip">Teacher</span></div>
          <div className="contrast-note"><span className="contrast-swatch" style={{ background: preview.branding.primary_color, color: readableText(preview.branding.primary_color) }}>Aa</span><span><strong>Primary button contrast</strong><small>Foreground automatically adjusts to the selected brand color.</small></span></div>
        </Card><Notice tone="info">Changes apply to both Admin and Teacher portals after saving. Your operating system’s reduced-motion preference always takes priority.</Notice><Notice tone="warning">Logo images are loaded from the URL you provide. Use a trusted HTTPS host; remote availability is checked by the browser, not fetched by the backend.</Notice></aside>
      </div> : null}
    </QueryPanel>
  </>;
}

export function AdminSecurityPage() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [resetPhrase, setResetPhrase] = useState('');
  const queryClient = useQueryClient();
  const mutation = useMutation({ mutationFn: () => api.admin.changePassword({ current_password: current, new_password: next }), onSuccess: () => { setCurrent(''); setNext(''); setConfirm(''); toast.success('Password updated. Other sessions were signed out.'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Password update failed') });
  const resetMutation = useMutation({
    mutationFn: () => api.admin.resetSchoolData({ current_password: resetPassword, confirmation: 'RESET SCHOOL DATA' }),
    onSuccess: async (result) => {
      setResetPassword(''); setResetPhrase('');
      await queryClient.invalidateQueries();
      toast.success(result.message);
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'School data reset failed'),
  });
  return <><PageHeader title="Account & security" description="Protect the Principal account and review the school’s authentication boundary." />
    <div className="security-grid"><Card className="panel-card"><div className="section-heading"><div><h2>Change Principal password</h2><p>Use a unique password with at least 12 characters.</p></div><KeyRound size={19} /></div>
      <form className="stack-form" onSubmit={(e) => { e.preventDefault(); if (next !== confirm) { toast.error('The new passwords do not match.'); return; } mutation.mutate(); }}><TextField label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required /><TextField label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} minLength={12} required /><TextField label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} minLength={12} required /><Button type="submit" loading={mutation.isPending} disabled={!current || next.length < 12 || !confirm}>Update password</Button></form>
    </Card><Card className="panel-card"><div className="section-heading"><div><h2>Security principles</h2><p>SCOLIQ AI keeps authorization on the backend.</p></div><ShieldCheck size={19} /></div><ul className="security-list"><li><CheckCircle2 size={17} /><span>Principal-only endpoints require a valid server-side session.</span></li><li><CheckCircle2 size={17} /><span>Teacher accounts authenticate with passkeys and remain class-scoped.</span></li><li><CheckCircle2 size={17} /><span>Session cookies are HttpOnly; mutation requests use CSRF protection.</span></li><li><CheckCircle2 size={17} /><span>No database credentials or privileged API keys are sent to the browser.</span></li></ul></Card></div>
    <Card className="panel-card" style={{ marginTop: 24 }}>
      <div className="section-heading"><div><h2>Reset school operational data</h2><p>Remove teachers, requests, classes, students, biometric templates and attendance. Principal login and school branding stay intact.</p></div><ShieldCheck size={19} /></div>
      <Notice tone="warning">This action is permanent for the live database. It also clears historical audit entries because they may contain staff or student identifiers. Database-provider backups and external logs are not erased by this action. Export a backup before continuing.</Notice>
      <form className="stack-form" onSubmit={(e) => { e.preventDefault(); if (resetPhrase !== 'RESET SCHOOL DATA') { toast.error('Type RESET SCHOOL DATA exactly to confirm.'); return; } resetMutation.mutate(); }}>
        <TextField label="Principal current password" type="password" autoComplete="current-password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} required />
        <TextField label="Type RESET SCHOOL DATA to confirm" value={resetPhrase} onChange={(e) => setResetPhrase(e.target.value)} required />
        <Button type="submit" variant="danger" loading={resetMutation.isPending} disabled={!resetPassword || resetPhrase !== 'RESET SCHOOL DATA'}>Permanently reset school data</Button>
      </form>
    </Card>
  </>;
}
