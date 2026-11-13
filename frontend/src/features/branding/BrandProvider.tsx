import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { SchoolBranding } from '../../api/types';
import { DEFAULT_SCHOOL_BRANDING, readableText } from './defaults';

type BrandContextValue = { brand: SchoolBranding; isLoading: boolean };
const BrandContext = createContext<BrandContextValue>({ brand: DEFAULT_SCHOOL_BRANDING, isLoading: true });

export function BrandProvider({ children }: { children: ReactNode }) {
  const query = useQuery({ queryKey: ['public-school-branding'], queryFn: api.publicBranding, retry: false, staleTime: 60_000 });
  const brand = query.data ?? DEFAULT_SCHOOL_BRANDING;

  useEffect(() => {
    const root = document.documentElement;
    const config = brand.branding;
    root.style.setProperty('--brand-primary', config.primary_color);
    root.style.setProperty('--brand-primary-contrast', readableText(config.primary_color));
    root.style.setProperty('--brand-accent', config.accent_color);
    root.dataset.profile = config.design_profile;
    root.dataset.radius = config.corner_radius;
    root.dataset.density = config.density;
    root.dataset.sidebar = config.sidebar_appearance;
    root.dataset.cards = config.card_appearance;
    root.dataset.heading = config.heading_style;
    root.dataset.masthead = config.masthead_style;
    root.dataset.motion = config.motion;
    root.dataset.background = config.page_background;
    root.dataset.sidebarCollapsed = String(config.sidebar_collapsed);
    root.dataset.logoSize = config.logo_size;
    root.dataset.logoPlacement = config.logo_placement;
    root.dataset.logoWithName = String(config.logo_with_school_name);

    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const applyAppearance = () => {
      const dark = config.appearance === 'dark' || (config.appearance === 'system' && media.matches);
      root.dataset.theme = dark ? 'dark' : 'light';
    };
    applyAppearance();
    media.addEventListener?.('change', applyAppearance);
    return () => media.removeEventListener?.('change', applyAppearance);
  }, [brand]);

  return <BrandContext.Provider value={{ brand, isLoading: query.isLoading }}>{children}</BrandContext.Provider>;
}

export function useBrand() {
  return useContext(BrandContext);
}
