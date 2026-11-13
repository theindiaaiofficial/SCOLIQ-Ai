import { describe, expect, it } from 'vitest';
import { DEFAULT_BRANDING, DEFAULT_SCHOOL_BRANDING, readableText } from '../src/features/branding/defaults';

describe('shared school branding defaults', () => {
  it('provides the complete safe presentation contract', () => {
    expect(DEFAULT_SCHOOL_BRANDING.branding).toEqual(DEFAULT_BRANDING);
    expect(DEFAULT_BRANDING.design_profile).toBe('clean');
    expect(DEFAULT_BRANDING.appearance).toBe('light');
    expect(DEFAULT_BRANDING.logo_with_school_name).toBe(true);
    expect(DEFAULT_BRANDING.primary_color).toMatch(/^#[0-9A-F]{6}$/);
  });

  it('chooses a readable text color for light and dark primary colors', () => {
    expect(readableText('#FFFFFF')).toBe('#101828');
    expect(readableText('#123456')).toBe('#FFFFFF');
    expect(readableText('not-a-color')).toBe('#FFFFFF');
  });
});
