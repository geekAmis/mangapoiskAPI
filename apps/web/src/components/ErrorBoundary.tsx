import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Icon } from './Icon';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  message: string;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, message: '' };

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : 'Неизвестная ошибка',
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('MangaPoisk Reborn: неперехваченная ошибка интерфейса', error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="fatal-screen">
        <div className="fatal-screen__card">
          <span className="fatal-screen__icon" aria-hidden="true">
            <Icon name="alert" size={30} />
          </span>
          <h1>Что-то сломалось</h1>
          <p>
            Интерфейс столкнулся с непредвиденной ошибкой. Перезагрузите страницу — данные и
            настройки сохранены локально.
          </p>
          {import.meta.env.DEV && this.state.message ? (
            <pre className="fatal-screen__debug">{this.state.message}</pre>
          ) : null}
          <div className="fatal-screen__actions">
            <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
              <Icon name="refresh" size={17} />
              Перезагрузить
            </button>
            <a className="btn btn--outline" href="/">
              На главную
            </a>
          </div>
        </div>
      </div>
    );
  }
}
