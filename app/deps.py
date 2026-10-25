from fastapi import Request
from .vault import Vault


def get_vault(request: Request) -> Vault:
    vault = request.app.state.vault
    vault.authenticate(request.cookies.get("sultan_session", ""))
    return vault
