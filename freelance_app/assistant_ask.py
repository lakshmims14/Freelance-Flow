"""
One entry point for the view:  answer, source = ask_assistant(user, question)

Order of attempts:
  1. the main Gemini model            (GEMINI_MODEL)
  2. the backup Gemini model          (GEMINI_FALLBACK_MODEL), if one is set
  3. the offline assistant            (always works, no internet)

source is one of:
  'gemini'            a Gemini model answered (the main one or the backup)
  'offline'           no Gemini key is set, the offline assistant answered
  'offline-fallback'  a key is set but every Gemini model failed (busy, no internet, quota...),
                      so the offline assistant answered instead
"""
import logging

from django.conf import settings

from .assistant_gemini import ask_gemini
from .assistant_offline import answer_offline

logger = logging.getLogger(__name__)


def gemini_models_to_try():
    """The main model first, then the backup model (only if one is set and it is a different one)."""
    models = [settings.GEMINI_MODEL]
    backup = getattr(settings, 'GEMINI_FALLBACK_MODEL', '')
    if backup and backup != settings.GEMINI_MODEL:
        models.append(backup)
    return models


def ask_assistant(user, question):
    if not settings.GEMINI_API_KEY:
        return answer_offline(user, question), 'offline'

    for model in gemini_models_to_try():
        try:
            return ask_gemini(user, question, model=model), 'gemini'
        except Exception as error:       # any failure at all -> try the next model, never show an error page
            logger.warning('Gemini failed with model %s (%s: %s).', model, type(error).__name__, error)

    logger.warning('All Gemini models failed. Answering offline.')
    return answer_offline(user, question), 'offline-fallback'