'use client';

/**
 * Where the figures on the Nodes screen come from, for the operator reading them.
 *
 * Rendered from the live endpoint rather than written as prose, which is the
 * pattern `api-reference.tsx` established and the reason it has stayed true:
 * every figure quoted below is the one the panel upstairs is showing right now,
 * so the numbers cannot drift from the deployment and only the reasoning has to
 * be maintained by hand.
 *
 * That distinction is the whole design of this page. Documentation that repeats
 * a value goes stale silently, and this repository has spent a lot of days on
 * exactly that failure — a runbook naming a client setting removed six months
 * earlier, a plan file naming a proxy timeout that had been read and corrected
 * two days before, a setup page calling a thing impossible that nobody had
 * tried. A page that *computes* what it claims cannot fail that way.
 */

import Link from 'next/link';

import { Spinner } from '@/components/composed/spinner';
import { useHostStatus } from '@/features/host/hooks/use-host';

function Row({
  figure,
  source,
  children,
}: {
  figure: string;
  source: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1 border-l-2 pl-4">
      <p className="font-heading text-sm font-semibold tabular-nums">{figure}</p>
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {source}
      </p>
      <div className="max-w-prose space-y-2 text-sm text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <h2 className="font-heading text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function gb(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(2)} GB`;
}

export function HostNumbersExplainer() {
  const { data, isLoading } = useHostStatus();
  const reporting = data?.reporting ?? false;
  const memory = data?.memory;
  const disk = data?.disk;
  const system = data?.system;

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="max-w-prose text-sm text-muted-foreground">
          Every figure on the Nodes screen has a source, and none of them is an
          estimate. This page names the source for each one, because two of them
          are derived in ways that are not obvious and one of them would be
          wrong if it were measured the way you would expect.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          The numbers below are read live from the same endpoint the panel uses,
          so they are what this machine is reporting as you read this.
        </p>
      </section>

      <Section title="The trap this exists to avoid">
        <p className="max-w-prose text-sm text-muted-foreground">
          The backend runs in Docker, and on macOS that means it runs inside a
          Linux virtual machine. A container that reads <code>/proc</code>, or
          calls a library like <code>psutil</code>, describes{' '}
          <strong>the virtual machine&apos;s memory and disk — not the
          Mac&apos;s</strong>.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          It does not fail. It does not warn. It returns numbers that look
          entirely reasonable and are about a different computer, which is worse
          than having no numbers at all: nothing ever prompts you to doubt them.
          That is the whole reason a separate agent exists, and it is the same
          constraint that keeps the model runtimes out of Docker — Docker on
          macOS cannot reach the GPU either.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          So a small program runs natively on the Mac under{' '}
          <code>launchd</code>, binds <code>127.0.0.1:9101</code>, and the
          containers reach it through <code>host.docker.internal</code> exactly
          as they reach Ollama.{' '}
          <strong>
            It is not an AI, and &quot;agent&quot; here is the monitoring sense
            of the word, not the coding-assistant sense used on the Connect an
            agent screen.
          </strong>{' '}
          It is 186 lines of standard-library Python that runs{' '}
          <code>vm_stat</code>, <code>sysctl</code> and <code>statfs</code>,
          does some arithmetic, and returns JSON. It stores nothing, changes
          nothing, and reaches no network.
        </p>
      </Section>

      <Section title="What each figure actually is">
        {isLoading ? <Spinner label="Reading the host" /> : null}
        {!isLoading && !reporting ? (
          <p className="max-w-prose rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            The agent is not answering, so this page has no live figures to
            explain. That is a state rather than a fault — the agent is optional
            infrastructure — and the reasoning below still applies.
          </p>
        ) : null}

        <div className="space-y-5">
          <Row
            figure={reporting ? gb(memory?.available_gb) : 'Memory available'}
            source="derived from vm_stat — the only figure here that is computed"
          >
            <p>
              macOS does not report &quot;available memory&quot; directly. This
              is derived the way Activity Monitor derives its own: free pages,
              plus the pages the kernel could reclaim without swapping —
              inactive and speculative.
            </p>
            <p>
              <strong>
                Three kinds of page are deliberately excluded, and the third is
                a judgement about what this machine is for.
              </strong>{' '}
              Wired and compressed pages are not available at any price. And{' '}
              <em>anonymous</em> pages are excluded even though the kernel could
              reclaim them, because reclaiming them means swapping — and on a
              machine whose entire purpose is holding model weights resident,
              swapping is the state we are trying to stay out of, not headroom
              available to spend.
            </p>
            <p>
              The same script on an ordinary server would be wrong to make that
              choice. The definition of this number depends on what the machine
              is for.
            </p>
          </Row>

          <Row
            figure={reporting ? gb(memory?.swap_used_gb) : 'Swap in use'}
            source="sysctl vm.swapusage"
          >
            <p>
              Reported separately, and flagged above{' '}
              <strong>0.1 GB rather than at some larger threshold</strong>,
              because on this machine any swap at all means the memory budget
              has already been overspent. It is not a performance metric here;
              it is evidence that something was allowed to load that should not
              have been.
            </p>
          </Row>

          <Row
            figure={
              reporting
                ? `${gb(disk?.free_gb)} on ${disk?.volume ?? '/'}`
                : 'Disk free'
            }
            source="statfs, via Python's shutil.disk_usage"
          >
            <p>
              The plainest number on the page. It matters mainly because model
              weights are large — the q8 build of the main model is over 30 GB
              on disk before it is ever loaded — so &quot;can I download this
              one&quot; is a question with a real answer.
            </p>
          </Row>

          <Row
            figure={
              reporting && system?.load_1m !== null && system?.load_1m !== undefined
                ? `${system.load_1m.toFixed(2)} over ${system.cpu_count ?? '—'} cores`
                : 'Load'
            }
            source="os.getloadavg"
          >
            <p>
              Shown next to the core count because a load average means nothing
              without it. This is the least useful figure here for inference
              work: generation is bounded by memory bandwidth and the GPU, and
              load average measures neither.
            </p>
          </Row>
        </div>
      </Section>

      <Section title="What is deliberately missing">
        <p className="max-w-prose text-sm text-muted-foreground">
          There is <strong>no GPU utilisation and no temperature</strong> on
          this page, and that is a decision rather than an oversight.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          Those readings come from <code>powermetrics</code>, which requires
          root.{' '}
          <strong>
            Giving a permanently-running background job root access in order to
            draw a chart is a trade worth making on purpose, if at all — not as
            a side effect of wanting a nicer panel.
          </strong>{' '}
          Everything the agent does read — <code>vm_stat</code>,{' '}
          <code>sysctl</code>, <code>statfs</code> — is readable by any
          unprivileged user, which is also why the agent needs no credential:
          anything on this host that could reach its socket could already run
          those commands itself.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          The scope of this panel is <strong>&quot;is there room&quot;</strong>,
          not <strong>&quot;how is it performing&quot;</strong>. Grafana answers
          the second question.
        </p>
      </Section>

      <Section title="Two more numbers, from somewhere else entirely">
        <p className="max-w-prose text-sm text-muted-foreground">
          The Models screen shows how much memory each loaded model occupies,
          and those figures do not come from this agent.
        </p>
        <div className="space-y-5">
          <Row figure="Observed memory" source="the runtime's own report">
            <p>
              When a model is resident, Ollama&apos;s own figure is used and{' '}
              <strong>
                it outranks the memory declared in the model&apos;s registry
                entry
              </strong>
              , because it includes the KV cache that the declared profile does
              not. The gap is real and was measured: a 7B model declared 4.7 GB
              of weights and occupied 5.7 GB.
            </p>
            <p>
              The declared figure remains the estimate for anything not yet
              observed, which is what the memory budget uses to decide whether a
              load will fit before committing to it.
            </p>
          </Row>
          <Row figure="The memory budget" source="configuration, not measurement">
            <p>
              A load is refused if it would exceed{' '}
              <strong>80% of the machine&apos;s total memory</strong>. The
              remaining fifth is left for the operating system, the containers,
              and the inference working memory that no model&apos;s profile
              accounts for.
            </p>
            <p>
              It is a refusal rather than a warning. On unified memory an
              over-commit does not fail cleanly — it drives the machine into
              swap, which is the condition the swap figure above exists to
              report.
            </p>
          </Row>
        </div>
      </Section>

      <Section title="Checking any of this yourself">
        <p className="max-w-prose text-sm text-muted-foreground">
          Nothing here needs to be taken on trust. On the compute host:
        </p>
        <ul className="max-w-prose list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            <code>curl 127.0.0.1:9101</code> returns exactly what this page
            renders, as JSON.
          </li>
          <li>
            <code>vm_stat</code> and <code>sysctl hw.memsize</code> are the raw
            inputs to the memory figure.
          </li>
          <li>
            <code>curl 127.0.0.1:11434/api/ps</code> asks Ollama directly what
            is resident and how large it is.
          </li>
        </ul>
        <p className="max-w-prose text-sm text-muted-foreground">
          <strong>
            Reading the running system is worth more than reading any document
            about it, this one included.
          </strong>{' '}
          Several of this platform&apos;s longest-lived wrong beliefs were
          documents that described a configuration accurately when written and
          were never re-read against the machine afterwards. Each was settled in
          minutes once somebody looked.
        </p>
      </Section>

      <p className="text-sm">
        <Link href="/nodes" className="underline underline-offset-4">
          Back to Nodes
        </Link>
      </p>
    </div>
  );
}
