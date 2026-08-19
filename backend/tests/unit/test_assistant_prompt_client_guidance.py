from __future__ import annotations

from app.application.use_cases.assist_operator import (
    _SURFACE_HELP,
)
from tests.unit.assistant_prompt_fixtures import (
    prompt,
)

pytest_plugins = ("tests.unit.assistant_prompt_fixtures",)


def test_the_prompt_gives_codex_the_setting_that_is_wrong_by_default() -> None:
    """`wire_api` is the whole of whether Codex starts.

    An answer that omits it is worse than no answer: the operator follows it,
    the client refuses to launch, and nothing in the message says which line
    was missing. It is asserted with the value spelled out because the previous
    documented value — `"chat"` — has been impossible since February 2026.
    """
    text = prompt()

    assert 'wire_api = "responses"' in text
    assert '"chat"' in text, "the wrong value must be named, or nobody knows what to change"


def test_the_prompt_says_env_key_is_a_variable_name() -> None:
    """The confusion that puts a credential in a config file.

    A real operator asked "base_url 跟 env_key 是什麼" on 2026-08-07 and the
    assistant answered that `env_key` is "your API key, copy it from the
    management interface". It is the *name* of an environment variable. Acting
    on that answer fails twice: the client does not start, and a live key ends
    up written into a file that gets copied, committed and shared.

    Pinned on the prompt rather than trusted to the model, because a fact the
    prompt omits is a fact a small model invents — which is exactly how that
    answer was produced.
    """
    text = prompt()

    assert "NAME of an environment variable" in text, (
        "the distinction has to be stated, not implied by the example"
    )
    assert "paste a key into" in text, "and the consequence of getting it wrong named"
    assert "RCSL_API_KEY" in text


def test_the_screen_the_prompt_sends_people_to_has_its_own_guidance() -> None:
    """The gap that was worse than a gap.

    The prompt tells the operator to go to "Connect an agent". Until
    2026-08-09 that screen registered no surface, so the drawer fell back to
    `other` — whose guidance opens "The operator has no settings form open".
    The one page the assistant sends people to was the one page it did not
    know it was on, and it said so out loud.

    Asserted as the *difference* between the two surfaces rather than on the
    text, because a surface added to the Literal and forgotten in
    `_SURFACE_HELP` falls back silently and this is the check that catches it.
    """
    assert "agent_setup" in _SURFACE_HELP, "a surface with no help falls back to `other` in silence"
    assert prompt(surface="agent_setup") != prompt(surface="other")
    assert "Connect an agent" in prompt(surface="agent_setup")


def test_the_prompt_says_how_to_undo_the_connection() -> None:
    """Handing somebody a default they cannot unset.

    The configuration changes Codex's *default*, which is why the desktop app
    followed the CLI across without being asked. An operator who cannot
    reverse that is stuck with it, and the platform-side answer — revoking the
    key — is the one thing the operator's own machine cannot undo, so it has
    to be named rather than implied.
    """
    text = prompt()

    assert "model_provider" in text and "--profile" in text
    assert "Revoking the key" in text, "the only disconnect this side enforces must be named"


def test_the_prompt_does_not_repeat_the_impossible_claim_about_the_desktop_app() -> None:
    """`/agent-setup` said Codex in the ChatGPT desktop app was impossible.

    It works, and needs no separate setup: every local surface reads the same
    `~/.codex/config.toml`. This prompt never carried the false claim — it
    said nothing at all — so this pins the correction rather than removing an
    error, and pins the narrower thing that *is* true beside it, because a
    flat "it works" invites the same answer for the web version.
    """
    text = prompt()

    assert "ChatGPT desktop app" in text
    assert "chatgpt.com/codex" in text, "the surface that genuinely cannot be pointed here"


def test_the_prompt_admits_codex_needs_node() -> None:
    """Asked "還要裝Node.js？", the assistant said no. It does.

    A wrong "no" here is worse than no answer: it sends somebody to debug a
    missing runtime as though it were a configuration problem, which is where
    that operator spent the next half hour.
    """
    text = prompt()

    assert "Node.js" in text
    assert "npm install -g @openai/codex" in text
