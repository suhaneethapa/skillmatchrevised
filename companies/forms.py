from datetime import date
from django import forms
from django.core.exceptions import ValidationError
from .models import Internship
from students.models import Application
from core.validators import validate_document_file


class IssueOfferForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = ['offer_letter']

    def clean_offer_letter(self):
        letter = self.cleaned_data.get('offer_letter')
        if letter:
            validate_document_file(letter)
        return letter


class InternshipForm(forms.ModelForm):
    class Meta:
        model = Internship
        fields = [
            'title',
            'description',
            'category',
            'location_type',
            'stipend',
            'deadline',
            'total_positions',
            'expected_duration',
        ]

    def clean_total_positions(self):
        positions = self.cleaned_data.get('total_positions')
        if positions is not None and positions < 1:
            raise ValidationError("Positions must be at least 1.")
        return positions

    def clean_deadline(self):
        deadline = self.cleaned_data.get('deadline')
        if deadline:
            if not self.instance.pk and deadline <= date.today():
                raise ValidationError("Deadline must be in the future.")
        return deadline

    def clean_stipend(self):
        stipend = self.cleaned_data.get('stipend')
        if stipend is not None and stipend < 0:
            raise ValidationError("Stipend cannot be negative.")
        return stipend
