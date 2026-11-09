"""
The GEMINI assistant: understands free-form questions.

How "tool calling" works here, in plain words:
  1. We send Gemini the question plus a list of our functions (the tools).
  2. Gemini does NOT see your database.  It replies "please run get_overdue_invoices".
  3. Our code runs that function (for the logged-in user only) and sends the result back.
  4. Gemini writes the final answer from those real numbers.
The library (google-genai) does steps 2-4 for us automatically.
"""
from django.conf import settings
from django.utils import timezone

from . import assistant_tools as tools


class AssistantUnavailable(Exception):
    """Raised when Gemini cannot be used (no key, empty answer...). The caller falls back to offline."""


def build_tools(user):
    """The functions Gemini may call.  `user` is fixed here, so Gemini can never ask for someone else's data."""

    def get_money_summary() -> dict:
        """Totals in rupees including GST: received (paid invoices), awaiting_payment (sent invoices, includes the overdue ones), overdue, overdue_count."""
        return tools.money_summary(user)

    def get_overdue_invoices() -> list:
        """Sent invoices that are past their due date: number, client, total, due_date, days_late, reminders_sent."""
        return tools.overdue_invoices(user)

    def get_gst_for_month(year: int, month: int) -> dict:
        """GST collected on Sent and Paid invoices issued in one calendar month (month is 1 to 12)."""
        return tools.gst_for_month(user, year, month)

    def get_gst_for_financial_year(start_year: int) -> dict:
        """GST for the Indian financial year April of start_year to March of start_year + 1. For FY 2026-27 pass 2026."""
        return tools.gst_for_financial_year(user, start_year)

    def get_client_scores() -> list:
        """Payment reliability score (0 to 100, higher is better) and label (Reliable, Average, Risky) for every client with history, worst first."""
        return tools.client_scores(user)

    def get_client_details(name: str) -> dict:
        """Details of one client found by name: reliability, projects, paid and awaiting totals, overdue invoice count."""
        return tools.client_summary(user, name)

    def get_deadlines() -> dict:
        """Open projects due in the next 14 days (upcoming) and open projects already past their deadline (past_deadline)."""
        return tools.deadlines(user)

    return [get_money_summary, get_overdue_invoices, get_gst_for_month, get_gst_for_financial_year,
            get_client_scores, get_client_details, get_deadlines]


def system_prompt():
    return (
        "You are the assistant inside FreelanceFlow, an invoicing app for Indian freelancers. "
        f"Today is {timezone.localdate().isoformat()}. "
        "Answer ONLY from the data returned by the tools. Never invent numbers, names or dates. "
        "If the tools cannot answer a question, say so briefly. "
        "Write amounts in rupees with the rupee sign. Reply in short plain text with no markdown "
        "(no asterisks, no headings); use a simple '-' for list items."
    )


def ask_gemini(user, question, model=None):
    """Ask one Gemini model.  `model` is optional: without it the main model from settings is used."""
    model = model or settings.GEMINI_MODEL
    if not settings.GEMINI_API_KEY:
        raise AssistantUnavailable('GEMINI_API_KEY is not set')

    from google import genai          # imported here so the app still starts if the library is missing
    from google.genai import types

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=20000),          # 20 seconds, then we fall back
    )
    # A "chat" is the library's recommended way to use automatic tool calling.
    # We start a fresh chat for every question, so nothing is remembered between questions.
    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt(),
            tools=build_tools(user),                             # automatic tool calling
            temperature=0.2,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=5),
        ),
    )
    response = chat.send_message(question)
    answer = (response.text or '').strip()
    if not answer:
        raise AssistantUnavailable('Gemini returned an empty answer')
    return answer