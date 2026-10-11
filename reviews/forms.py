from django import forms

from .models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[
            ("", "Choose a rating"),
            (1, "1 — Poor"),
            (2, "2 — Fair"),
            (3, "3 — Good"),
            (4, "4 — Very good"),
            (5, "5 — Excellent"),
        ],
        coerce=int,
        label="Rating",
    )

    title = forms.CharField(
        min_length=5,
        max_length=200,
        label="Review title",
        help_text="Use between 5 and 200 characters.",
        widget=forms.TextInput(
            attrs={"placeholder": "Summarize your experience"},
        ),
    )

    body = forms.CharField(
        min_length=20,
        max_length=5000,
        label="Your review",
        help_text="Use between 20 and 5,000 characters.",
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": (
                    "Describe what worked well and what could be better."
                ),
            },
        ),
    )

    class Meta:
        model = Review
        fields = ["rating", "title", "body"]