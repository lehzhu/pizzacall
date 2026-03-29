from app.pipeline.deepgram_stt import DeepgramSTTService


def test_extracts_transcript_from_channel_dict() -> None:
    service = DeepgramSTTService("test")
    transcript, confidence = service._extract_transcript(
        {
            "channel": {
                "alternatives": [
                    {"transcript": "press 1 for delivery", "confidence": 0.92},
                ]
            }
        }
    )
    assert transcript == "press 1 for delivery"
    assert confidence == 0.92


def test_extracts_transcript_from_results_channels_list() -> None:
    service = DeepgramSTTService("test")
    transcript, confidence = service._extract_transcript(
        {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {"transcript": "thanks for calling", "confidence": 0.87},
                        ]
                    }
                ]
            }
        }
    )
    assert transcript == "thanks for calling"
    assert confidence == 0.87
