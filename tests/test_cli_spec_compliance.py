import json
import plistlib
import sys
from pathlib import Path

import pytest

import ausum


class _FakeStdin:
    def write(self, _text):
        pass

    def flush(self):
        pass


class _FakeRpcProc:
    stdin = _FakeStdin()

    def __init__(self, stdout_lines):
        self._stdout = iter(stdout_lines)

    @property
    def stdout(self):
        return self._stdout

    def terminate(self):
        pass

    def wait(self):
        pass




def test_format_clickable_path_wraps_escaped_display_path_in_file_hyperlink():
    path = Path("/Users/roy/Library/Mobile Documents/Brain II/video (draft)-summary.md")

    formatted = ausum.format_clickable_path(path)

    assert formatted == (
        "\033]8;;"
        "file:///Users/roy/Library/Mobile%20Documents/Brain%20II/video%20%28draft%29-summary.md"
        "\033\\"
        "/Users/roy/Library/Mobile\\ Documents/Brain\\ II/video\\ \\(draft\\)-summary.md"
        "\033]8;;\033\\"
    )



def test_subcommand_parser_exposes_only_required_subcommands():
    parser = ausum.build_command_parser()
    subparsers_action = next(
        action for action in parser._actions if getattr(action, "choices", None)
    )

    assert set(subparsers_action.choices) == {
        "poll",
        "install-service",
        "uninstall-service",
        "clear",
    }



def test_main_preserves_direct_invocation_without_dl(monkeypatch):
    called = {}

    def fake_process_input(input_arg, outdir=None, read_summary=False):
        called["args"] = (input_arg, outdir, read_summary)
        return 0

    monkeypatch.setattr(ausum, "process_input", fake_process_input)
    monkeypatch.setattr(sys, "argv", ["ausum", "https://example.com/video", "-d", "/tmp/out", "--read"])

    assert ausum.main() == 0
    assert called["args"] == ("https://example.com/video", "/tmp/out", True)



def test_parse_summary_response_extracts_filename_description_and_summary():
    response = """Filename: AI Agent Folder Systems

# Summary

Use a folder-first workflow for agent context and reusable project memory."""

    filename_description, summary = ausum.parse_summary_response(response)

    assert filename_description == "AI Agent Folder Systems"
    assert summary == "# Summary\n\nUse a folder-first workflow for agent context and reusable project memory."



def test_preferred_free_models_default_order_starts_with_deepseek_then_mimo():
    assert ausum.PREFERRED_FREE_MODELS[0] == "opencode/deepseek-v4-flash-free"
    assert ausum.PREFERRED_FREE_MODELS[1] == "opencode/mimo-v2.5-free"



def test_build_output_basename_uses_description_and_remote_author():
    assert ausum.build_output_basename("Folder Based Agent Workflows", "Dave Shapiro") == "Folder Based Agent Workflows - Dave Shapiro"



def test_build_output_basename_omits_author_for_local_files():
    assert ausum.build_output_basename("Folder Based Agent Workflows", None) == "Folder Based Agent Workflows"



def test_parse_author_from_url_extracts_threads_username():
    assert ausum.parse_author_from_url("https://www.threads.com/@magdalenoxford/post/DZcWTgbjH4U?xmt=abc") == "magdalenoxford"



def test_parse_author_from_url_returns_none_when_url_has_no_author():
    assert ausum.parse_author_from_url("https://www.instagram.com/reel/DaOeY_Atxn0/") is None



def test_get_remote_metadata_falls_back_to_url_author_when_ytdlp_metadata_fails(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR: metadata failed"

    monkeypatch.setattr(ausum.subprocess, "run", lambda *_args, **_kwargs: Result())

    assert ausum.get_remote_metadata("https://www.threads.com/@magdalenoxford/post/DZcWTgbjH4U") == {"author": "magdalenoxford"}



def test_ytdlp_args_use_browser_cookies_for_instagram_by_default():
    args = ausum.build_ytdlp_args("https://www.instagram.com/reel/DYek2NZvp63/")

    assert "--cookies-from-browser" in args
    assert "chrome" in args



def test_ytdlp_args_do_not_use_browser_cookies_for_youtube_by_default():
    args = ausum.build_ytdlp_args("https://www.youtube.com/watch?v=abc")

    assert "--cookies-from-browser" not in args



def test_cmd_poll_deletes_threads_urls_without_processing(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [{"id": "thread-1", "url": "https://www.threads.com/@user/post/abc"}],
    )
    calls = {"processed": [], "deleted": []}
    monkeypatch.setattr(ausum, "process_input", lambda url: calls["processed"].append(url) or 0)
    monkeypatch.setattr(ausum, "queue_delete", lambda *_args: calls["deleted"].append(_args[-1]))

    assert ausum.cmd_poll() == 0
    assert calls["processed"] == []
    assert calls["deleted"] == ["thread-1"]

    captured = capsys.readouterr()
    assert "Skipping Threads URL" in captured.err



def test_process_input_names_remote_outputs_from_summary_description_and_author(monkeypatch, tmp_path):
    monkeypatch.setattr(ausum, "check_prerequisites", lambda: None)
    monkeypatch.setattr(ausum, "get_output_dirs", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(ausum, "load_config", lambda: {"save_transcript": True})
    monkeypatch.setattr(ausum, "get_remote_metadata", lambda _url: {"author": "example.creator"})
    monkeypatch.setattr(ausum, "download_and_convert_audio", lambda *_args: None)
    monkeypatch.setattr(ausum, "transcribe_audio", lambda _wav_path: "transcript text")
    monkeypatch.setattr(ausum, "summarize_transcript", lambda _transcript: ("Folder Based Agent Workflows", "# Summary"))

    assert ausum.process_input("https://example.com/video?id=123") == 0

    assert (tmp_path / "Folder Based Agent Workflows - example.creator.txt").read_text(encoding="utf-8") == "transcript text"
    assert (tmp_path / "Folder Based Agent Workflows - example.creator-summary.md").read_text(encoding="utf-8") == (
        "# Summary\n\n---\nSource: https://example.com/video"
    )



ZEN_MODELS_RESPONSE = {"data": [
    {"id": "glm-5.2", "pricing": {"input": 1, "output": 2}},
    {"id": "deepseek-v4-flash-free", "pricing": {"input": 0, "output": 0}},
    {"id": "mimo-v2.5-free", "pricing": {"input": 0, "output": 0}},
    {"id": "hy3-free", "pricing": {}},
    {"id": "nemotron-3-ultra-free", "pricing": {"input": 0, "output": 0}},
    {"id": "north-mini-code-free", "pricing": {"input": 0, "output": 0}},
    {"id": "big-pickle", "pricing": {"input": 0, "output": 0}},
]}


def test_fetch_free_models_filters_by_pricing_and_suffix(monkeypatch):
    monkeypatch.setattr(ausum, "_zen_models_http_get", lambda _url: json.dumps(ZEN_MODELS_RESPONSE))

    assert ausum.fetch_free_models() == [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
        "opencode/hy3-free",
        "opencode/nemotron-3-ultra-free",
        "opencode/north-mini-code-free",
        "opencode/big-pickle",
    ]


def test_fetch_free_models_returns_empty_list_on_http_failure(monkeypatch):
    def fail(_url):
        raise RuntimeError("network down")

    monkeypatch.setattr(ausum, "_zen_models_http_get", fail)

    assert ausum.fetch_free_models() == []


def test_build_failover_queue_preserves_static_priority_and_appends_dynamic(monkeypatch):
    monkeypatch.setattr(ausum, "fetch_free_models", lambda: [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
        "opencode/hy3-free",
        "opencode/nemotron-3-ultra-free",
        "opencode/north-mini-code-free",
        "opencode/big-pickle",
    ])

    assert ausum.build_failover_queue() == [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
        "opencode/hy3-free",
        "opencode/nemotron-3-ultra-free",
        "opencode/north-mini-code-free",
        "opencode/big-pickle",
    ]


def test_build_failover_queue_dedupes_static_and_dynamic(monkeypatch):
    monkeypatch.setattr(ausum, "fetch_free_models", lambda: ["opencode/deepseek-v4-flash-free", "opencode/x-free"])

    assert ausum.build_failover_queue() == [
        "opencode/deepseek-v4-flash-free",
        "opencode/mimo-v2.5-free",
        "opencode/x-free",
    ]


def test_summarize_transcript_succeeds_on_first_preferred_model_without_pushover(monkeypatch, capsys):
    monkeypatch.setattr(ausum, "build_failover_queue", lambda: ["opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free"])
    monkeypatch.setattr(ausum, "should_notify_pushover_for_model", lambda model: model not in ausum.PREFERRED_FREE_MODELS)

    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    def fake_popen(args, **_kwargs):
        return _FakeRpcProc([
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Filename: Desc\\n\\nsummary"}}',
            '{"type":"agent_end","willRetry":false}',
        ])

    monkeypatch.setattr(ausum.subprocess, "Popen", fake_popen)

    assert ausum.summarize_transcript("transcript") == ("Desc", "summary")
    assert pushover_calls == []

    stderr = capsys.readouterr().err
    assert "Model used: opencode/deepseek-v4-flash-free" in stderr


def test_summarize_transcript_failovers_to_next_model_on_error_event(monkeypatch, capsys):
    monkeypatch.setattr(ausum, "build_failover_queue", lambda: ["opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free"])
    monkeypatch.setattr(ausum, "should_notify_pushover_for_model", lambda model: model not in ausum.PREFERRED_FREE_MODELS)
    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    calls = []
    def fake_popen(args, **_kwargs):
        calls.append(args)
        if len(calls) == 1:
            return _FakeRpcProc([
                '{"type":"message_update","assistantMessageEvent":{"type":"error","reason":"error"}}',
                '{"type":"agent_end","willRetry":false}',
            ])
        return _FakeRpcProc([
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Filename: Desc\\n\\nsummary"}}',
            '{"type":"agent_end","willRetry":false}',
        ])

    monkeypatch.setattr(ausum.subprocess, "Popen", fake_popen)

    assert ausum.summarize_transcript("transcript") == ("Desc", "summary")
    assert [c[2] for c in calls] == ["opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free"]

    stderr = capsys.readouterr().err
    assert "Failed models: opencode/deepseek-v4-flash-free" in stderr
    assert "Model used: opencode/mimo-v2.5-free" in stderr


def test_summarize_transcript_sends_pushover_when_dynamic_fallback_wins(monkeypatch):
    monkeypatch.setattr(ausum, "build_failover_queue", lambda: ["opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free", "opencode/nemotron-3-ultra-free"])
    monkeypatch.setattr(ausum, "should_notify_pushover_for_model", lambda model: model not in ausum.PREFERRED_FREE_MODELS)
    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    calls = []
    def fake_popen(args, **_kwargs):
        calls.append(args)
        if len(calls) < 3:
            return _FakeRpcProc([
                '{"type":"message_update","assistantMessageEvent":{"type":"error","reason":"error"}}',
                '{"type":"agent_end","willRetry":false}',
            ])
        return _FakeRpcProc([
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Filename: Desc\\n\\nsummary"}}',
            '{"type":"agent_end","willRetry":false}',
        ])

    monkeypatch.setattr(ausum.subprocess, "Popen", fake_popen)

    ausum.summarize_transcript("transcript")
    assert len(pushover_calls) == 1
    assert "opencode/nemotron-3-ultra-free" in pushover_calls[0]["message"]


def test_summarize_transcript_raises_when_all_models_fail_and_sends_pushover(monkeypatch):
    monkeypatch.setattr(ausum, "build_failover_queue", lambda: ["opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free"])
    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    def fake_popen(args, **_kwargs):
        return _FakeRpcProc([
            '{"type":"message_update","assistantMessageEvent":{"type":"error","reason":"error"}}',
            '{"type":"agent_end","willRetry":false}',
        ])

    monkeypatch.setattr(ausum.subprocess, "Popen", fake_popen)

    with pytest.raises(RuntimeError, match="All summarization models failed"):
        ausum.summarize_transcript("transcript")
    assert len(pushover_calls) == 1


def test_send_pushover_returns_status_code_and_does_not_raise_on_http_error(monkeypatch):
    def raise_urlopen(*_args, **_kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(ausum.urllib.request, "urlopen", raise_urlopen)
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user")
    monkeypatch.setenv("ASUM_PUSHOVER_APP_TOKEN", "token")

    assert ausum.send_pushover(message="test") == 0


def test_cmd_poll_sends_pushover_when_process_input_raises(monkeypatch):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: [{"id": "1", "url": "https://example.com/video"}])
    monkeypatch.setattr(ausum, "process_input", lambda _url: (_ for _ in ()).throw(RuntimeError("download failed")))
    monkeypatch.setattr(ausum, "queue_delete", lambda *_args: None)

    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    assert ausum.cmd_poll() == 1
    assert any("download failed" in c["message"] for c in pushover_calls)


def test_cmd_poll_sends_pushover_on_queue_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: (_ for _ in ()).throw(RuntimeError("queue unreachable")))

    pushover_calls = []
    monkeypatch.setattr(ausum, "send_pushover", lambda **kwargs: pushover_calls.append(kwargs) or 0)

    assert ausum.cmd_poll() == 1
    assert any("queue unreachable" in c["message"] for c in pushover_calls)


def test_process_input_names_local_outputs_from_summary_description_without_author(monkeypatch, tmp_path):
    input_path = tmp_path / "original-video.mp4"
    input_path.write_text("media", encoding="utf-8")

    monkeypatch.setattr(ausum, "check_prerequisites", lambda: None)
    monkeypatch.setattr(ausum, "get_output_dirs", lambda: (tmp_path, tmp_path))
    monkeypatch.setattr(ausum, "load_config", lambda: {"save_transcript": True})
    monkeypatch.setattr(ausum, "convert_to_wav", lambda *_args: None)
    monkeypatch.setattr(ausum, "transcribe_audio", lambda _wav_path: "transcript text")
    monkeypatch.setattr(ausum, "summarize_transcript", lambda _transcript: ("Folder Based Agent Workflows", "# Summary"))

    assert ausum.process_input(str(input_path)) == 0

    assert (tmp_path / "Folder Based Agent Workflows.txt").read_text(encoding="utf-8") == "transcript text"
    assert (tmp_path / "Folder Based Agent Workflows-summary.md").read_text(encoding="utf-8") == (
        f"# Summary\n\n---\nSource: {input_path}"
    )



def test_ytdlp_retry_helper_retries_on_transient_json_parse_error(monkeypatch):
    calls = []

    class Result:
        returncode = 1
        stdout = ""

        def __init__(self, stderr):
            self.stderr = stderr

    def fake_run(args, **__):
        calls.append(args)
        if len(calls) == 1:
            return Result("Failed to parse JSON (caused by JSONDecodeError)")
        return Result("")

    monkeypatch.setattr(ausum.subprocess, "run", fake_run)

    ausum._run_ytdlp_with_retry(["yt-dlp", "--print", "%(uploader)s", "https://x"], retries=2, delay=0)

    assert len(calls) == 2


def test_ytdlp_retry_helper_does_not_retry_permanent_errors(monkeypatch):
    calls = []

    class Result:
        returncode = 1
        stdout = ""
        stderr = "Unsupported URL: not a video"

    def fake_run(args, **__):
        calls.append(args)
        return Result()

    monkeypatch.setattr(ausum.subprocess, "run", fake_run)

    ausum._run_ytdlp_with_retry(["yt-dlp", "--print", "%(uploader)s", "https://x"], retries=2, delay=0)

    assert len(calls) == 1


def test_ytdlp_retry_helper_retries_on_empty_media_response(monkeypatch):
    calls = []

    class Result:
        returncode = 1
        stdout = ""

        def __init__(self, stderr):
            self.stderr = stderr

    def fake_run(args, **__):
        calls.append(args)
        if len(calls) == 1:
            return Result("Instagram sent an empty media response")
        return Result("ok")

    monkeypatch.setattr(ausum.subprocess, "run", fake_run)

    ausum._run_ytdlp_with_retry(["yt-dlp", "--print", "%(uploader)s", "https://x"], retries=2, delay=0)
    assert len(calls) == 2


def test_ytdlp_retry_helper_returns_first_result_on_success(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = "author"
        stderr = ""

    def fake_run(args, **__):
        calls.append(args)
        return Result()

    monkeypatch.setattr(ausum.subprocess, "run", fake_run)

    result = ausum._run_ytdlp_with_retry(["yt-dlp", "--print", "%(uploader)s", "https://x"], retries=2, delay=0)
    assert len(calls) == 1
    assert result.returncode == 0


def test_ytdlp_retry_delay_applied_between_attempts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ausum.time, "sleep", lambda s: sleeps.append(s))

    class Result:
        returncode = 1
        stdout = ""
        stderr = "empty media response"

    monkeypatch.setattr(ausum.subprocess, "run", lambda *a, **kw: Result())

    ausum._run_ytdlp_with_retry(["yt-dlp", "https://x"], retries=2, delay=3)
    assert sleeps == [3, 3]


def test_download_and_convert_audio_retries_on_transient_error(monkeypatch):
    retry_calls = []

    class Result:
        returncode = 1
        stdout = ""
        stderr = "empty media response"

    monkeypatch.setattr(ausum, "_run_ytdlp_with_retry", lambda args, retries, delay: retry_calls.append(args) or Result())

    class _FakeTmpDir:
        def __enter__(self):
            return "/tmp/fake"

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(ausum.tempfile, "TemporaryDirectory", lambda **__: _FakeTmpDir())

    with pytest.raises(RuntimeError, match="Failed to download audio"):
        ausum.download_and_convert_audio("https://x", Path("out.wav"))
    assert len(retry_calls) == 1


def test_get_remote_metadata_retries_through_helper(monkeypatch):
    retry_calls = []

    class Result:
        returncode = 2
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ausum, "_run_ytdlp_with_retry", lambda args, retries, delay: retry_calls.append(args) or Result())

    result = ausum.get_remote_metadata("https://x")
    assert result == {"author": None}
    assert len(retry_calls) == 1



def test_main_help_exposes_subcommands_and_direct_cli_usage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ausum", "--help"])

    assert ausum.main() == 0

    captured = capsys.readouterr()
    assert "usage: ausum [-h] [-d OUTDIR] [--read] input" in captured.out
    assert "Commands:" in captured.out
    assert "poll" in captured.out
    assert "install-service" in captured.out
    assert "clear" in captured.out



def test_cmd_clear_deletes_all_queue_items_and_reports_count(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [
            {"id": "1", "url": "https://x.com/a"},
            {"id": "2", "url": "https://x.com/b"},
            {"id": "3", "url": "https://x.com/c"},
        ],
    )
    deleted = []
    monkeypatch.setattr(ausum, "queue_delete", lambda *a: deleted.append(a[-1]))

    assert ausum.cmd_clear() == 0
    assert deleted == ["1", "2", "3"]

    captured = capsys.readouterr()
    assert "Cleared 3 items" in captured.err


def test_cmd_clear_handles_empty_queue(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: [])
    monkeypatch.setattr(ausum, "queue_delete", lambda *a: (_ for _ in ()).throw(AssertionError("should not be called")))

    assert ausum.cmd_clear() == 0

    captured = capsys.readouterr()
    assert "No pending URLs" in captured.out


def test_cmd_clear_returns_1_on_queue_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: (_ for _ in ()).throw(RuntimeError("down")))

    assert ausum.cmd_clear() == 1


def test_cmd_clear_continues_on_delete_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [{"id": "1", "url": "https://x.com/a"}, {"id": "2", "url": "https://x.com/b"}],
    )
    calls = 0
    def flaky_delete(*_a):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("delete failed")
    monkeypatch.setattr(ausum, "queue_delete", flaky_delete)

    assert ausum.cmd_clear() == 1  # one error
    assert calls == 2  # still tried both

    captured = capsys.readouterr()
    assert "Failed to delete 1" in captured.err


def test_cmd_clear_handles_malformed_items(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: [None, {"id": "1", "url": "https://x.com/a"}])
    deleted = []
    monkeypatch.setattr(ausum, "queue_delete", lambda *a: deleted.append(a[-1]))

    assert ausum.cmd_clear() == 1
    assert deleted == ["1"]

    captured = capsys.readouterr()
    assert "Skipping malformed item" in captured.err


def test_main_prefers_existing_local_path_named_poll(monkeypatch, tmp_path):
    called = {}
    poll_path = tmp_path / "poll"
    poll_path.write_text("audio", encoding="utf-8")

    def fake_process_input(input_arg, outdir=None, read_summary=False):
        called["args"] = (input_arg, outdir, read_summary)
        return 0

    monkeypatch.setattr(ausum, "process_input", fake_process_input)
    monkeypatch.setattr(sys, "argv", ["ausum", str(poll_path)])

    assert ausum.main() == 0
    assert called["args"] == (str(poll_path), None, False)



def test_main_prefers_existing_local_path_named_subcommand_in_cwd(monkeypatch, tmp_path):
    called = {}
    install_path = tmp_path / "install-service"
    install_path.write_text("audio", encoding="utf-8")

    def fake_process_input(input_arg, outdir=None, read_summary=False):
        called["args"] = (input_arg, outdir, read_summary)
        return 0

    monkeypatch.setattr(ausum, "process_input", fake_process_input)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ausum", "install-service"])

    assert ausum.main() == 0
    assert called["args"] == ("install-service", None, False)



def test_main_uses_subcommand_when_name_is_not_existing_local_path(monkeypatch):
    called = {"poll": 0}

    monkeypatch.setattr(ausum, "cmd_poll", lambda: called.__setitem__("poll", called["poll"] + 1) or 0)
    monkeypatch.setattr(sys, "argv", ["ausum", "poll"])

    assert ausum.main() == 0
    assert called["poll"] == 1



def test_install_service_only_writes_plist(monkeypatch, tmp_path, capsys):
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.ausum.poll.plist"
    log_path = tmp_path / ".config" / "ausum" / "poll.log"
    subprocess_calls = []

    def fake_run(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        raise AssertionError("launchctl should not be called during install-service")

    monkeypatch.setattr(ausum, "_ausum_plist_path", lambda: plist_path)
    monkeypatch.setattr(ausum, "POLL_LOG_PATH", log_path)
    monkeypatch.setattr(ausum.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin")
    monkeypatch.setenv("WHISPER_CLI", "/Users/roy/bin/whisper-cli")
    monkeypatch.setenv("WHISPER_MODEL", "/Users/roy/models/ggml-large-v3-turbo.bin")
    monkeypatch.delenv("PUSHOVER_USER_KEY", raising=False)
    monkeypatch.delenv("ASUM_PUSHOVER_APP_TOKEN", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

    assert ausum.cmd_install_service() == 0

    assert plist_path.exists()
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["ProgramArguments"][-1] == "poll"
    assert plist["StandardOutPath"] == str(log_path)
    assert plist["StandardErrorPath"] == str(log_path)
    assert plist["EnvironmentVariables"] == {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "WHISPER_CLI": "/Users/roy/bin/whisper-cli",
        "WHISPER_MODEL": "/Users/roy/models/ggml-large-v3-turbo.bin",
    }
    assert subprocess_calls == []

    captured = capsys.readouterr()
    assert f"Installed: {plist_path}" in captured.out
    assert f"Logs at {log_path}" in captured.out



def test_install_service_preserves_pushover_and_opencode_credentials(monkeypatch, tmp_path):
    plist_path = tmp_path / "Library" / "LaunchAgents" / "com.ausum.poll.plist"
    log_path = tmp_path / ".config" / "ausum" / "poll.log"

    monkeypatch.setattr(ausum, "_ausum_plist_path", lambda: plist_path)
    monkeypatch.setattr(ausum, "POLL_LOG_PATH", log_path)
    monkeypatch.setattr(ausum.subprocess, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PUSHOVER_USER_KEY", "user-123")
    monkeypatch.setenv("ASUM_PUSHOVER_APP_TOKEN", "token-456")
    monkeypatch.setenv("OPENCODE_API_KEY", "oc-key-789")
    # Ensure whisper vars are unset so only pushover/opencode vars are asserted
    monkeypatch.delenv("WHISPER_CLI", raising=False)
    monkeypatch.delenv("WHISPER_MODEL", raising=False)

    assert ausum.cmd_install_service() == 0

    plist = plistlib.loads(plist_path.read_bytes())
    env = plist["EnvironmentVariables"]
    assert env["PUSHOVER_USER_KEY"] == "user-123"
    assert env["ASUM_PUSHOVER_APP_TOKEN"] == "token-456"
    assert env["OPENCODE_API_KEY"] == "oc-key-789"



def test_cmd_poll_returns_nonzero_when_queue_delete_fails_after_processing(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: [{"id": "123", "url": "https://example.com/video"}])
    monkeypatch.setattr(ausum, "process_input", lambda *_args, **_kwargs: 0)

    def fail_delete(*_args, **_kwargs):
        raise RuntimeError("delete failed")

    monkeypatch.setattr(ausum, "queue_delete", fail_delete)

    assert ausum.cmd_poll() == 1

    captured = capsys.readouterr()
    assert "Processed successfully but failed to acknowledge queue item 123" in captured.err
    assert "Done: 0 processed, 1 errors." in captured.err



def test_cmd_poll_skips_malformed_queue_items_and_payload(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )

    fetches = iter([
        "not-a-list",
        [None, {"id": "missing-url"}, {"url": "missing-id"}, {"id": "ok", "url": "https://example.com/video"}],
    ])

    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: next(fetches))
    monkeypatch.setattr(ausum, "process_input", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(ausum, "queue_delete", lambda *_args, **_kwargs: None)

    assert ausum.cmd_poll() == 1
    first = capsys.readouterr()
    assert "Malformed queue payload: items must be a list" in first.err

    assert ausum.cmd_poll() == 1
    second = capsys.readouterr()
    assert "Skipping malformed queue item: None" in second.err
    assert "Skipping malformed queue item: {'id': 'missing-url'}" in second.err
    assert "Skipping malformed queue item: {'url': 'missing-id'}" in second.err
    assert "Done: 1 processed, 3 errors." in second.err



def test_cmd_poll_treats_non_string_url_as_malformed(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [
            {"id": "123", "url": 42},
            {"id": "ok", "url": "https://example.com/video"},
        ],
    )

    calls = {"processed": [], "deleted": []}
    monkeypatch.setattr(
        ausum,
        "process_input",
        lambda url, *_args, **_kwargs: calls["processed"].append(url) or 0,
    )
    monkeypatch.setattr(
        ausum,
        "queue_delete",
        lambda *_args: calls["deleted"].append(_args[-1]),
    )

    assert ausum.cmd_poll() == 1
    assert calls["processed"] == ["https://example.com/video"]
    assert calls["deleted"] == ["ok"]

    captured = capsys.readouterr()
    assert "Skipping malformed queue item: {'id': '123', 'url': 42}" in captured.err
    assert "Done: 1 processed, 1 errors." in captured.err



def test_cmd_poll_skips_non_url_string_values_as_malformed(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [
            {"id": "readme", "url": "README.md"},
            {"id": "bad", "url": "not-a-url"},
            {"id": "ok", "url": "https://example.com/video"},
        ],
    )

    calls = {"processed": [], "deleted": []}
    monkeypatch.setattr(
        ausum,
        "process_input",
        lambda url, *_args, **_kwargs: calls["processed"].append(url) or 0,
    )
    monkeypatch.setattr(
        ausum,
        "queue_delete",
        lambda *_args: calls["deleted"].append(_args[-1]),
    )

    assert ausum.cmd_poll() == 1
    assert calls["processed"] == ["https://example.com/video"]
    assert calls["deleted"] == ["ok"]

    captured = capsys.readouterr()
    assert "Skipping malformed queue item: {'id': 'readme', 'url': 'README.md'}" in captured.err
    assert "Skipping malformed queue item: {'id': 'bad', 'url': 'not-a-url'}" in captured.err
    assert "Done: 1 processed, 2 errors." in captured.err



def test_cmd_poll_skips_invalid_item_id_scalar_types(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [
            {"id": False, "url": "https://example.com/false"},
            {"id": [], "url": "https://example.com/list"},
            {"id": {}, "url": "https://example.com/dict"},
            {"id": 1.5, "url": "https://example.com/float"},
            {"id": "ok", "url": "https://example.com/video"},
        ],
    )

    calls = {"processed": [], "deleted": []}
    monkeypatch.setattr(
        ausum,
        "process_input",
        lambda url, *_args, **_kwargs: calls["processed"].append(url) or 0,
    )
    monkeypatch.setattr(
        ausum,
        "queue_delete",
        lambda *_args: calls["deleted"].append(_args[-1]),
    )

    assert ausum.cmd_poll() == 1
    assert calls["processed"] == ["https://example.com/video"]
    assert calls["deleted"] == ["ok"]

    captured = capsys.readouterr()
    assert "Skipping malformed queue item: {'id': False, 'url': 'https://example.com/false'}" in captured.err
    assert "Skipping malformed queue item: {'id': [], 'url': 'https://example.com/list'}" in captured.err
    assert "Skipping malformed queue item: {'id': {}, 'url': 'https://example.com/dict'}" in captured.err
    assert "Skipping malformed queue item: {'id': 1.5, 'url': 'https://example.com/float'}" in captured.err
    assert "Done: 1 processed, 4 errors." in captured.err



def test_cmd_poll_returns_nonzero_on_partial_processing_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(
        ausum,
        "queue_fetch",
        lambda *_: [
            {"id": "ok", "url": "https://example.com/ok"},
            {"id": "bad", "url": "https://example.com/bad"},
        ],
    )

    def fake_process_input(url, *_args, **_kwargs):
        return 2 if url.endswith("/bad") else 0

    deleted = []
    monkeypatch.setattr(ausum, "process_input", fake_process_input)
    monkeypatch.setattr(ausum, "queue_delete", lambda *_args: deleted.append(_args[-1]))

    assert ausum.cmd_poll() == 1
    assert deleted == ["ok"]

    captured = capsys.readouterr()
    assert "Failed with exit code 2, keeping item in queue" in captured.err
    assert "Done: 1 processed, 1 errors." in captured.err



def test_cmd_poll_is_noninteractive_when_output_dirs_unconfigured(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {"queue_url": "https://queue.example", "queue_token": "secret"},
    )

    def fail_queue_fetch(*_args, **_kwargs):
        raise AssertionError("queue_fetch should not be called when output dirs are missing")

    def fail_process_input(*_args, **_kwargs):
        raise AssertionError("process_input should not be called when output dirs are missing")

    def fail_input(*_args, **_kwargs):
        raise AssertionError("input should not be called during poll")

    monkeypatch.setattr(ausum, "queue_fetch", fail_queue_fetch)
    monkeypatch.setattr(ausum, "process_input", fail_process_input)
    monkeypatch.setattr("builtins.input", fail_input)

    assert ausum.cmd_poll() == 1

    captured = capsys.readouterr()
    assert "summary_dir/transcript_dir" in captured.err
    assert "poll/install-service" in captured.err


def test_cmd_poll_rejects_non_string_queue_config(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": None,
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )

    def fail_queue_fetch(*_args, **_kwargs):
        raise AssertionError("queue_fetch should not be called when queue config is invalid")

    monkeypatch.setattr(ausum, "queue_fetch", fail_queue_fetch)

    assert ausum.cmd_poll() == 1

    captured = capsys.readouterr()
    assert "queue_url and queue_token not configured" in captured.err


def test_cmd_poll_rejects_non_string_output_dirs_noninteractively(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": 123,
            "transcript_dir": "/tmp/transcripts",
        },
    )

    def fail_queue_fetch(*_args, **_kwargs):
        raise AssertionError("queue_fetch should not be called when output dirs are invalid")

    monkeypatch.setattr(ausum, "queue_fetch", fail_queue_fetch)

    assert ausum.cmd_poll() == 1

    captured = capsys.readouterr()
    assert "summary_dir/transcript_dir" in captured.err
    assert "poll/install-service" in captured.err


def test_queue_delete_url_encodes_reserved_item_id(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b""

    def fake_urlopen(req, timeout=15):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ausum.urllib.request, "urlopen", fake_urlopen)

    ausum.queue_delete("https://queue.example", "secret", "a/b?c#d")

    assert captured == {
        "url": "https://queue.example/queue/a%2Fb%3Fc%23d",
        "method": "DELETE",
        "timeout": 15,
    }


def test_cmd_poll_accepts_zero_id_with_valid_url(monkeypatch, capsys):
    monkeypatch.setattr(
        ausum,
        "load_config",
        lambda: {
            "queue_url": "https://queue.example",
            "queue_token": "secret",
            "summary_dir": "/tmp/summaries",
            "transcript_dir": "/tmp/transcripts",
        },
    )
    monkeypatch.setattr(ausum, "queue_fetch", lambda *_: [{"id": 0, "url": "https://example.com/video"}])

    calls = {"processed": [], "deleted": []}
    monkeypatch.setattr(
        ausum,
        "process_input",
        lambda url, *_args, **_kwargs: calls["processed"].append(url) or 0,
    )
    monkeypatch.setattr(
        ausum,
        "queue_delete",
        lambda *_args: calls["deleted"].append(_args[-1]),
    )

    assert ausum.cmd_poll() == 0
    assert calls["processed"] == ["https://example.com/video"]
    assert calls["deleted"] == ["0"]

    captured = capsys.readouterr()
    assert "Skipping malformed queue item" not in captured.err
    assert "Done: 1 processed, 0 errors." in captured.err
