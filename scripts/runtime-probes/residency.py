"""E2: what loading a large model at each context does to the models beside it.

    cd backend && PYTHONPATH=$PWD uv run python ../scripts/runtime-probes/residency.py \
        --i-own-the-window --large gemma4:31b-it-q8_0 --contexts 139264,262144 \
        --sibling qwen2.5:7b=32768 --embedder nomic-embed-text=2048 --restore-ctx 262144

For each context the siblings are made resident first, then the large model is
(re)loaded and a long prompt generated, and residency is read after the load
and after the generation. The scheduler's prediction comes from the log, so it
is attributed to the load that printed it. Finally the production order is
restored: the large model first, then the siblings.

Measured 2026-10-07 on Ollama 0.33.2 (#24): every context from 139264 to 262144
evicted both siblings at load (predicted 52.4-70.9 GiB vs ~51.5 GiB available,
actual 32.5-33.6 GB); loading the large model first and the siblings after
left all three resident.
"""

from __future__ import annotations

import sys

from _common import LogTail, Recorder, answered, fingerprint, parser, require_window, runtime

LONG_PROMPT = "Summarise this code.\n" + ("def f(x):\n    return x * 2  # double\n" * 2500)


def main() -> None:
    p = parser(__doc__.splitlines()[0])
    p.add_argument("--large", required=True)
    p.add_argument("--contexts", required=True)
    p.add_argument("--sibling", action="append", default=[], help="model=num_ctx, repeatable")
    p.add_argument("--embedder", help="model=num_ctx, loaded through /api/embed")
    p.add_argument("--restore-ctx", type=int, required=True)
    args = p.parse_args()
    require_window(args)
    log = LogTail(args.ollama_log)
    siblings = [(m, int(c)) for m, _, c in (s.partition("=") for s in args.sibling)]
    embedder = None
    if args.embedder:
        name, _, ctx = args.embedder.partition("=")
        embedder = (name, int(ctx))

    with runtime(args) as rt:
        models = [args.large, *(m for m, _ in siblings), *([embedder[0]] if embedder else [])]
        rec = Recorder("residency", args.out, fingerprint(rt, models))

        def ensure_siblings() -> None:
            resident = {m["name"] for m in rt.resident()}
            for model, ctx in siblings:
                if model not in resident:
                    rt.load(model, ctx)
            if embedder and embedder[0] not in resident:
                rt.load_embedder(*embedder)

        initial = rt.resident()
        try:
            for ctx in [int(c) for c in args.contexts.split(",")]:
                ensure_siblings()
                before = rt.resident()
                log.mark()
                load_s = rt.load(args.large, ctx)
                after_load = rt.resident()
                prediction = [
                    line for line in log.lines() if "predicted" in line or "evict" in line
                ]
                generation = answered(
                    rt.chat(
                        args.large, [{"role": "user", "content": LONG_PROMPT}], ctx, num_predict=16
                    )
                )
                after_generation = rt.resident()
                rec.emit(
                    "load",
                    model=args.large,
                    num_ctx=ctx,
                    load_s=load_s,
                    resident_before=before,
                    resident_after_load=after_load,
                    resident_after_generation=after_generation,
                    siblings_after_load=sorted(
                        m["name"] for m in after_load if m["name"] != args.large
                    ),
                    prediction=prediction[-4:],
                    generation=generation,
                )

            rt.load(args.large, args.restore_ctx)
            ensure_siblings()
            rec.emit("restored", order="large first, then siblings", resident=rt.resident())
        except Exception as exc:
            # No further lifecycle commands into an uncertain state: report
            # what is resident and what to restore, and stop (review on #26).
            try:
                found = rt.resident()
            except Exception:  # noqa: BLE001 - the runtime may be what failed
                found = None
            rec.emit(
                "recovery_required",
                error=repr(exc)[:300],
                resident_now=found,
                restore_to=initial,
                order="largest model first, then the rest",
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
