import type { IconName } from '../../components/Icon';

export type AdminTabId =
  | 'overview'
  | 'servers'
  | 'deploy'
  | 'crawler'
  | 'media'
  | 'ads'
  | 'comments'
  | 'integrations'
  | 'audit'
  | 'terminal';

export interface AdminTabDefinition {
  id: AdminTabId;
  label: string;
  shortLabel: string;
  icon: IconName;
  description: string;
}

export const ADMIN_TABS: AdminTabDefinition[] = [
  {
    id: 'overview',
    label: 'Обзор',
    shortLabel: 'Обзор',
    icon: 'grid',
    description: 'Здоровье контура, активные задачи и последние события.',
  },
  {
    id: 'servers',
    label: 'Серверы',
    shortLabel: 'Серверы',
    icon: 'server',
    description: 'Inventory, health-check, реестр gateway и управление узлами.',
  },
  {
    id: 'deploy',
    label: 'Деплой',
    shortLabel: 'Деплой',
    icon: 'download',
    description: 'Задачи развёртывания, rollback и журнал выполнения.',
  },
  {
    id: 'crawler',
    label: 'Краулер и каталог',
    shortLabel: 'Каталог',
    icon: 'compass',
    description: 'Источники, backlog, ETA и обогащение каталога.',
  },
  {
    id: 'media',
    label: 'Медиа и хранилище',
    shortLabel: 'Медиа',
    icon: 'book',
    description: 'Кеш изображений, архивы глав и политика вытеснения.',
  },
  {
    id: 'ads',
    label: 'Реклама',
    shortLabel: 'Реклама',
    icon: 'sparkles',
    description: 'Провайдеры, ключи, слоты и аудитории.',
  },
  {
    id: 'comments',
    label: 'Комментарии',
    shortLabel: 'Комменты',
    icon: 'message',
    description: 'Жалобы читателей и модерация комментариев.',
  },
  {
    id: 'integrations',
    label: 'Интеграции',
    shortLabel: 'Интеграции',
    icon: 'link',
    description: 'Яндекс ID, cookie источников и импорт HAR.',
  },
  {
    id: 'audit',
    label: 'Аудит',
    shortLabel: 'Аудит',
    icon: 'list',
    description: 'Последние действия администраторов и control-сервиса.',
  },
  {
    id: 'terminal',
    label: 'Терминал',
    shortLabel: 'Терминал',
    icon: 'terminal',
    description: 'Ограниченная серверная консоль: allowlist и структурированные действия.',
  },
];

const TAB_IDS = new Set<string>(ADMIN_TABS.map((tab) => tab.id));

export function parseAdminTab(value: string | null | undefined): AdminTabId {
  return value && TAB_IDS.has(value) ? (value as AdminTabId) : 'overview';
}

export function adminTabDefinition(id: AdminTabId): AdminTabDefinition {
  return ADMIN_TABS.find((tab) => tab.id === id) ?? ADMIN_TABS[0];
}
