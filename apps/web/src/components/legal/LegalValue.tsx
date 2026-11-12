import { legalDisplayValue, isValidContactEmail } from '../../lib/legal';

export function LegalValue({
  value,
  envKey,
  email = false,
}: {
  value: string | null;
  envKey: string;
  email?: boolean;
}) {
  const display = legalDisplayValue(value, envKey);

  if (display.isPlaceholder || (email && !isValidContactEmail(value))) {
    return (
      <mark className="legal-placeholder">
        {display.isPlaceholder
          ? display.text
          : `Некорректный адрес — проверьте ${envKey} перед запуском`}
      </mark>
    );
  }

  if (email) {
    return <a href={`mailto:${value}`}>{value}</a>;
  }

  return <span>{display.text}</span>;
}
