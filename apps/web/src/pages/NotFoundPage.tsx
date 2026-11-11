import { Link, useNavigate } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { SearchBox } from '../components/SearchBox';
import { useDocumentTitle } from '../lib/hooks';

export default function NotFoundPage() {
  useDocumentTitle('Страница не найдена — MangaPoisk Reborn');
  const navigate = useNavigate();

  return (
    <section className="not-found" aria-labelledby="notfound-title">
      <div className="not-found__inner">
        <div className="not-found__code" aria-hidden="true">
          404
        </div>
        <h1 className="not-found__title" id="notfound-title">
          Эта страница потерялась между главами
        </h1>
        <p className="not-found__text">
          Возможно, ссылка устарела или в адресе опечатка. Вернитесь на главную, откройте каталог
          или найдите нужную историю поиском.
        </p>
        <div className="not-found__search">
          <SearchBox
            size="lg"
            placeholder="Название манги…"
            ariaLabel="Поиск манги на странице 404"
            onSubmit={(value) =>
              navigate(value ? `/catalogue?q=${encodeURIComponent(value)}` : '/catalogue')
            }
          />
        </div>
        <div className="not-found__actions">
          <Link to="/" className="btn btn--primary btn--lg">
            <Icon name="home" size={18} />
            На главную
          </Link>
          <Link to="/catalogue" className="btn btn--outline btn--lg">
            <Icon name="compass" size={18} />
            В каталог
          </Link>
        </div>
      </div>
    </section>
  );
}
