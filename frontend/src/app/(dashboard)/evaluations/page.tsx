import type { Metadata } from 'next';

import { PageHeader } from '@/components/composed/page-header';
import { RelatedScreens } from '@/components/composed/related-screens';
import { EvaluationView } from '@/features/evaluations/components/evaluation-view';

export const metadata: Metadata = { title: 'Model evaluation' };

/** Thin by design: pages assemble feature components (frontend.md section 2). */
export default function EvaluationsPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="Model evaluation"
        lead={
          <>
            Scores obtained by the models on this deployment against a set of
            programmatically checked tasks.{' '}
            <strong>
              This is the record of one execution, not a live measurement.
            </strong>
          </>
        }
      >
        <p>
          Each task has a verifiable result — code that must pass tests it has
          not been shown, or a question with a single correct answer — and every
          model is asked the same questions in a rotated order, several times.
        </p>
        <p>
          The platform does not re-run the task set and cannot determine whether
          a stored run still describes what is deployed. Read the date of
          execution beside the scores, and treat a run older than the models it
          names as historical.
        </p>
        <p>
          A ranking is worth no more than the tasks that produced it, so each
          task records its effect on the field: whether it separated the models,
          was passed or failed by all of them alike, or was scored without
          separating any of them. A task that distinguishes no model contributes
          nothing to the result, whatever number of such tasks a run contains.
        </p>
      </PageHeader>
      <EvaluationView />
      <RelatedScreens
        items={[
          {
            href: '/models',
            label: 'Models',
            requires: 'model:read',
            note: 'what is registered and loaded at present, which a stored run may predate; the reference a run names is the weights, not the alias pointing at them',
          },
          {
            href: '/routing-policies',
            label: 'Routing policies',
            requires: 'routing:read',
            note: 'where a decision taken on these figures takes effect: a capability serves whichever candidate a policy names',
          },
          {
            href: '/logs',
            label: 'Audit log',
            requires: 'logs:read',
            note: 'who loaded a run, and when; a re-import replaces the figures, so this is the only record that they were previously different',
          },
        ]}
      />
    </div>
  );
}
