import random
import time


RESPONSES = {
    "docker": "Docker packages the app and dependencies so the same image can run locally or in production.",
    "deploy": "Deployment is the path from local code to a public, observable service that users can reach.",
    "health": "The agent is healthy. Liveness and readiness checks are separate so platforms can restart or drain safely.",
    "redis": "Redis stores shared state outside the process, which lets multiple agent instances stay stateless.",
    "default": "Mock answer from the production agent. Swap this function for a real LLM client when an API key is available.",
}


def ask(question: str, history: list[dict] | None = None, delay: float = 0.05) -> str:
    time.sleep(delay + random.uniform(0, 0.02))
    lowered = question.lower()
    for keyword, answer in RESPONSES.items():
        if keyword != "default" and keyword in lowered:
            return answer
    if history and len(history) > 1:
        return f"{RESPONSES['default']} I also found {len(history)} prior messages in your conversation."
    return RESPONSES["default"]
