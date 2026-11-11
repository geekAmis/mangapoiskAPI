import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/layout/AppLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ReaderFallback } from './components/PageLoader';
import HomePage from './pages/HomePage';
import CataloguePage from './pages/CataloguePage';
import MangaPage from './pages/MangaPage';
import LibraryPage from './pages/LibraryPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ProfilePage from './pages/ProfilePage';
import SourcesPage from './pages/SourcesPage';
import NotFoundPage from './pages/NotFoundPage';

const ReaderPage = lazy(() => import('./pages/ReaderPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));

const readerElement = (
  <Suspense fallback={<ReaderFallback />}>
    <ReaderPage />
  </Suspense>
);

export default function App() {
  return (
    <Routes>
      <Route
        path="admin"
        element={
          <Suspense fallback={<div style={{ minHeight: '100dvh', background: '#07080b' }} />}>
            <AdminPage />
          </Suspense>
        }
      />

      <Route element={<AppLayout />}>
        <Route index element={<HomePage />} />
        <Route path="catalog" element={<CataloguePage />} />
        <Route path="catalogue" element={<CataloguePage />} />
        <Route path="manga/:id" element={<MangaPage />} />
        <Route
          path="library"
          element={
            <ProtectedRoute>
              <LibraryPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="profile"
          element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          }
        />
        <Route path="sources" element={<SourcesPage />} />
        <Route path="404" element={<NotFoundPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>

      <Route path="login" element={<LoginPage />} />
      <Route path="register" element={<RegisterPage />} />
      <Route path="read/:chapterId" element={readerElement} />
      <Route path="reader/:chapterId" element={readerElement} />
    </Routes>
  );
}
