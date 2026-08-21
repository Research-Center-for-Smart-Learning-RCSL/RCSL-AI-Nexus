
type PlatformShellSectionProps = {
  agentCapability: string;
};

export function PlatformShellSection({ agentCapability }: PlatformShellSectionProps) {
  return (
<section className="space-y-3">
        <h2 className="font-heading text-base font-semibold">
          Confirming that requests reach this platform
        </h2>
        <p className="text-sm text-muted-foreground">
          Worth establishing once: a misconfigured client that falls back to its
          vendor is indistinguishable from a correct one at the chat window.
        </p>
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[11rem_1fr]">
          <dt className="font-mono text-muted-foreground">the header</dt>
          <dd>
            Codex prints <code>model: {agentCapability}</code> and{' '}
            <code>provider: rcsl</code> at startup. No vendor offers a model
            under that name, so the line is itself evidence.
          </dd>
          <dt className="font-mono text-muted-foreground">codex doctor</dt>
          <dd>
            Reports <code>model: {agentCapability} · rcsl</code>,{' '}
            <code>requires OpenAI auth: false</code>, and whether the key
            variable was found.
          </dd>
          <dt className="font-mono text-muted-foreground">Usage</dt>
          <dd>
            The authoritative check. Every served request is a row this platform
            wrote, naming the capability and the model that answered. A request
            absent from that record was not served here.
          </dd>
        </dl>
        <p className="text-sm text-muted-foreground">
          A warning that model metadata for <code>{agentCapability}</code> was
          not found is expected and has no effect: the client is looking the
          capability up in its own catalogue of vendor models, where it
          correctly does not appear.
        </p>
      </section>
  );
}
