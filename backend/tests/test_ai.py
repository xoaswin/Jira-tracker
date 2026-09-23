"""Phase 5 AI tests: the provider interface, NullProvider, and safe_generate.

The critical section-8 guarantees are tested here without any network:
  * NullProvider returns the raw input unchanged and is always available.
  * safe_generate falls back to raw text on provider error, empty output, and
    timeout, always returning (text, used_ai) and never raising.
  * No em dash appears in any system prompt (section 18).
"""

import time

from app.ai import prompts
from app.ai.base import AIProvider
from app.ai.factory import safe_generate
from app.ai.null import NullProvider


def test_nullprovider_returns_raw_text_after_prompt_prefix():
    n = NullProvider()
    out = n.generate("system", "Rough notes:\n\nfixed the webhook bug")
    assert out == "fixed the webhook bug"
    assert n.is_available() is True


def test_nullprovider_verbatim_when_no_prefix():
    n = NullProvider()
    assert n.generate("s", "just some text") == "just some text"


def test_nullprovider_satisfies_protocol():
    assert isinstance(NullProvider(), AIProvider)


class _BoomProvider:
    name = "boom"

    def generate(self, system, user, max_tokens=512):
        raise RuntimeError("provider exploded")

    def is_available(self):
        return True


class _EmptyProvider:
    name = "empty"

    def generate(self, system, user, max_tokens=512):
        return "   "

    def is_available(self):
        return True


class _SlowProvider:
    name = "slow"

    def generate(self, system, user, max_tokens=512):
        time.sleep(30)  # would exceed the 10s timeout
        return "too late"

    def is_available(self):
        return True


class _GoodProvider:
    name = "good"

    def generate(self, system, user, max_tokens=512):
        return "polished text"

    def is_available(self):
        return True


def test_safe_generate_falls_back_on_error():
    text, used = safe_generate(_BoomProvider(), "s", "Notes:\n\nraw text")
    assert used is False
    assert text == "raw text"


def test_safe_generate_falls_back_on_empty():
    text, used = safe_generate(_EmptyProvider(), "s", "Notes:\n\nraw text")
    assert used is False
    assert text == "raw text"


def test_safe_generate_uses_good_provider():
    text, used = safe_generate(_GoodProvider(), "s", "Notes:\n\nraw text")
    assert used is True
    assert text == "polished text"


def test_safe_generate_nullprovider_is_not_marked_ai():
    text, used = safe_generate(NullProvider(), "s", "Notes:\n\nraw text")
    assert used is False
    assert text == "raw text"


def test_safe_generate_times_out(monkeypatch):
    # Shrink the timeout so the test is fast but still exercises the timeout path.
    import app.ai.factory as factory

    monkeypatch.setattr(factory, "AI_TIMEOUT_SECONDS", 0.5)
    start = time.monotonic()
    text, used = safe_generate(_SlowProvider(), "s", "Notes:\n\nraw text")
    elapsed = time.monotonic() - start
    assert used is False
    assert text == "raw text"
    assert elapsed < 5  # timed out quickly, did not wait 30s


def test_no_em_dash_in_prompts():
    for p in (
        prompts.DRAFT_ISSUE_SYSTEM,
        prompts.CLEANUP_COMMENT_SYSTEM,
        prompts.DAILY_SUMMARY_SYSTEM,
    ):
        assert "—" not in p  # em dash


def test_draft_prompt_asks_for_acceptance_criteria():
    assert "Acceptance Criteria" in prompts.DRAFT_ISSUE_SYSTEM
    assert "* [ ]" in prompts.DRAFT_ISSUE_SYSTEM  # checklist format instruction


def test_draft_text_ai_parses_model_criteria(monkeypatch):
    """When a provider returns 'summary\\n\\ndescription', drafting splits it and
    reports used_ai=True, so the AI-generated acceptance criteria flow through."""
    from app.services import drafting

    model_output = (
        "Migrate 16 VMs for B2Bi batch 2 and run cutover\n\n"
        "h3. Context\nBatch 2 of the Precisely migration.\n\n"
        "h3. Acceptance Criteria\n"
        "* [ ] All 16 VMs are migrated and reachable\n"
        "* [ ] Cutover completes with zero data loss\n"
    )

    class _Provider:
        name = "groq"

        def generate(self, system, user, max_tokens=512):
            return model_output

        def is_available(self):
            return True

    monkeypatch.setattr(drafting, "get_provider", lambda db: _Provider(), raising=False)
    # get_provider is imported inside the function; patch the factory instead.
    import app.ai.factory as factory

    monkeypatch.setattr(factory, "get_provider", lambda db: _Provider())

    summary, description, used_ai = drafting._draft_text_ai(None, "migrate 16 vms batch 2")
    assert used_ai is True
    assert summary == "Migrate 16 VMs for B2Bi batch 2 and run cutover"
    assert "Acceptance Criteria" in description
    assert "All 16 VMs are migrated" in description
