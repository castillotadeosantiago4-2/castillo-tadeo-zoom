# ========================================
# reuniones/zoom_service.py
# Servicio para OAuth User-Level (cuenta gratis)
# ========================================

import requests  # Para peticiones HTTP
from django.conf import settings  # Acceso a settings
from django.core.cache import cache  # Sistema de caché
import base64  # Codificación Base64
from datetime import datetime  # Manejo de fechas
from reuniones.models import Reunion
import json

class ZoomService:
    """
    Servicio para interactuar con Zoom API usando OAuth 2.0 User-Level.
    Compatible con cuentas Zoom Basic (gratuitas).
    """
    
    def __init__(self):
        # Credenciales OAuth
        self.client_id = settings.ZOOM_CLIENT_ID
        self.client_secret = settings.ZOOM_CLIENT_SECRET
        self.redirect_uri = settings.ZOOM_REDIRECT_URI
        
        # URLs de Zoom
        self.authorize_url = settings.ZOOM_OAUTH_AUTHORIZE_URL
        self.token_url = settings.ZOOM_OAUTH_TOKEN_URL
        self.api_base_url = settings.ZOOM_API_BASE_URL
    
    def get_authorization_url(self):
        """Genera URL para que el usuario autorice la app."""
        return (
            f"{self.authorize_url}"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
        )
    
    def exchange_code_for_token(self, code):
        """Intercambia el código de autorización por Access Token."""
        credentials = f"{self.client_id}:{self.client_secret}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()
        
        headers = {
            'Authorization': f'Basic {b64_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri
        }
        
        response = requests.post(self.token_url, headers=headers, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            cache.set('zoom_access_token', token_data['access_token'], 3300)
            cache.set('zoom_refresh_token', token_data['refresh_token'], 86400)
            return token_data
        else:
            raise Exception(f"Error obteniendo token: {response.text}")
    
    def refresh_access_token(self):
        refresh_token = cache.get('zoom_refresh_token')

        if not refresh_token:
            raise Exception("No hay refresh token disponible")

        credentials = f"{self.client_id}:{self.client_secret}"
        b64_credentials = base64.b64encode(credentials.encode()).decode()

        headers = {
            'Authorization': f'Basic {b64_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        data = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token
        }

        response = requests.post(
            self.token_url,
            headers=headers,
            data=data,
            timeout=10
        )

        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            new_refresh_token = token_data.get('refresh_token')

            if not access_token or not new_refresh_token:
                raise Exception("Respuesta inválida de Zoom al refrescar token")

            cache.set('zoom_access_token', access_token, 3300)
            cache.set('zoom_refresh_token', new_refresh_token, 86400)

            return access_token

        elif response.status_code in (400, 401):
            cache.delete('zoom_access_token')
            cache.delete('zoom_refresh_token')
            raise Exception("Refresh token inválido o expirado. Reautoriza la app en Zoom.")

        else:
            raise Exception(f"Error renovando token: {response.text}")

    def get_access_token(self):
        """Obtiene Access Token (desde caché o renovando)."""
        access_token = cache.get('zoom_access_token')
        if access_token:
            return access_token
        return self.refresh_access_token()
    
    # ---------------------------------------------------------
    # MÉTODO ACTUALIZADO: Acepta 'agenda' y 'settings'
    # ---------------------------------------------------------
    def crear_reunion(self, topic, start_time, duration, agenda=None, settings=None, timezone='America/Hermosillo'):
        """
        Crea una reunión en Zoom.
        Ahora acepta agenda y configuraciones dinámicas.
        """
        access_token = self.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        # 1. Configuración por defecto (Base)
        meeting_settings = {
            'host_video': True,
            'participant_video': True,
            'join_before_host': False,
            'mute_upon_entry': True,
            'waiting_room': True,
            'audio': 'both'
        }

        # 2. Si recibimos settings del usuario, actualizamos la base
        if settings:
            meeting_settings.update(settings)
        
        # 3. Construir el cuerpo de la petición
        data = {
            'topic': topic,
            'type': 2,  # Reunión programada
            'start_time': start_time,
            'duration': duration,
            'timezone': timezone,
            'settings': meeting_settings
        }

        # Agregar agenda solo si existe
        if agenda:
            data['agenda'] = agenda
        
        # 4. Obtener ID del usuario actual ("me")
        user_response = requests.get(
            f"{self.api_base_url}/users/me",
            headers=headers
        )
        
        if user_response.status_code != 200:
             raise Exception(f"Error obteniendo usuario: {user_response.text}")

        user_id = user_response.json()['id']
        
        # 5. Enviar petición a Zoom
        response = requests.post(
            f"{self.api_base_url}/users/{user_id}/meetings",
            headers=headers,
            json=data
        )
        
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Error creando reunión: {response.text}")
    
    def listar_reuniones(self):
        """Lista todas las reuniones programadas del usuario."""
        access_token = self.get_access_token()
        
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        user_response = requests.get(
            f"{self.api_base_url}/users/me",
            headers=headers
        )
        user_id = user_response.json()['id']
        
        response = requests.get(
            f"{self.api_base_url}/users/{user_id}/meetings",
            headers=headers
        )
        
        if response.status_code == 200:
            return response.json()['meetings']
        else:
            raise Exception(f"Error listando reuniones: {response.text}")
    
    def eliminar_reunion(self, meeting_id):
        """Elimina una reunión en Zoom y en la base de datos local."""
        access_token = self.get_access_token()

        headers = {
            'Authorization': f'Bearer {access_token}'
        }

        response = requests.delete(
            f"{self.api_base_url}/meetings/{meeting_id}",
            headers=headers
        )

        if response.status_code == 204:
            Reunion.objects.filter(zoom_meeting_id=meeting_id).delete()
            return True

        try:
            error_data = response.json()
            if error_data.get("code") == 3001:
                Reunion.objects.filter(zoom_meeting_id=meeting_id).delete()
                return True
        except ValueError:
            pass

        raise Exception(f"Error eliminando reunión: {response.text}")