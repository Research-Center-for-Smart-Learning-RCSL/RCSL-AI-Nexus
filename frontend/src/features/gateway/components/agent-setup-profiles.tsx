import { CodeBlock } from '@/components/composed/code-block';

type ProfilesSectionProps = {
  agentCapability: string;
};

export function ProfilesSection({ agentCapability }: ProfilesSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Reverting, and running both
        </h2>
        <p className="text-sm text-muted-foreground">
          Step 3 changes the client&apos;s <em>default</em>, which is why the
          desktop application follows it. Reverting is a matter of the same
          file: there is nothing to uninstall, and nothing on this platform to
          disconnect.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">revert</dt>
          <dd>
            Delete the <code>model</code> and <code>model_provider</code> lines
            from <code>~/.codex/config.toml</code>. The client returns to its
            own default. The <code>[model_providers.rcsl]</code> block may
            remain: it describes a provider, and nothing selects it once those
            two lines are removed.{' '}
            <strong>
              Restart the desktop application afterwards, since it reads the
              file at startup.
            </strong>{' '}
            <code>codex login</code> may be required to use OpenAI again,
            because pointing the client here never required it.{' '}
            <strong>Copy the file before the edit rather than after</strong>: a
            backup taken part way through reinstates what it was intended to
            remove.
          </dd>
          <dt className="font-mono text-muted-foreground">clear the key</dt>
          <dd>
            The configuration is removed, but <code>RCSL_API_KEY</code> outlives
            it and is what a provider block added subsequently would use without
            any key being entered. On Windows the variable has two scopes, and{' '}
            <code>setx</code> wrote to the first:
            <CodeBlock
              code={
                "[Environment]::SetEnvironmentVariable('RCSL_API_KEY',$null,'User')"
              }
              label="Copy"
            />
            Then check the second:{' '}
            <code>
              [Environment]::GetEnvironmentVariable(&apos;RCSL_API_KEY&apos;,&apos;Machine&apos;)
            </code>{' '}
            printing nothing is the expected result. Any value it prints was set
            machine-wide and requires an elevated shell to remove.
          </dd>
          <dt className="font-mono text-muted-foreground">run both</dt>
          <dd>
            Preferable to switching back and forth. Place the provider block in{' '}
            <code>~/.codex/rcsl.config.toml</code> instead, leave{' '}
            <code>config.toml</code> unchanged, and run{' '}
            <CodeBlock code={'codex --profile rcsl'} label="Copy" /> Plain{' '}
            <code>codex</code> remains on the default. Note that this is a{' '}
            <strong>separate file</strong> per profile in <code>0.147.0</code>,
            not a <code>[profiles.x]</code> table within{' '}
            <code>config.toml</code> as earlier instructions describe. Check{' '}
            <code>codex --help</code> against the installed version.
          </dd>
          <dt className="font-mono text-muted-foreground">run once</dt>
          <dd>
            <CodeBlock
              code={`codex -c model_provider=rcsl -c model=${agentCapability}`}
              label="Copy"
            />
            Nothing is written to any file. Suitable for establishing that the
            platform is reachable without committing the machine to it.
          </dd>
          <dt className="font-mono text-muted-foreground">disconnect fully</dt>
          <dd>
            <strong>Revoke the key</strong>, on API keys. Everything above is a
            setting on a machine under local control, and a copy of the
            configuration on another machine continues to work. Revocation is
            the only measure this platform enforces, and the only one that holds
            if the key has reached somewhere unintended.
          </dd>
        </dl>
      </section>
  );
}
