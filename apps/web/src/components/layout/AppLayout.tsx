import { Outlet } from 'react-router-dom';
import { useProgressSync } from '../../lib/useReading';
import { AdSlot } from '../ads/AdSlot';
import { ConsentBanner } from '../ConsentBanner';
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
      <div className="container">
        <AdSlot placement="header" />
      </div>
      <main id="main" className="site-main">
        <Outlet />
      </main>
      <Footer />
      <AdSlot placement="mobile-sticky" />
      <MobileNav />
      <AndroidApkBanner />
      <ConsentBanner />
    </div>
  );
}
