"""Tokens de un solo uso: verificacion del correo y renovacion de sesion.

En la base se guarda solo el sha256 del token (ajuste A-12, RNF-01): con
acceso de solo lectura a identity_db no se puede activar una cuenta ajena
ni robar una sesion.
"""

import hashlib
import secrets


def hash_de(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_opaco():
    """Devuelve (token en claro, su sha256). El claro solo viaja al usuario."""
    token = secrets.token_urlsafe(32)
    return token, hash_de(token)
