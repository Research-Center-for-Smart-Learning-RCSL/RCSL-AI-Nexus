'use client';

/**
 * Reference documentation for the compute-host panel on the Nodes screen.
 *
 * Written as specification rather than as narrative: each figure is given a
 * definition, a collection method and, where it is derived, the derivation.
 * The first draft explained the same facts in an essayistic register and was
 * rejected for it — this page sits inside a management interface, beside an
 * API reference, and is read by an operator checking a definition rather than
 * by someone being persuaded of anything.
 *
 * Figures are read live from the endpoint the panel itself uses, following the
 * pattern in `api-reference.tsx`. Documentation that restates a value acquires
 * a second source of truth and diverges from the first; documentation that
 * computes it cannot.
 */

import Link from 'next/link';

import { Spinner } from '@/components/composed/spinner';
import { useHostStatus } from '@/features/host/hooks/use-host';

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

function Definition({
  term,
  value,
  children,
}: {
  term: string;
  value?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h3 className="font-heading text-sm font-semibold">{term}</h3>
        {value ? (
          <span className="font-mono text-sm tabular-nums text-muted-foreground">
            {value}
          </span>
        ) : null}
      </div>
      <div className="max-w-prose space-y-2 text-sm text-muted-foreground">
        {children}
      </div>
    </div>
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

  const shown = (value: string) => (reporting ? value : undefined);

  return (
    <div className="space-y-8">
      <Section title="Scope">
        <p className="max-w-prose text-sm text-muted-foreground">
          The compute-host panel reports the capacity available on the machine
          running the model runtimes. Its scope is capacity, not performance:
          it answers whether a model can be loaded, not how quickly one is
          serving. Performance metrics are collected by Prometheus and
          presented in Grafana.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          Figures on this page are read from the same endpoint as the panel and
          reflect the current state of the deployment.
        </p>
      </Section>

      <Section title="Collection method">
        <p className="max-w-prose text-sm text-muted-foreground">
          The backend runs in Docker. On macOS, Docker runs containers inside a
          Linux virtual machine, so a container reading <code>/proc</code> or
          calling a process-inspection library reports the virtual
          machine&apos;s memory and disk rather than the host&apos;s. Such a
          reading returns plausible values without error, and no signal
          distinguishes it from a correct one.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          Collection therefore runs outside the container. A{' '}
          <code>launchd</code> service on the host binds{' '}
          <code>127.0.0.1:9101</code> and is reached by containers through{' '}
          <code>host.docker.internal</code>, the same arrangement used for the
          model runtimes, which are also not containerised because Docker on
          macOS cannot access the GPU.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          The service is a standard-library Python program of approximately 186
          lines. It executes <code>vm_stat</code>, <code>sysctl</code> and{' '}
          <code>statfs</code>, performs arithmetic on the results, and returns
          JSON. It holds no state, performs no writes, and makes no outbound
          network requests. The term &quot;agent&quot; is used here in its
          systems-monitoring sense and denotes no language model or autonomous
          behaviour.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          No authentication is applied. The listener is bound to the loopback
          interface, and every value it exposes is readable by any unprivileged
          process on the host through the commands above.
        </p>
      </Section>

      <Section title="Figure definitions">
        {isLoading ? <Spinner label="Reading the host" /> : null}
        {!isLoading && !reporting ? (
          <p className="max-w-prose rounded-md border border-dashed p-3 text-sm text-muted-foreground">
            The collection service is not responding, so no current values are
            available. The service is optional infrastructure and its absence
            is a defined state rather than a fault. The definitions below
            remain applicable.
          </p>
        ) : null}

        <div className="space-y-6">
          <Definition
            term="Memory available"
            value={shown(gb(memory?.available_gb))}
          >
            <p>
              The only derived figure on the panel. macOS does not report
              available memory directly; the value is computed from{' '}
              <code>vm_stat</code> page counts as free pages plus inactive and
              speculative pages — those the kernel can reclaim without
              swapping.
            </p>
            <p>
              Three page classes are excluded. Wired and compressed pages are
              not reclaimable. Anonymous pages are reclaimable but excluded by
              design: reclaiming them requires swapping, and on a host whose
              function is to hold model weights resident, swap constitutes a
              degraded state rather than available capacity.
            </p>
            <p>
              This exclusion is specific to the role of this machine. The same
              derivation applied to a general-purpose server would understate
              available memory.
            </p>
          </Definition>

          <Definition term="Swap in use" value={shown(gb(memory?.swap_used_gb))}>
            <p>
              Taken from <code>sysctl vm.swapusage</code>. The panel flags any
              value above 0.10 GB rather than applying a proportional
              threshold, because on this host any sustained swap indicates that
              the memory budget has already been exceeded.
            </p>
          </Definition>

          <Definition
            term="Disk free"
            value={shown(
              `${gb(disk?.free_gb)} of ${gb(disk?.total_gb)} on ${disk?.volume ?? '/'}`,
            )}
          >
            <p>
              Taken from <code>statfs</code>. Relevant primarily to model
              acquisition: quantised weights for the models in use range from
              approximately 0.3 GB to over 30 GB per build, and downloads are
              retained on disk independently of whether they are loaded.
            </p>
          </Definition>

          <Definition
            term="Load average"
            value={shown(
              system?.load_1m !== null && system?.load_1m !== undefined
                ? `${system.load_1m.toFixed(2)} over ${system.cpu_count ?? '—'} cores`
                : '—',
            )}
          >
            <p>
              Taken from <code>getloadavg</code> and displayed alongside the
              core count, without which the figure cannot be interpreted. It is
              of limited relevance to inference throughput, which is bounded by
              memory bandwidth and GPU capacity rather than by CPU run-queue
              length.
            </p>
          </Definition>
        </div>
      </Section>

      <Section title="Excluded from collection">
        <p className="max-w-prose text-sm text-muted-foreground">
          GPU utilisation and thermal state are not collected. Both require{' '}
          <code>powermetrics</code>, which requires root privileges. Granting
          root to a permanently running background service is a security
          decision disproportionate to the value of the additional readings,
          and is therefore not taken.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          The commands actually used require no elevated privileges, which is
          also the basis on which the service runs unprivileged and
          unauthenticated.
        </p>
      </Section>

      <Section title="Related figures from other sources">
        <p className="max-w-prose text-sm text-muted-foreground">
          Per-model memory figures shown on the Models screen are not produced
          by this service.
        </p>
        <div className="space-y-6">
          <Definition term="Observed memory">
            <p>
              Reported by the model runtime for a resident model. It takes
              precedence over the memory declared in the model&apos;s registry
              entry because it includes the key-value cache, which the declared
              profile does not. The difference is material: a 7B model
              declaring 4.7 GB of weights was measured occupying 5.7 GB.
            </p>
            <p>
              The declared figure remains in use as the estimate for models
              that have not yet been observed, and is what the memory budget
              evaluates before a load is permitted.
            </p>
          </Definition>
          <Definition term="Memory budget">
            <p>
              A load is refused if it would cause total declared or observed
              residency to exceed 80% of the node&apos;s{' '}
              <em>configured</em> total memory. The remaining share covers the
              operating system, the containers, and inference working memory
              not accounted for in any model profile.
            </p>
            <p>
              <strong>
                That configured figure, not the measurement above, is what the
                check uses.
              </strong>{' '}
              The two describe the same machine and are recorded separately: one
              is a number an administrator entered when registering the node,
              the other is read from the host each time this page loads. They
              are worth comparing — a configured total above the real capacity
              permits loads that push the host into swap — but the budget is
              never computed from the measured figure, and reconciling them as
              though it were will not add up.
            </p>
            <p>
              The check is a refusal rather than a warning. On unified memory,
              over-commitment does not fail cleanly; it induces swapping, which
              is the condition reported by the swap figure above.
            </p>
          </Definition>
        </div>
      </Section>

      <Section title="Verification">
        <p className="max-w-prose text-sm text-muted-foreground">
          Every value on the panel can be confirmed independently on the
          compute host:
        </p>
        <ul className="max-w-prose list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            <code>curl 127.0.0.1:9101</code> — the complete response underlying
            the panel.
          </li>
          <li>
            <code>vm_stat</code>, <code>sysctl hw.memsize</code>,{' '}
            <code>sysctl vm.swapusage</code> — the inputs to the memory
            figures.
          </li>
          <li>
            <code>curl 127.0.0.1:11434/api/ps</code> — the runtime&apos;s own
            report of resident models and their sizes.
          </li>
        </ul>
        <p className="max-w-prose text-sm text-muted-foreground">
          Where this page and the running system disagree, the running system
          is correct.
        </p>
      </Section>

      <p className="text-sm">
        <Link href="/nodes" className="underline underline-offset-4">
          Return to Nodes
        </Link>
      </p>
    </div>
  );
}
