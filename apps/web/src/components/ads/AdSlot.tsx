import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  fetchAdsConfig,
  useAdsConsent,
  type AdPlacement,
  type AdSlotConfig,
} from '../../api/ads';
import { useAuthStore } from '../../stores/auth';
import '../../styles/ads.css';

const CAP_WINDOW_MS = 24 * 60 * 60 * 1000;
const CAP_PREFIX = 'mp-ads-cap:';
const YANDEX_BLOCK_ID_RE = /^R-A-\d+-\d+$/;

export function yandexBlockIdFromConfig(
  config: Record<string, unknown> | undefined,
): string | null {
  const raw = config?.block_id;
  if (typeof raw !== 'string') return null;
  const blockId = raw.trim();
  return YANDEX_BLOCK_ID_RE.test(blockId) ? blockId : null;
}

function yandexContainerId(blockId: string): string {
  return `yandex_rtb_${blockId}`;
}

const DEFAULT_SIZES: Record<AdPlacement, { width: number; height: number }> = {
  header: { width: 970, height: 90 },
  sidebar: { width: 300, height: 250 },
  'in-feed': { width: 728, height: 90 },
  'post-chapter': { width: 728, height: 90 },
  'mobile-sticky': { width: 320, height: 50 },
};

interface CapState {
  count: number;
  since: number;
}

function readCap(id: string): CapState | null {
  try {
    const raw = localStorage.getItem(`${CAP_PREFIX}${id}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<CapState>;
    if (typeof parsed.count !== 'number' || typeof parsed.since !== 'number') return null;
    if (Date.now() - parsed.since > CAP_WINDOW_MS) return null;
    return { count: parsed.count, since: parsed.since };
  } catch {
    return null;
  }
}

function canShow(slot: AdSlotConfig): boolean {
  if (!slot.frequency_cap) return true;
  const cap = readCap(slot.id);
  return !cap || cap.count < slot.frequency_cap;
}

function recordImpression(slot: AdSlotConfig): void {
  if (!slot.frequency_cap) return;
  try {
    const current = readCap(slot.id) ?? { count: 0, since: Date.now() };
    localStorage.setItem(
      `${CAP_PREFIX}${slot.id}`,
      JSON.stringify({ count: current.count + 1, since: current.since }),
    );
  } catch {
    /* приватный режим: лимит не сохраняется */
  }
}

function sizeFor(slot: AdSlotConfig, placement: AdPlacement): { width: number; height: number } {
  const fallback = DEFAULT_SIZES[placement];
  return {
    width: slot.width && slot.width > 0 ? slot.width : fallback.width,
    height: slot.height && slot.height > 0 ? slot.height : fallback.height,
  };
}

interface AdSlotProps {
  placement: AdPlacement;
  adult?: boolean;
  className?: string;
}

/**
 * One reserved advertising placement.
 *
 * - The slot is absent (not an empty box) when no provider is configured.
 * - When a provider exists, the inner frame has a fixed height so a late
 *   banner/error cannot shift the page (CLS).
 * - A failed public-config request (adblock, control outage) renders nothing
 *   and does not write to the console.
 */
export function AdSlot({ placement, adult = false, className = '' }: AdSlotProps) {
  const token = useAuthStore((state) => state.accessToken);
  const consent = useAdsConsent();
  const [contentFailed, setContentFailed] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const recordedRef = useRef<string | null>(null);

  const query = useQuery({
    queryKey: ['ads-config', Boolean(token), adult, consent],
    queryFn: ({ signal }) => fetchAdsConfig({ adult, signal }),
    // Consent changes use a new query key.  Keeping the previous slots while
    // the new response loads avoids removing/re-creating the Yandex container
    // (and therefore a duplicate SDK render) on every consent click.
    placeholderData: (previousData) => previousData,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const slot = useMemo(
    () =>
      (query.data ?? []).find(
        (item) =>
          item.placement === placement &&
          (!item.require_consent || consent === 'granted') &&
          canShow(item),
      ),
    [query.data, placement, consent],
  );

  const yandexBlockId =
    slot?.type === 'yandex' ? yandexBlockIdFromConfig(slot.config) : null;
  const yandexRenderTo = yandexBlockId ? yandexContainerId(yandexBlockId) : null;
  const yandexRenderedRef = useRef<string | null>(null);
  const yandexAliveRef = useRef(false);

  useEffect(() => {
    if (!slot) return;
    if (recordedRef.current === slot.id) return;
    recordedRef.current = slot.id;
    recordImpression(slot);
  }, [slot]);

  useEffect(() => {
    setContentFailed(false);
  }, [slot?.id]);

  useEffect(() => {
    if (placement !== 'mobile-sticky' || !slot) return;
    document.body.classList.add('has-mobile-ad');
    return () => document.body.classList.remove('has-mobile-ad');
  }, [placement, slot]);

  useEffect(() => {
    if (slot?.content_type !== 'html') return;
    const root = contentRef.current;
    if (!root) return;
    const onError = (event: Event) => {
      if (event.target instanceof HTMLImageElement) {
        event.target.style.visibility = 'hidden';
        setContentFailed(true);
      }
    };
    root.addEventListener('error', onError, true);
    return () => root.removeEventListener('error', onError, true);
  }, [slot?.id, slot?.content_type]);

  useEffect(() => {
    if (slot?.type !== 'yandex' || !yandexBlockId || !yandexRenderTo) {
      yandexRenderedRef.current = null;
      yandexAliveRef.current = false;
      return;
    }

    const key = `${slot.id}:${yandexBlockId}`;
    yandexAliveRef.current = true;
    if (yandexRenderedRef.current === key) {
      // StrictMode runs effects twice without replacing the DOM node.  The
      // keyed ref keeps the SDK render exactly once for the same slot/block.
      return () => {
        yandexAliveRef.current = false;
      };
    }
    yandexRenderedRef.current = key;

    const render = () => {
      if (!yandexAliveRef.current || yandexRenderedRef.current !== key) return;
      const target = document.getElementById(yandexRenderTo);
      if (!target || target.dataset.yandexRendered === 'true') return;
      const advManager = window.Ya?.Context?.AdvManager;
      if (!advManager || typeof advManager.render !== 'function') return;
      target.dataset.yandexRendered = 'true';
      try {
        advManager.render({ blockId: yandexBlockId, renderTo: yandexRenderTo });
      } catch {
        // Adblock or a failed SDK call must not break the page or log errors.
        delete target.dataset.yandexRendered;
      }
    };

    if (window.Ya?.Context?.AdvManager?.render) {
      render();
    } else {
      const queue = Array.isArray(window.yaContextCb)
        ? window.yaContextCb
        : (window.yaContextCb = []);
      queue.push(render);
    }

    return () => {
      yandexAliveRef.current = false;
    };
  }, [slot?.id, slot?.type, yandexBlockId, yandexRenderTo]);

  if (!slot) return null;

  const size = sizeFor(slot, placement);
  const style = {
    '--ad-slot-width': `${size.width}px`,
    '--ad-slot-height': `${size.height}px`,
  } as CSSProperties;

  return (
    <aside
      className={`ad-slot ad-slot--${placement} ${className}`.trim()}
      style={style}
      aria-label="Реклама"
      data-ad-slot={slot.id}
      data-ad-provider={slot.type}
    >
      <span className="ad-slot__label">Реклама</span>
      {slot.type === 'yandex' ? (
        yandexBlockId && yandexRenderTo ? (
          <div id={yandexRenderTo} className="ad-slot__yandex" />
        ) : (
          <div className="ad-slot__placeholder">
            {slot.format || 'Рекламный блок'}
          </div>
        )
      ) : slot.content_type === 'html' && slot.content && !contentFailed ? (
        <div
          ref={contentRef}
          className="ad-slot__content"
          // Server-side sanitizer (services/control/app/ads.py) removes
          // scripts, event handlers, iframes and unsafe URL schemes.
          dangerouslySetInnerHTML={{ __html: slot.content }}
        />
      ) : slot.content_type === 'script' && slot.content ? (
        <iframe
          className="ad-slot__frame"
          title={`Рекламный блок: ${slot.name}`}
          srcDoc={slot.content}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
          loading="lazy"
        />
      ) : (
        <div className="ad-slot__placeholder">
          {contentFailed ? 'Рекламный блок недоступен' : slot.format || 'Рекламный блок'}
        </div>
      )}
    </aside>
  );
}
