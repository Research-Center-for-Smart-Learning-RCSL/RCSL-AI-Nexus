import type { Metadata } from 'next';

import { RelatedScreens } from '@/components/composed/related-screens';
import { EvaluationView } from '@/features/evaluations/components/evaluation-view';

export const metadata: Metadata = { title: 'Model evaluation' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function EvaluationsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">Model evaluation</h1>
        <p className="max-w-prose text-sm text-muted-foreground">
          What the models here scored on a set of tasks a program checks, rather
          than on an impression of their answers. Each task has a verifiable
          result — code that must pass tests it has not seen, or a question with
          one correct answer — and every model is asked the same questions in a
          rotated order, several times.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          <strong>This is a record of one execution, not a live measurement.</strong>{' '}
          The platform does not re-run the task set and cannot tell whether a
          stored run still describes what is deployed. Read the date it ran
          beside the scores, and treat a run older than the models it names as
          history.
        </p>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          A ranking is worth exactly as much as the tasks that produced it, so
          each task carries what it did to the field of models — separated them,
          was passed or failed by all of them alike, or was scored without ever
          separating anybody. A task nobody is distinguished by contributes
          nothing, however many of them a run contains.
        </p>
      </div>
      <EvaluationView />
      <RelatedScreens
        items={[
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'what is registered and loaded now, which a stored run may predate; the reference a run names is the weights, not the alias pointing at them',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'where a decision taken on these figures is actually made: a capability serves whichever candidate a policy names',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'who loaded a run, and when — a re-import replaces the numbers, so this is the only record that they were once different',
          },
        ]}
      />
    </div>
  );
}
