import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { RefusalsTable } from '@/features/refusals/components/refusals-table';

export const metadata: Metadata = { title: 'Refusals' };

export default function RefusalsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Refusals</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          Every request this platform turned away, with the message the caller
          was given and the figures that came with it. Your own by default;
          everyone’s with <code className="font-mono">refusal:read_all</code>.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          This screen exists because on 17 August two people spent an evening
          each on refusals that were correct, permanent, and silent about which
          of several things they had just changed had caused them. Both messages
          were fixed; neither fix helps the next one nobody has thought about,
          and nothing stored a refusal at all — so answering “what happened at
          19:16?” meant an administrator reading container logs.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Nothing here is more than you were already told. No request content is
          stored, no model is named, and the operator-facing detail that
          accompanies an error never leaves the server.
        </p>
      </div>
      <RefusalsTable />
      <RelatedScreens
        items={[
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'what people did, rather than what they were refused; a failed sign-in or an authorization denial is recorded there and not here',
          },
          {
            href: '/usage',
            label: 'Usage',
            requires: 'usage:read_own',
            note: 'the requests that succeeded, against the quota a 429 here would have been counted towards',
          },
          {
            href: '/retention',
            label: 'Retention',
            requires: 'retention:write',
            note: 'how long these are kept — a ceiling as well as a floor, because a year of refusals describes how somebody works',
          },
        ]}
      />
    </div>
  );
}
