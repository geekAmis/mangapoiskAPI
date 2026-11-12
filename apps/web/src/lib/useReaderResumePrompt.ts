import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * A saved position is only offered after the reader has been idle for a
 * moment.  Otherwise a slow progress request can make the prompt pop up on
 * top of a chapter the user has already started reading.
 */
export const RESUME_PROMPT_DELAY_MS = 1800;

interface ReaderResumePromptOptions {
  /** Loaded chapter id; an empty value means the chapter is not ready yet. */
  chapterId: string;
  currentPage: number;
  /** Validated saved page for this chapter, or null when there is none. */
  savedPage: number | null;
  resumeReady: boolean;
  requestedPage: boolean;
}

interface ReaderResumePromptState {
  showResume: boolean;
  progressEnabled: boolean;
  dismissResume: () => void;
}

export function useReaderResumePrompt({
  chapterId,
  currentPage,
  savedPage,
  resumeReady,
  requestedPage,
}: ReaderResumePromptOptions): ReaderResumePromptState {
  const [dismissed, setDismissed] = useState(false);
  const [armed, setArmed] = useState(false);
  const [progressEnabled, setProgressEnabled] = useState(false);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // A new chapter always starts with a clean prompt state.
  useEffect(() => {
    setDismissed(false);
    setArmed(false);
    setProgressEnabled(false);
    clearTimer();
  }, [chapterId, clearTimer]);

  useEffect(() => {
    if (!chapterId) return;
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setArmed(true);
    }, RESUME_PROMPT_DELAY_MS);
    return clearTimer;
  }, [chapterId, clearTimer]);

  const dismissResume = useCallback(() => {
    clearTimer();
    setDismissed(true);
    setProgressEnabled(true);
  }, [clearTimer]);

  const promptCandidate = Boolean(
    savedPage &&
      !requestedPage &&
      !dismissed &&
      savedPage > currentPage + 1,
  );

  // Without a candidate prompt, normal progress saving can start immediately.
  // A deep link (?page=) is an explicit position and never shows the prompt.
  useEffect(() => {
    if (requestedPage) {
      setProgressEnabled(true);
      return;
    }
    if (!resumeReady) return;
    setProgressEnabled(!promptCandidate);
  }, [requestedPage, resumeReady, promptCandidate]);

  const showResume = Boolean(
    resumeReady && armed && promptCandidate && !progressEnabled,
  );

  return { showResume, progressEnabled, dismissResume };
}
