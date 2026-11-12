import type { ReactNode, SVGProps } from 'react';

const ICONS = {
  home: (
    <>
      <path d="m3.5 10.5 8.5-7 8.5 7" />
      <path d="M5.5 9.5V20h13V9.5" />
      <path d="M9.5 20v-6h5v6" />
    </>
  ),
  grid: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.6" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.6" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.6" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.6" />
    </>
  ),
  bookmark: <path d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-4.2L6 21V4.5Z" />,
  user: (
    <>
      <circle cx="12" cy="8" r="3.6" />
      <path d="M4.5 20.5c.7-3.8 3.5-6 7.5-6s6.8 2.2 7.5 6" />
    </>
  ),
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.6" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  close: (
    <>
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </>
  ),
  menu: (
    <>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </>
  ),
  'chevron-left': <path d="m14.5 5.5-6.5 6.5 6.5 6.5" />,
  'chevron-right': <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />,
  'chevron-down': <path d="m5.5 9.5 6.5 6.5 6.5-6.5" />,
  'chevron-up': <path d="m5.5 14.5 6.5-6.5 6.5 6.5" />,
  star: <path d="m12 3.6 2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.8-5.2 2.8 1-5.8L3.5 9.8l5.9-.9L12 3.6Z" />,
  book: (
    <>
      <path d="M4 5.5C7 4 9.7 4.4 12 6.2c2.3-1.8 5-2.2 8-.7v13c-3-1.5-5.7-1.1-8 .7-2.3-1.8-5-2.2-8-.7v-13Z" />
      <path d="M12 6.2v13" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5.3l3.4 2" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h6" />
      <path d="M14 7h6" />
      <circle cx="12" cy="7" r="2" />
      <path d="M4 17h4" />
      <path d="M12 17h8" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  palette: (
    <>
      <path d="M12 3.5a8.5 8.5 0 1 0 0 17h1.2a1.8 1.8 0 0 0 1-3.3 1.8 1.8 0 0 1 1-3.3h2.3a3 3 0 0 0 3-3C20.5 6.6 16.9 3.5 12 3.5Z" />
      <circle cx="7.8" cy="9" r="1" fill="currentColor" stroke="none" />
      <circle cx="10.5" cy="6.6" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.4" cy="6.8" r="1" fill="currentColor" stroke="none" />
      <circle cx="7.2" cy="13" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  download: (
    <>
      <path d="M12 3.5v11" />
      <path d="m7.5 10.5 4.5 4.5 4.5-4.5" />
      <path d="M5 20.5h14" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6" />
      <path d="m20 4-9 9" />
      <path d="M18 14v5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 19V8a1.5 1.5 0 0 1 1.5-1.5h5" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.8 21 20H3L12 3.8Z" />
      <path d="M12 9v5" />
      <circle cx="12" cy="17.3" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  check: <path d="m4.5 12.5 5 5L19.5 7" />,
  eye: (
    <>
      <path d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  'eye-off': (
    <>
      <path d="M3 3.5 21 20.5" />
      <path d="M9.8 6.2A10.7 10.7 0 0 1 12 6c6 0 9.5 6 9.5 6a17.3 17.3 0 0 1-3 3.6" />
      <path d="M6.2 7.6A17 17 0 0 0 2.5 12S6 18 12 18a10 10 0 0 0 4.2-.9" />
      <path d="M10 10.2a2.8 2.8 0 0 0 3.8 3.8" />
    </>
  ),
  filter: (
    <>
      <path d="M4 6h16" />
      <path d="M7 12h10" />
      <path d="M10 18h4" />
    </>
  ),
  logout: (
    <>
      <path d="M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10" />
      <path d="M15 8l4 4-4 4" />
      <path d="M19 12H9" />
    </>
  ),
  maximize: (
    <>
      <path d="M8.5 3.5h-5v5" />
      <path d="M15.5 3.5h5v5" />
      <path d="M20.5 15.5v5h-5" />
      <path d="M3.5 15.5v5h5" />
    </>
  ),
  minimize: (
    <>
      <path d="M3.5 8.5h5v-5" />
      <path d="M20.5 8.5h-5v-5" />
      <path d="M20.5 15.5h-5v5" />
      <path d="M3.5 15.5h5v5" />
    </>
  ),
  columns: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M12 4.5v15" />
    </>
  ),
  scroll: (
    <>
      <rect x="5.5" y="2.5" width="13" height="19" rx="6.5" />
      <path d="M12 7v4" />
      <path d="m10.2 9.2 1.8 1.8 1.8-1.8" />
      <path d="M12 17v-4" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M9.5 7V4.5h5V7" />
      <path d="m6.5 7 .8 13h9.4l.8-13" />
      <path d="M10 11v5.5" />
      <path d="M14 11v5.5" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 5.5v5h-5" />
      <path d="M4 18.5v-5h5" />
      <path d="M18.5 9.5A7 7 0 0 0 6.6 7.2L4 10.5" />
      <path d="M5.5 14.5a7 7 0 0 0 11.9 2.3L20 13.5" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.8" r=".9" fill="currentColor" stroke="none" />
    </>
  ),
  'arrow-left': (
    <>
      <path d="M20 12H4" />
      <path d="m10 6-6 6 6 6" />
    </>
  ),
  'arrow-right': (
    <>
      <path d="M4 12h16" />
      <path d="m14 6 6 6-6 6" />
    </>
  ),
  play: <path d="M7.5 4.8 19 12 7.5 19.2V4.8Z" />,
  pause: (
    <>
      <path d="M8.5 4.5v15" />
      <path d="M15.5 4.5v15" />
    </>
  ),
  sparkles: (
    <>
      <path d="m12 3 1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3Z" />
      <path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" />
    </>
  ),
  link: (
    <>
      <path d="M10 13.5a4 4 0 0 0 5.7 0l2.8-2.8a4 4 0 1 0-5.7-5.7L11.5 6.3" />
      <path d="M14 10.5a4 4 0 0 0-5.7 0l-2.8 2.8a4 4 0 1 0 5.7 5.7l1.3-1.3" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5.5" width="18" height="13" rx="2" />
      <path d="m3.8 7 8.2 6 8.2-6" />
    </>
  ),
  lock: (
    <>
      <rect x="4.5" y="10" width="15" height="10.5" rx="2" />
      <path d="M8 10V7.5a4 4 0 0 1 8 0V10" />
      <circle cx="12" cy="15.2" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3 20 6v5.5c0 4.6-3 7.7-8 9.5-5-1.8-8-4.9-8-9.5V6l8-3Z" />
      <path d="m8.5 12 2.3 2.3 4.7-4.8" />
    </>
  ),
  list: (
    <>
      <path d="M9 6h11" />
      <path d="M9 12h11" />
      <path d="M9 18h11" />
      <circle cx="4.5" cy="6" r="1" fill="currentColor" stroke="none" />
      <circle cx="4.5" cy="12" r="1" fill="currentColor" stroke="none" />
      <circle cx="4.5" cy="18" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  compass: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" />
    </>
  ),
  loader: (
    <>
      <path d="M12 3a9 9 0 0 1 9 9" />
      <path d="M12 21a9 9 0 0 1-9-9" opacity=".45" />
    </>
  ),
  edit: (
    <>
      <path d="m4 20 1-5L16.5 3.5a2 2 0 0 1 2.8 0l1.2 1.2a2 2 0 0 1 0 2.8L9 19l-5 1Z" />
      <path d="m14.5 5.5 4 4" />
    </>
  ),
  terminal: (
    <>
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <path d="m8 9 3 3-3 3" />
      <path d="M13.5 15H17" />
    </>
  ),
  server: (
    <>
      <rect x="3.5" y="4" width="17" height="6" rx="1.8" />
      <rect x="3.5" y="14" width="17" height="6" rx="1.8" />
      <path d="M7 7h.01M7 17h.01" />
      <path d="M11 7h6M11 17h6" opacity=".55" />
    </>
  ),
  power: (
    <>
      <path d="M12 3v9" />
      <path d="M6.5 6.5a8 8 0 1 0 11 0" />
    </>
  ),
  heart: (
    <path d="M12 20.2S4.6 15.7 4.6 10.4A4.1 4.1 0 0 1 12 7.8a4.1 4.1 0 0 1 7.4 2.6c0 5.3-7.4 9.8-7.4 9.8Z" />
  ),
  message: (
    <>
      <path d="M4 5.5h16v10.2H9.2L4 20V5.5Z" />
      <path d="M8 9.2h8M8 12.2h5.5" opacity=".6" />
    </>
  ),
  send: (
    <>
      <path d="m21 3-7.4 18-4-7.6L2 9.4 21 3Z" />
      <path d="M21 3 9.6 13.4" opacity=".6" />
    </>
  ),
  bell: (
    <>
      <path d="M6 9.5a6 6 0 0 1 12 0c0 5 1.6 6.8 2.2 7.5H3.8C4.4 16.3 6 14.5 6 9.5Z" />
      <path d="M9.6 20a2.6 2.6 0 0 0 4.8 0" />
    </>
  ),
  'bell-off': (
    <>
      <path d="M6 9.5a6 6 0 0 1 9.7-4.8" />
      <path d="M18 11.5c0 4 1.2 5.7 1.8 6.4H8.5" />
      <path d="M9.6 20a2.6 2.6 0 0 0 4.8 0" />
      <path d="m3.5 3.5 17 17" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof ICONS;

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
  size?: number;
  title?: string;
}

export function Icon({ name, size = 20, title, className, strokeWidth = 1.8, ...rest }: IconProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      {ICONS[name]}
    </svg>
  );
}
