import contextlib
import io
import importlib
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch


class OpenRouterTelemetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dotenv_before = sys.modules.get("dotenv")
        sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None)
        try:
            sys.modules.pop("or_client", None)
            cls.or_client = importlib.import_module("or_client")
        finally:
            if cls._dotenv_before is None:
                sys.modules.pop("dotenv", None)
            else:
                sys.modules["dotenv"] = cls._dotenv_before

    def test_timeout_falls_back_to_next_model_and_records_elapsed_time(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
        }
        client = self.or_client.OpenRouterClient(api_key="test-key")

        with patch.object(
            self.or_client.requests,
            "post",
            side_effect=[self.or_client.requests.Timeout("simulated"), response],
        ) as post, self.assertLogs("or_client", level="WARNING") as captured:
            result = client._make_request("mocked prompt")

        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["timeout"], 45)
        self.assertTrue(any("error_type=Timeout" in line for line in captured.output))

    def test_connection_error_falls_back_to_next_model(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "recovered"}}],
        }
        client = self.or_client.OpenRouterClient(api_key="test-key")

        with patch.object(
            self.or_client.requests,
            "post",
            side_effect=[self.or_client.requests.ConnectionError("simulated disconnect"), response],
        ) as post, patch.object(client, "_log_rate_limit"), self.assertLogs(
            "or_client", level="WARNING"
        ) as captured:
            result = client._make_request("mocked prompt")

        self.assertEqual(result["choices"][0]["message"]["content"], "recovered")
        self.assertEqual(post.call_count, 2)
        self.assertTrue(any("error_type=ConnectionError" in line for line in captured.output))

    def test_429_and_5xx_continue_through_existing_model_order(self):
        rate_limited = Mock(status_code=429, text="rate limited")
        unavailable = Mock(status_code=503, text="temporarily unavailable")
        success = Mock(status_code=200)
        success.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        client = self.or_client.OpenRouterClient(api_key="test-key")

        with patch.object(
            self.or_client.requests,
            "post",
            side_effect=[rate_limited, unavailable, success],
        ) as post, patch.object(client, "_log_rate_limit"), self.assertLogs(
            "or_client", level="WARNING"
        ) as captured:
            client._make_request("mocked prompt")

        sent_models = [call.kwargs["json"]["model"] for call in post.call_args_list]
        self.assertEqual(sent_models, client._models)
        self.assertEqual(post.call_count, 3)
        self.assertTrue(any("status=429" in line for line in captured.output))
        self.assertTrue(any("status=503" in line for line in captured.output))


class ExecutorRecoveryTests(unittest.TestCase):
    def test_error_handler_receives_supported_attempt_keyword(self):
        from agent.error_handler import ErrorDecision
        from agent.executor import AgentExecutor

        step = {
            "step": 1,
            "tool": "mock_tool",
            "description": "mock step",
            "parameters": {},
        }
        plan = {"steps": [step]}

        with contextlib.redirect_stdout(io.StringIO()), patch(
            "agent.executor.create_plan", return_value=plan
        ), patch(
            "agent.executor._call_tool", side_effect=RuntimeError("simulated failure")
        ), patch(
            "agent.executor.analyze_error",
            return_value={
                "decision": ErrorDecision.ABORT,
                "reason": "mocked",
                "user_message": "",
            },
        ) as analyze_error:
            result = AgentExecutor().execute("mock goal")

        self.assertTrue(result.startswith("Tarea abortada."))
        analyze_error.assert_called_once()
        self.assertEqual(analyze_error.call_args.kwargs["attempt"], 1)


class ShortTermPartialWriterTests(unittest.TestCase):
    def test_flush_persists_only_the_latest_pending_values(self):
        from memory.partial_writer import ShortTermPartialWriter

        persisted = []
        writer = ShortTermPartialWriter(persisted.append, debounce_seconds=0.05)
        self.addCleanup(writer.close)

        writer.submit(user_partial="primera transcripción")
        writer.submit(user_partial="transcripción final")
        writer.submit(helena_partial="respuesta parcial")
        writer.flush()

        self.assertEqual(
            persisted,
            [{
                "user_partial": "transcripción final",
                "helena_partial": "respuesta parcial",
            }],
        )

    def test_close_flushes_pending_updates(self):
        from memory.partial_writer import ShortTermPartialWriter

        persisted = []
        writer = ShortTermPartialWriter(persisted.append, debounce_seconds=1)
        writer.submit(user_partial="continuidad")
        writer.close()

        self.assertEqual(persisted, [{"user_partial": "continuidad"}])


class UiBackgroundTaskTests(unittest.TestCase):
    def test_typed_user_message_is_classified_as_conversation(self):
        from utils.ui_tasks import is_conversation_line

        self.assertTrue(is_conversation_line("USUARIO: texto escrito"))
        self.assertTrue(is_conversation_line("Tú: texto por voz"))
        self.assertFalse(is_conversation_line("SYSTEM: evento"))

    def test_python_execution_uses_runner_and_returns_existing_output_format(self):
        from utils.ui_tasks import execute_code

        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            self.assertEqual(Path(command[1]).read_text(encoding="utf-8"), "print('mock')")
            return subprocess.CompletedProcess(command, 0, "mock output\n", "")

        result = execute_code("PYTHON", "print('mock')", runner)

        self.assertEqual(result, "SUCCESS >\nmock output")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["timeout"], 6)

    def test_python_timeout_is_reported_without_running_a_process(self):
        from utils.ui_tasks import execute_code

        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        self.assertEqual(
            execute_code("PYTHON", "while True: pass", runner),
            "ERROR > tiempo de ejecución agotado. Puede haber un bucle infinito.",
        )

    def test_code_file_read_is_limited_to_the_selected_temporary_file(self):
        from utils.ui_tasks import read_code_file

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sample.py"
            source.write_text("print('temporary')", encoding="utf-8")

            self.assertEqual(read_code_file(source), "print('temporary')")

    def test_project_scan_skips_configured_directories(self):
        from utils.ui_tasks import build_project_summary

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "sample"
            (root / "src").mkdir(parents=True)
            (root / ".git").mkdir()
            (root / "src" / "app.py").write_text("pass", encoding="utf-8")
            (root / ".git" / "internal.py").write_text("pass", encoding="utf-8")

            summary = build_project_summary(
                root,
                {".git"},
                lambda path: "code" if path.suffix == ".py" else "unknown",
                lambda size: f"{size} B",
            )

        self.assertIn("FILES: code=1", summary)
        self.assertIn("src\\app.py", summary)
        self.assertNotIn("internal.py", summary)

    def test_zip_scan_lists_entries_without_extracting_archive(self):
        from utils.ui_tasks import build_project_summary

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "sample.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("src/app.py", "pass")

            summary = build_project_summary(
                archive_path,
                set(),
                lambda _path: "code",
                lambda size: f"{size} B",
            )

        self.assertIn("FILES: 1", summary)
        self.assertIn("src/app.py", summary)

    def test_url_spans_trim_trailing_sentence_punctuation(self):
        from utils.ui_tasks import find_http_url_spans

        text = "Mirá https://example.com/path?a=1&b=2)."
        spans = find_http_url_spans(text)

        self.assertEqual(
            [(text[start:end], href) for start, end, href in spans],
            [("https://example.com/path?a=1&b=2", "https://example.com/path?a=1&b=2")],
        )


class AudioTimingMetricsTests(unittest.TestCase):
    def test_audio_timing_summary_uses_bounded_rolling_samples(self):
        from utils.audio_metrics import AudioTimingMetrics

        metrics = AudioTimingMetrics(max_samples=4)
        for elapsed_ms in (1, 2, 3, 4, 100):
            metrics.record("audio_in_send", elapsed_ms)

        summary = metrics.summary("audio_in_send")

        self.assertEqual(summary["samples"], 5)
        self.assertEqual(summary["window"], 4)
        self.assertEqual(summary["p50_ms"], 3)
        self.assertEqual(summary["max_ms"], 100)


if __name__ == "__main__":
    unittest.main()
