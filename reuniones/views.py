# ========================================
# reuniones/views.py
# Vistas para OAuth User-Level (gratuito)
# ========================================

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.cache import cache
from .zoom_service import ZoomService
from .models import Reunion, Participante
from datetime import datetime

# =====================================
# VISTAS DE AUTENTICACIÓN OAUTH
# =====================================

def zoom_login(request):
    """
    Redirige al usuario a la página de autorización de Zoom.
    Primera vez que el usuario autoriza la app.
    """
    zoom_service = ZoomService()
    authorization_url = zoom_service.get_authorization_url()
    return redirect(authorization_url)


def zoom_oauth_callback(request):
    """
    Callback de Zoom después de que el usuario autoriza.
    Recibe el código y lo intercambia por access token.
    """
    code = request.GET.get('code')
    
    if not code:
        messages.error(request, '❌ Error: No se recibió código de autorización')
        return redirect('inicio')
    
    try:
        zoom_service = ZoomService()
        token_data = zoom_service.exchange_code_for_token(code)
        
        messages.success(request, '✅ Autorización exitosa! Ya puedes crear reuniones.')
        return redirect('inicio')
    
    except Exception as e:
        messages.error(request, f'❌ Error al autorizar: {str(e)}')
        return redirect('inicio')


def verificar_autorizacion(request):
    """
    API para verificar si ya hay token (usuario ya autorizó).
    Usado por JavaScript en el frontend.
    """
    tiene_token = cache.get('zoom_access_token') is not None
    return JsonResponse({'autorizado': tiene_token})


# =====================================
# VISTAS PRINCIPALES
# =====================================

def inicio(request):
    """
    Página de inicio.
    Muestra botón de autorizar si no hay token.
    """
    tiene_token = cache.get('zoom_access_token') is not None
    
    context = {
        'autorizado': tiene_token
    }
    return render(request, 'reuniones/inicio.html', context)


@login_required
def crear_reunion(request):
    """
    Vista para crear una reunión de Zoom capturando opciones de seguridad.
    """
    if request.method == 'POST':
        try:
            # 1. Obtener datos básicos
            topic = request.POST.get('topic')
            start_time = request.POST.get('start_time')
            duration = int(request.POST.get('duration'))
            agenda = request.POST.get('agenda', '')  # Descripción opcional

            # 2. Obtener Configuración de Seguridad (Checkboxes)
            # En HTML, si el check no está marcado devuelve None, si está marcado devuelve 'on'
            waiting_room = request.POST.get('waiting_room') == 'on'
            join_before_host = request.POST.get('join_before_host') == 'on'
            mute_upon_entry = request.POST.get('mute_upon_entry') == 'on'
            
            # 3. Validar fecha
            if not start_time:
                raise ValueError("La fecha y hora son obligatorias")

            # Convertir string del input datetime-local a objeto datetime
            start_datetime = datetime.strptime(start_time, '%Y-%m-%dT%H:%M')
            # Convertir a string ISO 8601 para la API de Zoom
            start_time_iso = start_datetime.strftime('%Y-%m-%dT%H:%M:%S')
            
            # 4. Crear reunión en Zoom (API) enviando settings
            zoom_service = ZoomService()
            meeting_data = zoom_service.crear_reunion(
                topic=topic,
                start_time=start_time_iso,
                duration=duration,
                agenda=agenda,
                settings={
                    'waiting_room': waiting_room,
                    'join_before_host': join_before_host,
                    'mute_upon_entry': mute_upon_entry
                }
            )
            
            # 5. Guardar en base de datos local
            reunion = Reunion.objects.create(
                titulo=topic,
                zoom_meeting_id=meeting_data['id'],
                join_url=meeting_data['join_url'],
                start_url=meeting_data['start_url'],
                fecha_inicio=start_datetime,
                duracion=duration,
                creador=request.user,
                # Guardamos la configuración elegida
                sala_espera=waiting_room 
            )
            
            messages.success(request, f'✅ Reunión "{topic}" creada exitosamente!')
            return redirect('lista_reuniones')
        
        except Exception as e:
            messages.error(request, f'❌ Error al crear reunión: {str(e)}')
            # Es buena práctica devolver los datos previos en caso de error (opcional)
            return render(request, 'reuniones/crear_reunion.html')
    
    return render(request, 'reuniones/crear_reunion.html')

@login_required
def lista_reuniones(request):
    """
    Lista todas las reuniones creadas.
    """
    reuniones = Reunion.objects.filter(creador=request.user)
    
    context = {
        'reuniones': reuniones
    }
    return render(request, 'reuniones/lista_reuniones.html', context)


@login_required
def detalle_reunion(request, reunion_id):
    """
    Muestra detalles de una reunión específica.
    """
    reunion = get_object_or_404(Reunion, id=reunion_id, creador=request.user)
    
    context = {
        'reunion': reunion
    }
    return render(request, 'reuniones/detalle_reunion.html', context)


@login_required
def eliminar_reunion(request, reunion_id):
    """
    Elimina una reunión de Zoom y de la base de datos.
    """
    reunion = get_object_or_404(Reunion, id=reunion_id, creador=request.user)
    
    try:
        # Eliminar de Zoom
        zoom_service = ZoomService()
        zoom_service.eliminar_reunion(reunion.zoom_meeting_id)
        
        # Eliminar de base de datos
        titulo = reunion.titulo
        reunion.delete()
        
        messages.success(request, f'✅ Reunión "{titulo}" eliminada correctamente.')
    
    except Exception as e:
        messages.error(request, f'❌ Error al eliminar: {str(e)}')
    
    return redirect('lista_reuniones')


@login_required
def sincronizar_reuniones(request):
    """
    Sincroniza reuniones desde Zoom API.
    Útil para obtener reuniones creadas directamente en Zoom.
    """
    try:
        zoom_service = ZoomService()
        meetings = zoom_service.listar_reuniones()
        
        count = 0
        for meeting in meetings:
            # Crear o actualizar en base de datos
            Reunion.objects.update_or_create(
                zoom_meeting_id=meeting['id'],
                defaults={
                    'titulo': meeting['topic'],
                    'join_url': meeting['join_url'],
                    'start_url': meeting.get('start_url', ''),
                    'fecha_inicio': datetime.strptime(
                        meeting['start_time'], 
                        '%Y-%m-%dT%H:%M:%SZ'
                    ),
                    'duracion': meeting['duration'],
                    'creador': request.user
                }
            )
            count += 1
        
        messages.success(request, f'✅ Sincronizadas {count} reuniones desde Zoom.')
    
    except Exception as e:
        messages.error(request, f'❌ Error al sincronizar: {str(e)}')
    
    return redirect('lista_reuniones')
from django.views.decorators.csrf import csrf_exempt  # Desactivar CSRF para webhook
from django.http import JsonResponse  # Respuesta JSON
import json  # Parser JSON

@csrf_exempt  # Zoom no puede enviar CSRF token
def zoom_webhook(request):
    """
    Endpoint que recibe notificaciones de Zoom
    URL debe ser pública: https://tudominio.com/api/zoom/webhook/
    """
    
    if request.method == 'POST':  # Zoom envía POST
        
        # Parsear payload JSON
        payload = json.loads(request.body)  # Convierte string a dict
        
        # Obtener tipo de evento
        event_type = payload.get('event')  # Ejemplo: "meeting.participant_joined"
        
        # Validación de URL (solo primera vez)
        if event_type == 'endpoint.url_validation':  # Zoom valida la URL
            plain_token = payload.get('payload', {}).get('plainToken')  # Token enviado
            return JsonResponse({  # Responder con token encriptado
                'plainToken': plain_token,
                'encryptedToken': plain_token  # En producción encriptar con SHA256
            })
        
        # Procesar evento de participante
        if event_type == 'meeting.participant_joined':
            meeting_id = payload.get('payload', {}).get('object', {}).get('id')  # ID reunión
            participant_name = payload.get('payload', {}).get('object', {}).get('participant', {}).get('user_name')  # Nombre
            
            # Actualizar asistencia en base de datos
            try:
                reunion = Reunion.objects.get(zoom_meeting_id=meeting_id)  # Busca reunión
                participante = Participante.objects.filter(  # Busca participante
                    reunion=reunion,
                    nombre__icontains=participant_name  # Coincidencia parcial
                ).first()
                
                if participante:
                    participante.asistio = True  # Marca asistencia
                    participante.save()  # Guarda en BD
            except Reunion.DoesNotExist:
                pass  # Reunión no encontrada
        
        # Responder con éxito a Zoom
        return JsonResponse({'status': 'success'}, status=200)  # Zoom espera 200 OK
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)  # Solo POST permitido