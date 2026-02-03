from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('zoom/', include('reuniones.urls')),  # Incluir URLs de la app
]