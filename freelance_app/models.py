from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Client(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clients')
    name = models.CharField(max_length=100)
    company = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=60, default='India')

    def __str__(self):
        return self.name

    def reliability_score(self):
        """100 = always pays on time. Returns None if the client has no invoices."""
        delays = []
        for inv in Invoice.objects.filter(project__client=self):
            if inv.status == 'paid' and inv.paid_date:
                delays.append(max(0, (inv.paid_date - inv.due_date).days))
            elif inv.is_overdue():
                delays.append((timezone.localdate() - inv.due_date).days)
        if not delays:
            return None
        average_late = sum(delays) / len(delays)
        return max(0, round(100 - average_late * 3))

    def reliability_label(self):
        score = self.reliability_score()
        if score is None:
            return 'No history'
        if score >= 80:
            return 'Reliable'
        if score >= 50:
            return 'Average'
        return 'Risky'


class Project(models.Model):
    STATUS_CHOICES = [
        ('proposal', 'Proposal'),
        ('active', 'In progress'),
        ('on_hold', 'On hold'),
        ('completed', 'Completed'),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='proposal')
    budget = models.DecimalField(max_digits=10, decimal_places=2)
    start_date = models.DateField()
    deadline = models.DateField()

    def __str__(self):
        return self.title

    def days_left(self):
        """Days until the deadline (negative when the deadline has passed)."""
        return (self.deadline - timezone.localdate()).days

    def progress(self):
        """Percentage of tasks that are done."""
        total = self.tasks.count()
        if total == 0:
            return 0
        done = self.tasks.filter(status='done').count()
        return round(done * 100 / total)

    def is_overdue(self):
        return self.status != 'completed' and self.deadline < timezone.localdate()


class Task(models.Model):
    STATUS_CHOICES = [('todo', 'To do'), ('doing', 'In progress'), ('done', 'Done')]
    PRIORITY_CHOICES = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=140)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='todo')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    hours_estimated = models.DecimalField(max_digits=5, decimal_places=1, default=1)

    def __str__(self):
        return self.title


class Invoice(models.Model):
    STATUS_CHOICES = [('draft', 'Draft'), ('sent', 'Sent'), ('paid', 'Paid')]

    number = models.CharField(max_length=20)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='invoices')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst_percent = models.DecimalField(max_digits=4, decimal_places=1, default=18)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    paid_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    reminder_count = models.PositiveIntegerField(default=0)
    last_reminder_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        # The first time an invoice is marked Paid, record today's date.
        if self.status == 'paid' and not self.paid_date:
            self.paid_date = timezone.localdate()
        super().save(*args, **kwargs)

    def tax(self):
        return (self.amount * self.gst_percent / 100).quantize(Decimal('0.01'))

    def total(self):
        return self.amount + self.tax()

    def is_overdue(self):
        return self.status == 'sent' and self.due_date < timezone.localdate()