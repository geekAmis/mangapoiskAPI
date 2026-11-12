import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { AdminSeo } from './components/AdminSeo';
import { ProtectedRoute } from './components/ProtectedRoute';
import { PageLoader, ReaderFallback } from './components/PageLoader';
import HomePage from './pages/HomePage';
import CataloguePage from './pages/CataloguePage';
import CollectionPage from './pages/CollectionPage';
import MangaPage from './pages/MangaPage';
import LibraryPage from './pages/LibraryPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import YandexFinishPage from './pages/YandexFinishPage';
import ProfilePage from './pages/ProfilePage';
import PublicProfilePage from './pages/PublicProfilePage';
import SourcesPage from './pages/SourcesPage';
import NotFoundPage from './pages/NotFoundPage';
import TermsPage from './pages/TermsPage';
import PrivacyPage from './pages/PrivacyPage';
import DmcaPage from './pages/DmcaPage';
import ContactsPage from './pages/ContactsPage';
import AgePage from './pages/AgePage';

const ReaderPage = lazy(() => import('./pages/ReaderPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const OfflineMangaPage = lazy(() => import('./pages/OfflineMangaPage'));
const OfflineReaderPage = lazy(() => import('./pages/OfflineReaderPage'));

const readerElement = (
  <Suspense fallback={<ReaderFallback />}>
    <ReaderPage />
  </Suspense>
);

const offlineMangaElement = (
  <Suspense fallback={<PageLoader label="Открываем скачанный тайтл…" />}>
    <OfflineMangaPage />
  </Suspense>
);

const offlineReaderElement = (
  <Suspense fallback={<ReaderFallback />}>
    <OfflineReaderPage />
  </Suspense>
);

export default function App() {
  return (
    <Routes>
      <Route
        path="admin"
        element={
          <>
            <AdminSeo />
            <Suspense fallback={<div style={{ minHeight: '100dvh', background: '#07080b' }} />}>
              <AdminPage />
            </Suspense>
          </>
        }
      />

      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="catalog" element={<CataloguePage />} />
        <Route path="catalog/genres" element={<CataloguePage />} />
        <Route path="catalogue" element={<CataloguePage />} />
        <Route path="manga/:id" element={<MangaPage />} />
        <Route path="collections/:slug" element={<CollectionPage />} />
        <Route
          path="library"
          element={
            <ProtectedRoute>
              <LibraryPage />
            </ProtectedRoute>
          }
        />
        <Route path="offline/manga/:mangaId" element={offlineMangaElement} />
        <Route
          path="profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route path="u/:handle" element={<PublicProfilePage />} />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="terms" element={<TermsPage />} />
        <Route path="privacy" element={<PrivacyPage />} />
        <Route path="dmca" element={<DmcaPage />} />
        <Route path="contacts" element={<ContactsPage />} />
        <Route path="age" element={<AgePage />} />
        <Route path="404" element={<NotFoundPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>

      <Route path="login" element={<LoginPage />} />
      <Route path="register" element={<RegisterPage />} />
      <Route path="auth/yandex/finish" element={<YandexFinishPage />} />
      <Route path="read/:chapterId" element={readerElement} />
      <Route path="reader/:chapterId" element={readerElement} />
      <Route path="offline/read/:mangaId/:chapterId" element={offlineReaderElement} />
    </Routes>
  );
}
