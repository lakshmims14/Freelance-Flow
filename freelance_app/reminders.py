from django.utils import timezone

from .templatetags.ff_tags import inr_pdf


def build_reminder(invoice, tone, sender_name):
    """Write a payment reminder. Returns (subject, body).

    tone is 'polite' or 'firm'. A firm tone is only used when the invoice is overdue.
    Amounts are written as 'Rs.' because plain-text emails and Windows terminals
    do not always handle the rupee sign.
    """
    client = invoice.project.client
    total = inr_pdf(invoice.total())
    due = invoice.due_date.strftime('%d %b %Y')
    days_late = (timezone.localdate() - invoice.due_date).days
    day_word = 'day' if days_late == 1 else 'days'
    project = invoice.project.title

    # 1. Not overdue yet: a gentle heads-up
    if days_late <= 0:
        subject = f'Upcoming payment: invoice {invoice.number}'
        lines = [
            f'Hi {client.name},',
            '',
            f'I hope you are doing well. This is a quick reminder that invoice {invoice.number} '
            f'for "{project}" is due on {due}.',
            '',
            f'Amount due: {total} (including GST)',
            '',
            'If you have already arranged the payment, please ignore this message. '
            'Thank you for your business.',
            '',
            'Best regards,',
            sender_name,
        ]

    # 2. Overdue and a firm tone
    elif tone == 'firm':
        subject = f'Payment overdue: invoice {invoice.number}'
        lines = [ 
            f'Dear {client.name},',
            '',
            f'Invoice {invoice.number} for "{project}" was due on {due} and is now '
            f'{days_late} {day_word} overdue.',
            '',
            f'Amount outstanding: {total} (including GST)',
            '',
            'Please arrange the payment within the next 3 days. If there is any problem with '
            'this invoice, reply to this email right away so we can sort it out.',
            '',
            'Regards,',
            sender_name,
        ]

    # 3. Overdue and a polite tone
    else:
        subject = f'Friendly reminder: invoice {invoice.number}'
        lines = [
            f'Hi {client.name},',
            '',
            f'I hope you are doing well. I wanted to remind you that invoice {invoice.number} '
            f'for "{project}" was due on {due} ({days_late} {day_word} ago).',
            '',
            f'Amount due: {total} (including GST)',
            '',
            'If you have already made the payment, please ignore this message and accept my thanks. '
            'Otherwise, I would be grateful if you could arrange it at your earliest convenience.',
            '',
            'Best regards,',
            sender_name,
        ]

    return subject, '\n'.join(lines)