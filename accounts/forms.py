from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User
from core.models import College


class StudentRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    college = forms.ModelChoiceField(queryset=College.objects.all())
    department = forms.CharField(max_length=100)
    semester = forms.IntegerField(min_value=1, max_value=8)
    
    class Meta:
        model = User
        fields = ('email', 'password1', 'password2', 'college', 'department', 'semester')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.role = 'student'
        user.status = 'pending_email'
        if commit:
            user.save()
            from students.models import StudentProfile
            StudentProfile.objects.create(
                user=user,
                college=self.cleaned_data['college'],
                department=self.cleaned_data['department'],
                semester=self.cleaned_data['semester'],
                college_verified=False
            )
        return user


class CompanyRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    organization_name = forms.CharField(max_length=255)
    contact_person = forms.CharField(max_length=255)
    industry = forms.CharField(max_length=100)
    hq_location = forms.CharField(max_length=255, required=True, label="Headquarters Location")
    description = forms.CharField(widget=forms.Textarea)
    
    class Meta:
        model = User
        fields = ('email', 'password1', 'password2', 'organization_name', 'contact_person', 'industry', 'hq_location', 'description')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.role = 'company'
        user.status = 'pending_email'
        if commit:
            user.save()
            from companies.models import CompanyProfile
            CompanyProfile.objects.create(
                user=user,
                organization_name=self.cleaned_data['organization_name'],
                contact_person=self.cleaned_data['contact_person'],
                industry=self.cleaned_data['industry'],
                hq_location=self.cleaned_data['hq_location'],
                description=self.cleaned_data['description']
            )
        return user


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)