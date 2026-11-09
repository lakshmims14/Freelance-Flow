from decimal import Decimal

from django import template

register = template.Library()

ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
        'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen',
        'Eighteen', 'Nineteen']
TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


@register.filter
def inr(value):
    """Show a number as Indian rupees with lakh/crore commas: 141600 -> ₹1,41,600.00"""
    try:
        number = Decimal(value).quantize(Decimal('0.01'))
    except Exception:
        return value
    sign = '-' if number < 0 else ''
    whole, fraction = f'{abs(number):.2f}'.split('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ','.join(groups + [tail])
    return f'{sign}₹{whole}.{fraction}'


@register.filter
def inr_pdf(value):
    """Same as inr, but writes 'Rs.' because the standard PDF fonts cannot draw the ₹ sign."""
    return str(inr(value)).replace('₹', 'Rs. ')


def two_digits(n):
    if n < 20:
        return ONES[n]
    return TENS[n // 10] + (' ' + ONES[n % 10] if n % 10 else '')


def three_digits(n):
    words = ''
    if n >= 100:
        words = ONES[n // 100] + ' Hundred'
        n = n % 100
        if n:
            words += ' '
    return words + two_digits(n)


@register.filter
def rupees_words(value):
    """118000 -> 'Rupees One Lakh Eighteen Thousand Only'"""
    try:
        amount = Decimal(value).quantize(Decimal('0.01'))
    except Exception:
        return ''
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    crore, rest = divmod(rupees, 10000000)
    lakh, rest = divmod(rest, 100000)
    thousand, rest = divmod(rest, 1000)

    parts = []
    if crore:
        parts.append(three_digits(crore) + ' Crore')
    if lakh:
        parts.append(two_digits(lakh) + ' Lakh')
    if thousand:
        parts.append(two_digits(thousand) + ' Thousand')
    if rest:
        parts.append(three_digits(rest))

    text = 'Rupees ' + (' '.join(parts) or 'Zero')
    if paise:
        text += ' and ' + two_digits(paise) + ' Paise'
    return text + ' Only'