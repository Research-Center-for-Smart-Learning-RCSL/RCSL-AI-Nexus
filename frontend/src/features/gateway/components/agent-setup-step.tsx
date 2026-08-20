import type { ReactNode } from 'react';

export function Step({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <h3 className="font-heading text-sm font-semibold">
        <span className="mr-2 inline-flex size-5 items-center justify-center rounded-full bg-muted text-xs">
          {n}
        </span>
        {title}
      </h3>
      <div className="space-y-2 pl-7 text-sm text-muted-foreground">
        {children}
      </div>
    </div>
  );
}
