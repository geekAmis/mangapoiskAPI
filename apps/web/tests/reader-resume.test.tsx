import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ReaderResumePrompt } from '../src/components/ReaderResumePrompt';
import {
  RESUME_PROMPT_DELAY_MS,
  useReaderResumePrompt,
} from '../src/lib/useReaderResumePrompt';

interface PromptProps {
  chapterId: string;
  currentPage: number;
  savedPage: number | null;
  resumeReady: boolean;
  requestedPage: boolean;
}

const BASE_PROPS: PromptProps = {
  chapterId: 'chapter-1',
  currentPage: 1,
  savedPage: 3,
  resumeReady: true,
  requestedPage: false,
};

function renderPrompt(overrides: Partial<PromptProps> = {}) {
  const initialProps = { ...BASE_PROPS, ...overrides };
  return renderHook(
    (props: PromptProps) => useReaderResumePrompt(props),
    { initialProps },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('reader resume prompt', () => {
  it('stays hidden when resume data arrives after the user interacted', () => {
    const { result, rerender } = renderPrompt({
      savedPage: null,
      resumeReady: false,
    });

    act(() => {
      vi.advanceTimersByTime(RESUME_PROMPT_DELAY_MS);
    });
    expect(result.current.showResume).toBe(false);

    // Wheel/scroll/page navigation dismisses the prompt before the slow
    // progress request resolves.
    act(() => result.current.dismissResume());
    rerender({ ...BASE_PROPS, savedPage: 3, resumeReady: true });

    expect(result.current.showResume).toBe(false);
    expect(result.current.progressEnabled).toBe(true);
  });

  it('never shows the prompt when the saved page is the current page or behind', () => {
    const current = renderPrompt({ currentPage: 3, savedPage: 3 });
    act(() => {
      vi.advanceTimersByTime(RESUME_PROMPT_DELAY_MS);
    });
    expect(current.result.current.showResume).toBe(false);
    expect(current.result.current.progressEnabled).toBe(true);

    const behind = renderPrompt({ currentPage: 3, savedPage: 2 });
    act(() => {
      vi.advanceTimersByTime(RESUME_PROMPT_DELAY_MS);
    });
    expect(behind.result.current.showResume).toBe(false);
    expect(behind.result.current.progressEnabled).toBe(true);
  });

  it('shows the prompt for an idle reader only after the grace period', () => {
    const { result } = renderPrompt({ savedPage: 3, currentPage: 1 });

    expect(result.current.showResume).toBe(false);
    expect(result.current.progressEnabled).toBe(false);

    act(() => {
      vi.advanceTimersByTime(RESUME_PROMPT_DELAY_MS - 1);
    });
    expect(result.current.showResume).toBe(false);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.showResume).toBe(true);
    expect(result.current.progressEnabled).toBe(false);
  });

  it('does not arm the prompt after an interaction and clears the timer', () => {
    const { result } = renderPrompt({ savedPage: 3, currentPage: 1 });

    act(() => result.current.dismissResume());
    act(() => {
      vi.advanceTimersByTime(RESUME_PROMPT_DELAY_MS);
    });

    expect(result.current.showResume).toBe(false);
    expect(result.current.progressEnabled).toBe(true);
  });

  it('clears the pending timer on unmount', () => {
    const clearTimeout = vi.spyOn(window, 'clearTimeout');
    const { unmount } = renderPrompt({ savedPage: 3, currentPage: 1 });

    expect(vi.getTimerCount()).toBe(1);
    unmount();

    expect(vi.getTimerCount()).toBe(0);
    expect(clearTimeout).toHaveBeenCalled();
  });
});

describe('ReaderResumePrompt', () => {
  it('renders the saved page and wires both actions', () => {
    const onContinue = vi.fn();
    const onStartOver = vi.fn();

    render(
      <ReaderResumePrompt
        page={3}
        onContinue={onContinue}
        onStartOver={onStartOver}
      />,
    );

    expect(screen.getByText('Продолжить со страницы 3?')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Продолжить' }));
    expect(onContinue).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'С начала' }));
    expect(onStartOver).toHaveBeenCalledTimes(1);
  });
});
