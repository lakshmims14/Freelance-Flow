from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User

from .models import Client, Invoice, Project, Task



def add_bootstrap(form):
    """Give every field in the form the Bootstrap look."""
    for field in form.fields.values():
        if isinstance(field.widget, forms.Select):
            field.widget.attrs['class'] = 'form-select'
        else:
            field.widget.attrs['class'] = 'form-control'


# ------------------------------------------------------------ Signup / Login
class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email']   # the two password fields come from UserCreationForm

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap(self)

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap(self)


# ------------------------------------------------------------------- Client
class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'company', 'email', 'phone', 'country']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap(self)


# ------------------------------------------------------------------ Project
class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['client', 'title', 'description', 'status', 'budget', 'start_date', 'deadline']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'deadline': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            # The dropdown shows only this user's own clients
            self.fields['client'].queryset = Client.objects.filter(owner=user)
        add_bootstrap(self)

    def clean_budget(self):
        budget = self.cleaned_data['budget']
        if budget <= 0:
            raise forms.ValidationError('Budget must be greater than zero.')
        return budget

    def clean(self):
        data = super().clean()
        start = data.get('start_date')
        end = data.get('deadline')
        if start and end and end < start:
            self.add_error('deadline', 'Deadline cannot be before the start date.')
        return data


# --------------------------------------------------------------------- Task
class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ['project', 'title', 'status', 'priority', 'due_date', 'hours_estimated']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['project'].queryset = Project.objects.filter(client__owner=user)
        add_bootstrap(self)


# ------------------------------------------------------------------ Invoice
class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['number', 'project', 'amount', 'gst_percent',
                  'issue_date', 'due_date', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
            'issue_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields['project'].queryset = Project.objects.filter(client__owner=user)
        add_bootstrap(self)

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be greater than zero.')
        return amount

    def clean(self):
        data = super().clean()
        issue = data.get('issue_date')
        due = data.get('due_date')
        if issue and due and due < issue:
            self.add_error('due_date', 'Due date cannot be before the issue date.')
        return data

class ReminderForm(forms.Form):
    subject = forms.CharField(max_length=150)
    message = forms.CharField(widget=forms.Textarea(attrs={'rows': 12}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap(self)

    def clean_subject(self):
        # An email subject must be a single line, so join any line breaks into spaces
        return ' '.join(self.cleaned_data['subject'].split())