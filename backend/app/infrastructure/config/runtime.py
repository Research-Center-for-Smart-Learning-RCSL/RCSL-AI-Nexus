"""Flat runtime setting declarations."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class RuntimeSettings(BaseSettings):
    ollama_base_url: str = "http://host.docker.internal:11434"

    mlx_base_url: str = "http://host.docker.internal:8080"
    """`mlx_lm.server` on the host, reached the same way as Ollama. Downloads it
    triggers land under HF_HOME, which the Compose file bind-mounts onto the host
    HuggingFace cache the native server reads; see adapters/runtime/mlx_adapter.py."""

    mlx_tool_calling_verified: bool = False
    """Whether a real tool call has been observed against *this* server build.

    False refuses tool-carrying requests on the MLX path rather than serving
    them, because a build without tool support accepts the `tools` field and
    answers with prose — a 200 no client can tell from a model that chose not
    to call anything. That indistinguishability is also why this cannot be
    probed and has to be asserted by a person; the reasoning is in
    `MlxAdapter._assert_tools_are_verified`.

    Defaults to False because "nobody has checked" is the true state of every
    deployment until somebody has."""

    node_id: str = "local"

    node_name: str = "local"

    node_total_memory_gb: float = 64.0

    node_heartbeat_interval_seconds: int = 30
    """How often the admin app probes each node and writes the observed status,
    so a routing requirement of an online node reflects reality rather than the
    value provisioning wrote once. Zero or negative disables the loop."""

    max_concurrent_inference: int = 4
    """Sized to the deployment: a lab whose peak is four people at once.

    Note what it does not buy. The GPU serves one generation at a time, so a
    fourth slot is queueing depth, not throughput — it decides whether a fourth
    caller waits or is refused, and waiting is the better answer at this size.
    """

    queue_wait_seconds: int = 1200
    """How long a request may wait for an inference slot before `503 overloaded`.

    Before 2026-08-05 the queue was unbounded and invisible: a caller arriving
    with every slot held waited producing zero bytes — no status, no code —
    until their own client timeout killed the connection, which is
    indistinguishable from a hung deployment. A slot can legitimately be held
    for 35 minutes (`request_timeout_seconds` + `generation_deadline_seconds`),
    so that silence had real depth.

    Raised from 120 to 1200 on 2026-09-05 so that two heavy users on one
    machine wait for each other rather than the second being refused after two
    minutes while the first still has fifteen to run. Matches
    `request_timeout_seconds`, which is the longest a single generation is
    expected to hold a slot. Zero or negative restores the unbounded queue.
    """

    gateway_max_body_bytes: int = 4 * 1024 * 1024
    """Ceiling on a gateway request body, in bytes, refused before it is read.

    Derived from `max_context_length` rather than picked: 65536 tokens at the
    four-characters-per-token rule is 256 KiB of *characters*, and a character
    outside ASCII costs up to four bytes in UTF-8 — so a legitimate maximum
    prompt is about 1 MiB before JSON escaping and tool definitions. Four
    times that leaves room for both and still refuses everything else.

    It is a distinct guardrail from the context ceiling, not a duplicate of it,
    because it is the only one of the two that applies to a caller who has not
    authenticated. See `middleware/body_limit.py` for why that gap existed.

    Sits **below** the `client_max_body_size` the inference host is asked for,
    so ours is the limit that fires and the caller gets a code naming the
    reason instead of nginx's HTML — the arrangement `upload_policy.py`
    documents for the management host.
    """

    admin_max_body_bytes: int = 40 * 1024 * 1024
    """The same ceiling on the admin entrances, where uploads are legitimate.

    Above `upload_policy.MAX_UPLOAD_BYTES` (32 MiB) plus multipart framing, so
    a file between the two limits is still refused by `assert_upload_allowed`,
    which names the reason; below the management host's 64m, so this fires
    before nginx does. Both entrances get it: the public one faces the
    internet, and the tailnet one would otherwise be the softer of the two.
    """

    max_tokens_ceiling: int = 16384
    """Hard ceiling on tokens per generation, thinking included.

    4096 → 8192 → 16384. `eval_count` counts reasoning, and a thinking model
    can spend an entire budget deliberating: GLM-4.7-Flash produced 8192 tokens
    of reasoning on a three-guards logic puzzle and no answer, twice.

    Raising it does not fix that case and was not meant to — the same question
    ran to 23,632 tokens without answering, so no affordable ceiling would.
    What it buys is room for legitimate long answers now that reasoning shares
    the budget. The case that will not converge is bounded by the wall-clock
    deadline below and by `think: false`, which answered that same question in
    49 seconds.
    """

    ollama_keep_alive: str = "-1"
    """How long Ollama keeps a model resident after serving a request.

    `-1` keeps it until something asks otherwise, which is what makes the
    registry's `loaded` state true rather than aspirational: the row says
    loaded, the memory budget reserves the weights, and `unload` is the release
    path. A duration such as `10m` is also accepted.

    Sent on every generation, not only on load. Ollama applies its own default
    (five minutes) to any request that omits the field, so a generate without it
    silently overwrites what `load` asked for — measured as 14 reloads in a day
    while the configured value was `10m` and never once in force.
    """

    ollama_thinking: bool = True
    """The default for a request that expresses no preference.

    Per-request `think` overrides it (chat_schemas.py). Only ever expressed as
    a suppression: `think: false` is sent when thinking is off, and nothing is
    sent when it is on, because Ollama rejects `think: true` for a model that
    does not support it. Graded values are not offered — `think: "low"` is
    accepted by Ollama and measurably changes nothing.
    """

    ollama_models_path: str = "/ollama-models"
    """Where this host's Ollama model store is mounted, read-only, or empty.

    The platform reads two things out of the GGUF a reference resolves to — the
    vocabulary and the chat template — and counts a prompt with them instead of
    estimating it from character widths. See
    `adapters/tokenizer/gguf_token_counter.py` for what that is worth and
    `adapters/tokenizer/ollama_blobs.py` for how a `ref` becomes a file.

    **The mount is read-only and the reads are bounded to the header.** A GGUF
    is tens of gigabytes of tensors behind a few megabytes of metadata, and
    nothing here ever seeks past the metadata: 11.9 MiB and 0.14 s for
    `qwen3.6:35b-a3b-q8_0`, once per model per process.

    Empty disables exact counting, and that is a supported deployment rather
    than a broken one: a host serving MLX has no GGUF to read, and the
    character estimate is what every request was counted by before 2026-08-17.
    What the platform must never do is have no answer at all — the guardrail
    this feeds runs before any hardware is committed.
    """

    token_counter_cache_size: int = 2
    """How many vocabularies one process keeps built at once.

    Measured on the Mac Studio: 132 MB resident for the 248320-entry vocabulary
    of `qwen3.6:35b-a3b-q8_0`, and about 25 MB more for a second one. Two is
    what this deployment actually needs — the gateway serves `chat` and `code`
    from one model and falls back to another, and the admin entrances serve
    `assist` from a third — and a third entry would hold memory against a
    budget whose headroom is the constraint the whole deployment is designed
    around. Eviction is least-recently-used and costs a rebuild of a quarter of
    a second, not a wrong answer.

    **A model occupies a slot here only if it can be counted exactly, and since
    2026-08-21 the main one cannot.** `gemma4:31b-it-q8_0` declares
    `tokenizer.ggml.pre = gemma4`, which is not in `KNOWN_PRE_TOKENIZERS`, so
    `prepare` refuses it and `chat` and `code` are estimated instead: the
    gateway currently builds one vocabulary rather than two. Two is still the
    right value — it is what the arrangement needs whenever a countable model
    serves `chat`, and shrinking it to match an accident would only have to be
    undone. Measured 2026-09-02; see `docs/roadmap/decisions.md`.
    """

    max_context_length: int = 122880
    """Ceiling on a request's input, in tokens, counted with the vocabulary of
    the model that will read it — or estimated from the text when no vocabulary
    can be resolved (`RouteChatRequest._count_prompt`).

    **Where in the request it is applied moved on 2026-08-17.** Counting
    exactly needs the target, and the target is not known until the routing
    reads inside the concurrency slot, so this ceiling is now judged there. What
    runs before the slot is a lower bound that no tokeniser could contradict,
    which turns away about a megabyte of prose and nothing smaller. The reason
    is a client refused that day at 140059 estimated tokens whose payload was
    about 99000 real ones: it was refused by the estimator, before any model had
    been chosen, and the model that would have served it could read 131072.

    32768 → 65536 on 2026-08-05, for agent clients. An agent replays the whole
    conversation on every turn and grows it with file contents and tool output,
    so it crossed the old ceiling within a few rounds and the 413 arrived in the
    middle of a task rather than at the start of one. 65536 → 98304 on
    2026-08-14 for the same reason, after a Codex session reached the ceiling
    two work items into a task. 98304 → 122880 on 2026-08-17, after
    `qwen36-35b-a3b-q8` was registered at its native 262144 rather than 196608:
    the truncation point below moved to 131072, and this now sits under it
    rather than on it, which is the error the next paragraph records.

    **This value, `request_timeout_seconds` and the model's registered
    `context_length` are one decision and have to be changed together.** Two
    separate limits sit above this one and neither announces itself:

    - *The runtime truncates rather than refuses.* Ollama evaluates at most
      `num_ctx / 2` prompt tokens and silently drops the rest, reporting
      `done_reason: "length"` — the same value a generation that ran out of
      room reports. Measured on 2026-08-14: `num_ctx=4096` evaluated 2051 of a
      8506-token prompt, `num_ctx=16384` evaluated all 8506. So this ceiling
      must stay below half the registered `context_length` of every model that
      serves a capability, or the guardrail's remedy becomes an answer given
      without the beginning of the conversation.

      **That is no longer maintained here by hand, because it was not being
      maintained.** On 2026-08-17 this value was 98304 and exactly half of
      qwen36-35b-a3b-q8's registered 196608 — at the truncation point rather
      than below it — while `chat` still fell back to qwen7b, whose 8192 put
      the same point at 4096. Only the absence of long `chat` traffic had kept
      that from being served, and `assist`, which routes to qwen7b alone, was
      being served truncated whenever a conversation reached a second turn.
      qwen7b was widened to its native 32768 that evening, which is the fix for
      that capability; the rule below is what made it visible.
      `RouteChatRequest._refuse_what_this_target_would_truncate`
      now applies the rule against whichever model routing actually picked, so
      this value bounds hardware cost and that one bounds correctness. Keep
      them consistent anyway: a global ceiling above a target's half turns what
      should be a start-of-task refusal into a mid-task one.
    - *Prompt evaluation produces no bytes*, so what bounds it in transit is
      the per-read timeout. **The rate this was sized against belonged to a
      model that now serves nothing.** 105.5 to 141.5 tok/s was measured on
      2026-08-14 across four cold requests to the dense model then deployed,
      giving

          98304 / 105.5 = 932 seconds

      against a 1200 second read timeout — close enough that the coupling read
      as tight, and it was quoted as tight in three places. Re-measured on
      2026-08-17 from three cold session starts on `qwen36-35b-a3b-q8`, the MoE
      now serving `code`: 711, 725 and 730 tok/s, so the same calculation is

          122880 / 711 = 173 seconds

      Raising this without raising that still gives a ceiling the guardrail
      admits and the transport then kills, and that failure does not heal: a
      prefill killed part way is **not** kept in the runtime's prefix cache
      (measured 2026-08-14), so the retry re-evaluates from nothing and times
      out again. What changed is the headroom rather than the rule — the read
      timeout stopped being the binding constraint when the dense model was
      replaced, and nothing had gone back to check.

      **It stopped being unbinding four days later, and this is now broken.**
      On 2026-08-21 `chat` and `code` both went back to
      `gemma4:31b-it-q8_0` and nothing revisited the ceiling that had been
      raised for the model they left. Measured 2026-09-02 at the ceiling
      itself rather than extrapolated from a shallow prompt:

          121892 tokens at 88.4 tok/s = 1379 seconds

      against the same 1200 second read timeout, crossing near 110000 tokens.
      **Every earlier figure in this paragraph was taken shallow, and the rate
      is not flat**: on this model prompt evaluation runs at 209 tok/s over the
      first 10k tokens, 172 at 25k, 105 at 93k. So a request this ceiling admits
      cannot complete, and the guardrail whose whole purpose is to refuse before
      the transport kills is the thing letting it through. Nothing raised the
      ceiling to cause it — the throughput underneath it was lowered — which is
      a direction this docstring had no rule for and now does: **whichever of
      the three moves, the other two are re-derived.** Options and what each
      costs are in `docs/roadmap/decisions.md`; nothing is changed here yet
      because each one gives back something a previous decision bought.

    This is one of the six resource guardrails security.md section 4.3 counts
    on, so raising it costs something real: context is superlinear on unified
    memory, and measured throughput already decays from 60.8 to 23.5 tok/s
    across a single generation. The other five are unchanged.

    A caller cannot smuggle past it through `tools`: tool definitions and prior
    tool calls are counted too.
    """

    request_timeout_seconds: int = 1200
    """Per-read HTTP timeout on a runtime call: the longest gap between bytes.

    **This is what bounds prompt evaluation**, because a runtime reading a long
    prompt sends nothing at all while it does so. Sized from `max_context_length`
    above, with room over the 932 seconds a full context cost when it was set;
    the two move together or the larger one is unreachable.

    **They are not in step as of 2026-09-02 and this is the smaller half.** A
    full `max_context_length` prompt measures 1379 seconds against this 1200,
    so the larger one is currently unreachable — the case this docstring names
    and had never been measured at. See `max_context_length` above.

    300 → 600 on 2026-08-05 with the context ceiling, and 600 → 1200 on
    2026-08-14 with it again. The cost is paid by a *hung* runtime rather than a
    busy one, since a stream that is producing resets this on every chunk: a
    runtime that has stopped answering now holds one of
    `max_concurrent_inference` slots for twenty minutes instead of ten.

    That cost is worth naming, because the case it buys is the cold one. A
    conversation an agent is part way through prefills in seconds — the runtime
    holds its prefix — and only the first turn of a long one, or the first after
    an eviction, pays the full 932 seconds. Sizing this to the warm case would
    make the cold one unreachable rather than slow.
    """

    generation_deadline_seconds: int = 900
    """Wall-clock ceiling on a single generation while it holds a concurrency slot.

    Raised from 600 with the token ceiling, so that the ceiling is what binds a
    long answer rather than this. Throughput decays badly with context on this
    hardware — 60.8 tok/s at the start of a generation, 23.5 by the 16000th
    token, measured — which puts a full 16384-token generation at roughly 700
    seconds. At 600 this cut first, and a limit that fires before the one it is
    meant to backstop reports the wrong reason.

    **Measured from the first chunk, not from the request** (2026-08-05). It
    bounds a stream that keeps *producing* too slowly to finish, and a runtime
    evaluating a long prompt produces nothing while it does so, so counting from
    the request charged the answer's budget for reading the question. At the
    context ceiling above that is most of it: 556 seconds of prompt evaluation
    against 900 here, leaving a stream to be cut on its first token and report
    `finish_reason: "length"` — telling a client the model talked too much when
    it had not yet started. Prompt evaluation is bounded by
    `request_timeout_seconds` instead, which is the limit designed for "no bytes
    for the interval".

    So the two compose rather than overlap, and one request's worst case is
    their sum: ten minutes reading plus fifteen writing, which is the longest
    one caller can hold one of `max_concurrent_inference` slots.

    Zero or negative disables it. The stream is cut with
    `finish_reason=length`, the honest signal to an OpenAI client that the model
    did not finish."""

    assistant_max_tokens: int = 1536
    """Token ceiling for one management assistant reply.

    Far below `max_tokens_ceiling`, because the two are answering different
    questions. That one is the most the hardware should ever spend on a
    generation; this is the most a two-or-three-sentence answer in a drawer
    could possibly need, and a ceiling near the length of a good answer turns a
    model that has started rambling into a cut-off paragraph rather than ten
    minutes of held concurrency slot.

    It bounds the proposal too. A block that runs past the ceiling arrives
    unterminated and is discarded, so the visible cost of setting this too low
    is a card that does not appear, not a malformed one that does.
    """
