

type PlatformShellSectionProps = {
  agentCapability: string;
};

export function PlatformShellSection({ agentCapability }: PlatformShellSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Confirming it is really this platform
        </h2>
        <p className="text-sm text-muted-foreground">
          Worth doing once, because a misconfigured client that quietly falls
          back to its vendor looks identical from the chat window.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">the header</dt>
          <dd>
            Codex prints <code>model: {agentCapability}</code> and{' '}
            <code>provider: rcsl</code> when it starts. No vendor has a model by
            that name, so seeing it is already evidence.
          </dd>
          <dt className="font-mono text-muted-foreground">codex doctor</dt>
          <dd>
            Reports <code>model: {agentCapability} · rcsl</code>,{' '}
            <code>requires OpenAI auth: false</code>, and whether your key
            variable was found.
          </dd>
          <dt className="font-mono text-muted-foreground">Usage</dt>
          <dd>
            The one that cannot be faked. Every served request is a row this
            platform wrote, naming the capability and the model that answered.
            If it is not there, it did not happen here.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          A warning that model metadata for{' '}
          <code>{agentCapability}</code> was not found is expected and harmless:
          the client is looking your capability up in its own catalogue of
          vendor models and not finding it, which is exactly right.
        </p>
      </section>
  );
}
