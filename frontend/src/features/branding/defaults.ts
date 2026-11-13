import type { Branding, SchoolBranding } from '../../api/types';

export const DEFAULT_BRANDING: Branding = {
  design_profile: 'clean',
  appearance: 'light',
  primary_color: '#3157D5',
  accent_color: '#148A78',
  sidebar_appearance: 'subtle',
  sidebar_collapsed: false,
  card_appearance: 'outlined',
  corner_radius: 'balanced',
  density: 'comfortable',
  heading_style: 'modern',
  masthead_style: 'prominent',
  motion: 'subtle',
  page_background: 'soft-tint',
  logo_size: 'medium',
  logo_placement: 'beside',
  logo_with_school_name: true,
};

export const DEFAULT_SCHOOL_BRANDING: SchoolBranding = {
  school_name: 'My School',
  logo_url: null,
  branding: DEFAULT_BRANDING,
};

export function readableText(hex: string): '#101828' | '#FFFFFF' {
  const normalized = hex.replace('#', '');
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return '#FFFFFF';
  const channels = [0, 2, 4].map((i) => parseInt(normalized.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b! > 0.42 ? '#101828' : '#FFFFFF';
}
