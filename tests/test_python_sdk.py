from unittest.mock import Mock

from sdk.python.client import AssistantClient


def test_sdk_continuation_is_bound_to_the_tenant_and_local_alias():
    client = AssistantClient("https://example.test", tenant="EXAMPLE")
    response = Mock()
    response.json.return_value = {"reply": "Hello", "conversation_token": "signed-token"}
    client._session.post = Mock(return_value=response)

    client.send_message("Hello", session_id="local-alias")
    initial = client._session.post.call_args.kwargs["json"]
    assert initial["conversation_token"] is None
    assert "session_id" not in initial
    client.send_message("Continue", session_id="local-alias")
    continued = client._session.post.call_args.kwargs["json"]
    assert continued["conversation_token"] == "signed-token"
    assert continued["message_id"] != initial["message_id"]

    client.tenant = "SECOND"
    client.send_message("Hello", session_id="local-alias")
    assert client._session.post.call_args.kwargs["json"]["conversation_token"] is None
    client.send_message("Continue", conversation_token="explicit-token")
    assert client._session.post.call_args.kwargs["json"]["conversation_token"] == "explicit-token"
