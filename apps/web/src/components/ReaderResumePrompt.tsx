interface ReaderResumePromptProps {
  page: number;
  onContinue: () => void;
  onStartOver: () => void;
}

export function ReaderResumePrompt({
  page,
  onContinue,
  onStartOver,
}: ReaderResumePromptProps) {
  return (
    <div className="reader-resume" role="status">
      <div className="reader-resume__body">
        <div className="reader-resume__title">Продолжить со страницы {page}?</div>
        <div className="reader-resume__text">
          Вы остановились здесь в прошлый раз. Можно начать заново.
        </div>
      </div>
      <div className="reader-resume__actions">
        <button type="button" className="btn btn--primary" onClick={onContinue}>
          Продолжить
        </button>
        <button type="button" className="btn btn--ghost" onClick={onStartOver}>
          С начала
        </button>
      </div>
    </div>
  );
}
