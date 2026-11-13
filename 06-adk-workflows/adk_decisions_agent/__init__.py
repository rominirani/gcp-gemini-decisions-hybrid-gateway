"""ADK 2.0 Workflow combining deterministic Python rules, Gemini Decision 1, and Gemini 3.8 Flash."""

from dotenv import load_dotenv

load_dotenv()

from . import agent  # noqa: E402, F401
