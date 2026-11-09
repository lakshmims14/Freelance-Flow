"""
Read-only "tools" that the assistant uses to look at the data.

SAFETY RULE: every function here takes the logged-in `user` and filters by it
(owner=user / project__client__owner=user), so the assistant can only ever see
that user's own data.  The AI never chooses the user: our code passes it in.

Money comes back as plain numbers (float) in rupees, including GST where noted.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from .models import Client, Invoice, Project


def _money(value):
    """Decimal -> float with two decimals (so it can be sent to the AI as JSON)."""
    return float(Decimal(value).quantize(Decimal('0.01')))


def _invoices(user):
    """All invoices of this user, and nobody else's."""
    return Invoice.objects.filter(project__client__owner=user).select_related('project__client')


def financial_year_start(day):
    """The Indian financial year runs April to March: 5 Nov 2026 belongs to the year starting 2026."""
    return day.year if day.month >= 4 else day.year - 1


# ---------------------------------------------------------------------
# 1. Money
# ---------------------------------------------------------------------
def money_summary(user):
    """Received, awaiting payment and overdue totals (all include GST)."""
    invoices = list(_invoices(user))
    received = sum((i.total() for i in invoices if i.status == 'paid'), Decimal('0'))
    awaiting = sum((i.total() for i in invoices if i.status == 'sent'), Decimal('0'))   # includes overdue ones
    overdue = [i for i in invoices if i.is_overdue()]
    overdue_total = sum((i.total() for i in overdue), Decimal('0'))
    return {
        'received': _money(received),
        'awaiting_payment': _money(awaiting),
        'overdue': _money(overdue_total),
        'overdue_count': len(overdue),
    }


def overdue_invoices(user):
    """Sent invoices whose due date has passed, the most late first."""
    today = timezone.localdate()
    rows = []
    for inv in _invoices(user):
        if inv.is_overdue():
            rows.append({
                'number': inv.number,
                'client': inv.project.client.name,
                'total': _money(inv.total()),
                'due_date': inv.due_date.isoformat(),
                'days_late': (today - inv.due_date).days,
                'reminders_sent': inv.reminder_count,
            })
    rows.sort(key=lambda r: r['days_late'], reverse=True)
    return rows


# ---------------------------------------------------------------------
# 2. GST (Sent and Paid invoices only; drafts are not counted)
# ---------------------------------------------------------------------
def _gst_totals(invoices):
    taxable = sum((i.amount for i in invoices), Decimal('0'))
    gst = sum((i.tax() for i in invoices), Decimal('0'))
    total = sum((i.total() for i in invoices), Decimal('0'))
    return {'invoice_count': len(invoices), 'taxable': _money(taxable), 'gst': _money(gst), 'total': _money(total)}


def gst_for_month(user, year, month):
    """GST on invoices issued in one calendar month."""
    invoices = list(_invoices(user).filter(status__in=['sent', 'paid'],
                                           issue_date__year=year, issue_date__month=month))
    result = _gst_totals(invoices)
    result['period'] = f'{year}-{month:02d}'
    return result


def gst_for_financial_year(user, start_year=None):
    """GST for one Indian financial year (April of start_year to March of the next year)."""
    if start_year is None:
        start_year = financial_year_start(timezone.localdate())
    first_day = date(start_year, 4, 1)
    last_day = date(start_year + 1, 3, 31)
    invoices = list(_invoices(user).filter(status__in=['sent', 'paid'],
                                           issue_date__gte=first_day, issue_date__lte=last_day))
    result = _gst_totals(invoices)
    result['period'] = f'FY {start_year}-{(start_year + 1) % 100:02d}'
    return result


# ---------------------------------------------------------------------
# 3. Clients
# ---------------------------------------------------------------------
def client_scores(user):
    """Every client that has payment history, the lowest (worst) score first."""
    rows = []
    for client in Client.objects.filter(owner=user):
        score = client.reliability_score()
        if score is not None:
            rows.append({
                'name': client.name,
                'company': client.company,
                'score': score,
                'label': client.reliability_label(),
            })
    rows.sort(key=lambda r: r['score'])
    return rows


def client_summary(user, name):
    """Everything about one client, found by (part of) the name."""
    client = Client.objects.filter(owner=user, name__icontains=name.strip()).order_by('name').first()
    if client is None:
        return {'found': False}
    invoices = list(_invoices(user).filter(project__client=client))
    paid = sum((i.total() for i in invoices if i.status == 'paid'), Decimal('0'))
    awaiting = sum((i.total() for i in invoices if i.status == 'sent'), Decimal('0'))
    return {
        'found': True,
        'name': client.name,
        'company': client.company,
        'country': client.country,
        'reliability_score': client.reliability_score(),
        'reliability_label': client.reliability_label(),
        'projects': Project.objects.filter(client=client).count(),
        'paid_total': _money(paid),
        'awaiting_total': _money(awaiting),
        'overdue_invoices': sum(1 for i in invoices if i.is_overdue()),
    }


# ---------------------------------------------------------------------
# 4. Projects
# ---------------------------------------------------------------------
def deadlines(user, within_days=14):
    """Open projects due in the next few days, and open projects already past their deadline."""
    today = timezone.localdate()
    open_projects = Project.objects.filter(client__owner=user).exclude(status='completed').select_related('client')

    def row(p):
        return {'project': p.title, 'client': p.client.name,
                'deadline': p.deadline.isoformat(), 'days_left': (p.deadline - today).days}

    coming = open_projects.filter(deadline__gte=today, deadline__lte=today + timedelta(days=within_days)).order_by('deadline')
    late = open_projects.filter(deadline__lt=today).order_by('deadline')
    return {'upcoming': [row(p) for p in coming], 'past_deadline': [row(p) for p in late]}