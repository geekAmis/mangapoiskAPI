import { DancingLoader } from './DancingLoader';

export function PageLoader({ label = 'Загружаем страницу…' }: { label?: string }) {
  return <DancingLoader overlay label={label} />;
}

export function ReaderFallback() {
  return <DancingLoader overlay label="Открываем главу…" />;
}
