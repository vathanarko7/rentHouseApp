from django.conf import settings
from django.utils import translation


class DefaultLanguageMiddleware:
    """
    Force default language on first visit when no language cookie is set.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        cookie_name = getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language")
        if cookie_name not in request.COOKIES and "language" not in request.GET:
            default_lang = getattr(settings, "LANGUAGE_CODE", "km")
            translation.activate(default_lang)
            request.LANGUAGE_CODE = default_lang

        response = self.get_response(request)

        if cookie_name not in request.COOKIES and "language" not in request.GET:
            response.set_cookie(cookie_name, getattr(settings, "LANGUAGE_CODE", "km"))

        return response
