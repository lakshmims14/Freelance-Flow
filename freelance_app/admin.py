from django.contrib import admin
from .models import Client, Invoice, Project, Task


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'email', 'owner')
    search_fields = ('name', 'company', 'email')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'client', 'status', 'budget', 'deadline')
    list_filter = ('status',)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'project', 'status', 'priority', 'due_date')
    list_filter = ('status', 'priority')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'project', 'amount', 'status', 'due_date', 'paid_date')
    list_filter = ('status',)