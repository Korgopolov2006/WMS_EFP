from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

# Create your views here.


@login_required
def me(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/me.html")
