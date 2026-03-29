from __future__ import annotations

from app.agent.state_machine import AgentStateMachine
from app.models import SessionState


class AudioOutputGate:
    def __init__(self, state_machine: AgentStateMachine) -> None:
        self.state_machine = state_machine

    def allows_output(self, session: SessionState, employee_speaking: bool, hold_active: bool) -> bool:
        return self.state_machine.can_output_audio(session, employee_speaking=employee_speaking, hold_active=hold_active)
