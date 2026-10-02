import { useT } from '@open-codesign/i18n';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface AssistantTextProps {
  text: string;
  /** When true, append three animated dots after the text to signal streaming. */
  streaming?: boolean;
}

export function AssistantText({ text, streaming }: AssistantTextProps) {
  const t = useT();
  return (
    <div className="space-y-[var(--space-1_5)]">
      <div className="max-w-[90%] rounded-2xl rounded-bl-md bg-[var(--color-surface)] shadow-[0_1px_3px_rgba(0,0,0,0.06)] border border-[var(--color-border-muted)] px-[var(--space-3)] py-[var(--space-2)] text-[14px] leading-relaxed text-[var(--color-text-primary)] break-words codesign-prose">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      {streaming ? (
        <div
          className="flex items-center gap-[5px] pl-[var(--space-2)] h-[16px]"
          aria-label={t('sidebar.chat.streamingLabel')}
        >
          <span className="codesign-stream-dot" />
          <span className="codesign-stream-dot" style={{ animationDelay: '150ms' }} />
          <span className="codesign-stream-dot" style={{ animationDelay: '300ms' }} />
        </div>
      ) : null}
    </div>
  );
}
