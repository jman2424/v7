"""Business conditions must survive tone controls and optional model polishing."""
from unittest.mock import Mock

import pytest

from renderer_v7 import RendererV7


@pytest.mark.parametrize("action,fact", [("FAQ_LOOKUP", "faq"), ("STORE_INFO", "store_info")])
def test_configured_answer_is_not_rewritten_or_truncated(action, fact):
    rewriter = Mock()
    rewriter.rewrite.return_value = "Delivery is always free."
    answer = "Delivery is free over £60. Remote areas are excluded. Order before 3pm."
    renderer = RendererV7(rewriter=rewriter, tone_style="concise", max_sentences=1)
    result = renderer.render(user_text="What are the conditions?", plan={"action": action},
                             facts={fact: {"answer": answer}}, session={})
    assert result == answer
    rewriter.rewrite.assert_not_called()
