from django.urls import path

from api import views

urlpatterns = [
    path("health", views.health),
    path("geocode", views.geocode),
    path("reverse", views.reverse),
    path("trips/plan", views.planTripView),
    path("trips/heatmap", views.heatmapView),
]
