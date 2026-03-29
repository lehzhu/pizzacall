from __future__ import annotations

from dataclasses import dataclass

from app.agent.hold import HoldDetector
from app.agent.human_detection import HumanDetector
from app.agent.ivr import IVRClassification, IVRController
from app.models import HumanSubphase, IVRSubphase, PendingActionType, Phase, SessionState


@dataclass(slots=True)
class TransitionOutcome:
    phase: Phase
    subphase: str
    audio_output_enabled: bool
    reason: str


class AgentStateMachine:
    def __init__(self, ivr: IVRController, hold_detector: HoldDetector, human_detector: HumanDetector) -> None:
        self.ivr = ivr
        self.hold_detector = hold_detector
        self.human_detector = human_detector

    def begin_live_call(self, session: SessionState) -> TransitionOutcome:
        session.phase = Phase.dialing
        session.subphase = IVRSubphase.menu.value
        session.audio_output_enabled = False
        return TransitionOutcome(session.phase, session.subphase, False, "live audio connected")

    def apply_ivr_classification(self, session: SessionState, classification: IVRClassification) -> TransitionOutcome:
        if classification.terminal_failure:
            session.terminal_failure_count += 1
            if session.terminal_failure_count >= 3:
                session.phase = Phase.failed
                session.audio_output_enabled = False
                return TransitionOutcome(session.phase, session.subphase, False, "terminal IVR failure threshold reached")
        session.subphase = classification.subphase.value
        session.audio_output_enabled = classification.subphase != IVRSubphase.transfer
        if classification.repeated:
            session.ivr_retry_count += 1
        else:
            session.ivr_retry_count = 0
        if classification.subphase == IVRSubphase.transfer:
            session.phase = Phase.hold
            session.subphase = "waiting_for_human"
            session.audio_output_enabled = False
            session.pending_action = None
            session.transcript_buffer = []
        return TransitionOutcome(session.phase, session.subphase, session.audio_output_enabled, "classified IVR prompt")

    def on_hold_transcript(self, session: SessionState, transcript_window: list[str], seconds_without_ivr: float) -> TransitionOutcome:
        latest = transcript_window[-1] if transcript_window else ""
        if self.hold_detector.classify(latest):
            session.phase = Phase.hold
            session.subphase = "waiting_for_human"
            session.audio_output_enabled = False
            session.pending_action = None
            return TransitionOutcome(session.phase, session.subphase, False, "hold evidence remains active")
        decision = self.human_detector.classify(transcript_window, seconds_without_ivr)
        session.human_confidence = decision.confidence
        if decision.is_human:
            session.phase = Phase.human
            session.subphase = HumanSubphase.greeting.value
            session.audio_output_enabled = True
            session.pending_action = None
            session.transcript_buffer = []
            return TransitionOutcome(session.phase, session.subphase, True, "promoted to human")
        session.audio_output_enabled = False
        return TransitionOutcome(session.phase, session.subphase, False, "still waiting for conservative human evidence")

    def on_uncertain_transcript(self, session: SessionState, transcript_window: list[str], seconds_without_ivr: float) -> TransitionOutcome:
        latest = transcript_window[-1] if transcript_window else ""
        if self.hold_detector.classify(latest):
            session.phase = Phase.hold
            session.subphase = "waiting_for_human"
            session.audio_output_enabled = False
            session.pending_action = None
            session.transcript_buffer = []
            return TransitionOutcome(session.phase, session.subphase, False, "entered hold from non-ivr transcript")
        decision = self.human_detector.classify(transcript_window, seconds_without_ivr)
        session.human_confidence = decision.confidence
        if decision.is_human:
            session.phase = Phase.human
            session.subphase = HumanSubphase.greeting.value
            session.audio_output_enabled = True
            session.pending_action = None
            session.transcript_buffer = []
            return TransitionOutcome(session.phase, session.subphase, True, "promoted to human without IVR")
        return TransitionOutcome(session.phase, session.subphase, session.audio_output_enabled, "insufficient evidence to leave current phase")

    def can_output_audio(self, session: SessionState, employee_speaking: bool, hold_active: bool) -> bool:
        if not session.audio_output_enabled:
            return False
        if employee_speaking or hold_active:
            return False
        if session.pending_action and session.pending_action.type == PendingActionType.dtmf:
            return False
        return True
