import asyncio
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from actions.discord_music import DiscordMusicPlayer, MusicTrack, _log


class DiscordMusicPanelTests(unittest.IsolatedAsyncioTestCase):
    def test_log_replaces_characters_unavailable_in_console_encoding(self):
        output = io.BytesIO()
        console = io.TextIOWrapper(output, encoding="cp1252")

        with patch("sys.stdout", console):
            _log("⚠️ música")
            console.flush()

        self.assertEqual(
            output.getvalue().decode("cp1252").replace("\r\n", "\n"),
            "[DiscordMusic] ?? m?sica\n",
        )

    async def test_panel_message_is_reused_and_updated(self):
        class Message:
            id = 123

            def __init__(self, content):
                self.content = content
                self.edits = []

            async def edit(self, content, view=None):
                self.content = content
                self.edits.append((content, view))

        class Channel:
            def __init__(self):
                self.messages = []

            async def send(self, content, view=None):
                message = Message(content)
                self.messages.append(message)
                return message

        class Client:
            def __init__(self, channel):
                self.channel = channel

            def get_channel(self, channel_id):
                return self.channel if channel_id == 456 else None

        channel = Channel()
        player = DiscordMusicPlayer()
        player.current_track = MusicTrack(url="audio", title="First track")
        player.is_playing = True
        player.set_bridge(
            type(
                "Bridge",
                (),
                {
                    "client": Client(channel),
                    "loop": asyncio.get_running_loop(),
                    "config": type("Config", (), {"text_channel_id": 456})(),
                },
            )()
        )

        with patch("actions.discord_music._cfg_int", return_value=0), patch(
            "actions.discord_music.DISCORD_UI_AVAILABLE", False
        ):
            player._send_music_panel()
            await asyncio.sleep(0.01)
            self.assertEqual(len(channel.messages), 1)
            panel_message = channel.messages[0]

            player.current_track = MusicTrack(url="audio-2", title="Second track")
            player._update_music_panel("track changed")
            await asyncio.sleep(0.01)

        self.assertIs(player.panel_message, panel_message)
        self.assertEqual(len(channel.messages), 1)
        self.assertEqual(len(panel_message.edits), 1)
        self.assertIn("Second track", panel_message.content)
        self.assertIn("Playlist:", panel_message.content)

    def test_playback_advances_queue_and_refreshes_panel(self):
        player = DiscordMusicPlayer()
        tracks = [
            MusicTrack(url=f"audio-{index}", title=f"Track {index}")
            for index in range(1, 4)
        ]
        player.current_track = tracks[0]
        player.queue = tracks[1:]
        player.is_playing = True
        played = []
        panel_updates = []

        def play_url(url, _headers):
            played.append(url)

        with patch.object(player, "_play_url", side_effect=play_url), patch.object(
            player, "_update_music_panel", side_effect=panel_updates.append
        ):
            player._playback_worker()

        self.assertEqual(played, [track.url for track in tracks])
        self.assertIsNone(player.current_track)
        self.assertFalse(player.is_playing)
        self.assertIn("track changed", panel_updates)
        self.assertIn("queue finished", panel_updates)

    def test_ytdlp_playback_streams_original_query(self):
        player = DiscordMusicPlayer()
        track = MusicTrack(
            url="https://audio.example/expired",
            title="Test track",
            source="ytdlp",
            query="test track",
            http_headers={"User-Agent": "old-agent"},
        )
        player.current_track = track
        player.is_playing = True

        with patch.object(
            player,
            "_play_ytdlp_query",
        ) as play_query, patch.object(player, "_resolve_query_with_ytdlp") as resolve:
            player._playback_worker()

        play_query.assert_called_once_with("test track")
        resolve.assert_not_called()

    def test_ytdlp_query_uses_stdout_pipe_as_ffmpeg_input(self):
        player = DiscordMusicPlayer()
        source_process = SimpleNamespace(stdout=Mock(), stderr=Mock())

        with patch("actions.discord_music._check_ytdlp", return_value=True), patch(
            "actions.discord_music.subprocess.Popen",
            return_value=source_process,
        ) as popen, patch.object(player, "_run_ffmpeg_to_bridge") as run_ffmpeg:
            player._play_ytdlp_query("test track")

        ytdlp_command = popen.call_args.args[0]
        self.assertIn("--output", ytdlp_command)
        self.assertEqual(ytdlp_command[ytdlp_command.index("--output") + 1], "-")
        self.assertEqual(ytdlp_command[-1], "ytsearch1:test track")

        ffmpeg_command = run_ffmpeg.call_args.args[0]
        self.assertEqual(ffmpeg_command[ffmpeg_command.index("-i") + 1], "pipe:0")
        self.assertIs(run_ffmpeg.call_args.kwargs["input_process"], source_process)

    def test_queue_preserves_original_ytdlp_query(self):
        player = DiscordMusicPlayer()

        with patch.object(
            player,
            "_resolve_query_with_ytdlp",
            return_value=(
                "https://audio.example/stream",
                "Resolved title",
                60,
                {"User-Agent": "test-agent"},
            ),
        ):
            result = player.add_to_queue("original search terms")

        self.assertIn("Agregué Resolved title", result)
        self.assertEqual(player.queue[0].query, "original search terms")
        self.assertEqual(player.queue[0].url, "https://audio.example/stream")

    def test_ytdlp_metadata_includes_http_headers(self):
        player = DiscordMusicPlayer()
        metadata = {
            "url": "https://audio.example/stream",
            "title": "Test track",
            "duration": 60,
            "http_headers": {"User-Agent": "test-agent", "Referer": "https://example/"},
        }
        result = subprocess.CompletedProcess(
            args=["yt-dlp"], returncode=0, stdout=json.dumps(metadata), stderr=""
        )

        with patch("actions.discord_music._check_ytdlp", return_value=True), patch(
            "actions.discord_music.subprocess.run", return_value=result
        ):
            resolved = player._resolve_query_with_ytdlp("test track")

        self.assertEqual(resolved, (
            metadata["url"],
            metadata["title"],
            metadata["duration"],
            metadata["http_headers"],
        ))

    def test_unresolved_search_returns_clean_error(self):
        player = DiscordMusicPlayer()
        result = subprocess.CompletedProcess(
            args=["yt-dlp"], returncode=1, stdout="", stderr="search failed"
        )

        with patch("actions.discord_music._check_ytdlp", return_value=True), patch(
            "actions.discord_music.subprocess.run", return_value=result
        ):
            response = player.add_to_queue("unavailable search")

        self.assertEqual(response, "No pude resolver esa búsqueda. Probá con un archivo local o URL directa.")

    def test_url_playback_passes_required_headers_to_ffmpeg(self):
        player = DiscordMusicPlayer()
        headers = {"User-Agent": "test-agent", "Referer": "https://example/"}
        run_ffmpeg = Mock()

        with patch.object(player, "_run_ffmpeg_to_bridge", run_ffmpeg):
            player._play_url("https://audio.example/stream", headers)

        command = run_ffmpeg.call_args.args[0]
        self.assertIn("-headers", command)
        self.assertEqual(
            command[command.index("-headers") + 1],
            "User-Agent: test-agent\r\nReferer: https://example/\r\n",
        )

    def test_failed_stream_keeps_track_and_records_error(self):
        player = DiscordMusicPlayer()
        track = MusicTrack(url="https://audio.example/stream", title="Test track")
        player.current_track = track
        player.is_playing = True
        panel_updates = []

        def failed_playback(_url, _headers):
            player._playback_error = "HTTP 403"
            player._playback_started_event.set()

        with patch.object(player, "_play_url", side_effect=failed_playback), patch.object(
            player, "_update_music_panel", side_effect=panel_updates.append
        ):
            player._playback_worker()

        self.assertIs(player.current_track, track)
        self.assertFalse(player.is_playing)
        self.assertEqual(player._playback_error, "HTTP 403")
        self.assertIn("playback failed", panel_updates)

    def test_play_does_not_confirm_when_stream_fails(self):
        player = DiscordMusicPlayer()
        bridge = type(
            "Bridge",
            (),
            {"voice_client": type("VoiceClient", (), {"is_connected": lambda _self: True})()},
        )()
        player.set_bridge(bridge)

        def fail_before_playback():
            player._playback_error = "HTTP 403"
            player._playback_started_event.set()

        with patch.object(player, "_check_ffmpeg", return_value=True), patch.object(
            player, "_start_playback", side_effect=fail_before_playback
        ), patch.object(player, "_send_music_panel"):
            result = player.play("https://audio.example/stream")

        self.assertEqual(result, "No pude reproducir el tema: HTTP 403")
        self.assertIsNotNone(player.current_track)

    def test_ffmpeg_zero_audio_surfaces_stderr_as_playback_error(self):
        class FailedProcess:
            stdout = io.BytesIO()
            stderr = io.BytesIO(b"HTTP error 403 Forbidden")

            def wait(self, timeout=None):
                return 1

            def terminate(self):
                pass

            def kill(self):
                pass

        player = DiscordMusicPlayer()
        player.set_bridge(SimpleNamespace(voice_client=None))

        with patch("actions.discord_music.subprocess.Popen", return_value=FailedProcess()):
            player._run_ffmpeg_to_bridge(["ffmpeg", "-i", "https://audio.example/stream"])

        self.assertEqual(
            player._playback_error,
            "No se recibió audio de la fuente. HTTP error 403 Forbidden",
        )
        self.assertTrue(player._playback_started_event.is_set())

    def test_play_waits_for_worker_without_holding_player_lock(self):
        player = DiscordMusicPlayer()
        bridge = type(
            "Bridge",
            (),
            {"voice_client": type("VoiceClient", (), {"is_connected": lambda _self: True})()},
        )()
        player.set_bridge(bridge)

        def send_first_audio_chunk(_url, _headers):
            player._playback_started_event.set()

        with patch.object(player, "_check_ffmpeg", return_value=True), patch.object(
            player, "_play_url", side_effect=send_first_audio_chunk
        ), patch.object(player, "_send_music_panel"), patch(
            "actions.discord_music.MUSIC_PREFS_AVAILABLE", False
        ):
            result = player.play("https://audio.example/stream")

        self.assertEqual(result, "Reproduciendo: URL directa de audio")
        player._playback_thread.join(timeout=1)
        self.assertFalse(player._playback_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
