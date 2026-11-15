from django import forms
from .models import StudentProfile
from core.validators import validate_document_file


class StudentProfileEditForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = [
            'department',
            'semester',
            'college',
            'bio',
            'github_url',
            'linkedin_url',
            'cv_file',
        ]

    def clean_cv_file(self):
        cv = self.cleaned_data.get('cv_file')
        if cv:
            validate_document_file(cv)
        return cv
