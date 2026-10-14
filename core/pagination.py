from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """{count, next, previous, results} with page_size default 20, max 100."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
