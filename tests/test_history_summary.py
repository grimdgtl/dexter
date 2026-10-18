from dexter.agent import summary
from dexter.agent.prompts import turn_context


def test_summary_entries_preserve_confirmation_outcomes_without_memory_or_image_bytes():
    content = [
        {
            "type": "text",
            "text": turn_context([{"id": 1, "text": "STARA_MEMORIJA"}], notes=["Otkazano slanje."]),
        },
        {"type": "image", "source": {"data": "BASE64_TAJNA"}},
        {"type": "text", "text": "Нови договор."},
    ]
    data = summary.entries([{"role": "user", "content": content}])
    assert "Otkazano slanje" in data[0] and "Novi dogovor" in data[0]
    assert "STARA_MEMORIJA" not in data[0] and "BASE64_TAJNA" not in data[0]
