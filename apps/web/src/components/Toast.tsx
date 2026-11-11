import { useToastStore } from '../stores/toast';
import { Icon, type IconName } from './Icon';

const TONE_ICONS: Record<string, IconName> = {
  info: 'info',
  success: 'check',
  error: 'alert',
};

export function ToastHost() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  return (
    <div className="toast-region" aria-live="polite" aria-relevant="additions">
      {toasts.map((item) => (
        <div key={item.id} className={`toast toast--${item.tone}`} role={item.tone === 'error' ? 'alert' : 'status'}>
          <span className="toast__icon" aria-hidden="true">
            <Icon name={TONE_ICONS[item.tone] ?? 'info'} size={18} />
          </span>
          <span className="toast__message">{item.message}</span>
          <button
            type="button"
            className="toast__close"
            onClick={() => dismiss(item.id)}
            aria-label="Закрыть уведомление"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}
