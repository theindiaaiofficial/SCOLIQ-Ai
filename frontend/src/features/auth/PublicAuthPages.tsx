import { useState } from 'react';
import type * as React from 'react';
import { startAuthentication, startRegistration, browserSupportsWebAuthn } from '@simplewebauthn/browser';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Fingerprint, KeyRound, ShieldCheck, UserRoundPlus } from 'lucide-react';
import { toast } from 'sonner';
import { api, ApiError } from '../../api/client';
import { useBrand } from '../branding/BrandProvider';
import { BrandMark, Button, LoadingState, Notice, TextField } from '../../components/ui';

function AuthFrame({ eyebrow, title, description, children, portal }: { eyebrow: string; title: string; description: string; children: React.ReactNode; portal: 'Principal' | 'Teacher' }) {
  const { brand } = useBrand();
  return <main className="auth-page"><div className="auth-orbit auth-orbit-one" /><div className="auth-orbit auth-orbit-two" />
    <div className="auth-wrap"><header className="auth-brand"><BrandMark name={brand.school_name} logoUrl={brand.logo_url} size="lg" />{brand.branding.logo_with_school_name ? <div><strong>{brand.school_name}</strong><span>SCOLIQ AI</span></div> : null}<span className="auth-portal-tag">{brand.branding.logo_with_school_name ? `${portal} portal` : `${brand.school_name} · ${portal} portal`}</span></header>
      <section className="auth-card"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p className="auth-description">{description}</p>{children}</section>
      <footer className="auth-footer"><ShieldCheck size={14} /> Secure school workspace · Your school’s data stays within this installation</footer>
    </div>
  </main>;
}

export function AdminLoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [setupMode, setSetupMode] = useState(false);
  const [setupToken, setSetupToken] = useState('');
  const [fullName, setFullName] = useState('');
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const status = useQuery({ queryKey: ['admin-bootstrap-status'], queryFn: api.admin.bootstrapStatus, retry: false });
  const login = useMutation({ mutationFn: () => api.admin.login({ email, password }), onSuccess: () => { queryClient.clear(); toast.success('Welcome back'); navigate('/admin/dashboard', { replace: true }); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Sign in failed') });
  const bootstrap = useMutation({ mutationFn: () => api.admin.bootstrap({ setup_token: setupToken, full_name: fullName, email: newEmail, password: newPassword }), onSuccess: () => { queryClient.clear(); toast.success('Principal account created'); navigate('/admin/dashboard', { replace: true }); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Account setup failed') });
  return <AuthFrame portal="Principal" eyebrow="ADMINISTRATOR ACCESS" title={setupMode ? 'Set up your Principal account' : 'Welcome back'} description={setupMode ? 'Create the first Principal account using the one-time setup secret configured for this school.' : 'Sign in to manage your school, teachers, classes and attendance.'}>
    {setupMode ? <form className="stack-form" onSubmit={(e) => { e.preventDefault(); bootstrap.mutate(); }}>
      <TextField label="One-time setup token" type="password" value={setupToken} onChange={(e) => setSetupToken(e.target.value)} minLength={24} required />
      <TextField label="Principal full name" value={fullName} onChange={(e) => setFullName(e.target.value)} minLength={2} required />
      <TextField label="Principal email" type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required />
      <TextField label="Password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={12} hint="At least 12 characters." required />
      <Button type="submit" block loading={bootstrap.isPending} disabled={setupToken.length < 24 || fullName.trim().length < 2 || !newEmail.includes('@') || newPassword.length < 12}>Create Principal account <ArrowRight size={16} /></Button>
      <Button variant="ghost" type="button" onClick={() => setSetupMode(false)}>Back to sign in</Button>
    </form> : <form className="stack-form" onSubmit={(e) => { e.preventDefault(); login.mutate(); }}>
      <TextField label="Email address" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
      <TextField label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      <Button type="submit" block loading={login.isPending} disabled={!email.includes('@') || !password}>Sign in securely <ArrowRight size={16} /></Button>
      <div className="auth-links"><span>Teacher? <Link to="/teacher">Open the shared Teacher portal</Link></span>{status.data?.available ? <button type="button" onClick={() => setSetupMode(true)}>First-time setup</button> : null}</div>
      {status.isError ? <Notice tone="warning">Unable to check bootstrap status. The Principal may need to create the first account using the documented CLI setup.</Notice> : null}
    </form>}
  </AuthFrame>;
}

export function TeacherLoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [identifier, setIdentifier] = useState('');
  const [busy, setBusy] = useState(false);
  const webAuthnAvailable = browserSupportsWebAuthn();
  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!webAuthnAvailable) { toast.error('This browser does not support passkeys. Try a supported, updated browser.'); return; }
    setBusy(true);
    try {
      const options = await api.teacher.loginOptions(identifier.trim());
      const credential = await startAuthentication({ optionsJSON: options as never });
      await api.teacher.loginVerify(identifier.trim(), credential);
      queryClient.clear();
      toast.success('Signed in successfully');
      navigate('/teacher/dashboard', { replace: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Passkey sign-in did not complete');
    } finally { setBusy(false); }
  };
  return <AuthFrame portal="Teacher" eyebrow="TEACHER ACCESS" title="Your classroom, in one place" description="Sign in with the passkey registered to your school account. Your device may ask for a screen lock, fingerprint, face unlock or another supported method.">
    <form className="stack-form" onSubmit={handleLogin}>
      <TextField label="School email or mobile number" autoComplete="username webauthn" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required />
      <Button type="submit" block loading={busy} disabled={!identifier.trim() || !webAuthnAvailable}><Fingerprint size={17} /> Continue with passkey</Button>
      {!webAuthnAvailable ? <Notice tone="warning">Passkeys are not available in this browser or context. Use HTTPS or localhost with a supported browser.</Notice> : <div className="passkey-note"><KeyRound size={16} /><span>Your passkey’s private key stays protected by your device. SCOLIQ AI never receives your fingerprint or face-unlock data.</span></div>}
      <div className="auth-divider"><span>New to SCOLIQ AI?</span></div>
      <Link className="button button-secondary button-block" to="/teacher/request-access"><UserRoundPlus size={16} /> Request teacher access</Link>
      <Link className="auth-secondary-link" to="/teacher/activate">Already approved? Enter activation code <ArrowRight size={14} /></Link>
    </form>
  </AuthFrame>;
}

export function TeacherRequestPage() {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [staffId, setStaffId] = useState('');
  const [reference, setReference] = useState<string | null>(null);
  const [lookup, setLookup] = useState('');
  const [statusLookup, setStatusLookup] = useState(false);
  const [lookupError, setLookupError] = useState('');
  const [result, setResult] = useState<{ status: string; requested_at: string; reviewed_at: string | null } | null>(null);
  const create = useMutation({ mutationFn: () => api.teacher.requestAccess({ full_name: name, phone, email: email || undefined, staff_identifier: staffId || undefined }), onSuccess: (data) => { setReference(data.public_reference); toast.success('Request submitted'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Request could not be submitted') });
  const submitLookup = async (event: React.FormEvent) => {
    event.preventDefault(); setLookupError(''); setResult(null); setStatusLookup(true);
    try { setResult(await api.teacher.requestStatus(lookup.trim())); } catch (e) { setLookupError(e instanceof Error ? e.message : 'Request not found'); }
    finally { setStatusLookup(false); }
  };
  return <AuthFrame portal="Teacher" eyebrow="TEACHER ONBOARDING" title="Request school access" description="Submit your staff details. The Principal will verify your identity before any teacher account is activated.">
    {reference ? <div className="success-panel"><div className="success-icon"><ShieldCheck size={22} /></div><h2>Request received</h2><p>Your request is waiting for Principal approval. Keep this private reference so you can check the status later.</p><code className="reference-code">{reference}</code><Button block variant="secondary" onClick={() => { void navigator.clipboard.writeText(reference); toast.success('Reference copied'); }}>Copy reference</Button><Link className="button button-primary button-block" to="/teacher">Return to teacher sign in</Link></div> : <form className="stack-form" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
      <TextField label="Mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} required minLength={7} placeholder="Include country code if needed" />
      <TextField label="School email (optional)" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <TextField label="Staff identifier (optional)" value={staffId} onChange={(e) => setStaffId(e.target.value)} />
      <Notice tone="info">This form does not create an active account or grant access to student information.</Notice>
      <Button block type="submit" loading={create.isPending} disabled={name.trim().length < 2 || phone.replace(/\D/g, '').length < 7}>Submit access request <ArrowRight size={16} /></Button>
    </form>}
    <div className="auth-divider"><span>Already submitted a request?</span></div>
    <form className="stack-form" onSubmit={submitLookup}><TextField label="Private request reference" value={lookup} onChange={(e) => setLookup(e.target.value)} hint="The reference is not sent in the URL." /><Button variant="outline" type="submit" loading={statusLookup} disabled={lookup.trim().length < 32}>Check request status</Button>
      {lookupError ? <Notice tone="danger">{lookupError}</Notice> : null}{result ? <Notice tone={result.status === 'ACTIVE' ? 'success' : result.status === 'REJECTED' ? 'danger' : 'info'}>Status: <strong>{result.status.replaceAll('_', ' ')}</strong>{result.reviewed_at ? ` · Reviewed ${new Date(result.reviewed_at).toLocaleDateString()}` : ' · Waiting for review'}</Notice> : null}
    </form>
    <Link className="auth-secondary-link" to="/teacher"><ArrowLeft size={14} /> Back to teacher sign in</Link>
  </AuthFrame>;
}

export function TeacherActivationPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const status = useQuery({ queryKey: ['teacher-activation-status'], queryFn: api.teacher.activationStatus, retry: false, staleTime: 0 });
  const redeem = useMutation({ mutationFn: () => api.teacher.redeem(code.trim()), onSuccess: async () => { setCode(''); await queryClient.invalidateQueries({ queryKey: ['teacher-activation-status'] }); toast.success('Activation accepted. Register your passkey next.'); }, onError: (e) => toast.error(e instanceof Error ? e.message : 'Activation failed') });
  const register = async () => {
    if (!browserSupportsWebAuthn()) { toast.error('This browser does not support passkeys.'); return; }
    setBusy(true);
    try {
      const options = await api.teacher.registrationOptions();
      const credential = await startRegistration({ optionsJSON: options as never });
      await api.teacher.registrationVerify(credential);
      await queryClient.invalidateQueries({ queryKey: ['teacher-me'] });
      toast.success('Passkey registered. Your teacher account is active.');
      navigate('/teacher/dashboard', { replace: true });
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Passkey registration failed'); }
    finally { setBusy(false); }
  };
  if (status.isLoading) return <AuthFrame portal="Teacher" eyebrow="TEACHER ACTIVATION" title="Checking activation" description="Verifying your short-lived activation session."><LoadingState /></AuthFrame>;
  return <AuthFrame portal="Teacher" eyebrow="TEACHER ACTIVATION" title={status.data ? `Welcome, ${status.data.full_name.split(' ')[0]}` : 'Activate your teacher account'} description={status.data ? 'Your approval is confirmed. Register a passkey on this device to finish activation.' : 'Enter the one-time code provided by your Principal through a trusted private channel.'}>
    {status.data ? <div className="stack-form"><div className="passkey-illustration"><Fingerprint size={28} /></div><Notice tone="success">The activation code has been accepted. This temporary session allows passkey registration only.</Notice><Button block loading={busy} onClick={register}><KeyRound size={17} /> Set up device passkey</Button><Button variant="ghost" block onClick={() => navigate('/teacher/login')}>Cancel activation</Button></div> : <form className="stack-form" onSubmit={(e) => { e.preventDefault(); redeem.mutate(); }}><TextField label="One-time activation code" type="password" value={code} onChange={(e) => setCode(e.target.value)} minLength={20} required /><Notice tone="info">Activation codes expire and can be used only once. Do not share this code with anyone else.</Notice><Button block type="submit" loading={redeem.isPending} disabled={code.length < 20}>Verify code <ArrowRight size={16} /></Button></form>}
    {status.isError && (status.error instanceof ApiError && status.error.status !== 401 ? <Notice tone="warning">{status.error.message}</Notice> : null)}
    <Link className="auth-secondary-link" to="/teacher/login"><ArrowLeft size={14} /> Back to teacher sign in</Link>
  </AuthFrame>;
}
