from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import (ClientForm, InvoiceForm, LoginForm, ProjectForm,ReminderForm,SignUpForm, TaskForm)
from .models import Client, Invoice, Project, Task
from django.http import HttpResponse
from django.template.loader import get_template
from django.utils.text import slugify
from xhtml2pdf import pisa
from django.conf import settings
from django.core.mail import EmailMessage
from .reminders import build_reminder
from .assistant_ask import ask_assistant
from .payment_forecast import build_forecast



def home(request):
    # Logged-in users skip the home page and go straight to the dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'home.html')


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()          # creates the user in the auth_user table
            login(request, user)        # logs them in straight away
            messages.success(request, 'Welcome! Your account is ready.')
            return redirect('dashboard')
    else:
        form = SignUpForm()
    return render(request, 'signup.html', {'form': form})


def user_login(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('dashboard')
    else:
        form = LoginForm()
    return render(request, 'login.html', {'form': form})


def user_logout(request):
    # Logout only happens on POST (a button), never from just opening a link
    if request.method == 'POST':
        logout(request)
        messages.success(request, 'You have been logged out.')
    return redirect('home')


# =====================================================================
# SMALL HELPERS FOR THE CHARTS
# =====================================================================
def last_months(today, how_many=6):
    """The last few (year, month) pairs, oldest first. Example: [(2026, 6), (2026, 7), ...]"""
    year, month = today.year, today.month
    result = []
    for _ in range(how_many):
        result.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return result[::-1]


def percent(part, whole):
    """part as a whole-number percentage of whole (0 when whole is 0)."""
    return round(part * 100 / whole) if whole else 0



def dashboard(request):
    today = timezone.localdate()

    # Only THIS user's data
    clients = Client.objects.filter(owner=request.user)
    projects = Project.objects.filter(client__owner=request.user)
    invoices = Invoice.objects.filter(project__client__owner=request.user).select_related('project__client')

    paid_total = sum((i.total() for i in invoices if i.status == 'paid'), Decimal('0'))
    pending_total = sum((i.total() for i in invoices if i.status == 'sent'), Decimal('0'))
    overdue_invoices = [i for i in invoices if i.is_overdue()]
    overdue_total = sum((i.total() for i in overdue_invoices), Decimal('0'))

    # Clients to watch = clients whose reliability label is "Risky"
    risky_clients = [c for c in clients if c.reliability_label() == 'Risky']

    open_projects = projects.exclude(status='completed')
    upcoming = open_projects.filter(deadline__gte=today).order_by('deadline')[:5]
    late_projects = open_projects.filter(deadline__lt=today)

    status_counts = []
    for value, label in Project.STATUS_CHOICES:
        count = projects.filter(status=value).count()
        if count:
            status_counts.append({'value': value, 'label': label, 'count': count})

    context = {
        'client_count': clients.count(),
        'active_projects': projects.filter(status='active').count(),
        'open_tasks': Task.objects.filter(project__client__owner=request.user).exclude(status='done').count(),
        'paid_total': paid_total,
        'pending_total': pending_total,
        'overdue_invoices': overdue_invoices,
        'overdue_total': overdue_total,
        'risky_clients': risky_clients,
        'upcoming': upcoming,
        'late_projects': late_projects,
        'status_counts': status_counts,
    }

    # ---- data for the charts -------------------------------------------------
    # 1. Billed per month for the last 6 months (invoices that are Sent or Paid, incl. GST)
    billed = {key: [Decimal('0'), 0] for key in last_months(today)}
    for inv in invoices:
        key = (inv.issue_date.year, inv.issue_date.month)
        if inv.status in ('sent', 'paid') and key in billed:
            billed[key][0] += inv.total()
            billed[key][1] += 1
    context['billed_chart'] = [
        {'label': date(y, m, 1).strftime('%b'), 'full': date(y, m, 1).strftime('%B %Y'),
         'value': float(amount), 'note': f'{count} invoice{"" if count == 1 else "s"}'}
        for (y, m), (amount, count) in billed.items()
    ]
    context['billed_six_months'] = sum((amount for amount, count in billed.values()), Decimal('0'))

    # 2. Where the money is: received, waiting, overdue
    waiting_total = pending_total - overdue_total
    money_total = paid_total + pending_total
    context['money_split'] = [
        {'key': 'paid', 'label': 'Received', 'amount': paid_total, 'percent': percent(paid_total, money_total)},
        {'key': 'awaiting', 'label': 'Waiting', 'amount': waiting_total, 'percent': percent(waiting_total, money_total)},
        {'key': 'overdue', 'label': 'Overdue', 'amount': overdue_total, 'percent': percent(overdue_total, money_total)},
    ]
    context['money_total'] = money_total

    # 3. Top clients by amount billed
    per_client = {}
    for inv in invoices:
        if inv.status in ('sent', 'paid'):
            client = inv.project.client
            per_client[client] = per_client.get(client, Decimal('0')) + inv.total()
    ranked = sorted(per_client.items(), key=lambda pair: pair[1], reverse=True)[:5]
    biggest = ranked[0][1] if ranked else Decimal('0')
    context['top_clients'] = [
        {'client': client, 'amount': amount, 'width': percent(amount, biggest)} for client, amount in ranked
    ]

    # 4. How many clients are Reliable / Average / Risky / without history
    labels = [c.reliability_label() for c in clients]
    context['reliability_split'] = [
        {'key': key, 'label': label, 'count': labels.count(label), 'percent': percent(labels.count(label), len(labels))}
        for key, label in [('reliable', 'Reliable'), ('average', 'Average'), ('risky', 'Risky'), ('nohistory', 'No history')]
        if labels.count(label)
    ]
    return render(request, 'dashboard.html', context)


# =====================================================================
# CLIENTS
# =====================================================================


# =====================================================================
# CLIENTS
# =====================================================================
@login_required
def client_list(request):
    clients = Client.objects.filter(owner=request.user).order_by('name')
    q = request.GET.get('q', '').strip()
    if q:
        clients = clients.filter(Q(name__icontains=q) | Q(company__icontains=q) | Q(email__icontains=q))
    return render(request, 'client_list.html', {'clients': clients})


@login_required
def client_create(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)   # don't save yet...
            client.owner = request.user        # ...first attach the logged-in user
            client.save()
            messages.success(request, 'Client added.')
            return redirect('client_detail', pk=client.pk)
    else:
        form = ClientForm()
    return render(request, 'form.html', {'form': form, 'title': 'Add client'})


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    return render(request, 'client_detail.html', {
        'client': client,
        'projects': client.projects.all(),
    })


@login_required
def client_update(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Client updated.')
            return redirect('client_detail', pk=client.pk)
    else:
        form = ClientForm(instance=client)
    return render(request, 'form.html', {'form': form, 'title': 'Edit client'})


@login_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk, owner=request.user)
    if request.method == 'POST':
        client.delete()
        messages.success(request, 'Client deleted along with their projects, tasks and invoices.')
        return redirect('client_list')
    return render(request, 'confirm_delete.html', {
        'object': client,
        'cancel_url': 'client_detail',
        'cancel_pk': client.pk,
    })


# =====================================================================
# PROJECTS
# =====================================================================
@login_required
def project_list(request):
    projects = Project.objects.filter(client__owner=request.user).select_related('client')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        projects = projects.filter(Q(title__icontains=q) | Q(client__name__icontains=q))
    if status:
        projects = projects.filter(status=status)
    return render(request, 'project_list.html', {
        'projects': projects,
        'statuses': Project.STATUS_CHOICES,
    })


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST, user=request.user)
        if form.is_valid():
            project = form.save()
            messages.success(request, 'Project created.')
            return redirect('project_detail', pk=project.pk)
    else:
        initial = {'start_date': timezone.localdate()}
        if request.GET.get('client'):          # e.g. /projects/new/?client=3
            initial['client'] = request.GET['client']
        form = ProjectForm(user=request.user, initial=initial)
    return render(request, 'form.html', {'form': form, 'title': 'New project'})


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk, client__owner=request.user)
    return render(request, 'project_detail.html', {
        'project': project,
        'tasks': project.tasks.all(),
        'invoices': project.invoices.all(),
    })


@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk, client__owner=request.user)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Project updated.')
            return redirect('project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project, user=request.user)
    return render(request, 'form.html', {'form': form, 'title': 'Edit project'})


@login_required
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk, client__owner=request.user)
    if request.method == 'POST':
        project.delete()
        messages.success(request, 'Project deleted along with its tasks and invoices.')
        return redirect('project_list')
    return render(request, 'confirm_delete.html', {
        'object': project,
        'cancel_url': 'project_detail',
        'cancel_pk': project.pk,
    })


# =====================================================================
# TASKS (they live on the project page, so no list/detail pages)
# =====================================================================
@login_required
def task_create(request):
    if request.method == 'POST':
        form = TaskForm(request.POST, user=request.user)
        if form.is_valid():
            task = form.save()
            messages.success(request, 'Task added.')
            return redirect('project_detail', pk=task.project.pk)
    else:
        initial = {}
        if request.GET.get('project'):         # e.g. /tasks/new/?project=5
            initial['project'] = request.GET['project']
        form = TaskForm(user=request.user, initial=initial)
    return render(request, 'form.html', {'form': form, 'title': 'Add task'})


@login_required
def task_update(request, pk):
    task = get_object_or_404(Task, pk=pk, project__client__owner=request.user)
    if request.method == 'POST':
        form = TaskForm(request.POST, instance=task, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Task updated.')
            return redirect('project_detail', pk=task.project.pk)
    else:
        form = TaskForm(instance=task, user=request.user)
    return render(request, 'form.html', {'form': form, 'title': 'Edit task'})


@login_required
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk, project__client__owner=request.user)
    project_pk = task.project.pk
    if request.method == 'POST':
        task.delete()
        messages.success(request, 'Task deleted.')
        return redirect('project_detail', pk=project_pk)
    return render(request, 'confirm_delete.html', {
        'object': task,
        'cancel_url': 'project_detail',
        'cancel_pk': project_pk,
    })


# =====================================================================
# INVOICES
# =====================================================================
@login_required
def invoice_list(request):
    invoices = Invoice.objects.filter(project__client__owner=request.user).select_related('project__client')
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '')
    if q:
        invoices = invoices.filter(
            Q(number__icontains=q) | Q(project__title__icontains=q) | Q(project__client__name__icontains=q)
        )
    if status == 'overdue':
        invoices = invoices.filter(status='sent', due_date__lt=timezone.localdate())
    elif status:
        invoices = invoices.filter(status=status)
    # Totals for the strip above the table (always for ALL your invoices, not just the filtered ones)
    everything = Invoice.objects.filter(project__client__owner=request.user)
    received = sum((i.total() for i in everything if i.status == 'paid'), Decimal('0'))
    waiting = sum((i.total() for i in everything if i.status == 'sent'), Decimal('0'))
    overdue = sum((i.total() for i in everything if i.is_overdue()), Decimal('0'))
    return render(request, 'invoice_list.html', {
        'invoices': invoices.order_by('-issue_date', '-id'),
        'statuses': list(Invoice.STATUS_CHOICES) + [('overdue', 'Overdue')],
        'received': received,
        'waiting': waiting,
        'overdue_amount': overdue,
    })


@login_required
def invoice_create(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST, user=request.user)
        if form.is_valid():
            invoice = form.save()
            messages.success(request, 'Invoice created.')
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        today = timezone.localdate()
        count = Invoice.objects.filter(project__client__owner=request.user).count()
        initial = {
            'number': f'INV-{today.year}-{count + 1:03d}',   # e.g. INV-2026-004
            'issue_date': today,
            'due_date': today + timedelta(days=15),
        }
        if request.GET.get('project'):
            initial['project'] = request.GET['project']
        form = InvoiceForm(user=request.user, initial=initial)
    return render(request, 'form.html', {'form': form, 'title': 'Create invoice'})


@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, project__client__owner=request.user)
    return render(request, 'invoice_detail.html', {'invoice': invoice})


@login_required
def invoice_update(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, project__client__owner=request.user)
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Invoice updated.')
            return redirect('invoice_detail', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice, user=request.user)
    return render(request, 'form.html', {'form': form, 'title': 'Edit invoice'})


@login_required
def invoice_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, project__client__owner=request.user)
    if request.method == 'POST':
        invoice.delete()
        messages.success(request, 'Invoice deleted.')
        return redirect('invoice_list')
    return render(request, 'confirm_delete.html', {
        'object': invoice,
        'cancel_url': 'invoice_detail',
        'cancel_pk': invoice.pk,
    })


# =====================================================================
# GST MONTHLY SUMMARY (the Indian-freelancer feature)
# =====================================================================
@login_required
def gst_summary(request):
    # Only invoices that were actually issued (Sent or Paid), not Drafts
    invoices = Invoice.objects.filter(
        project__client__owner=request.user,
        status__in=['sent', 'paid'],
    )

    months = {}         # one entry per (year, month)
    years = {}          # one entry per financial year (April to March)

    for inv in invoices:
        # ---- month row ----
        key = (inv.issue_date.year, inv.issue_date.month)
        if key not in months:
            months[key] = {'label': inv.issue_date.strftime('%B %Y'), 'count': 0,
                           'taxable': Decimal('0'), 'gst': Decimal('0'), 'total': Decimal('0')}
        row = months[key]
        row['count'] += 1
        row['taxable'] += inv.amount
        row['gst'] += inv.tax()
        row['total'] += inv.total()

        # ---- financial year row (April = start of the Indian financial year) ----
        start_year = inv.issue_date.year if inv.issue_date.month >= 4 else inv.issue_date.year - 1
        fy_label = f'FY {start_year}-{(start_year + 1) % 100:02d}'
        if fy_label not in years:
            years[fy_label] = {'label': fy_label, 'count': 0,
                               'taxable': Decimal('0'), 'gst': Decimal('0'), 'total': Decimal('0')}
        fy = years[fy_label]
        fy['count'] += 1
        fy['taxable'] += inv.amount
        fy['gst'] += inv.tax()
        fy['total'] += inv.total()

    month_rows = [months[k] for k in sorted(months, reverse=True)]   # newest first
    year_rows = [years[k] for k in sorted(years, reverse=True)]

    # Chart: GST collected in each of the latest 12 months, oldest first
    gst_chart = [
        {'label': row['label'][:3], 'full': row['label'], 'value': float(row['gst']),
         'note': f"{row['count']} invoice{'' if row['count'] == 1 else 's'}"}
        for row in reversed(month_rows[:12])
    ]
    totals = {
        'gst': sum((row['gst'] for row in month_rows), Decimal('0')),
        'taxable': sum((row['taxable'] for row in month_rows), Decimal('0')),
        'count': sum(row['count'] for row in month_rows),
    }

    return render(request, 'gst_summary.html', {
        'month_rows': month_rows,
        'year_rows': year_rows,
        'gst_chart': gst_chart,
        'totals': totals,
    })

    # =====================================================================
# INVOICE AS PDF
# =====================================================================
@login_required
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, project__client__owner=request.user)

    # 1. Turn the HTML template into text, filled with this invoice's data
    html = get_template('invoice_pdf.html').render({
        'invoice': invoice,
        'freelancer': request.user,
    })

    # 2. Convert that HTML into a PDF and write it straight into the response
    filename = (slugify(invoice.number) or 'invoice') + '.pdf'
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{filename}"'
    result = pisa.CreatePDF(html, dest=response)

    if result.err:
        return HttpResponse('Sorry, the PDF could not be created.', status=500)
    return response

# =====================================================================
# PAYMENT REMINDER EMAIL
# =====================================================================
@login_required
def invoice_reminder(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, project__client__owner=request.user)

    # Only invoices that were sent to the client and are not paid yet need a reminder
    if invoice.status != 'sent':
        messages.warning(request, 'Reminders can only be sent for invoices marked Sent.')
        return redirect('invoice_detail', pk=invoice.pk)

    # "polite" or "firm". A firm tone only makes sense when the invoice is overdue.
    tone = request.GET.get('tone', 'polite')
    if tone != 'firm' or not invoice.is_overdue():
        tone = 'polite'

    if request.method == 'POST':
        form = ReminderForm(request.POST)
        if form.is_valid():
            email = EmailMessage(
                subject=form.cleaned_data['subject'],
                body=form.cleaned_data['message'],
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[invoice.project.client.email],
                reply_to=[request.user.email] if request.user.email else None,
            )
            try:
                email.send(fail_silently=False)
            except Exception as error:      # for example: no internet, wrong email password
                messages.warning(request, f'The reminder could not be sent: {error}')
            else:
                invoice.reminder_count += 1
                invoice.last_reminder_date = timezone.localdate()
                invoice.save(update_fields=['reminder_count', 'last_reminder_date'])
                messages.success(request, f'Reminder sent to {invoice.project.client.email}.')
                return redirect('invoice_detail', pk=invoice.pk)
    else:
        sender_name = request.user.get_full_name() or request.user.username
        subject, body = build_reminder(invoice, tone, sender_name)
        form = ReminderForm(initial={'subject': subject, 'message': body})

    return render(request, 'invoice_reminder.html', {
        'form': form,
        'invoice': invoice,
        'tone': tone,
        'is_overdue': invoice.is_overdue(),
        'console_mode': settings.EMAIL_BACKEND.endswith('console.EmailBackend'),
    })

# =====================================================================
# AI ASSISTANT
# =====================================================================
@login_required
def assistant(request):
    # The conversation is kept in the session (the browser cookie), so it is per user and per browser.
    history = request.session.get('assistant_history', [])

    if request.method == 'POST':
        if 'clear' in request.POST:
            history = []
        else:
            question = request.POST.get('question', '').strip()[:300]
            if question:
                answer, source = ask_assistant(request.user, question)
                history.append({'question': question, 'answer': answer, 'source': source})
                history = history[-8:]                  # keep only the last 8 exchanges
        request.session['assistant_history'] = history
        return redirect('assistant')

    examples = [
        'Which invoices are overdue?',
        'How much GST did I collect this month?',
        'Which clients are risky?',
        'How much money have I received?',
    ]
    return render(request, 'assistant.html', {
        'history': list(reversed(history)),             # newest first
        'examples': examples,
        'gemini_on': bool(settings.GEMINI_API_KEY),
    })


@login_required
def forecast(request):
    return render(request, 'forecast.html', {'result': build_forecast(request.user)})