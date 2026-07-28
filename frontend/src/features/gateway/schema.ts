import { z } from 'zod';

import { capabilitySchema } from '@/features/models/schema';

/**
 * What an integrator needs in order to use a key: where to send it, and what
 * the `model` field of a request accepts.
 *
 * The second one is unusual enough to be worth naming. This platform routes by
 * *capability* rather than model name, so `model: "chat"` is correct and
 * `model: "qwen2.5:7b"` is not. A capability is listed here only when a
 * routing policy serves it, which is what makes the list an answer to "what
 * will work" rather than "what can be spelled".
 */
export const gatewayInfoSchema = z.object({
  base_url: z.string(),
  capabilities: z.array(capabilitySchema),
});
export type GatewayInfo = z.infer<typeof gatewayInfoSchema>;

/** Placed in the Authorization header, verbatim. */
export function bearerHeader(plaintext: string): string {
  return `Authorization: Bearer ${plaintext}`;
}

/**
 * The snippets shown beside a newly issued key.
 *
 * The plaintext is inlined rather than left as a placeholder, because this is
 * the one moment it exists and a snippet the holder has to edit before it runs
 * is a snippet they will get wrong. Everything else is real too: the origin
 * comes from configuration and the capability is the one they just chose, so
 * what is on screen is what works.
 */
export function integrationSnippets({
  baseUrl,
  plaintext,
  capability,
}: {
  baseUrl: string;
  plaintext: string;
  capability: string;
}): { label: string; language: string; code: string }[] {
  return [
    {
      label: 'curl',
      language: 'bash',
      code: `curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer ${plaintext}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${capability}",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
    },
    {
      label: 'Python',
      language: 'python',
      code: `from openai import OpenAI

client = OpenAI(
    base_url="${baseUrl}/v1",
    api_key="${plaintext}",
)

completion = client.chat.completions.create(
    # A capability, not a model name. Routing decides what serves it.
    model="${capability}",
    messages=[{"role": "user", "content": "Hello"}],
)
print(completion.choices[0].message.content)`,
    },
    {
      label: 'TypeScript',
      language: 'typescript',
      code: `import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: '${baseUrl}/v1',
  apiKey: '${plaintext}',
});

const completion = await client.chat.completions.create({
  // A capability, not a model name. Routing decides what serves it.
  model: '${capability}',
  messages: [{ role: 'user', content: 'Hello' }],
});
console.log(completion.choices[0].message.content);`,
    },
  ];
}
