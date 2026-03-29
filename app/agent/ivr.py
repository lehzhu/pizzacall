from __future__ import annotations

from dataclasses import dataclass
import re

from app.models import IVRSubphase, NormalizedOrderRequest, PendingAction, PendingActionType, RestaurantProfile


@dataclass(slots=True)
class IVRClassification:
    subphase: IVRSubphase
    confidence: float
    repeated: bool = False
    terminal_failure: bool = False


class IVRController:
    def __init__(self, profile: RestaurantProfile) -> None:
        self.profile = profile

    def classify_prompt(self, transcript: str, current_subphase: IVRSubphase) -> IVRClassification | None:
        lowered = self._normalize_prompt(transcript)
        for pattern in self.profile.failure_patterns:
            if self._normalize_prompt(pattern) in lowered:
                return IVRClassification(current_subphase, confidence=1.0, terminal_failure=True)
        for name, patterns in self.profile.prompt_patterns.items():
            if any(self._normalize_prompt(pattern) in lowered for pattern in patterns):
                matched = IVRSubphase(name)
                return IVRClassification(
                    subphase=matched,
                    confidence=1.0,
                    repeated=matched == current_subphase,
                )
        heuristic = self._heuristic_match(lowered, current_subphase)
        if heuristic is not None:
            return heuristic
        return None

    def _normalize_prompt(self, text: str) -> str:
        normalized = text.lower()
        replacements = {
            " zero ": " 0 ",
            " one ": " 1 ",
            " two ": " 2 ",
            " three ": " 3 ",
            " four ": " 4 ",
            " five ": " 5 ",
            " six ": " 6 ",
            " seven ": " 7 ",
            " eight ": " 8 ",
            " nine ": " 9 ",
        }
        normalized = f" {normalized} "
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return normalized.strip()

    def _heuristic_match(self, normalized: str, current_subphase: IVRSubphase) -> IVRClassification | None:
        if "press 1" in normalized or "press 2" in normalized or "for delivery" in normalized:
            return IVRClassification(subphase=IVRSubphase.menu, confidence=0.8, repeated=current_subphase == IVRSubphase.menu)
        if ("name" in normalized and ("order" in normalized or "say" in normalized)) or "who is this order for" in normalized:
            return IVRClassification(subphase=IVRSubphase.name, confidence=0.75, repeated=current_subphase == IVRSubphase.name)
        if any(token in normalized for token in ["phone number", "callback number", "telephone number", "call back number"]):
            return IVRClassification(subphase=IVRSubphase.callback, confidence=0.8, repeated=current_subphase == IVRSubphase.callback)
        if any(token in normalized for token in ["zip code", "postal code", "postcode"]):
            return IVRClassification(subphase=IVRSubphase.zip, confidence=0.8, repeated=current_subphase == IVRSubphase.zip)
        if ("correct" in normalized or "confirm" in normalized) and ("yes" in normalized or "no" in normalized):
            return IVRClassification(subphase=IVRSubphase.confirm, confidence=0.8, repeated=current_subphase == IVRSubphase.confirm)
        if any(token in normalized for token in ["please hold", "transfer", "representative", "team member", "store associate"]):
            return IVRClassification(subphase=IVRSubphase.transfer, confidence=0.75, repeated=current_subphase == IVRSubphase.transfer)
        return None

    def next_action(self, subphase: IVRSubphase, order: NormalizedOrderRequest, confirm_matches: bool = True) -> PendingAction:
        if subphase == IVRSubphase.menu:
            return PendingAction(type=PendingActionType.dtmf, value=self.profile.ivr_targets.get("menu", "1"), reason="press menu option")
        if subphase == IVRSubphase.name:
            return PendingAction(type=PendingActionType.say, value=order.customer_name, reason="speak exact customer name")
        if subphase == IVRSubphase.callback:
            return PendingAction(type=PendingActionType.dtmf, value=order.phone_number, reason="enter callback number")
        if subphase == IVRSubphase.zip:
            return PendingAction(type=PendingActionType.say, value=order.zip_code, reason="speak ZIP code")
        if subphase == IVRSubphase.confirm:
            value = self.profile.ivr_targets["confirm_yes"] if confirm_matches else self.profile.ivr_targets["confirm_no"]
            return PendingAction(type=PendingActionType.say, value=value, reason="confirm recognized details")
        return PendingAction(type=PendingActionType.wait, reason="wait for transfer")
