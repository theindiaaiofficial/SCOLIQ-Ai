import { useState, createContext, useContext, useEffect, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Activity, BookOpen, Building2, CalendarDays, ChartNoAxesCombined, ClipboardList, GraduationCap,
  LayoutDashboard, LogOut, Menu, Palette, Settings, ShieldCheck, Users, X,
  type LucideIcon,
} from 'lucide-react';
import { api } from '../api/client';
import type { Principal, TeacherIdentity } from '../api/types';
import { useBrand } from '../features/branding/BrandProvider';
import { BrandMark, Button } from './ui';

type NavItem = { label: string; to: string; icon: LucideIcon; group?: string };

type ClassScope = { classId: string | null; setClassId: (id: string) => void };
const ClassScopeContext = createContext<ClassScope>({ classId: null, setClassId: () => undefined });
export const useClassScope = () => useContext(ClassScopeContext);

const adminNav: NavItem[] = [
  { label: 'Overview', to: '/admin/dashboard', icon: LayoutDashboard, group: 'Workspace' },
  { label: 'Teacher requests', to: '/admin/requests', icon: ClipboardList, group: 'Workspace' },
  { label: 'Teachers', to: '/admin/teachers', icon: Users, group: 'Workspace' },
  { label: 'Classes & assignments', to: '/admin/classes', icon: BookOpen, group: 'School' },
  { label: 'Students & consent', to: '/admin/students', icon: GraduationCap, group: 'School' },
  { label: 'Live attendance', to: '/admin/live-attendance', icon: Activity, group: 'Attendance' },
  { label: 'Attendance reports', to: '/admin/reports', icon: ChartNoAxesCombined, group: 'Attendance' },
  { label: 'Brand studio', to: '/admin/settings', icon: Palette, group: 'Administration' },
  { label: 'School settings', to: '/admin/school-settings', icon: Settings, group: 'Administration' },
  { label: 'Audit log', to: '/admin/audit', icon: ShieldCheck, group: 'Administration' },
  { label: 'Account & security', to: '/admin/security', icon: Settings, group: 'Administration' },
];

function Sidebar({ children, role, onNavigate }: { children?: ReactNode; role: 'admin' | 'teacher'; onNavigate?: () => void }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { brand } = useBrand();
  const adminItems = adminNav;
  const teacherItems: NavItem[] = [
    { label: 'My dashboard', to: '/teacher/dashboard', icon: LayoutDashboard },
    { label: 'My students', to: '/teacher/students', icon: GraduationCap },
    { label: 'Attendance workspace', to: '/teacher/attendance', icon: CalendarDays },
    { label: 'Attendance history', to: '/teacher/history', icon: ChartNoAxesCombined },
    { label: 'Passkeys & security', to: '/teacher/security', icon: ShieldCheck },
  ];
  const items = role === 'admin' ? adminItems : teacherItems;
  const nav = <nav className="side-nav" aria-label={`${role} navigation`}>
    {role === 'admin' ? <>
      {['Workspace', 'School', 'Attendance', 'Administration'].map((group) => <div className="nav-group" key={group}>
        <span className="nav-group-title">{group}</span>
        {items.filter((item) => item.group === group).map((item) => {
          const Icon = item.icon;
          return <NavLink key={item.to} to={item.to} onClick={() => { setMobileOpen(false); onNavigate?.(); }} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
            <Icon size={17} strokeWidth={1.8} /><span>{item.label}</span>
          </NavLink>;
        })}
      </div>)}
    </> : items.map((item) => {
      const Icon = item.icon;
      return <NavLink key={item.to} to={item.to} onClick={() => { setMobileOpen(false); onNavigate?.(); }} className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}>
        <Icon size={17} strokeWidth={1.8} /><span>{item.label}</span>
      </NavLink>;
    })}
  </nav>;
  return <>
    <button className="mobile-menu-trigger" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={21} /></button>
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
      <div className="sidebar-brand"><BrandMark name={brand.school_name} logoUrl={brand.logo_url} size="lg" />{brand.branding.logo_with_school_name ? <div><strong>{brand.school_name}</strong><span>{role === 'admin' ? 'Principal workspace' : 'Teacher workspace'}</span></div> : null}<button className="icon-button sidebar-close" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={18} /></button></div>
      {nav}
      <div className="sidebar-footer"><div className="sidebar-footer-mark"><Building2 size={15} /><span>Independent school workspace</span></div><small>SCOLIQ AI</small></div>
    </aside>
    {mobileOpen ? <button className="sidebar-overlay" aria-label="Close navigation overlay" onClick={() => setMobileOpen(false)} /> : null}
    {children}
  </>;
}

export function AdminLayout({ user }: { user: Principal }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { brand } = useBrand();
  const [busy, setBusy] = useState(false);
  const logout = async () => {
    setBusy(true);
    try { await api.admin.logout(); } finally { queryClient.clear(); navigate('/admin/login', { replace: true }); setBusy(false); }
  };
  return <div className="portal-layout portal-admin">
    <Sidebar role="admin" />
    <div className="portal-main">
      <header className="topbar"><div className="topbar-crumb"><span>School administration</span><span className="crumb-separator">/</span><strong>Principal portal</strong></div><div className="topbar-right"><span className="role-label"><ShieldCheck size={14} /> Principal</span><div className="user-chip"><span className="avatar avatar-primary">{user.full_name.split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase()}</span><span>{user.full_name}</span></div><Button variant="ghost" size="sm" onClick={logout} loading={busy}><LogOut size={15} /> Sign out</Button></div></header>
      <main className="portal-content">
        <div className="school-masthead">
          <BrandMark name={brand.school_name} logoUrl={brand.logo_url} size="lg" />
          <div><span className="eyebrow">SCHOOL MANAGEMENT</span><h1>{brand.school_name}</h1><p>A clear view of your school, people and daily attendance.</p></div>
          <div className="masthead-actions"><span className="live-dot" /> School workspace</div>
        </div>
        <Outlet />
      </main>
      <footer className="portal-footer"><span>SCOLIQ AI</span><span>One secure workspace for your school</span></footer>
    </div>
  </div>;
}

export function TeacherLayout({ user }: { user: TeacherIdentity }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { brand } = useBrand();
  const [selectedClass, setSelectedClass] = useState<string | null>(user.classes[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!selectedClass && user.classes[0]?.id) setSelectedClass(user.classes[0].id);
    if (selectedClass && !user.classes.some((item) => item.id === selectedClass)) {
      queryClient.removeQueries({ predicate: (query) => [
        'teacher-class', 'teacher-students', 'teacher-student-detail', 'teacher-history', 'teacher-attendance-session',
      ].includes(String(query.queryKey[0])) });
      setSelectedClass(user.classes[0]?.id ?? null);
    }
  }, [selectedClass, user.classes, queryClient]);
  const current = user.classes.find((item) => item.id === selectedClass) ?? user.classes[0];
  const chooseClass = (id: string) => {
    if (id === selectedClass) return;
    queryClient.removeQueries({ predicate: (query) => [
      'teacher-class', 'teacher-students', 'teacher-student-detail', 'teacher-history', 'teacher-attendance-session',
    ].includes(String(query.queryKey[0])) });
    setSelectedClass(id);
  };
  const logout = async () => {
    setBusy(true);
    try { await api.teacher.logout(); } finally { queryClient.clear(); navigate('/teacher/login', { replace: true }); setBusy(false); }
  };
  const context = { classId: selectedClass, setClassId: chooseClass };
  return <ClassScopeContext.Provider value={context}>
    <div className="portal-layout portal-teacher">
      <Sidebar role="teacher" />
      <div className="portal-main">
        <header className="topbar"><div className="topbar-crumb"><span>Teacher workspace</span><span className="crumb-separator">/</span><strong>My classroom</strong></div><div className="topbar-right">
          {user.classes.length > 1 ? <label className="class-switcher"><span>Class</span><select aria-label="Choose assigned class" value={selectedClass ?? ''} onChange={(event) => chooseClass(event.target.value)}>{user.classes.map((item) => <option value={item.id} key={item.id}>Grade {item.grade} · {item.section} · {item.academic_year}</option>)}</select></label> : current ? <span className="role-label"><BookOpen size={14} /> Grade {current.grade} · {current.section}</span> : null}
          <div className="user-chip"><span className="avatar avatar-accent">{user.full_name.split(/\s+/).slice(0, 2).map((p) => p[0]).join('').toUpperCase()}</span><span>{user.full_name}</span></div><Button variant="ghost" size="sm" onClick={logout} loading={busy}><LogOut size={15} /> Sign out</Button>
        </div></header>
        <main className="portal-content">
          <div className="teacher-masthead"><div className="teacher-brand"><BrandMark name={brand.school_name} logoUrl={brand.logo_url} size="lg"/><div><span className="eyebrow">{brand.school_name}</span><h1>Good day, {user.full_name.split(' ')[0]}</h1><p>{current ? `Grade ${current.grade} · Section ${current.section} · ${current.academic_year}` : 'Your teacher workspace'}</p></div></div><div className="masthead-actions"><span className="live-dot" /> Teacher portal</div></div>
          <Outlet />
        </main>
        <footer className="portal-footer"><span>SCOLIQ AI</span><span>{brand.school_name} · Teacher workspace</span></footer>
      </div>
    </div>
  </ClassScopeContext.Provider>;
}
