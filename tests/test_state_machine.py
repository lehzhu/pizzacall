from app.agent.hold import HoldDetector
from app.agent.human_detection import HumanDetector
from app.agent.ivr import IVRClassification, IVRController
from app.agent.state_machine import AgentStateMachine
from app.agent.conversation import HumanConversationPlanner
from app.agent.policy import PolicyEngine
from app.models import IVRSubphase, NormalizedOrderRequest, OrderRequest, RestaurantProfile, SessionState, SidePreferences


def make_session() -> SessionState:
    order = NormalizedOrderRequest.from_order_request(
        OrderRequest(
            customer_name="Jane Doe",
            destination_number="6465550101",
            phone_number="2125550101",
            delivery_address="123 Main St New York NY 10001",
            budget_max=30,
            pizza={"desired_toppings": ["pepperoni"]},
        )
    )
    return SessionState(session_id=order.session_id, order_request=order)


def build_machine() -> AgentStateMachine:
    profile = RestaurantProfile(
        prompt_patterns={"menu": ["press 1"], "transfer": ["please hold"]},
        hold_patterns=["your call is important", "music", "please stay on hold"],
        human_patterns=["what can i get started", "thanks for calling", "how may i take your order"],
        bot_suspected_patterns=["press 1", "for delivery"],
    )
    return AgentStateMachine(
        IVRController(profile),
        HoldDetector(profile.hold_patterns),
        HumanDetector(profile.human_patterns, profile.bot_suspected_patterns, 2.0),
    )


def test_transfer_moves_to_hold_and_disables_audio() -> None:
    session = make_session()
    machine = build_machine()
    machine.begin_live_call(session)
    outcome = machine.apply_ivr_classification(session, IVRClassification(subphase=IVRSubphase.transfer, confidence=1.0))
    assert outcome.phase == session.phase
    assert session.phase == "hold"
    assert session.subphase == "waiting_for_human"
    assert not session.audio_output_enabled


def test_human_requires_conservative_signals() -> None:
    session = make_session()
    machine = build_machine()
    session.phase = "hold"
    session.subphase = "waiting_for_human"
    outcome = machine.on_hold_transcript(session, ["thanks for calling", "what can i get started"], 0.5)
    assert outcome.phase == "human"
    assert session.audio_output_enabled


def test_uncertain_ivr_can_promote_direct_human() -> None:
    session = make_session()
    machine = build_machine()
    machine.begin_live_call(session)
    outcome = machine.on_uncertain_transcript(session, ["thanks for calling", "what can i get started"], 3.0)
    assert outcome.phase == "human"
    assert session.subphase == "greeting"


def test_uncertain_transcript_can_enter_hold() -> None:
    session = make_session()
    machine = build_machine()
    machine.begin_live_call(session)
    outcome = machine.on_uncertain_transcript(session, ["your call is important", "music"], 0.0)
    assert outcome.phase == "hold"
    assert session.subphase == "waiting_for_human"


def test_human_transition_ignores_older_ivr_language() -> None:
    session = make_session()
    machine = build_machine()
    session.phase = "hold"
    session.subphase = "waiting_for_human"
    outcome = machine.on_hold_transcript(
        session,
        ["press 1 for delivery", "please stay on hold", "how may i take your order"],
        3.0,
    )
    assert outcome.phase == "human"
    assert session.pending_action is None


def test_transfer_clears_stale_pending_action() -> None:
    session = make_session()
    machine = build_machine()
    machine.begin_live_call(session)
    session.pending_action = controller_pending_action()
    machine.apply_ivr_classification(session, IVRClassification(subphase=IVRSubphase.transfer, confidence=1.0))
    assert session.pending_action is None


def test_live_call_starts_in_dialing_not_ivr() -> None:
    session = make_session()
    machine = build_machine()
    outcome = machine.begin_live_call(session)
    assert outcome.phase == "dialing"
    assert session.phase == "dialing"


def test_ivr_matches_spelled_out_digit_menu_prompt() -> None:
    profile = RestaurantProfile(prompt_patterns={"menu": ["press 1", "for delivery press 1"]})
    controller = IVRController(profile)
    classification = controller.classify_prompt("Welcome to the store, press one for delivery.", IVRSubphase.menu)
    assert classification is not None
    assert classification.subphase == IVRSubphase.menu


def test_ivr_matches_callback_heuristic() -> None:
    controller = IVRController(RestaurantProfile())
    classification = controller.classify_prompt("Please enter your phone number now.", IVRSubphase.menu)
    assert classification is not None
    assert classification.subphase == IVRSubphase.callback


def test_ivr_matches_name_heuristic() -> None:
    controller = IVRController(RestaurantProfile())
    classification = controller.classify_prompt("Who is this order for?", IVRSubphase.menu)
    assert classification is not None
    assert classification.subphase == IVRSubphase.name


def controller_pending_action():
    from app.models import PendingAction, PendingActionType

    return PendingAction(type=PendingActionType.dtmf, value="1", reason="menu")


def test_conversation_rejects_no_go_topping_without_parroting() -> None:
    session = make_session()
    session.order_request.pizza.description = "large thin crust pizza"
    session.order_request.pizza.no_go_toppings = ["olives"]
    planner = HumanConversationPlanner(PolicyEngine())
    session.partial_result["delivery_opening_sent"] = True
    session.partial_result["pizza_requested"] = True
    step = planner.next_step(session, "Would you like olives")
    assert step.text == "No olives."


def test_conversation_does_not_repeat_side_after_confirmation() -> None:
    session = make_session()
    session.order_request.side = SidePreferences(first_choice="buffalo wings, 12 count")
    session.order_request.drink = None
    planner = HumanConversationPlanner(PolicyEngine())
    session.partial_result.update(
        {
            "delivery_opening_sent": True,
            "pizza_requested": True,
            "pizza_confirmed": True,
            "side_requested": True,
            "side_resolved": True,
        }
    )
    step = planner.next_step(session, "Do you want anything else")
    assert step.text == "What's the item prices, total, delivery time, and order number?"


def test_conversation_returns_customer_name_when_asked() -> None:
    session = make_session()
    planner = HumanConversationPlanner(PolicyEngine())
    session.partial_result["delivery_opening_sent"] = True
    step = planner.next_step(session, "What is your name")
    assert step.text == "Jane Doe"


def test_conversation_confirms_delivery_when_asked() -> None:
    session = make_session()
    planner = HumanConversationPlanner(PolicyEngine())
    session.partial_result["delivery_opening_sent"] = True
    step = planner.next_step(session, "Is that for delivery or for pickup")
    assert step.text == "Delivery."


def test_conversation_repeats_pizza_request_when_order_is_unclear() -> None:
    session = make_session()
    session.order_request.pizza.description = "a large thin crust pizza with pepperoni"
    planner = HumanConversationPlanner(PolicyEngine())
    session.partial_result["delivery_opening_sent"] = True
    step = planner.next_step(session, "What are you trying to order")
    assert step.text == "A large thin crust pizza with pepperoni"
