import json
from pathlib import Path

import responses

from newsdash.http import make_session
from newsdash.summarize import summarize

FIX = Path(__file__).parent / "fixtures" / "llm"
CHAT_URL = "https://api.openai.com/v1/chat/completions"


def make_payloads(news=None, papers=None):
    return {
        "news": {"items": news or []},
        "papers": {"items": papers or []},
    }


def news_item(i, score=0.5):
    return {"title": f"Story {i}", "summary": "…", "source": "S", "score": score}


def paper_item(i, score=0.5):
    return {"title": f"Paper {i}", "summary": "…", "source": "S", "score": score}


def test_no_api_key_makes_no_call():
    payloads = make_payloads(news=[news_item(1)])
    assert summarize(payloads, {}, make_session()) is None


@responses.activate
def test_kill_switch_makes_no_call():
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test", "LLM_SUMMARY_ENABLED": "0"}
    assert summarize(payloads, env, make_session()) is None
    assert len(responses.calls) == 0


def test_empty_items_skips_without_call():
    payloads = make_payloads()
    env = {"LLM_API_KEY": "sk-test"}
    assert summarize(payloads, env, make_session()) is None


@responses.activate
def test_happy_path_returns_all_four_keys():
    responses.post(CHAT_URL, body=(FIX / "chat_completion.json").read_text())
    payloads = make_payloads(
        news=[news_item(i) for i in range(30)],
        papers=[paper_item(i) for i in range(15)],
    )
    env = {"LLM_API_KEY": "sk-test", "LLM_MODEL": "gpt-4o-mini"}
    result = summarize(payloads, env, make_session())
    assert result.keys() == {"brief", "news_summary", "papers_summary", "image_query"}
    assert result["image_query"] == "clockwork automatons"

    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(req.body)
    assert body["model"] == "gpt-4o-mini"
    assert body["response_format"] == {"type": "json_object"}
    # capped: only the first MAX_NEWS_ITEMS/MAX_PAPER_ITEMS appear in the prompt
    prompt = body["messages"][1]["content"]
    assert "Story 19" in prompt and "Story 20" not in prompt
    assert "Paper 9" in prompt and "Paper 10" not in prompt


@responses.activate
def test_markdown_fenced_json_is_unwrapped():
    # some OpenAI-compatible providers still fence JSON in ```json ... ```
    # even with response_format set — must not break parsing.
    fenced = "```json\n" + json.dumps({
        "brief": "b", "news_summary": "n", "papers_summary": "p",
        "image_query": "q",
    }) + "\n```"
    responses.post(CHAT_URL, json={"choices": [{"message": {"content": fenced}}]})
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test"}
    result = summarize(payloads, env, make_session())
    assert result == {"brief": "b", "news_summary": "n", "papers_summary": "p",
                       "image_query": "q"}


@responses.activate
def test_malformed_json_content_returns_none():
    responses.post(CHAT_URL, json={
        "choices": [{"message": {"content": "not json at all"}}],
    })
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test"}
    assert summarize(payloads, env, make_session()) is None


@responses.activate
def test_missing_key_in_json_returns_none():
    responses.post(CHAT_URL, json={
        "choices": [{"message": {"content": json.dumps({"brief": "x"})}}],
    })
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test"}
    assert summarize(payloads, env, make_session()) is None


@responses.activate
def test_empty_completion_content_returns_none(capsys):
    # Reasoning-capable models can burn the whole token budget on hidden
    # chain-of-thought and come back with an empty `content` and
    # finish_reason="length" — must not surface as a confusing
    # JSONDecodeError("Expecting value: line 1 column 1 (char 0)").
    responses.post(CHAT_URL, json={
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
    })
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test"}
    assert summarize(payloads, env, make_session()) is None
    err = capsys.readouterr().out
    assert "finish_reason=length" in err


@responses.activate
def test_http_error_returns_none():
    responses.post(CHAT_URL, status=500)
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test"}
    assert summarize(payloads, env, make_session()) is None


@responses.activate
def test_empty_string_base_url_falls_back_to_default():
    # GitHub Actions sets an env var to "" (not absent) when a workflow
    # references ${{ vars.X }} for a Variable that was never created —
    # env.get(key, default) would NOT catch this (the key exists), only
    # `or default` does. Regression test for exactly that failure mode
    # (surfaced in production as requests.exceptions.MissingSchema).
    responses.post(CHAT_URL, body=(FIX / "chat_completion.json").read_text())
    payloads = make_payloads(news=[news_item(1)])
    env = {"LLM_API_KEY": "sk-test", "LLM_BASE_URL": "", "LLM_MODEL": ""}
    result = summarize(payloads, env, make_session())
    assert result is not None
    assert responses.calls[0].request.url == CHAT_URL
    assert json.loads(responses.calls[0].request.body)["model"] == "gpt-4o-mini"
