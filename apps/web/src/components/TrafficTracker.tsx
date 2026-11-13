import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { analyticsOptedOut } from '../lib/analytics';
import { installMetrika, metrikaCounterId, metrikaHit } from '../lib/metrika';
import { recordTrafficVisit, trafficPathGroup } from '../lib/traffic';

interface TrafficTrackerProps {
  /**
   * Counter id override for tests.  Undefined reads the build-time env;
   * null/empty disables Metrika injection while keeping the first-party
   * traffic beacon active.
   */
  counterId?: string | null;
}

/**
 * SPA page-view tracker.
 *
 * Public routes only; private/admin/reader pages and DNT/GPC visitors are
 * skipped both in Metrika and in the first-party traffic beacon.  The ref
 * guard prevents duplicate effects (StrictMode, re-renders) from counting the
 * same pathname twice.
 */
export function TrafficTracker({ counterId }: TrafficTrackerProps = {}) {
  const location = useLocation();
  const lastPath = useRef<string | null>(null);

  useEffect(() => {
    const path = location.pathname || '/';
    if (lastPath.current === path) return;
    lastPath.current = path;

    const group = trafficPathGroup(path);
    if (group === null || analyticsOptedOut()) return;

    const rawId = counterId === undefined ? undefined : (counterId ?? '');
    const id = metrikaCounterId(rawId);
    if (id) {
      installMetrika(id);
      metrikaHit(id, path, group);
    }
    recordTrafficVisit(path);
  }, [location.pathname, counterId]);

  return null;
}
