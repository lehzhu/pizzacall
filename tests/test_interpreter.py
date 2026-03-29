from app.agent.interpreter import TranscriptInterpreter


def test_extracts_total_time_and_order_number() -> None:
    interpreter = TranscriptInterpreter()
    facts = interpreter.extract_facts("Your total is 24.75 and it will be 35 to 45 minutes. Confirmation number is A12B.")
    assert facts.total == 24.75
    assert facts.delivery_time == "35 to 45 minutes"
    assert facts.order_number == "A12B"
