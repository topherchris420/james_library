"""Response generation pipeline: prompt building, LLM calls, refinement, and completion."""

import threading
import time
from typing import Optional, Tuple

import openai

from rain_lab_chat._logging import get_logger
from rain_lab_chat.agents import Agent
from rain_lab_chat.config import Config
from rain_lab_chat.guardrails import (
    complete_truncated,
    detect_repeated_intro,
)

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_style_instruction(agent: Agent, prev_speaker: str) -> str:
    """Choose a conversational style based on the agent's agreeableness."""
    if agent.agreeableness < 0.3:
        return (
            f"STYLE: You STRONGLY DISAGREE with {prev_speaker}. Be direct and combative:\n"
            f"- Challenge their assumptions or data interpretation\n"
            f"- Point out flaws in their reasoning or missing considerations"
        )
    if agent.agreeableness < 0.5:
        return (
            f"STYLE: You're SKEPTICAL of what {prev_speaker} said. Question their claims:\n"
            f"- Demand evidence or point out logical gaps\n"
            f"- Ask probing questions about feasibility or rigor"
        )
    if agent.agreeableness < 0.7:
        return (
            f"STYLE: You PARTIALLY AGREE with {prev_speaker} but add nuance:\n"
            f"- Acknowledge one valid point then offer a different angle\n"
            f"- Redirect the discussion toward your specialty"
        )
    return (
        f"STYLE: You AGREE with {prev_speaker} and BUILD on it:\n"
        f"- Add a NEW insight they didn't mention\n"
        f"- Extend their idea in a new direction"
    )


def build_user_message(
    agent: Agent,
    recent_chat: str,
    mission: str,
    prev_speaker: Optional[str],
    graph_findings: Optional[str] = None,
) -> str:
    """Build the user-role message sent to the LLM."""
    if prev_speaker and prev_speaker != agent.name and prev_speaker != "FOUNDER":
        style = build_style_instruction(agent, prev_speaker)
        msg = (
            f"LIVE TEAM MEETING - Your turn to speak.\n\n"
            f"RECENT DISCUSSION:\n{recent_chat}\n\n"
            f"{style}\n\n"
            f"=== CRITICAL RULES (MUST FOLLOW) ===\n"
            f'1. YOU ARE {agent.name.upper()} - Never speak as another person or quote what others "would say"\n'
            f"2. DO NOT REPEAT phrases others just said - use completely different wording\n"
            f"3. ADVANCE the discussion - raise a NEW point, question, or angle not yet discussed\n"
            f"4. Focus on YOUR specialty: {agent.focus}\n"
            f"5. Keep response under 80 words - be concise\n"
            f"6. CRITICAL: If you need to verify a fact online, type: [SEARCH: your query]\n\n"
            f"Your task: {mission}\n\n"
            f"Respond as {agent.name} only:"
        )
    else:
        msg = (
            f"You are {agent.name}, STARTING a team meeting discussion.\n\n"
            f"Previous context: {recent_chat}\n\n"
            f"=== YOUR INSTRUCTIONS ===\n"
            f"1. Open casually and introduce the topic briefly\n"
            f"2. Share ONE specific observation from the papers\n"
            f"3. End with a question to spark discussion\n"
            f"4. Keep it under 80 words\n\n"
            f"Your specialty: {agent.focus}\n"
            f"Your task: {mission}\n\n"
            f"Respond as {agent.name} only:"
        )

    if graph_findings:
        msg += (
            f"\n\nHIDDEN CONNECTIONS (KNOWLEDGE HYPERGRAPH):\n"
            f"{graph_findings}\n"
            f"Use these links to propose creative cross-paper insights if relevant.\n"
        )

    return msg


# ---------------------------------------------------------------------------
# LLM call with retry
# ---------------------------------------------------------------------------


def call_llm_with_retry(
    client: openai.OpenAI,
    config: Config,
    system_content: str,
    user_content: str,
    max_retries: Optional[int] = None,
    log_failures: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """Call the LLM with retry logic.

    Returns (content, finish_reason) or (None, None) on total failure.
    """
    retries = max_retries if max_retries is not None else config.max_retries
    poll_interval_s = 0.5

    for attempt in range(retries):
        try:
            result: dict[str, object] = {}
            error: dict[str, Exception] = {}
            done = threading.Event()

            def _request_worker() -> None:
                try:
                    result["response"] = client.chat.completions.create(
                        model=config.model_name,
                        messages=[
                            {"role": "system", "content": system_content},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=config.temperature,
                        max_tokens=config.max_tokens,
                    )
                except Exception as exc:  # pragma: no cover - passthrough for upstream handlers
                    error["exc"] = exc
                finally:
                    done.set()

            thread = threading.Thread(target=_request_worker, daemon=True)
            thread.start()

            waited_s = 0.0
            while not done.wait(timeout=poll_interval_s):
                waited_s += poll_interval_s
                if waited_s >= float(config.timeout):
                    raise TimeoutError(f"LLM request exceeded {config.timeout:.0f}s")

            thread.join(timeout=0.1)
            if "exc" in error:
                raise error["exc"]

            response = result.get("response")
            if response is None:
                raise RuntimeError("LLM call failed without response payload")
            content = response.choices[0].message.content.strip()
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            return content, finish_reason

        except TimeoutError:
            if log_failures:
                log.warning("Timeout (attempt %d/%d)", attempt + 1, retries)
            if attempt < retries - 1:
                time.sleep(2)
            else:
                if log_failures:
                    log.error("LLM request timed out after %d retries. Check LM Studio.", retries)
                return None, None

        except openai.APITimeoutError:
            if log_failures:
                log.warning("API timeout (attempt %d/%d)", attempt + 1, retries)
            if attempt < retries - 1:
                time.sleep(2)
            else:
                if log_failures:
                    log.error("LLM API timed out after %d retries.", retries)
                return None, None

        except openai.APIConnectionError:
            if log_failures:
                log.warning("Connection lost (attempt %d/%d)", attempt + 1, retries)
            if attempt < retries - 1:
                time.sleep(3)
            else:
                if log_failures:
                    log.error("Connection failed after %d retries. Is LM Studio running?", retries)
                return None, None

        except openai.APIError as e:
            if log_failures:
                log.error("API error: %s", e)
            if attempt < retries - 1:
                time.sleep(2)
            else:
                return None, None

        except Exception as e:
            if log_failures:
                log.exception("Unexpected LLM error: %s", e)
            return None, None

    return None, None


# ---------------------------------------------------------------------------
# Post-processing pipeline
# ---------------------------------------------------------------------------


def fix_repeated_intro(
    client: openai.OpenAI,
    config: Config,
    agent: Agent,
    content: str,
    context_block: str,
) -> str:
    """Re-generate if James is repeating his opening-meeting template."""
    if not detect_repeated_intro(content):
        return content

    corrected, _ = call_llm_with_retry(
        client,
        config,
        system_content=f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}",
        user_content=(
            "You are in mid-meeting, not opening the session. "
            "Do NOT use intro phrases like 'Hey team' or restate the topic. "
            "React to the previous speaker by name in the first sentence, "
            "add one new concrete paper-grounded point, and end with a question. "
            "Keep under 80 words."
        ),
        max_retries=1,
    )
    return corrected if corrected else content


def refine_response(
    client: openai.OpenAI,
    config: Config,
    agent: Agent,
    content: str,
    context_block: str,
    metrics_tracker=None,
) -> str:
    """Recursive critique + revise loop for self-reflection."""
    if not config.recursive_intellect or config.recursive_depth <= 0 or not content:
        return content

    for _ in range(config.recursive_depth):
        pre_critique_text = content

        # Critique pass
        critique_text, _ = call_llm_with_retry(
            client,
            config,
            system_content=f"You are a strict research editor for {agent.name}.",
            user_content=(
                "Review this draft and return a compact critique with exactly 3 bullets: "
                "(1) factual grounding to provided papers, (2) novelty vs prior turns, "
                "(3) clarity under 80 words.\n\n"
                f"DRAFT:\n{content}\n\n"
                "If there are no issues, still return 3 bullets and say what is strong."
            ),
            max_retries=1,
        )

        if not critique_text:
            break

        # Revision pass
        revised, _ = call_llm_with_retry(
            client,
            config,
            system_content=f"{agent.soul}\n\n### RESEARCH DATABASE\n{context_block}",
            user_content=(
                f"Revise this response as {agent.name} using critique below. "
                "Keep it under 80 words, add one concrete paper-grounded point, "
                "avoid repetition, and respond in first person only.\n\n"
                f"ORIGINAL:\n{content}\n\n"
                f"CRITIQUE:\n{critique_text}"
            ),
            max_retries=1,
        )

        content = revised if revised else content

        if metrics_tracker is not None:
            metrics_tracker.record_critique(pre_critique_text, content)

    return content


def handle_truncation(
    client: openai.OpenAI,
    config: Config,
    agent: Agent,
    content: str,
    finish_reason: Optional[str],
) -> str:
    """Attempt to complete a truncated response."""
    is_truncated = finish_reason == "length" or (
        content and not content.endswith((".", "!", "?", '"', "'", ")")) and len(content) > 50
    )

    if not is_truncated:
        return content

    log.debug("Attempting truncation completion for %d-char response", len(content))
    try:
        cont_text, _ = call_llm_with_retry(
            client,
            config,
            system_content=f"{agent.soul}",
            user_content=f"Complete this thought in ONE sentence. Keep it brief:\n\n{content}",
            max_retries=1,
        )
        if cont_text and not cont_text.startswith(content[:20]):
            if not cont_text[0].isupper():
                return content + " " + cont_text
            else:
                return complete_truncated(content)
    except Exception:
        log.debug("Truncation completion LLM call failed; using heuristic")

    return complete_truncated(content)


# ---------------------------------------------------------------------------
# Wrap-up instructions
# ---------------------------------------------------------------------------


def get_wrap_up_instruction(agent: Agent, topic: str) -> str:
    """Get wrap-up phase instructions for each agent to close the meeting naturally."""
    wrap_up_instructions = {
        "James": (
            f"WRAP-UP TIME: You are closing the meeting. As lead scientist:\n"
            f"- Summarize the KEY TAKEAWAY about '{topic}' from today's discussion\n"
            f"- Mention 1-2 specific insights from your colleagues that stood out\n"
            f"- Suggest ONE concrete next step or action item for the team\n"
            f"- End with something like 'Good discussion today' or 'Let's pick this up next time'\n"
            f"Keep it under 80 words - this is a quick closing summary."
        ),
        "Jasmine": (
            f"WRAP-UP TIME: Give your closing thoughts on '{topic}':\n"
            f"- State your MAIN CONCERN or practical challenge going forward\n"
            f"- Acknowledge if any colleague made a good point about feasibility\n"
            f"- Mention what you'd need to see before moving forward\n"
            f"Keep it under 60 words - be direct and practical as always."
        ),
        "Luca": (
            f"WRAP-UP TIME: Give your closing synthesis on '{topic}':\n"
            f"- Find the COMMON GROUND between what everyone said\n"
            f"- Highlight how different perspectives complemented each other\n"
            f"- Express optimism about where the research is heading\n"
            f"Keep it under 60 words - stay diplomatic and unifying."
        ),
        "Elena": (
            f"WRAP-UP TIME: Give your final assessment of '{topic}':\n"
            f"- State the most important MATHEMATICAL or THEORETICAL point established\n"
            f"- Note any concerns about rigor that still need addressing\n"
            f"- Acknowledge good work from colleagues if warranted\n"
            f"Keep it under 60 words - maintain your standards but be collegial."
        ),
    }
    return wrap_up_instructions.get(agent.name, f"Provide your closing thoughts on '{topic}' in under 60 words.")
