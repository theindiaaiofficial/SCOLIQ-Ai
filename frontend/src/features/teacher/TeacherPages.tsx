import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowRight, BookOpen, CalendarCheck, Camera, CheckCircle2, Fingerprint,
  GraduationCap, KeyRound, Plus, RefreshCw, SwitchCamera, Users,
} from 'lucide-react';
import { api, ApiError } from '../../api/client';
import type { AttendanceReview } from '../../api/types';
import { useClassScope } from '../../components/PortalShells';
import { useBrand } from '../branding/BrandProvider';
import {
  Button, Card, ConfirmButton, EmptyState, ErrorState, LoadingState, Modal, Notice,
  PageHeader, Pagination, SearchField, SelectField, StatusPill, Table, TextField,
} from '../../components/ui';

function useClassQueryKey(base: string, classId: string | null) { return [base, classId] as const; }

export function TeacherDashboardPage() {
  const { classId } = useClassScope();
  const classQuery = useQuery({ queryKey: useClassQueryKey('teacher-class', classId), queryFn: () => api.teacher.currentClass(classId), enabled: Boolean(classId), retry: false });
  const health = useQuery({ queryKey: ['service-health'], queryFn: async () => {
    const response = await fetch('/health/ready', { credentials: 'include' });
    if (!response.ok) throw new Error('Service readiness is not available');
    return response.json() as Promise<{ status: string; database: string; face_provider: string }>;
  }, retry: false, staleTime: 60_000 });
  const students = useQuery({ queryKey: useClassQueryKey('teacher-students', classId), queryFn: () => api.teacher.students('', 1, classId), enabled: Boolean(classId) });
  const readyForAttendance = Boolean(classId);
  const manualMode = !health.data || ['manual', 'unavailable', 'fake'].includes(health.data.face_provider);
  return <>
    <PageHeader title="My classroom" description="Everything you need to keep your class roster and morning attendance up to date." actions={<Button onClick={() => window.location.assign('/teacher/attendance')} disabled={!readyForAttendance}><CalendarCheck size={16} /> Open attendance</Button>} />
    {classQuery.isError && classQuery.error instanceof Error && classQuery.error.message.includes('No active class') ? <ClassSetupPrompt /> : classQuery.isLoading ? <LoadingState label="Loading your class details…" /> : classQuery.data ? <>
      <div className="metrics-grid teacher-metrics">
        <div className="metric-card card"><span className="metric-icon metric-violet"><GraduationCap size={19} /></span><span className="metric-label">Students in my class</span><strong className="metric-value">{classQuery.data.total_enrolled_students}</strong><span className="metric-detail">Active enrollments</span></div>
        <div className="metric-card card"><span className="metric-icon metric-green"><BookOpen size={19} /></span><span className="metric-label">My class</span><strong className="metric-value metric-value-class">Grade {classQuery.data.grade} · {classQuery.data.section}</strong><span className="metric-detail">Academic year {classQuery.data.academic_year}</span></div>
        <div className="metric-card card"><span className="metric-icon metric-amber"><CalendarCheck size={19} /></span><span className="metric-label">Attendance workspace</span><strong className="metric-value metric-value-class">Ready when you are</strong><span className="metric-detail">Review and submit manually</span></div>
        <div className="metric-card card"><span className="metric-icon metric-blue"><Fingerprint size={19} /></span><span className="metric-label">Identification mode</span><strong className="metric-value metric-value-class">{manualMode ? 'Manual' : 'Configured'}</strong><span className="metric-detail">{manualMode ? 'Manual attendance is active' : 'Provider configured; verify readiness'}</span></div>
      </div>
      <div className="dashboard-grid">
        <Card className="panel-card"><div className="section-heading"><div><h2>Start your day</h2><p>Open today’s attendance and confirm each student’s status.</p></div><CalendarCheck size={19} /></div><div className="attendance-launch"><div className="launch-icon"><CalendarCheck size={24} /></div><div><strong>Morning attendance</strong><span>Review, confirm and submit your class attendance.</span></div><Button onClick={() => window.location.assign('/teacher/attendance')}>Go to attendance <ArrowRight size={15} /></Button></div>{manualMode ? <Notice tone="info">Manual attendance mode is active. Face identification is not enabled, and the attendance workspace will not display a simulated scanner.</Notice> : null}</Card>
        <Card className="panel-card"><div className="section-heading"><div><h2>Roster snapshot</h2><p>Your current class enrollment.</p></div><Users size={19} /></div>{students.isLoading ? <LoadingState label="Loading roster…" /> : students.data?.items.length ? <div className="mini-roster">{students.data.items.slice(0, 5).map((student) => <div className="mini-roster-row" key={student.student_id}><span className="avatar avatar-muted">{student.full_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join('')}</span><span><strong>{student.full_name}</strong><small>Roll {student.roll_number}</small></span><StatusPill value={student.consent_status} /></div>)}<a className="text-link" href="/teacher/students">View all students <ArrowRight size={14} /></a></div> : <EmptyState title="No students enrolled" description="Add students to build your class roster." action={<a href="/teacher/students" className="button button-secondary">Add student</a>} />}</Card>
      </div>
    </> : classQuery.isError ? <ErrorState message={classQuery.error instanceof Error ? classQuery.error.message : 'Unable to load your class.'} onRetry={() => void classQuery.refetch()} /> : <ClassSetupPrompt />}
  </>;
}

function ClassSetupPrompt() {
  const { brand } = useBrand();
  return <Card className="panel-card class-setup-prompt"><div className="large-empty-icon"><BookOpen size={25} /></div><div><h2>Your class is not set up yet</h2><p>Complete class setup using the academic year configured by {brand.school_name}. If your class already has a teacher, contact the Principal to resolve the assignment.</p><a className="button button-primary" href="/teacher/class-setup">Set up my class <ArrowRight size={15} /></a></div></Card>;
}


export function ClassSetupPage() {
  const { brand } = useBrand();
  const [grade, setGrade] = useState('');
  const [section, setSection] = useState('');
  const [year, setYear] = useState('');
  const queryClient = useQueryClient();
  const mutation = useMutation({ mutationFn: () => api.teacher.setupClass({ grade_label: grade.trim(), section_label: section.trim(), academic_year: year.trim() }), onSuccess: async () => { toast.success('Class setup completed'); await queryClient.invalidateQueries({ queryKey: ['teacher-me'] }); window.location.assign('/teacher/dashboard'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Class setup failed') });
  return <><PageHeader title="Set up your class" description={`Create or claim the class assignment for ${brand.school_name}.`} />
    <Card className="panel-card setup-card"><div className="setup-intro"><BookOpen size={22} /><div><h2>Class details</h2><p>The Principal can resolve ownership conflicts or reassign a class if needed.</p></div></div>
      <form className="form-grid" onSubmit={(e) => { e.preventDefault(); mutation.mutate(); }}><TextField label="Grade / class" value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="Example: 8" required /><TextField label="Section" value={section} onChange={(e) => setSection(e.target.value)} placeholder="Example: A" required /><TextField label="Academic year" value={year} onChange={(e) => setYear(e.target.value)} placeholder="Example: 2026-27" hint="Must match the school's configured academic year." required /><div className="form-span"><Button type="submit" loading={mutation.isPending} disabled={!grade.trim() || !section.trim() || year.trim().length < 4}>Save class assignment</Button></div></form>
      <Notice tone="info">One active class teacher is supported per class, section and academic year. The backend verifies that the assignment is available.</Notice>
    </Card>
  </>;
}

export function TeacherStudentsPage() {
  const { classId } = useClassScope();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [addOpen, setAddOpen] = useState(false);
  const [name, setName] = useState('');
  const [roll, setRoll] = useState('');
  const [code, setCode] = useState('');
  const [faceStudent, setFaceStudent] = useState<{ id: string; name: string; consent: string } | null>(null);
  const [editStudent, setEditStudent] = useState<{ id: string; name: string; roll: string; status: 'ACTIVE' | 'TRANSFERRED' | 'INACTIVE' } | null>(null);
  const [detailStudentId, setDetailStudentId] = useState<string | null>(null);
  const [consentStudent, setConsentStudent] = useState<{ id: string; name: string; status: 'GRANTED' | 'WITHDRAWN' } | null>(null);
  const [consentMethod, setConsentMethod] = useState('Guardian consent form');
  const [consentReference, setConsentReference] = useState('');
  useEffect(() => { setPage(1); setSearch(''); setFaceStudent(null); setEditStudent(null); setDetailStudentId(null); setConsentStudent(null); }, [classId]);
  const students = useQuery({ queryKey: ['teacher-students', classId, search, page], queryFn: () => api.teacher.students(search, page, classId), enabled: Boolean(classId) });
  const teacherMe = useQuery({ queryKey: ['teacher-me'], queryFn: api.teacher.me, staleTime: 30_000 });
  const queryClient = useQueryClient();
  const add = useMutation({ mutationFn: () => api.teacher.createStudent({ full_name: name.trim(), roll_number: roll.trim(), school_student_code: code.trim() || null }, classId), onSuccess: async () => { setAddOpen(false); setName(''); setRoll(''); setCode(''); await queryClient.invalidateQueries({ queryKey: ['teacher-students'] }); await queryClient.invalidateQueries({ queryKey: ['teacher-class'] }); toast.success('Student added. Guardian consent is pending.'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Student could not be added') });
  const update = useMutation({
    mutationFn: () => {
      if (!editStudent) throw new Error('Select a student record first.');
      return api.teacher.updateStudent(editStudent.id, { full_name: editStudent.name.trim(), roll_number: editStudent.roll.trim(), status: editStudent.status }, classId);
    },
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['teacher-students'] }); await queryClient.invalidateQueries({ queryKey: ['teacher-class'] }); setEditStudent(null); toast.success('Student record updated'); },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Student record could not be updated'),
  });
  const recordConsent = useMutation({
    mutationFn: () => {
      if (!consentStudent) throw new Error('Choose a student first.');
      return api.teacher.recordGuardianConsent(consentStudent.id, { consent_status: consentStudent.status, consent_method: consentMethod.trim(), consent_record_reference: consentReference.trim() }, classId);
    },
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['teacher-students'] }); await queryClient.invalidateQueries({ queryKey: ['teacher-student-detail'] }); setConsentStudent(null); setConsentReference(''); toast.success('Guardian consent record saved and audited'); },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Consent record could not be saved'),
  });
  const health = useQuery({ queryKey: ['service-health'], queryFn: async () => { const response = await fetch('/health/ready'); if (!response.ok) throw new Error('Readiness unavailable'); return response.json() as Promise<{ face_provider: string }>; }, retry: false });
  const realFaceEnabled = Boolean(health.data?.face_provider && !['manual', 'unavailable', 'fake'].includes(health.data.face_provider));
  const canRecordConsent = Boolean(teacherMe.data?.can_record_guardian_consent);
  return <><PageHeader title="My students" description="View and maintain your current class roster and verified guardian-consent records." actions={<Button onClick={() => setAddOpen(true)} disabled={!classId}><Plus size={16} /> Add student</Button>} />
    {canRecordConsent ? <Notice tone="success">The Principal has delegated guardian-consent recording to you. Record only permission actually received from the parent or guardian, and enter its real reference. This action is audited.</Notice> : <Notice tone="info">Guardian consent remains PENDING until the Principal or a Principal-authorized teacher records verified permission. Adding a student never grants consent automatically.</Notice>}
    {realFaceEnabled ? <Notice tone="warning">Face enrollment is available only when the latest guardian-consent record is GRANTED.</Notice> : <Notice tone="info">Manual attendance mode is active. Face enrollment and scanning are unavailable; no simulated camera recognition is shown.</Notice>}
    <Card className="panel-card"><div className="toolbar"><SearchField value={search} onChange={(value) => { setSearch(value); setPage(1); }} placeholder="Search by student name or roll number" /><span className="toolbar-count">{students.data?.total ?? 0} students</span></div>
      {students.isLoading ? <LoadingState /> : students.isError ? <ErrorState message={students.error instanceof Error ? students.error.message : 'Could not load roster.'} requestId={students.error instanceof ApiError ? students.error.requestId : undefined} onRetry={() => void students.refetch()} /> : students.data?.items.length ? <Table><thead><tr><th>Student</th><th>Roll number</th><th>Consent</th><th>Face enrollment</th><th>Roster status</th><th>Actions</th></tr></thead><tbody>{students.data.items.map((student) => <tr key={student.student_id}><td><strong>{student.full_name}</strong><small className="table-subtext">{student.school_student_code || 'No school code'}</small></td><td>{student.roll_number}</td><td><StatusPill value={student.consent_status} /></td><td>{student.face_enrolled ? <StatusPill value="ENROLLED" /> : realFaceEnabled && student.consent_status === 'GRANTED' ? <Button size="sm" variant="outline" onClick={() => setFaceStudent({ id: student.student_id, name: student.full_name, consent: student.consent_status })}>Enroll face template</Button> : <span className="muted-text">{realFaceEnabled ? 'Consent required' : 'Manual mode'}</span>}</td><td><StatusPill value={student.status} /></td><td><div className="row-actions">{canRecordConsent ? <Button size="sm" variant="outline" onClick={() => { setConsentStudent({ id: student.student_id, name: student.full_name, status: student.consent_status === 'GRANTED' ? 'WITHDRAWN' : 'GRANTED' }); setConsentMethod('Guardian consent form'); setConsentReference(''); }}>{student.consent_status === 'GRANTED' ? 'Withdraw consent' : 'Record consent'}</Button> : null}<Button size="sm" variant="ghost" onClick={() => setDetailStudentId(student.student_id)}>View</Button><Button size="sm" variant="outline" onClick={() => setEditStudent({ id: student.student_id, name: student.full_name, roll: student.roll_number, status: student.status as 'ACTIVE' | 'TRANSFERRED' | 'INACTIVE' })}>Edit</Button></div></td></tr>)}</tbody></Table> : <EmptyState icon={<GraduationCap size={23} />} title="Your class roster is empty" description="Add a student to start building the roster for this academic year." action={<Button onClick={() => setAddOpen(true)}><Plus size={15} /> Add student</Button>} />}
      {students.data ? <Pagination page={students.data.page} pageSize={students.data.page_size} total={students.data.total} onPageChange={setPage} /> : null}
    </Card>
    {addOpen ? <Modal title="Add student" description="Student details are saved to your assigned class. Consent is set to PENDING and can only be verified by the Principal." onClose={() => setAddOpen(false)}><form className="stack-form" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}><TextField label="Student full name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /><TextField label="Roll number" value={roll} onChange={(e) => setRoll(e.target.value)} required /><TextField label="School student code (optional)" value={code} onChange={(e) => setCode(e.target.value)} /><Notice tone="info">No student mobile number or unnecessary guardian details are collected here. Consent remains pending.</Notice><div className="modal-actions"><Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button><Button type="submit" loading={add.isPending} disabled={!classId || name.trim().length < 2 || !roll.trim()}>Add to roster</Button></div></form></Modal> : null}
    {consentStudent ? <Modal title={consentStudent.status === 'GRANTED' ? 'Record guardian consent' : 'Withdraw guardian consent'} description={`Student: ${consentStudent.name}. Enter the real record details from the parent or guardian.`} onClose={() => { if (!recordConsent.isPending) setConsentStudent(null); }}>
      <div className="stack-form"><Notice tone={consentStudent.status === 'GRANTED' ? 'warning' : 'info'}>{consentStudent.status === 'GRANTED' ? 'Only continue after the parent or legal guardian has explicitly agreed to face processing. Do not create a consent record based on assumption.' : 'Withdrawal immediately removes the active face template. Manual attendance remains available.'}</Notice><TextField label="Consent method" value={consentMethod} onChange={(e) => setConsentMethod(e.target.value)} maxLength={80} required /><TextField label="Actual consent record reference" value={consentReference} onChange={(e) => setConsentReference(e.target.value)} maxLength={255} placeholder="School form / register reference" required /><div className="modal-actions"><Button variant="ghost" disabled={recordConsent.isPending} onClick={() => setConsentStudent(null)}>Cancel</Button><Button loading={recordConsent.isPending} disabled={consentMethod.trim().length < 3 || consentReference.trim().length < 3} onClick={() => recordConsent.mutate()}>{consentStudent.status === 'GRANTED' ? 'Save verified consent' : 'Confirm withdrawal'}</Button></div></div>
    </Modal> : null}
    {editStudent ? <Modal title="Edit student record" description="Updates apply only to the student in your assigned class. Status changes are recorded by the backend." onClose={() => { if (!update.isPending) setEditStudent(null); }}>
      <div className="stack-form"><TextField label="Student full name" value={editStudent.name} onChange={(event) => setEditStudent({ ...editStudent, name: event.target.value })} minLength={2} maxLength={180} /><TextField label="Roll number" value={editStudent.roll} onChange={(event) => setEditStudent({ ...editStudent, roll: event.target.value })} maxLength={32} /><SelectField label="Roster status" value={editStudent.status} onChange={(event) => setEditStudent({ ...editStudent, status: event.target.value as 'ACTIVE' | 'TRANSFERRED' | 'INACTIVE' })}><option value="ACTIVE">Active</option><option value="TRANSFERRED">Transferred</option><option value="INACTIVE">Inactive</option></SelectField>
        {editStudent.status !== 'ACTIVE' ? <Notice tone="warning">This status removes the student from the active class roster and current attendance totals.</Notice> : null}
        <div className="modal-actions"><Button variant="ghost" disabled={update.isPending} onClick={() => setEditStudent(null)}>Cancel</Button><Button loading={update.isPending} disabled={editStudent.name.trim().length < 2 || !editStudent.roll.trim()} onClick={() => update.mutate()}>Save student changes</Button></div>
      </div>
    </Modal> : null}
    {detailStudentId ? <StudentDetailModal studentId={detailStudentId} classId={classId} onClose={() => setDetailStudentId(null)} /> : null}
    {faceStudent ? <FaceEnrollmentModal student={faceStudent} onClose={() => setFaceStudent(null)} classId={classId} /> : null}
  </>;
}

function StudentDetailModal({ studentId, classId, onClose }: { studentId: string; classId: string | null; onClose: () => void }) {
  const query = useQuery({ queryKey: ['teacher-student-detail', classId, studentId], queryFn: () => api.teacher.student(studentId, classId), enabled: Boolean(studentId && classId) });
  return <Modal title="Student details" description="Record details are retrieved from the backend for your currently assigned class." onClose={onClose}>
    {query.isLoading ? <LoadingState label="Loading student details…" /> : query.isError ? <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load student details.'} requestId={query.error instanceof ApiError ? query.error.requestId : undefined} onRetry={() => void query.refetch()} /> : query.data ? <dl className="detail-list"><div><dt>Full name</dt><dd>{query.data.full_name}</dd></div><div><dt>Roll number</dt><dd>{query.data.roll_number}</dd></div><div><dt>School student code</dt><dd>{query.data.school_student_code || 'Not supplied'}</dd></div><div><dt>Roster status</dt><dd><StatusPill value={query.data.status} /></dd></div><div><dt>Guardian consent</dt><dd><StatusPill value={query.data.consent_status} /></dd></div><div><dt>Enrollment reference</dt><dd><code className="small-code">{query.data.enrollment_id}</code></dd></div></dl> : null}
  </Modal>;
}

type FaceGuidanceData = {
  face_detected: boolean;
  pose_bucket: string;
  quality_grade: string;
  capture_ready: boolean;
  guidance: string[];
  metrics: Record<string, number | number[] | null>;
};

type LiveCaptureMode = 'enrollment' | 'attendance-fast' | 'attendance-guided';

const FRONT_STAGE = { bucket: 'front', title: 'Front', instruction: 'Look straight at the camera.' } as const;
const LEFT_STAGE = { bucket: 'turn_left', title: 'Left', instruction: 'Turn your head slightly to your left.' } as const;
const RIGHT_STAGE = { bucket: 'turn_right', title: 'Right', instruction: 'Turn your head slightly to your right.' } as const;
const LIVE_ENROLLMENT_STAGES = [FRONT_STAGE, LEFT_STAGE, RIGHT_STAGE] as const;

function FaceCaptureCamera({
  classId,
  onCaptured,
  onCancel,
  onRetry,
  processing = false,
  mode = 'enrollment',
}: {
  classId: string | null;
  onCaptured: (files: File[]) => void;
  onCancel: () => void;
  onRetry: () => void;
  processing?: boolean;
  mode?: LiveCaptureMode;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const callbackRef = useRef(onCaptured);
  const streamRef = useRef<MediaStream | null>(null);
  const [capturedCount, setCapturedCount] = useState(0);
  const [guidance, setGuidance] = useState('Starting camera');
  const [analysis, setAnalysis] = useState<FaceGuidanceData | null>(null);
  const [cameraError, setCameraError] = useState('');
  const [complete, setComplete] = useState(false);
  const [poseVisual, setPoseVisual] = useState<'waiting' | 'good' | 'bad'>('waiting');
  const [cameraFacingMode, setCameraFacingMode] = useState<'user' | 'environment'>('user');
  const [activeCameraFacingMode, setActiveCameraFacingMode] = useState<'user' | 'environment'>('user');

  const stages = mode === 'attendance-fast'
    ? [FRONT_STAGE]
    : mode === 'attendance-guided'
      ? [LEFT_STAGE, RIGHT_STAGE]
      : LIVE_ENROLLMENT_STAGES;
  const stableFramesRequired = mode === 'enrollment' ? 3 : mode === 'attendance-fast' ? 1 : 2;
  const analysisIntervalMs = mode === 'enrollment' ? 650 : mode === 'attendance-fast' ? 220 : 300;
  const stage = stages[Math.min(capturedCount, stages.length - 1)] ?? FRONT_STAGE;
  const isAttendance = mode !== 'enrollment';
  const directionLabel = stage.bucket === 'turn_left' ? 'TURN LEFT' : stage.bucket === 'turn_right' ? 'TURN RIGHT' : 'FACE CAMERA';

  useEffect(() => { callbackRef.current = onCaptured; }, [onCaptured]);

  useEffect(() => {
    let cancelled = false;
    let busy = false;
    let timer: number | undefined;
    let currentStage = 0;
    let stable = 0;
    let consecutiveErrors = 0;
    const captured: File[] = [];
    const stopStream = () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };

    const captureFrame = (video: HTMLVideoElement): Promise<Blob | null> => new Promise((resolve) => {
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 960 / video.videoWidth);
      canvas.width = Math.max(160, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(160, Math.round(video.videoHeight * scale));
      const context = canvas.getContext('2d');
      if (!context) return resolve(null);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.84);
    });

    const analyze = async () => {
      const video = videoRef.current;
      if (cancelled || busy || !video || video.readyState < 2 || !video.videoWidth || currentStage >= stages.length) return;
      busy = true;
      try {
        const blob = await captureFrame(video);
        if (!blob || cancelled) return;
        const current = stages[currentStage];
        const previewFile = new File([blob], `live-${current.bucket}.jpg`, { type: 'image/jpeg' });
        const result = await api.teacher.faceCaptureGuidance(previewFile, classId);
        consecutiveErrors = 0;
        if (cancelled) return;
        setAnalysis(result);
        const poseMatches = result.face_detected && result.pose_bucket === current.bucket;
        const ready = poseMatches && result.capture_ready;
        setPoseVisual(!result.face_detected ? 'waiting' : ready ? 'good' : 'bad');
        if (ready) {
          stable += 1;
          setGuidance(stable >= stableFramesRequired ? 'Pose locked' : 'Hold this position');
          if (stable >= stableFramesRequired) {
            captured.push(new File([blob], `${current.bucket}-${Date.now()}.jpg`, { type: 'image/jpeg' }));
            currentStage += 1;
            stable = 0;
            setCapturedCount(currentStage);
            if (currentStage >= stages.length) {
              setComplete(true);
              setPoseVisual('good');
              setGuidance('Capture complete');
              stopStream();
              callbackRef.current(captured);
            } else {
              setPoseVisual('waiting');
              setGuidance('Follow the next arrow');
            }
          }
        } else {
          stable = 0;
          if (!result.face_detected) setGuidance('Move face into the frame');
          else if (!result.capture_ready) setGuidance(result.guidance?.[0] || 'Improve light and hold steady');
          else setGuidance('Follow the arrow');
        }
      } catch (error) {
        consecutiveErrors += 1;
        if (!cancelled) {
          const message = error instanceof Error ? error.message : 'Live camera analysis failed.';
          if (error instanceof ApiError || consecutiveErrors >= 3) {
            setCameraError(message);
            setPoseVisual('bad');
            stopStream();
          } else {
            setGuidance('Reconnecting camera analysis');
          }
        }
      } finally {
        busy = false;
      }
    };

    const start = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera requires HTTPS. Open the secure tunnel URL.');
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: cameraFacingMode }, width: { ideal: 1280 }, height: { ideal: 720 } },
        });
        if (cancelled) { stream.getTracks().forEach((track) => track.stop()); return; }
        streamRef.current = stream;
        const actualFacing = stream.getVideoTracks()[0]?.getSettings().facingMode;
        setActiveCameraFacingMode(actualFacing === 'environment' ? 'environment' : actualFacing === 'user' ? 'user' : cameraFacingMode);
        const video = videoRef.current;
        if (!video) throw new Error('Camera preview is unavailable.');
        video.srcObject = stream;
        await video.play();
        setGuidance('Find your face');
        timer = window.setInterval(() => { void analyze(); }, analysisIntervalMs);
        void analyze();
      } catch (error) {
        if (!cancelled) setCameraError(error instanceof Error ? error.message : 'Camera permission was not granted.');
      }
    };
    void start();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
      stopStream();
    };
  }, [classId, mode, analysisIntervalMs, stableFramesRequired, cameraFacingMode]);

  const progressCount = Math.min(capturedCount, stages.length);
  const arrowPath = stage.bucket === 'turn_left'
    ? { path: 'M155 45 C125 8 75 8 45 45', head: 'M45 45 L67 27 M45 45 L67 63' }
    : stage.bucket === 'turn_right'
      ? { path: 'M25 45 C55 8 105 8 135 45', head: 'M135 45 L113 27 M135 45 L113 63' }
      : { path: 'M90 78 C90 56 90 39 90 18', head: 'M90 18 L70 39 M90 18 L110 39' };

  return <div className={`live-face-capture live-face-capture--fullscreen ${isAttendance ? 'is-attendance' : 'is-enrollment'}`}>
    <div className="live-camera-frame">
      <video ref={videoRef} autoPlay muted playsInline className={`live-camera-video ${activeCameraFacingMode === 'user' ? 'is-selfie' : 'is-rear'}`} />
      {!complete && !cameraError ? <div className={`live-camera-reticle state-${poseVisual}`}><span /><span /><span /><span /></div> : null}
      {!complete && !cameraError ? <div className={`live-camera-arrow state-${poseVisual} ${activeCameraFacingMode === 'user' ? 'is-selfie-mirrored' : 'is-rear-normal'}`} aria-hidden="true">
        <svg viewBox="0 0 180 90" role="presentation"><path className="live-arrow-wave" d={arrowPath.path} /><path className="live-arrow-head" d={arrowPath.head} /></svg>
      </div> : null}
      {complete ? <div className="live-camera-success"><div className="live-success-ring"><CheckCircle2 size={46} /></div><strong>{isAttendance ? 'FACE CAPTURED' : 'ENROLLMENT CAPTURED'}</strong><span>{mode === 'attendance-fast' ? 'Checking identity…' : mode === 'attendance-guided' ? 'Extra angles captured · checking identity…' : 'Front · Left · Right'}</span></div> : null}
      {cameraError ? <div className="live-camera-error"><Camera size={30} /><strong>CAMERA UNAVAILABLE</strong><span>{cameraError}</span></div> : null}
    </div>
    <div className="live-camera-topbar"><div className="live-camera-brand"><span className="live-camera-brand-dot" /><div><strong>SCOLIQ AI</strong><small>{isAttendance ? 'FACE IDENTIFICATION' : 'FACE ENROLLMENT'}</small></div></div><div className="live-camera-top-actions"><span className="live-camera-lens-label">{activeCameraFacingMode === 'user' ? 'SELFIE' : 'REAR'}</span><button type="button" className="live-camera-switch" onClick={() => { setCapturedCount(0); setAnalysis(null); setGuidance('Switching camera'); setCameraError(''); setComplete(false); setPoseVisual('waiting'); setCameraFacingMode((current) => current === 'user' ? 'environment' : 'user'); }} aria-label="Switch front or rear camera"><SwitchCamera size={19} /></button><button type="button" onClick={onCancel} aria-label="Close face camera">×</button></div></div>
    {!complete && !cameraError ? <div className={`live-camera-direction state-${poseVisual}`}>
      <span className="live-camera-direction-kicker">{mode === 'attendance-guided' ? 'GUIDED RETRY' : mode === 'attendance-fast' ? 'QUICK CHECK' : 'POSE GUIDE'}</span>
      <strong>{directionLabel}</strong>
      <span>{poseVisual === 'good' ? 'HOLD · POSITION LOCKING' : poseVisual === 'bad' ? 'ADJUST TO THE ARROW' : 'CENTER YOUR FACE'}</span>
    </div> : null}
    {!cameraError ? <div className="live-camera-progress" aria-label={`${progressCount} of ${stages.length} poses captured`}>
      {stages.map((item, index) => <span key={item.bucket} className={index < progressCount ? 'is-done' : index === capturedCount ? 'is-current' : ''} />)}
    </div> : null}
    <div className="live-camera-bottom-hud">
      {complete ? <span className="live-camera-status-good">{processing ? 'SECURING FACE TEMPLATE…' : 'CAPTURE COMPLETE'}</span> : cameraError ? <span className="live-camera-status-bad">CAMERA ERROR</span> : <span className={`live-camera-status-${poseVisual}`}>{guidance.toUpperCase()}</span>}
      {analysis && !complete && !cameraError ? <small>{analysis.quality_grade} QUALITY</small> : null}
      {complete || cameraError ? <div className="live-camera-actions">
        {!processing ? <Button variant="secondary" onClick={onRetry}>Try again</Button> : <span className="muted-text">Please wait…</span>}
        <Button variant="ghost" onClick={onCancel}>Close</Button>
      </div> : <small className="live-camera-privacy">Temporary camera frames only · no video recording</small>}
    </div>
  </div>;
}

function FaceEnrollmentModal({ student, onClose, classId }: { student: { id: string; name: string; consent: string }; onClose: () => void; classId: string | null }) {
  const [cameraRun, setCameraRun] = useState(0);
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (files: File[]) => api.teacher.faceEnrollment(student.id, files, classId),
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['teacher-students'] }); toast.success('Three-angle face template encrypted and enrolled'); onClose(); },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Face enrollment failed'),
  });
  return <Modal title="Live guided face enrollment" description={`Enrollment for ${student.name}. The camera will automatically capture front, left and right poses.`} onClose={onClose}>
    <Notice tone="warning">Confirm that the latest guardian-consent record is GRANTED and that explicit permission was actually received before continuing. Do not proceed without that permission.</Notice>
    {student.consent === 'GRANTED' ? <FaceCaptureCamera key={cameraRun} classId={classId} onCaptured={(files) => mutation.mutate(files)} onCancel={onClose} onRetry={() => { mutation.reset(); setCameraRun((value) => value + 1); }} processing={mutation.isPending} /> : <Notice tone="danger">Verified guardian consent is required before face enrollment.</Notice>}
  </Modal>;
}

export function TeacherAttendancePage() {
  const { classId } = useClassScope();
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionClassId, setSessionClassId] = useState<string | null>(classId);
  const [review, setReview] = useState<AttendanceReview | null>(null);
  const [statuses, setStatuses] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [showLiveScanner, setShowLiveScanner] = useState(false);
  const [scannerRun, setScannerRun] = useState(0);
  const [scannerMode, setScannerMode] = useState<'fast' | 'guided'>('fast');
  const [scanResult, setScanResult] = useState<import('../../api/types').FaceIdentifyResult | null>(null);
  const health = useQuery({ queryKey: ['service-health'], queryFn: async () => { const response = await fetch('/health/ready', { credentials: 'include' }); if (!response.ok) throw new Error('Readiness unavailable'); return response.json() as Promise<{ face_provider: string }>; }, retry: false, staleTime: 60_000 });
  const faceProvider = health.data?.face_provider ?? 'unavailable';
  const faceEnabled = !['manual', 'unavailable', 'fake'].includes(faceProvider);
  const [finalResult, setFinalResult] = useState<{ present_count: number; absent_count: number } | null>(null);
  const showingSession = Boolean(sessionId && sessionClassId === classId);
  useEffect(() => {
    setSessionId(null);
    setSessionClassId(classId);
    setReview(null);
    setStatuses({});
    setNotes({});
    setShowLiveScanner(false);
    setScanResult(null);
    setFinalResult(null);
    void queryClient.removeQueries({ queryKey: ['teacher-attendance-session'] });
  }, [classId, queryClient]);
  const sessionQuery = useQuery({ queryKey: ['teacher-attendance-session', sessionClassId, sessionId], queryFn: () => api.teacher.attendanceSession(sessionId!), enabled: showingSession, retry: false });
  const open = useMutation({ mutationFn: () => api.teacher.openAttendance(classId), onSuccess: async (data) => { setSessionClassId(classId); setSessionId(data.session_id); setReview(null); setFinalResult(null); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, data.session_id] }); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not open attendance') });
  const loadReview = useMutation({ mutationFn: (id: string) => api.teacher.attendanceReview(id), onSuccess: async (data) => { setReview(data); const next: Record<string, string> = {}; [...data.marks, ...data.absent_candidates].forEach((mark) => { next[mark.enrollment_id] = mark.status === 'UNCONFIRMED_ABSENT_CANDIDATE' ? '' : mark.status; }); setStatuses(next); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, sessionId] }); } , onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not load review') });
  const identify = useMutation({ mutationFn: (files: File[]) => { if (!sessionId) throw new Error('Open an attendance session first.'); return api.teacher.identify(sessionId, files, classId); }, onSuccess: async (data) => { setScanResult(data); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, sessionId] }); if (scannerMode === 'fast' && ['NO_MATCH', 'AMBIGUOUS'].includes(data.status)) { setScannerMode('guided'); setScannerRun((value) => value + 1); setShowLiveScanner(true); return; } toast.success(data.status === 'MATCHED' ? 'Candidate identified; teacher review is required.' : data.message); setScannerMode('fast'); }, onError: (e) => { if (scannerMode === 'fast' && e instanceof ApiError && ['NO_FACE_DETECTED', 'POOR_FACE_QUALITY', 'FACE_PROCESSING_FAILED'].includes(e.code ?? '')) { setScannerMode('guided'); setScannerRun((value) => value + 1); setShowLiveScanner(true); toast.error('Front scan needs more evidence. Follow the left/right arrows.'); return; } toast.error(e instanceof Error ? e.message : 'Face identification could not be completed'); } });
  const resume = useMutation({ mutationFn: () => api.teacher.resumeScanning(sessionId!), onSuccess: async () => { setReview(null); setScanResult(null); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, sessionId] }); toast.success('Scanning resumed'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not resume scanning') });
  const saveMark = useMutation({ mutationFn: ({ enrollmentId, status }: { enrollmentId: string; status: 'PRESENT' | 'ABSENT' | 'LATE' | 'EXCUSED' }) => api.teacher.markAttendance(sessionId!, enrollmentId, status, notes[enrollmentId] || null), onSuccess: async () => { toast.success('Student status confirmed'); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, sessionId] }); if (sessionId) { const refreshed = await api.teacher.attendanceReview(sessionId); setReview(refreshed); const next: Record<string, string> = {}; [...refreshed.marks, ...refreshed.absent_candidates].forEach((mark) => { next[mark.enrollment_id] = mark.status === 'UNCONFIRMED_ABSENT_CANDIDATE' ? '' : mark.status; }); setStatuses(next); } }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save attendance status') });
  const finalize = useMutation({ mutationFn: () => api.teacher.finalizeAttendance(sessionId!), onSuccess: async (data) => { setReview(null); setFinalResult({ present_count: Number((data as { present_count?: number }).present_count ?? 0), absent_count: Number((data as { absent_count?: number }).absent_count ?? 0) }); await queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session', classId, sessionId] }); toast.success('Attendance submitted and finalized'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Final submission failed') });

  const allMarks = review ? [...review.marks, ...review.absent_candidates] : [];
  const complete = Boolean(review && allMarks.length === review.total_enrolled && allMarks.every((mark) => mark.confirmed));
  const finalized = sessionQuery.data?.status === 'FINALIZED' || Boolean(finalResult);

  return <><PageHeader title="Attendance workspace" description="Work through the roster, confirm every student’s status and submit one final record for today." actions={<Button variant="secondary" onClick={() => { setSessionId(null); setSessionClassId(classId); setReview(null); setStatuses({}); setNotes({}); setShowLiveScanner(false); setScanResult(null); setFinalResult(null); void queryClient.invalidateQueries({ queryKey: ['teacher-attendance-session'] }); }}><RefreshCw size={15} /> Reset view</Button>} />
    {!faceEnabled ? <Notice tone="info">Manual attendance mode is active because the configured face provider is {faceProvider}. No camera scanner is displayed. Manual attendance is fully available; failed identification is never treated as absence.</Notice> : <Notice tone="warning">Face identification is enabled through the configured provider. Capture one student at a time under teacher supervision. Every suggested match remains provisional and must be checked during review.</Notice>}
    {!showingSession ? <Card className="attendance-start-card"><div className="attendance-start-icon"><CalendarCheck size={28} /></div><div><span className="eyebrow">TODAY'S CLASS SESSION</span><h2>Open or resume attendance</h2><p>The system creates at most one attendance session for your assigned class and local school date.</p><Button onClick={() => open.mutate()} loading={open.isPending} disabled={!classId}>Open today's session <ArrowRight size={16} /></Button></div></Card> : sessionQuery.isLoading ? <LoadingState label="Loading attendance session…" /> : sessionQuery.isError ? <ErrorState message={sessionQuery.error instanceof Error ? sessionQuery.error.message : 'Could not load session.'} onRetry={() => void sessionQuery.refetch()} /> : sessionQuery.data ? <>
      <Card className="session-status-card"><div><span className="eyebrow">{new Date(`${sessionQuery.data.attendance_date}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</span><h2>Morning attendance</h2><p>Session ID · {sessionQuery.data.session_id.slice(0, 8)}</p></div><StatusPill value={sessionQuery.data.status} /><div className="session-stats"><span><b>{sessionQuery.data.total_enrolled ?? review?.total_enrolled ?? '—'}</b><small>Enrolled</small></span><span><b>{sessionQuery.data.provisional_present_count ?? sessionQuery.data.final_present_count ?? 0}</b><small>{finalized ? 'Final present' : 'Provisional present'}</small></span>{finalized ? <span><b>{sessionQuery.data.final_absent_count ?? finalResult?.absent_count ?? 0}</b><small>Final absent</small></span> : null}</div></Card>
      {finalized ? <Card className="panel-card finalized-panel"><div className="success-icon"><CheckCircle2 size={24} /></div><h2>Attendance finalized</h2><p>The final record has been submitted. Teacher edits are locked unless the Principal formally reopens the session.</p>{finalResult ? <div className="attendance-summary"><div><span className="summary-number text-success">{finalResult.present_count}</span><span>Present</span></div><div><span className="summary-number">{finalResult.absent_count}</span><span>Absent</span></div></div> : null}<a className="text-link" href="/teacher/history">View attendance history <ArrowRight size={14} /></a></Card> : !review ? <>
        {faceEnabled && ['OPEN', 'REOPENED'].includes(sessionQuery.data.status) ? <Card className="panel-card scan-workspace"><div className="section-heading"><div><h2>Live face identification</h2><p>Fast front-face check first. Extra left/right guidance appears only when the first scan cannot confidently identify a candidate.</p></div><Fingerprint size={20} /></div><div className="scan-actions"><span className="muted-text">Fast front scan · guided retry only if needed</span><Button disabled={identify.isPending} loading={identify.isPending} onClick={() => { setScannerMode('fast'); setScannerRun((value) => value + 1); setShowLiveScanner(true); }}>Start live face scan <Camera size={15} /></Button></div>{scanResult ? <div className="scan-result"><div className="section-heading"><div><span className="eyebrow">LATEST SCAN</span><h3>{scanResult.candidate ? scanResult.candidate.name : 'No student candidate returned'}</h3><p>{scanResult.message}</p></div><StatusPill value={scanResult.status} /></div>{scanResult.candidate ? <div className="scan-candidate"><strong>Roll {scanResult.candidate.roll_number}</strong><span>Match score: {scanResult.score === null ? 'Not provided' : `${Math.round(scanResult.score * 100)}%`}</span></div> : null}<Notice tone="warning">This is a provisional suggestion, not proof of identity. Verify the student in person and confirm or correct the status during review. An unknown or ambiguous scan is not an absence.</Notice></div> : null}</Card> : null}
        {sessionQuery.data.status === 'REVIEW' ? <Card className="panel-card attendance-review-launch"><div><h2>Attendance is in review</h2><p>Return to scanning to add more provisional matches, or open the roster review to confirm each student’s status.</p></div><div className="row-actions">{faceEnabled ? <Button variant="secondary" onClick={() => resume.mutate()} loading={resume.isPending}>Return to scanning</Button> : null}<Button onClick={() => { if (sessionId) loadReview.mutate(sessionId); }} loading={loadReview.isPending}>Review attendance <ArrowRight size={16} /></Button></div></Card> : <Card className="panel-card attendance-review-launch"><div><h2>Ready to review the class roster?</h2><p>Open the review step to mark Present, Absent, Late or Excused for every active student. Students without a prior mark are candidates only until you confirm them.</p></div><Button onClick={() => { if (sessionId) loadReview.mutate(sessionId); }} loading={loadReview.isPending}>Review attendance <ArrowRight size={16} /></Button></Card>}
      </> : <Card className="panel-card">
        <div className="section-heading"><div><h2>Confirm each student</h2><p>Choose a status, then confirm it. Every active enrollment needs an explicit status before final submission.</p></div><div className="review-progress"><strong>{review.marks.filter((mark) => mark.confirmed).length} / {review.total_enrolled}</strong><small>confirmed</small></div></div>
        <div className="progress-track"><span style={{ width: `${review.total_enrolled ? 100 * allMarks.filter((mark) => mark.confirmed).length / review.total_enrolled : 0}%` }} /></div>
        <Table><thead><tr><th>Student</th><th>Current mark</th><th>Source</th><th>Confirm status</th><th>Notes (optional)</th><th>Action</th></tr></thead><tbody>{allMarks.map((mark) => <tr key={mark.enrollment_id}><td><strong>{mark.student_name}</strong><small className="table-subtext">Roll {mark.roll_number}</small></td><td>{mark.confirmed ? <StatusPill value={mark.status} /> : mark.status === 'UNCONFIRMED_ABSENT_CANDIDATE' ? <span className="muted-text">Not yet confirmed</span> : <StatusPill value={mark.status} />}</td><td>{mark.source || 'Manual review'}</td><td><SelectField label="Status" aria-label={`Attendance status for ${mark.student_name}`} value={statuses[mark.enrollment_id] ?? ''} onChange={(e) => setStatuses((old) => ({ ...old, [mark.enrollment_id]: e.target.value }))}><option value="">Choose status…</option><option value="PRESENT">Present</option><option value="ABSENT">Absent</option><option value="LATE">Late</option><option value="EXCUSED">Excused</option></SelectField></td><td><input className="input notes-input" aria-label={`Optional note for ${mark.student_name}`} value={notes[mark.enrollment_id] ?? ''} maxLength={300} onChange={(e) => setNotes((old) => ({ ...old, [mark.enrollment_id]: e.target.value }))} placeholder="Optional" /></td><td><Button size="sm" variant={mark.confirmed ? 'secondary' : 'primary'} disabled={!statuses[mark.enrollment_id]} loading={saveMark.isPending && saveMark.variables?.enrollmentId === mark.enrollment_id} onClick={() => saveMark.mutate({ enrollmentId: mark.enrollment_id, status: statuses[mark.enrollment_id] as 'PRESENT' | 'ABSENT' | 'LATE' | 'EXCUSED' })}>{mark.confirmed ? 'Update' : 'Confirm'}</Button></td></tr>)}</tbody></Table>
        <div className="finalize-footer"><span>{allMarks.filter((mark) => mark.confirmed).length} of {review.total_enrolled} students confirmed</span><Button disabled={!complete} loading={finalize.isPending} onClick={() => { if (window.confirm('Submit final attendance? This locks teacher edits until the Principal reopens the session.')) finalize.mutate(); }}>Submit final attendance <CheckCircle2 size={16} /></Button></div>
        {!complete ? <Notice tone="warning">Confirm every student before submitting. An unrecognized student is not automatically absent.</Notice> : <Notice tone="success">All student statuses are confirmed. You can now submit the final attendance record.</Notice>}
      </Card>}
    </> : null}
    {showLiveScanner && sessionId ? <Modal title={scannerMode === 'fast' ? 'Quick live face identification' : 'Guided face identification retry'} description={scannerMode === 'fast' ? 'A front-facing frame is checked first. Additional angles are requested only if needed.' : 'The first scan needs more evidence. Follow the live left/right arrows.'} onClose={() => setShowLiveScanner(false)}><FaceCaptureCamera key={`${scannerRun}-${scannerMode}`} classId={classId} mode={scannerMode === 'fast' ? 'attendance-fast' : 'attendance-guided'} onCaptured={(files) => { setShowLiveScanner(false); identify.mutate(files); }} onCancel={() => setShowLiveScanner(false)} onRetry={() => { identify.reset(); setScannerRun((value) => value + 1); }} processing={identify.isPending} /></Modal> : null}
  </>;
}

export function TeacherHistoryPage() {
  const { classId } = useClassScope();
  const [page, setPage] = useState(1);
  const query = useQuery({ queryKey: ['teacher-history', classId, page], queryFn: () => api.teacher.history(page, classId), enabled: Boolean(classId) });
  return <><PageHeader title="Attendance history" description="Finalized attendance for your assigned class." /><Card className="panel-card">{query.isLoading ? <LoadingState /> : query.isError ? <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load history.'} onRetry={() => void query.refetch()} /> : query.data?.items.length ? <Table><thead><tr><th>Date</th><th>Present</th><th>Absent</th><th>Finalized at</th><th>Status</th></tr></thead><tbody>{query.data.items.map((item) => <tr key={item.session_id}><td>{new Date(`${item.date}T00:00:00`).toLocaleDateString()}</td><td className="text-success"><strong>{item.present_count}</strong></td><td>{item.absent_count}</td><td>{new Date(item.finalized_at).toLocaleString()}</td><td><StatusPill value="FINALIZED" /></td></tr>)}</tbody></Table> : <EmptyState icon={<CalendarCheck size={23} />} title="No finalized attendance yet" description="Once you submit today's attendance, it will be available here." />}{query.data ? <Pagination page={query.data.page} pageSize={query.data.page_size} total={query.data.total} onPageChange={setPage} /> : null}</Card></>;
}

export function TeacherSecurityPage() {
  const query = useQuery({ queryKey: ['teacher-passkeys'], queryFn: api.teacher.passkeys });
  const queryClient = useQueryClient();
  const revoke = useMutation({ mutationFn: (id: string) => api.teacher.revokePasskey(id), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['teacher-passkeys'] }); toast.success('Passkey revoked'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Passkey could not be revoked') });
  return <><PageHeader title="Passkeys & security" description="Review the passkeys linked to your school account. Device biometrics remain on your authenticator." />
    <Notice tone="info">Your passkey may use fingerprint, face unlock, a device PIN or another local method. SCOLIQ AI does not receive those biometric details.</Notice>
    <Card className="panel-card">{query.isLoading ? <LoadingState /> : query.isError ? <ErrorState message={query.error instanceof Error ? query.error.message : 'Could not load passkeys.'} onRetry={() => void query.refetch()} /> : query.data?.length ? query.data.map((key, index) => <div className="passkey-row" key={key.id}><span className="passkey-row-icon"><KeyRound size={20} /></span><div><strong>Passkey {index + 1}</strong><small>Added {new Date(key.created_at).toLocaleDateString()} · {key.device_type ?? 'Device authenticator'}</small><small>Last used {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'Not recorded'} · {key.backed_up ? 'Synced backup available' : 'Device-held credential'}</small></div><ConfirmButton confirmText="Remove this passkey? Keep another active passkey or ask the Principal for recovery." onConfirm={() => revoke.mutate(key.id)}>Revoke</ConfirmButton></div>) : <EmptyState icon={<Fingerprint size={23} />} title="No passkey credentials returned" description="Contact the Principal if you need to recover access to your teacher account." />}
    </Card>
  </>;
}
