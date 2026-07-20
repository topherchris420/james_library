import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { LogOut, Menu, Settings, X } from 'lucide-react';
import { t } from '@/lib/i18n';
import { useLocaleContext } from '@/App';
import { useAuth } from '@/hooks/useAuth';
import { SettingsModal } from '@/components/SettingsModal';

const routeTitles: Record<string, string> = {
  '/': 'nav.dashboard',
  '/agent': 'nav.agent',
  '/tools': 'nav.tools',
  '/cron': 'nav.cron',
  '/integrations': 'nav.integrations',
  '/memory': 'nav.memory',
  '/config': 'nav.config',
  '/cost': 'nav.cost',
  '/logs': 'nav.logs',
  '/doctor': 'nav.doctor',
};

interface HeaderProps {
  /** Toggles the mobile navigation drawer. */
  onMenuClick?: () => void;
  /** Whether the mobile navigation drawer is currently open. */
  menuOpen?: boolean;
}

export default function Header({ onMenuClick, menuOpen = false }: HeaderProps) {
  const location = useLocation();
  const { logout } = useAuth();
  const { locale, setAppLocale } = useLocaleContext();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const titleKey = routeTitles[location.pathname] ?? 'nav.dashboard';
  const pageTitle = t(titleKey);

  // Keep the browser tab title in sync with the current page
  useEffect(() => {
    document.title = `${pageTitle} · R.A.I.N.`;
  }, [pageTitle]);

  const toggleLanguage = () => {
    // Cycle through: en -> zh -> tr -> en
    const nextLocale = locale === 'en' ? 'zh' : locale === 'zh' ? 'tr' : 'en';
    setAppLocale(nextLocale);
  };

  return (
    <>
      <header className="h-14 flex items-center justify-between px-4 sm:px-6 border-b animate-fade-in" style={{ background: 'var(--pc-bg-surface)', borderColor: 'var(--pc-border)', backdropFilter: 'blur(12px)', }}>
        <div className="flex items-center gap-2 min-w-0">
          {/* Mobile navigation toggle */}
          <button
            type="button"
            onClick={onMenuClick}
            className="lg:hidden h-9 w-9 flex items-center justify-center rounded-xl transition-all shrink-0"
            style={{ color: 'var(--pc-text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
            aria-label={menuOpen ? t('nav.close_menu') : t('nav.open_menu')}
            aria-expanded={menuOpen}
            aria-controls="app-sidebar"
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>

          {/* Page title */}
          <h1 className="h-9 leading-9 text-lg font-semibold tracking-tight truncate" style={{ color: 'var(--pc-text-primary)' }}>{pageTitle}</h1>
        </div>

        {/* Right-side controls */}
        <div className="flex items-center gap-2 h-9">
          {/* Settings */}
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="h-9 w-9 flex items-center justify-center rounded-xl text-xs transition-all"
            style={{ color: 'var(--pc-text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
            onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--pc-text-primary)'; e.currentTarget.style.background = 'var(--pc-hover)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--pc-text-muted)'; e.currentTarget.style.background = 'transparent'; }}
            aria-label={t('settings.title')}
          >
            <Settings className="h-3.5 w-3.5" />
          </button>

          {/* Language switcher */}
          <button
            type="button"
            onClick={toggleLanguage}
            className="h-9 px-3 rounded-xl text-xs font-semibold border transition-all flex items-center"
            style={{
              borderColor: 'var(--pc-border)',
              color: 'var(--pc-text-secondary)',
              background: 'var(--pc-bg-elevated)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--pc-accent-dim)';
              e.currentTarget.style.color = 'var(--pc-text-primary)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--pc-border)';
              e.currentTarget.style.color = 'var(--pc-text-secondary)';
            }}
            aria-label={t('header.switch_language')}
            title={t('header.switch_language')}
          >
            {locale === 'en' ? 'EN' : locale === 'zh' ? 'ZH' : 'TR'}
          </button>

          {/* Logout */}
          <button
            type="button"
            onClick={logout}
            className="h-9 px-3 rounded-xl text-xs transition-all flex items-center gap-1.5"
            style={{ color: 'var(--pc-text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = '#f87171';
              e.currentTarget.style.background = 'rgba(239, 68, 68, 0.08)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--pc-text-muted)';
              e.currentTarget.style.background = 'transparent';
            }}
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>{t('auth.logout')}</span>
          </button>
        </div>
      </header>

      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </>
  );
}
