"""Template rendering and fingerprints.

These tests are about the rendering *mechanism*, not about what the templates say.
``prompts/system.md`` is the main thing anyone editing this agent will change, so a
test asserting its wording would go red on every intended edit and teach nobody
anything. What is worth pinning is that substitution happens, that a missing value
is refused rather than sent, and that the fingerprint moves when a template does.
"""

from __future__ import annotations

import pytest

from support_agent import prompts, retrieve, tools

TEMPLATE = "Date: {{as_of_date}}\nCustomer: {{customer_id}}\n"


def test_substitution_replaces_every_placeholder() -> None:
    out = prompts.render(TEMPLATE, {"as_of_date": "2026-07-28", "customer_id": "cust-1042"})

    assert out == "Date: 2026-07-28\nCustomer: cust-1042\n"
    # A surplus value is not an error; a repeated placeholder substitutes each time.
    assert prompts.render("{{a}}-{{a}}", {"a": "x", "unused": "y"}) == "x-x"


def test_a_missing_value_is_refused_rather_than_sent() -> None:
    """An unsubstituted ``{{customer_id}}`` reaching the model produces a
    plausible-looking answer built on a literal placeholder. Cheaper to catch here."""
    with pytest.raises(prompts.UnrenderedPlaceholder) as caught:
        prompts.render(TEMPLATE, {"as_of_date": "2026-07-28"})

    assert "customer_id" in str(caught.value)
    # The message lists what *was* available, so the fix is obvious.
    assert "as_of_date" in str(caught.value)


def test_the_shipped_templates_render_with_nothing_left_over() -> None:
    """Adding a ``{{variable}}`` to a template without teaching the renderer about
    it is the one editing mistake this catches, and it costs no API call.

    Nothing here requires ``system.md`` to *use* every value it is offered: a
    surplus value is allowed by design, so dropping a placeholder is a prompt
    decision, and prompt decisions must not turn this suite red. The context
    template is held to more — the message and the retrieved documents have to
    reach the model, or retrieval is decoration and a scorer cannot check a
    citation against the ``retrieved`` list on the same step."""
    system = prompts.render_system("cust-1042", "sess-0088", "2026-07-28")
    assert "{{" not in system

    hits = [hit.to_trace() for hit in retrieve.retrieve("I want a refund")]
    context = prompts.render_context("I want a refund", hits)
    assert "{{" not in context
    assert "I want a refund" in context
    for hit in hits:
        # The doc id has to survive into the context, or a scorer cannot check a
        # citation against the retrieved list on the same step.
        assert hit["doc_id"] in context
        assert hit["text"] in context


def test_a_fingerprint_moves_when_its_surface_does() -> None:
    surfaces = prompts.fingerprint(tools.TOOL_SCHEMAS)
    assert set(surfaces) == {"prompt_sha256", "tools_sha256", "corpus_sha256"}
    assert all(len(digest) == 64 for digest in surfaces.values())

    # Descriptions are inside the digest, because their wording is what decides
    # whether a tool gets called at the right moment.
    edited = [dict(schema) for schema in tools.TOOL_SCHEMAS]
    edited[0]["description"] += " Also, hurry."
    assert prompts.tools_fingerprint(edited) != surfaces["tools_sha256"]
