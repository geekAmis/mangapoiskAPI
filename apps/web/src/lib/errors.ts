import { ApiError, isApiError } from '../api/client';

const DEFAULT_MESSAGE = 'Что-то пошло не так. Попробуйте ещё раз.';

export function isOfflineError(error: unknown): boolean {
  return isApiError(error) && error.status === 0;
}

export function humanizeError(error: unknown, fallback = DEFAULT_MESSAGE): string {
  if (!isApiError(error)) return fallback;

  if (error.status === 0) {
    return 'Нет соединения с сервером. Проверьте интернет и попробуйте снова.';
  }

  switch (error.status) {
    case 400:
      return 'Сервер не принял запрос. Проверьте введённые данные.';
    case 401:
      return 'Сессия истекла. Войдите в аккаунт снова.';
    case 403:
      return 'Недостаточно прав для этого действия.';
    case 404:
      return 'Запрашиваемая информация не найдена.';
    case 409:
      return 'Такая запись уже существует.';
    case 413:
      return 'Файл слишком большой.';
    case 422:
      return 'Проверьте правильность заполнения полей.';
    case 429:
      return 'Слишком много запросов. Подождите немного и попробуйте снова.';
    case 500:
    case 502:
    case 503:
    case 504:
      return 'Сервер временно недоступен. Попробуйте чуть позже.';
    default:
      break;
  }

  if (error.code === 'rate_limited') {
    return 'Слишком много запросов. Подождите немного и попробуйте снова.';
  }
  if (error.code === 'not_found') return 'Запрашиваемая информация не найдена.';
  if (error.code === 'unauthorized') return 'Сессия истекла. Войдите в аккаунт снова.';

  return fallback;
}

export function authErrorMessage(error: unknown, mode: 'login' | 'register'): string {
  if (!isApiError(error)) return DEFAULT_MESSAGE;

  if (error.status === 0) {
    return 'Нет соединения с сервером. Проверьте интернет и попробуйте снова.';
  }
  if (error.status === 401) {
    return mode === 'login' ? 'Неверный email или пароль.' : 'Не удалось создать аккаунт.';
  }
  if (error.status === 409) {
    return 'Аккаунт с таким email уже существует. Попробуйте войти.';
  }
  if (error.status === 422) {
    return 'Проверьте email, пароль и имя: некоторые поля заполнены неверно.';
  }
  if (error.status === 429) {
    return 'Слишком много попыток. Подождите несколько минут.';
  }
  if (error.status >= 500) {
    return 'Сервер временно недоступен. Попробуйте чуть позже.';
  }
  if (error.code.includes('email') || error.code.includes('exists')) {
    return 'Аккаунт с таким email уже существует.';
  }
  return mode === 'login' ? 'Не удалось войти. Попробуйте ещё раз.' : 'Не удалось создать аккаунт.';
}

export function apiErrorDetails(error: unknown): ApiError | null {
  return isApiError(error) ? error : null;
}
