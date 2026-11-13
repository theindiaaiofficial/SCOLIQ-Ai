import { useEffect, useRef, useState, type ReactNode } from 'react';
import type * as React from 'react';
import { AlertCircle, Check, ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, Search, X } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useBrand } from '../features/branding/BrandProvider';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  block?: boolean;
};

export function Button({ children, variant = 'primary', size = 'md', loading = false, disabled, block = false, className = '', ...props }: ButtonProps) {
  return <button className={`button button-${variant} button-${size} ${block ? 'button-block' : ''} ${className}`.trim()} disabled={disabled || loading} {...props}>
    {loading ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : null}{children}
  </button>;
}

export function TextField({ label, hint, error, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  const id = props.id ?? props.name;
  return <label className="field" htmlFor={id}>
    <span className="field-label">{label}</span>
    <input className={`input ${error ? 'input-error' : ''}`} id={id} {...props} />
    {error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
  </label>;
}

export function SelectField({ label, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = props.id ?? props.name;
  return <label className="field" htmlFor={id}>
    <span className="field-label">{label}</span>
    <span className="select-wrap"><select className="input select" id={id} {...props}>{children}</select><ChevronDown size={15} aria-hidden="true" /></span>
  </label>;
}

export function Card({ children, className = '', ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={`card ${className}`} {...props}>{children}</section>;
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return <div className="page-header">
    <div><h1>{title}</h1>{description ? <p>{description}</p> : null}</div>
    {actions ? <div className="page-actions">{actions}</div> : null}
  </div>;
}

export function LoadingState({ label = 'Loading your workspace…' }: { label?: string }) {
  return <div className="loading-state"><LoaderCircle className="spin" size={22} /><span>{label}</span></div>;
}

export function ErrorState({ message, requestId, onRetry }: { message: string; requestId?: string; onRetry?: () => void }) {
  return <div className="error-state" role="alert"><AlertCircle size={18} /><div><strong>We couldn’t load this information.</strong><p>{message}</p>{requestId ? <small>Support reference: {requestId}</small> : null}{onRetry ? <div><Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button></div> : null}</div></div>;
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{description}</p>{action}</div>;
}

export function StatusPill({ value }: { value: string }) {
  const normalized = value.toLowerCase().replaceAll('_', '-');
  return <span className={`status-pill status-${normalized}`}>{value.replaceAll('_', ' ')}</span>;
}

export function Table({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`table-scroll ${className}`}><table className="data-table">{children}</table></div>;
}

export function SearchField({ value, onChange, placeholder = 'Search records…' }: { value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label className="search-field"><Search size={16} aria-hidden="true" /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} aria-label={placeholder} /></label>;
}

export function Pagination({ page, pageSize, total, onPageChange }: { page: number; pageSize: number; total: number; onPageChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return null;
  return <nav className="pagination" aria-label="Table pagination">
    <span>Page <strong>{page}</strong> of <strong>{pages}</strong> · {total.toLocaleString()} records</span>
    <div><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page"><ChevronLeft size={15} /> Previous</Button><Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPageChange(page + 1)} aria-label="Next page">Next <ChevronRight size={15} /></Button></div>
  </nav>;
}

export function Modal({ title, description, children, onClose, wide = false }: { title: string; description?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []).filter((element) => element.offsetParent !== null);
    (focusable()[0] ?? dialog)?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const elements = focusable();
      if (!elements.length) { event.preventDefault(); dialog?.focus(); return; }
      const first = elements[0]!;
      const last = elements[elements.length - 1]!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => { document.removeEventListener('keydown', onKeyDown); previous?.focus(); };
  }, []);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} tabIndex={-1} className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="modal-title" aria-describedby={description ? 'modal-description' : undefined}>
      <header className="modal-header"><div><h2 id="modal-title">{title}</h2>{description ? <p id="modal-description">{description}</p> : null}</div><button className="icon-button" type="button" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></header>
      <div className="modal-body">{children}</div>
    </section>
  </div>;
}

export function ConfirmButton({ children, confirmText, onConfirm, variant = 'danger' }: { children: ReactNode; confirmText: string; onConfirm: () => void; variant?: 'danger' | 'primary' }) {
  const [confirming, setConfirming] = useState(false);
  if (confirming) return <span className="confirm-inline"><span>{confirmText}</span><Button size="sm" variant={variant} onClick={() => { onConfirm(); setConfirming(false); }}>Confirm</Button><Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button></span>;
  return <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>{children}</Button>;
}

export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'success' | 'danger' }) {
  return <div className={`notice notice-${tone}`} role="status">{tone === 'success' ? <Check size={17} /> : <AlertCircle size={17} />}{children}</div>;
}

export function BrandMark({ name, logoUrl, size = 'md' }: { name: string; logoUrl: string | null; size?: 'sm' | 'md' | 'lg' }) {
  const initials = name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'S';
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [logoUrl]);
  return <span className={`brand-mark brand-mark-${size}`}>
    {logoUrl && !failed ? <img src={logoUrl} alt={`${name} logo`} onError={() => setFailed(true)} /> : <span aria-hidden="true">{initials}</span>}
  </span>;
}

export function BrandIdentity({ compact = false, to = '/teacher' }: { compact?: boolean; to?: string }) {
  const { brand } = useBrand();
  return <Link className={`brand-identity ${compact ? 'brand-identity-compact' : ''}`} to={to} aria-label={`${brand.school_name} home`}>
    <BrandMark name={brand.school_name} logoUrl={brand.logo_url} />
    {brand.branding.logo_with_school_name ? <span className="brand-name">{brand.school_name}</span> : null}
  </Link>;
}

