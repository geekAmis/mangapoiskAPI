import { Outlet } from 'react-router-dom';
import { useProgressSync } from '../../lib/useReading';
import { OfflineBanner } from '../OfflineBanner';
import { QueryCacheBridge } from '../QueryCacheBridge';
import { AndroidApkBanner } from './AndroidApkBanner';
import { Footer } from './Footer';
import { Header } from './Header';
import { MobileNav } from './MobileNav';

export function AppLayout() {
  useProgressSync();
  return (
    <div className="app-shell">
      <QueryCacheBridge />
      <a className="skip-link" href="#main">
        Перейти к содержимому
      </a>
      <Header />
      <OfflineBanner />
      <main id="main" className="site-main">
        <Outlet />
      </main>
      <Footer />
      <MobileNav />
      <AndroidApkBanner />
    </div>
  );
}
