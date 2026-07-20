import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import SecurityBanner from '@/components/SecurityBanner';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import { ErrorBoundary } from '@/App';
import { t } from '@/lib/i18n';

export default function Layout() {
  const { pathname } = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Close the mobile drawer whenever the route changes
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  // Close the mobile drawer on Escape
  useEffect(() => {
    if (!sidebarOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [sidebarOpen]);

  return (
    <div className="min-h-screen text-white" style={{ background: 'var(--pc-bg-base)' }}>
      {/* Sidebar: fixed column on desktop, slide-in drawer on mobile */}
      <Sidebar open={sidebarOpen} />

      {/* Overlay behind the mobile drawer */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-[110] bg-black/50 lg:hidden"
          role="presentation"
          aria-label={t('nav.close_menu')}
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main area offset by sidebar width (240px / w-60) on desktop */}
      <div className="lg:ml-60 flex flex-col flex-1 min-w-0 h-screen">
        <SecurityBanner />
        <Header onMenuClick={() => setSidebarOpen((open) => !open)} menuOpen={sidebarOpen} />

        {/* Page content — ErrorBoundary keyed by pathname so the nav shell
            survives a page crash and the boundary resets on route change */}
        <main className="flex-1 overflow-y-auto min-h-0">
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
