from django import forms
from .models import ReviewReport
from reviews.models import Review


class ReviewDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            ("", "Choose a decision"),
            (Review.Status.APPROVED, "Approve"),
            (Review.Status.REJECTED, "Reject"),
        ],
        label="Decision",
    )

    reason = forms.CharField(
        min_length=10,
        max_length=2000,
        label="Reason for this decision",
        help_text="Use between 10 and 2,000 characters.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    expected_updated_at = forms.DateTimeField(
        widget=forms.HiddenInput(),
    )

class ReviewReportForm(forms.ModelForm):
    details = forms.CharField(
        required=False,
        max_length=2000,
        label="Additional details",
        help_text="Optional. Maximum 2,000 characters.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    class Meta:
        model = ReviewReport
        fields = ["reason", "details"]

class ReportDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            ("", "Choose a decision"),
            (ReviewReport.Status.RESOLVED, "Resolved"),
            (ReviewReport.Status.DISMISSED, "Dismissed"),
        ],
        label="Report outcome",
    )

    reason = forms.CharField(
        min_length=10,
        max_length=2000,
        label="Resolution note",
        help_text="Explain the outcome in 10 to 2,000 characters.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    expected_updated_at = forms.DateTimeField(
        widget=forms.HiddenInput(),
    )

    expected_review_updated_at = forms.DateTimeField(
        widget=forms.HiddenInput(),
    )

class AccountDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            ("", "Choose an action"),
            ("suspend", "Suspend account"),
            ("restore", "Restore account"),
        ],
        label="Account action",
    )

    reason = forms.CharField(
        min_length=10,
        max_length=2000,
        label="Reason",
        help_text="Use between 10 and 2,000 characters.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    expected_session_version = forms.IntegerField(
        min_value=0,
        widget=forms.HiddenInput(),
    )