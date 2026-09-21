"""Provider-agnostic AI layer.

One entry point (``client.generate_json``) that reaches OpenRouter first and
falls back to Gemini, so a single provider being rate limited never breaks a
feature. New AI features (ATS, resume, generic text) build on this instead of
calling a provider directly.
"""
