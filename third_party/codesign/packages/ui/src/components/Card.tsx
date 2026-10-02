import type { HTMLAttributes, ReactNode } from 'react';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  elevated?: boolean;
  children: ReactNode;
}

export function Card({ elevated = false, className = '', children, ...rest }: CardProps) {
  const shadow = elevated ? 'shadow-[var(--shadow-card)]' : 'shadow-[var(--shadow-soft)]';
  return (
    <div
      className={`bg-[var(--color-surface)] border border-[var(--color-border)] rounded-[var(--radius-xl)] ${shadow} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}
