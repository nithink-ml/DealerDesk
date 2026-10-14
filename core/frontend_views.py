"""Frontend views for VIKMO DealerDesk Dashboard and Documentation."""
from django.shortcuts import render


def index(request):
    """Serve the complete single-page application dashboard."""
    return render(request, "dealerdesk/index.html")


def docs(request):
    """Serve interactive API specification documentation."""
    return render(request, "dealerdesk/docs.html")
