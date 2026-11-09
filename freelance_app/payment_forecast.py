"""
Late-payment prediction: a small machine-learning model (scikit-learn).

THE QUESTION:  "Will this unpaid invoice be paid LATE?"   (yes / no, with a probability)

HOW IT LEARNS
  1. Look at the freelancer's past invoices whose result is known:
        paid on time -> label 0      paid late, or still unpaid after the due date -> label 1
  2. For each one, describe what was known WHEN IT WAS ISSUED (the "features"):
        how often this client paid earlier invoices late, how many days late on average,
        how many earlier invoices there are, the invoice size and the payment term.
        (The client's country and name are deliberately NOT used: when tested, the country added about
        one point of accuracy, which is not worth judging clients by where they live.)
  3. A Logistic Regression model learns which of those clues go with late payment.
  4. We then describe every unpaid invoice that is not due yet in the same way and ask for a probability.

IMPORTANT HONEST RULES
  * Only each freelancer's OWN invoices are used (every query filters by the user).
  * Features use only what was known at the time ("time-aware"), so the model never peeks at the answer.
  * With too little history the page says "not enough history" instead of guessing.
  * The accuracy shown is measured on past invoices (cross-validation) and is compared with a
    "guess the most common answer" baseline.  On a small history it can be no better than that.
"""
import math
from datetime import timedelta

from django.utils import timezone

from .models import Invoice

# The clues (features) given to the model, in this fixed order
FEATURES = ['prev_late_rate', 'prev_avg_days_late', 'prev_count', 'log_amount', 'term_days']

# One plain-English sentence per clue that can raise the risk.
# (prev_count is left out: "more history" does not say anything simple about risk.)
REASONS = {
    'prev_late_rate': 'This client often paid earlier invoices late',
    'prev_avg_days_late': 'Earlier invoices were paid many days late',
    'log_amount': 'Large invoice amount',
    'term_days': 'Long payment term',
}

MIN_SAMPLES = 20        # at least this many invoices with a known result
MIN_PER_CLASS = 5       # and at least this many late AND this many on-time
HIGH_RISK = 0.65        # probability of paying late at or above this -> "High"
MEDIUM_RISK = 0.35      # at or above this -> "Medium", below -> "Low"


# ---------------------------------------------------------------------
# 1. What happened to an invoice?
# ---------------------------------------------------------------------
def invoices_of(user):
    """All invoices of this user, and nobody else's."""
    return Invoice.objects.filter(project__client__owner=user).select_related('project__client')


def final_outcome(invoice, today):
    """(paid_late, days_late) if the result is known today, otherwise None."""
    if invoice.status == 'paid' and invoice.paid_date:
        days = (invoice.paid_date - invoice.due_date).days
        return days > 0, max(0, days)
    if invoice.status == 'sent' and invoice.due_date < today:
        return True, (today - invoice.due_date).days          # still unpaid after the due date
    return None                                               # drafts, or not due yet


def outcome_as_of(invoice, as_of):
    """What was known about this invoice on the day `as_of`?  (paid_late, days_late) or None."""
    if invoice.status == 'draft' or invoice.issue_date >= as_of:
        return None
    if invoice.status == 'paid' and invoice.paid_date and invoice.paid_date < as_of:
        days = (invoice.paid_date - invoice.due_date).days
        return days > 0, max(0, days)
    if invoice.due_date < as_of:                              # not paid yet on that day, and already past due
        return True, (as_of - invoice.due_date).days
    return None


# ---------------------------------------------------------------------
# 2. Turn an invoice into numbers (the features)
# ---------------------------------------------------------------------
def history_features(other_invoices, as_of):
    """(late rate, average days late, count) of the client's EARLIER invoices, as known on `as_of`."""
    known = [o for o in (outcome_as_of(inv, as_of) for inv in other_invoices) if o]
    count = len(known)
    late = sum(1 for was_late, _ in known if was_late)
    late_rate = (late + 1) / (count + 2)                      # smoothed: a new client starts at 0.5, not 0 or 1
    avg_days = min(60.0, sum(days for _, days in known) / count) if count else 0.0
    return late_rate, avg_days, count


def make_row(invoice, client_invoices, as_of):
    others = [j for j in client_invoices if j.pk != invoice.pk]
    late_rate, avg_days, count = history_features(others, as_of)
    term_days = max(0, (invoice.due_date - invoice.issue_date).days)
    amount = max(1.0, float(invoice.total()))
    return [late_rate, avg_days, float(count), math.log10(amount), float(term_days)]


def build_dataset(user, today=None):
    """
    Returns (X, y, open_items):
      X, y        training rows and labels (1 = paid late) for invoices whose result is known
      open_items  [(invoice, features)] for sent invoices that are not due yet (the ones to predict)
    """
    today = today or timezone.localdate()
    by_client = {}
    for invoice in invoices_of(user):
        by_client.setdefault(invoice.project.client_id, []).append(invoice)

    X, y, open_items = [], [], []
    for client_invoices in by_client.values():
        for invoice in client_invoices:
            outcome = final_outcome(invoice, today)
            if outcome is not None:
                X.append(make_row(invoice, client_invoices, as_of=invoice.issue_date))   # what was known at issue time
                y.append(1 if outcome[0] else 0)
            elif invoice.status == 'sent':
                open_items.append((invoice, make_row(invoice, client_invoices, as_of=today)))
    return X, y, open_items


# ---------------------------------------------------------------------
# 3. The model
# ---------------------------------------------------------------------
def make_model():
    # scikit-learn is imported here (not at the top) so the rest of the site still starts without it
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(class_weight='balanced', max_iter=1000))


def measure_accuracy(X, y):
    """
    Cross-validation: train on part of the past, test on the rest.  Returns (accuracy, baseline).
    It is repeated 5 times with different splits (25 tests in all), so one lucky split cannot flatter the result.
    """
    from sklearn.model_selection import RepeatedStratifiedKFold, cross_val_score
    minority = min(sum(y), len(y) - sum(y))
    folds = RepeatedStratifiedKFold(n_splits=min(5, minority), n_repeats=5, random_state=0)
    accuracy = float(cross_val_score(make_model(), X, y, cv=folds, scoring='accuracy').mean())
    baseline = max(sum(y), len(y) - sum(y)) / len(y)           # always answering the most common result
    return accuracy, baseline


def risk_level(probability):
    if probability >= HIGH_RISK:
        return 'High'
    if probability >= MEDIUM_RISK:
        return 'Medium'
    return 'Low'


def main_reason(model, features):
    """The clue that pushes this invoice's risk up the most, as a plain sentence."""
    scaler = model.named_steps['standardscaler']
    classifier = model.named_steps['logisticregression']
    pushes = classifier.coef_[0] * scaler.transform([features])[0]
    for index in sorted(range(len(FEATURES)), key=lambda i: pushes[i], reverse=True):
        if pushes[index] <= 0.1:
            break
        if FEATURES[index] in REASONS:
            return REASONS[FEATURES[index]]
    return 'No warning signs in the data'


# ---------------------------------------------------------------------
# 4. Everything the page needs
# ---------------------------------------------------------------------
def build_forecast(user, today=None):
    today = today or timezone.localdate()
    X, y, open_items = build_dataset(user, today)
    late = sum(y)
    result = {
        'ready': False, 'message': '',
        'samples': len(y), 'late': late, 'on_time': len(y) - late,
        'accuracy': None, 'baseline': None, 'rows': [],
        'min_samples': MIN_SAMPLES, 'min_per_class': MIN_PER_CLASS,
    }

    if len(y) < MIN_SAMPLES:
        result['message'] = (f'Not enough history yet. The model needs at least {MIN_SAMPLES} invoices '
                             f'with a known result (paid, or overdue). You have {len(y)}.')
        return result
    if late < MIN_PER_CLASS or len(y) - late < MIN_PER_CLASS:
        result['message'] = (f'The model needs at least {MIN_PER_CLASS} late and {MIN_PER_CLASS} on-time examples '
                             f'to learn the difference. You have {late} late and {len(y) - late} on time.')
        return result

    model = make_model()
    model.fit(X, y)
    result['accuracy'], result['baseline'] = measure_accuracy(X, y)
    result['ready'] = True

    if open_items:
        probabilities = model.predict_proba([features for _, features in open_items])[:, 1]
        for (invoice, features), probability in zip(open_items, probabilities):
            risk = risk_level(float(probability))
            result['rows'].append({
                'invoice': invoice,
                'client': invoice.project.client,
                'total': invoice.total(),
                'probability': float(probability),
                'percent': round(float(probability) * 100),
                'risk': risk,
                'reliability': invoice.project.client.reliability_label(),
                # a reason only makes sense for an invoice that is actually flagged
                'reason': main_reason(model, features) if risk != 'Low' else 'No strong warning signs',
            })
        result['rows'].sort(key=lambda row: row['probability'], reverse=True)
    return result