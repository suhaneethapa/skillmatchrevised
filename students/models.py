from datetime import date
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from core.validators import validate_document_file


class StudentProfile(models.Model):
    """
    Extended profile for Student users.
    Linked 1-to-1 with the User model (one User = one StudentProfile).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_profile'
    )
    college = models.ForeignKey(
        'core.College',
        on_delete=models.PROTECT,
        help_text="College selected from admin-maintained list"
    )
    department = models.CharField(max_length=100)
    semester = models.PositiveSmallIntegerField()
    bio = models.TextField(blank=True)
    github_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    cv_file = models.FileField(upload_to='cvs/', blank=True, validators=[validate_document_file])
    college_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.college.name}"


class StudentSkill(models.Model):
    """
    Junction table: which skills each student has.
    Many-to-many relationship between User and Skill.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_skills'
    )
    skill = models.ForeignKey(
        'core.Skill',
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ('student', 'skill')
        # Prevents duplicate entries: a student can't have "Python" twice


class Application(models.Model):
    """
    Represents a student applying to an internship.
    Stores the match score at application time (denormalized for performance).
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('offer_issued', 'Offer Issued'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='applications'
    )
    internship = models.ForeignKey(
        'companies.Internship',  # String reference because Internship hasn't been defined yet
        on_delete=models.CASCADE,
        related_name='applications'
    )
    cover_letter = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    match_score = models.DecimalField(max_digits=5, decimal_places=2)
    applied_at = models.DateTimeField(auto_now_add=True)
    REJECTION_REASONS = [
        ('Skills mismatch', 'Skills mismatch'),
        ('Position filled', 'Position filled'),
        ('Stronger candidates', 'Stronger candidates'),
        ('No response from candidate', 'No response from candidate'),
        ('Other', 'Other'),
    ]

    offer_letter = models.FileField(upload_to='offer_letters/', blank=True, validators=[validate_document_file])
    rejection_reason = models.CharField(max_length=50, choices=REJECTION_REASONS, blank=True)
    rejection_feedback = models.TextField(blank=True)

    @property
    def is_below_threshold(self):
        """Returns True if the current match score is below the 50% eligibility threshold."""
        return float(self.match_score) < 50.0

    def compute_current_match(self, save=False):
        """
        Recomputes live match score based on candidate's current skills.
        Updates self.match_score in-memory, and only saves to database if save=True.
        """
        from matching.engine import compute_match_score
        student_skills = set(self.student.student_skills.values_list('skill__name', flat=True))
        req_skills = list(self.internship.internship_skills.values_list('skill__name', 'is_required'))
        score, gap = compute_match_score(student_skills, req_skills)
        self.match_score = score
        if save:
            self.save(update_fields=['match_score'])
        return score, (score < 50.0)

    def clean(self):
        super().clean()
        if self._state.adding and self.internship_id:
            if self.internship.status != 'approved':
                raise ValidationError("Applications can only be submitted to approved listings.")
            if self.internship.deadline and self.internship.deadline < date.today():
                raise ValidationError("Cannot apply to an expired internship listing.")

    class Meta:
        unique_together = ('student', 'internship')
        constraints = [
            models.UniqueConstraint(fields=['student', 'internship'], name='unique_student_internship_application')
        ]
        # Prevents duplicate applications: one student can only apply once per internship


class JournalEntry(models.Model):
    """
    Weekly progress journal for students in active internships.
    Only visible when Application.status = 'accepted'.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='journal_entries'
    )
    application = models.ForeignKey(
        Application,
        on_delete=models.CASCADE,
        related_name='journal_entries'
    )
    week_number = models.PositiveSmallIntegerField()
    entry_date = models.DateField()
    hours_worked = models.PositiveSmallIntegerField()
    description = models.TextField()

    class Meta:
        unique_together = ('student', 'application', 'week_number')
        # One entry per week per internship
