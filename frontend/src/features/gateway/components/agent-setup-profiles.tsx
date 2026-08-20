import { CodeBlock } from '@/components/composed/code-block';

type ProfilesSectionProps = {
  agentCapability: string;
};

export function ProfilesSection({ agentCapability }: ProfilesSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Going back, and keeping both
        </h2>
        <p className="text-sm text-muted-foreground">
          Step 3 changes the client&apos;s <em>default</em>, which is why the
          desktop app followed it across. Undoing that is a matter of the same
          file — there is nothing to uninstall, and nothing on this platform to
          disconnect.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">go back</dt>
          <dd>
            Delete the <code>model</code> and <code>model_provider</code> lines
            from <code>~/.codex/config.toml</code>. The client returns to its
            own default. The <code>[model_providers.rcsl]</code> block can stay
            — it describes a provider, and nothing selects it once those two
            lines are gone.{' '}
            <strong>
              Restart the desktop app afterwards; it reads the file at startup.
            </strong>{' '}
            You may need <code>codex login</code> to use OpenAI again, since
            pointing here never required it.{' '}
            <strong>Copy the file before the edit, not after</strong> — a backup
            taken partway through reinstates what it was meant to remove when
            somebody restores it an hour later.
          </dd>
          <dt className="font-mono text-muted-foreground">clear the key</dt>
          <dd>
            The configuration is gone, but <code>RCSL_API_KEY</code> outlives it
            and is what a provider block added later would pick up with nobody
            typing a key. On Windows it has two scopes, and <code>setx</code>{' '}
            wrote to the first:
            <CodeBlock
              code={
                "[Environment]::SetEnvironmentVariable('RCSL_API_KEY',$null,'User')"
              }
              label="Copy"
            />
            Then check the other:{' '}
            <code>
              [Environment]::GetEnvironmentVariable(&apos;RCSL_API_KEY&apos;,&apos;Machine&apos;)
            </code>{' '}
            printing nothing is the pass. Anything it prints was set machine-wide
            and needs an elevated shell to remove.
          </dd>
          <dt className="font-mono text-muted-foreground">keep both</dt>
          <dd>
            Better than switching back and forth. Put the provider block in{' '}
            <code>~/.codex/rcsl.config.toml</code> instead, leave{' '}
            <code>config.toml</code> alone, and run{' '}
            <CodeBlock code={'codex --profile rcsl'} label="Copy" /> Plain{' '}
            <code>codex</code> stays on the default. Note this is a{' '}
            <strong>separate file</strong> per profile in{' '}
            <code>0.147.0</code>, not a <code>[profiles.x]</code> table inside{' '}
            <code>config.toml</code> as older guides show — check{' '}
            <code>codex --help</code> against your own version.
          </dd>
          <dt className="font-mono text-muted-foreground">just once</dt>
          <dd>
            <CodeBlock
              code={`codex -c model_provider=rcsl -c model=${agentCapability}`}
              label="Copy"
            />
            Nothing is written to any file. Useful for proving the platform
            half works without committing the machine to it.
          </dd>
          <dt className="font-mono text-muted-foreground">really disconnect</dt>
          <dd>
            <strong>Revoke the key</strong>, on API keys. Everything above is a
            setting on a machine you control, and a copy of the configuration
            on some other machine keeps working. Revoking is the only one of
            these that this platform enforces, and the only one that holds if
            the key has gone somewhere you did not intend.
          </dd>
        </dl>
      </section>
  );
}
