"""Lazy, configurable OpenAI and Gemini chat model construction."""

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from enterprise_os.config import Settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when the selected model provider is missing valid configuration."""


class LLMCallError(RuntimeError):
    """Raised when an LLM request fails or returns an invalid structured result."""


class ChatModelProvider:
    """Create and reuse one configured provider client for the application."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: BaseChatModel | None = None

    def get_model(self) -> BaseChatModel:
        """Return the configured model, creating it lazily on the first request."""
        if self._model is not None:
            return self._model

        if self._settings.llm_provider == "openai":
            api_key = self._settings.openai_api_key
            model_name = self._settings.openai_model
            if api_key is None or not api_key.get_secret_value().strip():
                raise LLMConfigurationError(
                    "Set OPENAI_API_KEY in the repository .env file to use OpenAI."
                )
            if model_name is None or not model_name.strip():
                raise LLMConfigurationError(
                    "Set OPENAI_MODEL in the repository .env file to use OpenAI."
                )
            try:
                from langchain_openai import ChatOpenAI

                self._model = ChatOpenAI(
                    model=model_name.strip(),
                    api_key=api_key.get_secret_value(),
                    timeout=self._settings.llm_timeout_seconds,
                    max_retries=0,
                )
            except Exception as exc:
                logger.error("OpenAI client initialization failed (%s).", type(exc).__name__)
                raise LLMConfigurationError(
                    "The configured OpenAI client could not be initialized."
                ) from exc
            return self._model

        api_key = self._settings.gemini_api_key
        model_name = self._settings.gemini_model
        if api_key is None or not api_key.get_secret_value().strip():
            raise LLMConfigurationError(
                "Set GEMINI_API_KEY in the repository .env file to use Gemini."
            )
        if model_name is None or not model_name.strip():
            raise LLMConfigurationError(
                "Set GEMINI_MODEL in the repository .env file to use Gemini."
            )
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self._model = ChatGoogleGenerativeAI(
                model=model_name.strip(),
                api_key=api_key.get_secret_value(),
            )
        except Exception as exc:
            logger.error("Gemini client initialization failed (%s).", type(exc).__name__)
            raise LLMConfigurationError(
                "The configured Gemini client could not be initialized."
            ) from exc
        return self._model
