import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { LEGAL_PAGES, LEGAL_UPDATED_LABEL } from '../../lib/legal';

interface LegalLayoutProps {
  title: string;
  intro: string;
  children: ReactNode;
}

export function LegalLayout({ title, intro, children }: LegalLayoutProps) {
  return (
    <div className="page container legal-page">
      <div className="legal-page__grid">
        <aside className="legal-nav" aria-label="Юридические документы">
          <span className="legal-nav__heading">Документы</span>
          <nav className="legal-nav__links" aria-label="Список юридических документов">
            {LEGAL_PAGES.map((page) => (
              <NavLink
                key={page.path}
                to={page.path}
                className={({ isActive }) =>
                  `legal-nav__link${isActive ? ' is-active' : ''}`
                }
              >
                {page.shortLabel}
              </NavLink>
            ))}
          </nav>
          <p className="legal-nav__note">
            Документы описывают текущую версию сервиса и не заменяют юридическую
            консультацию. Контактные данные владельца указаны на странице{' '}
            <Link to="/contacts">«Контакты»</Link>.
          </p>
        </aside>

        <article className="legal-doc">
          <header className="legal-doc__head">
            <span className="eyebrow">Правовая информация</span>
            <h1>{title}</h1>
            <p className="legal-doc__intro">{intro}</p>
            <p className="legal-doc__meta">
              Редакция от {LEGAL_UPDATED_LABEL}. Документ действует для сайта
              MangaPoisk Reborn.
            </p>
          </header>

          <div className="legal-doc__body">{children}</div>

          <div className="legal-doc__foot">
            <span>Остались вопросы по документу? Напишите владельцу сервиса.</span>
            <Link to="/contacts">Контакты и реквизиты</Link>
          </div>
        </article>
      </div>
    </div>
  );
}

export function LegalSection({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="legal-section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

export function LegalList({ children }: { children: ReactNode }) {
  return <ul className="legal-list">{children}</ul>;
}

export function LegalCallout({
  title,
  tone = 'info',
  children,
}: {
  title: string;
  tone?: 'info' | 'warning';
  children: ReactNode;
}) {
  return (
    <aside className={`legal-callout legal-callout--${tone}`} role="note">
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </aside>
  );
}
