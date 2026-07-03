import os
from google import genai
# pyrefly: ignore [missing-import]
from google.genai import errors
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class LLMClient:
    """
    A shared client wrapper for the Google Gen AI SDK.
    Other agents import this client to call the Gemini API,
    so that API keys and configurations are managed centrally.
    """
    def __init__(self, api_key: str = None, default_model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.default_model = default_model
        
        # If API key is not present, we will still initialize genai.Client()
        # because the SDK can fall back to environment variable GEMINI_API_KEY.
        # However, we can handle initialization errors gracefully.
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = genai.Client()

    def is_configured(self) -> bool:
        """Checks if the Gemini API Key is configured."""
        return bool(self.api_key or os.getenv("GEMINI_API_KEY"))

    def generate_content(self, message: str, model: str = None, **kwargs) -> str:
        """
        Sends a generate content request to the Gemini API.
        """
        if not self.is_configured():
            raise ValueError(
                "Gemini API key is not configured. Please set the GEMINI_API_KEY "
                "environment variable."
            )
            
        target_model = model or self.default_model
        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=message,
                **kwargs
            )
            return response.text
        except errors.APIError as e:
            raise e

# Shared singleton instance
_llm_client_instance = None

def get_llm_client() -> LLMClient:
    """Returns the shared LLMClient singleton instance."""
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LLMClient()
    return _llm_client_instance
