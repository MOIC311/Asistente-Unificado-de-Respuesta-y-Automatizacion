
import os
import time
import queue
import shutil
import subprocess
from pathlib import Path

import numpy as np
import sounddevice as sd
import spotipy
from spotipy.oauth2 import SpotifyOAuth


# ============================================================
# CONFIGURACIÓN: MODIFICAR AQUÍ
# ============================================================

# MODIFICAR AQUÍ:
# Configura estas dos variables en la terminal de PowerShell.
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# MODIFICAR AQUÍ:
# Debe coincidir exactamente con la URI registrada en Spotify
# Developer Dashboard > tu aplicación > Redirect URIs.
REDIRECT_URI = "http://127.0.0.1:8888/callback"

# MODIFICAR AQUÍ:
# Esta es la canción que se reproducirá cuando detecte un aplauso.
# Para usar otra canción, reemplaza la URI por la de Spotify.
TRACK_URI = "spotify:track:0C80GCp0mMuBzLf3EAXqxv"

# Permisos necesarios para consultar el dispositivo y reproducir música.
SCOPE = "user-modify-playback-state user-read-playback-state"

# MODIFICAR AQUÍ:
# Sensibilidad del micrófono. Un valor menor detecta sonidos más débiles.
# Si detecta ruido constantemente, aumenta el valor.
# Si no detecta tus aplausos, disminúyelo poco a poco.
UMBRAL = 0.12

# Tiempo mínimo entre activaciones para evitar varios disparos seguidos.
ESPERA = 5.0

# MODIFICAR AQUÍ:
# Si VS Code está instalado en una ubicación diferente,
# agrega su ruta a la lista de buscar_vscode().
RUTAS_VSCODE = [
    Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe",
    Path("C:/Program Files/Microsoft VS Code/Code.exe"),
    Path("C:/Program Files (x86)/Microsoft VS Code/Code.exe"),
]


# ============================================================
# VARIABLES INTERNAS
# ============================================================

eventos = queue.Queue()
ultima_activacion = 0.0


# ============================================================
# CONEXIÓN CON SPOTIFY
# ============================================================

def conectar_spotify():
    # Comprueba que configuraste las credenciales en PowerShell.
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Faltan las credenciales de Spotify.\n"
            "Configura SPOTIFY_CLIENT_ID y "
            "SPOTIFY_CLIENT_SECRET en PowerShell."
        )

    auth = SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=str(Path(__file__).parent / ".spotify_cache"),
        open_browser=True,
    )

    return spotipy.Spotify(auth_manager=auth)


# ============================================================
# BUSCAR Y ABRIR VISUAL STUDIO CODE
# ============================================================

def buscar_vscode():
    # Busca Code.exe en las ubicaciones habituales de Windows.
    for ruta in RUTAS_VSCODE:
        if ruta.exists():
            return str(ruta)

    # También intenta encontrar el comando "code" en PATH.
    comando = shutil.which("code")
    if comando:
        return comando

    return None


def abrir_vscode():
    vscode = buscar_vscode()

    if vscode:
        try:
            subprocess.Popen([vscode])
            print("Visual Studio Code abierto.")
        except OSError as error:
            print(f"No se pudo abrir VS Code: {error}")
    else:
        print(
            "No se encontró Visual Studio Code.\n"
            "Agrega la ruta de Code.exe en RUTAS_VSCODE."
        )


# ============================================================
# REPRODUCIR LA CANCIÓN
# ============================================================

def reproducir_cancion(sp):
    try:
        # Intenta abrir Spotify Desktop.
        try:
            os.startfile("spotify:")
        except OSError:
            print(
                "No se pudo abrir Spotify mediante su protocolo. "
                "Comprueba que Spotify esté instalado."
            )

        # Da tiempo a Spotify para iniciar.
        time.sleep(3)

        # Consulta los dispositivos disponibles en la cuenta.
        dispositivos = sp.devices().get("devices", [])

        if not dispositivos:
            print(
                "No hay dispositivos Spotify disponibles.\n"
                "Abre Spotify, inicia sesión y reproduce algo "
                "o selecciona este equipo como dispositivo."
            )
            return

        # Prefiere un dispositivo que ya esté activo.
        dispositivo = next(
            (d for d in dispositivos if d.get("is_active")),
            None,
        )

        # Si ninguno está activo, prefiere Spotify Desktop.
        if dispositivo is None:
            dispositivo = next(
                (d for d in dispositivos
                 if d.get("type") == "Computer"),
                dispositivos[0],
            )

        device_id = dispositivo.get("id")

        if not device_id:
            print("Spotify no devolvió un ID de dispositivo válido.")
            return

        # Solicita la reproducción de la canción configurada.
        sp.start_playback(
            device_id=device_id,
            uris=[TRACK_URI],
        )

        print(
            f"Reproduciendo canción en: "
            f"{dispositivo.get('name', 'dispositivo Spotify')}"
        )

    except spotipy.SpotifyException as error:
        print(f"Spotify devolvió un error: {error}")
        print(
            "Comprueba tu autorización, que la cuenta tenga "
            "Premium y que exista un dispositivo disponible."
        )

    except Exception as error:
        print(f"Error al reproducir la canción: {error}")


# ============================================================
# DETECCIÓN DE APLAUSOS
# ============================================================

def escuchar(indata, frames, tiempo_audio, estado):
    global ultima_activacion

    # Calcula el volumen RMS del sonido captado.
    volumen = float(np.sqrt(np.mean(indata ** 2)))

    ahora = time.monotonic()

    # Evita poner demasiados eventos en la cola.
    if volumen > UMBRAL and (ahora - ultima_activacion) >= ESPERA:
        ultima_activacion = ahora
        eventos.put("aplauso")


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    print("=" * 48)
    print(" ASISTENTE POR APLAUSOS")
    print("=" * 48)

    print("Conectando con Spotify...")

    try:
        sp = conectar_spotify()

        # Comprueba que la autenticación funcione.
        usuario = sp.current_user()
        print(
            "Conectado con Spotify como:",
            usuario.get("display_name") or usuario.get("id"),
        )

    except Exception as error:
        print(f"No se pudo conectar con Spotify: {error}")
        print(
            "\nRevisa las credenciales, la Redirect URI "
            "y la autorización de la aplicación."
        )
        return

    print("\nAsistente listo.")
    print("Da una palmada para abrir VS Code y reproducir la canción.")
    print("Presiona Ctrl+C para terminar.\n")

    try:
        # El callback de audio solo detecta y encola el evento.
        # Las acciones se ejecutan en el bucle principal.
        with sd.InputStream(
            channels=1,
            samplerate=44100,
            blocksize=1024,
            callback=escuchar,
        ):
            while True:
                try:
                    evento = eventos.get(timeout=0.5)
                except queue.Empty:
                    continue

                if evento == "aplauso":
                    print("\n¡Aplauso detectado!")

                    abrir_vscode()
                    reproducir_cancion(sp)

    except KeyboardInterrupt:
        print("\nAsistente detenido.")

    except Exception as error:
        print(f"Error al acceder al micrófono: {error}")
        print(
            "Comprueba que el micrófono esté conectado "
            "y que Windows permita su uso."
        )


if __name__ == "__main__":
    main()
