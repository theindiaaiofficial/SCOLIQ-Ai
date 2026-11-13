import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BrandMark, Button, Modal } from '../src/components/ui';

describe('accessible shared UI primitives', () => {
  it('renders a school initials fallback when the hosted logo fails', () => {
    render(<BrandMark name="Northfield Academy" logoUrl="https://school.example/logo.png" />);
    fireEvent.error(screen.getByRole('img', { name: 'Northfield Academy logo' }));
    expect(screen.getByText('NA')).toBeInTheDocument();
  });

  it('disables a submit action while its mutation is pending', () => {
    render(<Button type="submit" loading>Save changes</Button>);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  });

  it('closes an open dialog on Escape', () => {
    const onClose = vi.fn();
    render(<Modal title="Confirm action" description="Please review this action." onClose={onClose}><p>Dialog content</p></Modal>);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
