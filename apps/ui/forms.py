from django.contrib.auth.forms import AuthenticationForm

INPUT_CLASS = "mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-slate-900"


class WorkplaceAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Имя пользователя"
        self.fields["password"].label = "Пароль"
        self.fields["username"].widget.attrs.update(
            {"class": INPUT_CLASS, "autofocus": True, "autocomplete": "username"}
        )
        self.fields["password"].widget.attrs.update(
            {"class": INPUT_CLASS, "autocomplete": "current-password"}
        )
