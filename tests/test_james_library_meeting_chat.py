from pathlib import Path

from james_library.rain_lab_meeting_chat_version import MeetingChatConfig, MeetingChatService


class DummyModel:
    def complete(self, prompt: str, *, timeout_s: float) -> str:
        assert "assistant:" in prompt
        assert timeout_s > 0
        return "ack"


class DummyChannel:
    def __init__(self):
        self.messages = []

    def send(self, text: str) -> None:
        self.messages.append(text)


def test_command_reset(tmp_path: Path):
    channel = DummyChannel()
    service = MeetingChatService(
        config=MeetingChatConfig(transcript_path=tmp_path / "t.jsonl"),
        model=DummyModel(),
        channel=channel,
    )

    service.handle_user_message("hello")
    assert channel.messages[-1] == "ack"
    assert service.handle_user_message("/reset") == "Conversation reset."


def test_transcript_written(tmp_path: Path):
    channel = DummyChannel()
    transcript = tmp_path / "meeting.jsonl"
    service = MeetingChatService(
        config=MeetingChatConfig(transcript_path=transcript),
        model=DummyModel(),
        channel=channel,
    )

    service.handle_user_message("test")
    assert transcript.exists()
    assert transcript.read_text(encoding="utf-8").strip()
