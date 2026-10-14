from django.urls import path

from api import views

urlpatterns = [
    path("health", views.health),
    path("geocode", views.geocode),
    path("trips/plan", views.planTripView),
]
