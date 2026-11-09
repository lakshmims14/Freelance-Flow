"""
The OFFLINE assistant: no internet, no API key, no cost.

It reads the question, spots keywords (overdue, GST, risky...), calls the data
tools in assistant_tools.py and writes the answer in plain English.
It is also the safety net: if Gemini fails, this answers instead.
"""
import calendar
import re

from django.utils import timezone

from . import assistant_tools as tools
from .models import Client
from .templatetags.ff_tags import inr

HELP_TEXT = (
    "I can answer questions about your own data. Try:\n"
    "• Which invoices are overdue?\n"
    "• How much GST did I collect this month?\n"
    "• GST for October\n"
    "• GST for this financial year\n"
    "• Which clients are risky?\n"
    "• How much money have I received?\n"
    "• What deadlines are coming up?\n"
    "• Tell me about Aarav"
)

# month name or 3-letter short name -> number   ('january' -> 1, 'jan' -> 1)
MONTHS = {}
for number in range(1, 13):
    MONTHS[calendar.month_name[number].lower()] = number
    MONTHS[calendar.month_abbr[number].lower()] = number


def money(value):
    return inr(value)


def plural(count, word):
    return f'{count} {word}' if count == 1 else f'{count} {word}s'


def which_month(words, text, today):
    """Work out (year, month) from phrases like 'this month', 'last month', 'october', 'oct 2025'."""
    if 'month' in words and (words & {'last', 'previous'}):
        if today.month > 1:
            return today.year, today.month - 1
        return today.year - 1, 12
    for word in words:
        if word in MONTHS:
            month = MONTHS[word]
            years = re.findall(r'\b(20\d\d)\b', text)
            if years:
                return int(years[0]), month
            # no year given: use the most recent such month that is not in the future
            return (today.year if month <= today.month else today.year - 1), month
    return today.year, today.month


def answer_offline(user, question):
    text = question.lower()
    words = set(re.findall(r"[a-z']+", text))
    today = timezone.localdate()

    # 1. Is the question about one of this user's clients?  ("Tell me about Aarav")
    for client in Client.objects.filter(owner=user):
        name_parts = [client.name.lower()] + [p for p in re.findall(r'[a-z]+', client.name.lower()) if len(p) >= 3]
        if any(re.search(r'\b' + re.escape(part) + r'\b', text) for part in name_parts):
            return client_answer(user, client.name)

    # 2. Otherwise decide by keywords (the order matters)
    if words & {'gst', 'tax'}:
        return gst_answer(user, words, text, today)
    if words & {'risky', 'risk', 'reliable', 'reliability', 'score', 'worst', 'trust'}:
        return risk_answer(user)
    if (words & {'overdue', 'late', 'unpaid', 'outstanding', 'owe', 'owes'}
            or re.search(r"(not|n't) paid|haven't paid", text)):
        return overdue_answer(user)
    if words & {'deadline', 'deadlines', 'upcoming', 'due'}:
        return deadline_answer(user)
    if words & {'earn', 'earned', 'income', 'revenue', 'received', 'paid', 'awaiting', 'pending', 'money', 'total', 'collected'}:
        return money_answer(user)
    return HELP_TEXT


# ---------------------------------------------------------------------
# One small function per kind of answer
# ---------------------------------------------------------------------
def overdue_answer(user):
    rows = tools.overdue_invoices(user)
    if not rows:
        return 'Nothing is overdue. 🎉'
    total = sum(r['total'] for r in rows)
    lines = [f'You have {plural(len(rows), "overdue invoice")}, worth {money(total)} in total:']
    for r in rows:
        lines.append(f"• {r['number']} - {r['client']} - {money(r['total'])} - "
                     f"{plural(r['days_late'], 'day')} late ({plural(r['reminders_sent'], 'reminder')} sent)")
    return '\n'.join(lines)


def money_answer(user):
    m = tools.money_summary(user)
    return (f"Received (paid, incl. GST): {money(m['received'])}\n"
            f"Awaiting payment: {money(m['awaiting_payment'])}, of which {money(m['overdue'])} is overdue "
            f"({plural(m['overdue_count'], 'invoice')})")


def gst_answer(user, words, text, today):
    if words & {'year', 'fy', 'financial'}:
        start = tools.financial_year_start(today)
        if 'last' in words or 'previous' in words:
            start -= 1
        data = tools.gst_for_financial_year(user, start)
        label = data['period']
    else:
        year, month = which_month(words, text, today)
        data = tools.gst_for_month(user, year, month)
        label = f'{calendar.month_name[month]} {year}'
    if data['invoice_count'] == 0:
        return f'No sent or paid invoices were issued in {label}, so there is no GST to report.'
    return (f"GST for {label}: {money(data['gst'])} across {plural(data['invoice_count'], 'invoice')}\n"
            f"Taxable amount: {money(data['taxable'])}  |  Total with GST: {money(data['total'])}\n"
            "(Counts Sent and Paid invoices by issue date; drafts are not included.)")


def risk_answer(user):
    rows = tools.client_scores(user)
    if not rows:
        return 'No client has payment history yet, so there are no reliability scores.'
    risky = [r for r in rows if r['label'] == 'Risky']
    if risky:
        lines = [f'{plural(len(risky), "client")} marked Risky:']
        shown = risky
    else:
        lines = ['No client is marked Risky. The lowest scores are:']
        shown = rows[:3]
    for r in shown:
        lines.append(f"• {r['name']} ({r['company']}) - score {r['score']}/100, {r['label']}")
    return '\n'.join(lines)


def deadline_answer(user):
    data = tools.deadlines(user)
    if not data['upcoming'] and not data['past_deadline']:
        return 'No open project has a deadline in the next 14 days, and none is past its deadline.'
    lines = []
    if data['upcoming']:
        lines.append('Due in the next 14 days:')
        for r in data['upcoming']:
            lines.append(f"• {r['project']} ({r['client']}) - {r['deadline']}, {plural(r['days_left'], 'day')} left")
    if data['past_deadline']:
        lines.append('Past their deadline:')
        for r in data['past_deadline']:
            lines.append(f"• {r['project']} ({r['client']}) - was due {r['deadline']}")
    return '\n'.join(lines)


def client_answer(user, name):
    c = tools.client_summary(user, name)
    if not c['found']:
        return f'I could not find a client called "{name}".'
    if c['reliability_score'] is None:
        reliability = 'No payment history yet'
    else:
        reliability = f"{c['reliability_label']} ({c['reliability_score']}/100)"
    place = f"{c['company']}, {c['country']}" if c['company'] else c['country']
    return (f"{c['name']} ({place})\n"
            f"Reliability: {reliability}\n"
            f"Projects: {c['projects']}  |  Paid so far: {money(c['paid_total'])}  |  "
            f"Awaiting: {money(c['awaiting_total'])}\n"
            f"Overdue invoices: {c['overdue_invoices']}")