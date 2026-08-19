'use client';

import { memo, useMemo } from 'react';
import Markdown from 'react-markdown';
import rehypeSanitize from 'rehype-sanitize';

export const SanitisedMarkdown = memo(function SanitisedMarkdown({
  text,
}: {
  text: string;
}) {
  const plugins = useMemo(() => [rehypeSanitize], []);
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert [&_pre]:overflow-x-auto">
      <Markdown rehypePlugins={plugins}>{text}</Markdown>
    </div>
  );
});
