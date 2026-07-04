"""Sonda de protocolo para el enchufe CozyLife (puerto 5555).

Prueba varios formatos de mensaje conocidos del protocolo local CozyLife
y reporta cual obtiene respuesta. Uso:

    python tools/test_cozylife.py 192.168.1.15
"""

import json
import socket
import sys
import time

PORT = 5555


def escuchar_saludo(ip: str, wait: float = 4) -> str:
    """Algunos dispositivos mandan un mensaje al conectarse, sin preguntar."""
    try:
        s = socket.create_connection((ip, PORT), timeout=wait)
        s.settimeout(wait)
        try:
            data = s.recv(4096)
            return repr(data.decode(errors="replace")) if data else "(conexion cerrada sin datos)"
        except socket.timeout:
            return "(sin saludo espontaneo)"
        finally:
            s.close()
    except Exception as e:
        return f"ERROR: {e}"


def probe(ip: str, payload: dict, term: str, wait: float = 4) -> str:
    """Manda un mensaje y espera respuesta."""
    try:
        s = socket.create_connection((ip, PORT), timeout=wait)
        s.sendall((json.dumps(payload) + term).encode())
        s.settimeout(wait)
        data = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
        except socket.timeout:
            pass
        s.close()
        return repr(data.decode(errors="replace")) if data else "(sin respuesta)"
    except Exception as e:
        return f"ERROR: {e}"


def main():
    if len(sys.argv) != 2:
        print("Uso: python tools/test_cozylife.py <IP-del-enchufe>")
        sys.exit(1)

    ip = sys.argv[1]
    sn = str(int(time.time() * 1000))

    print(f"=== Sondeando {ip}:{PORT} ===\n")

    print("--- saludo espontaneo (solo escuchar) ---")
    print(escuchar_saludo(ip))
    print()

    pruebas = [
        ("cmd0 info, term \\r\\n", {"cmd": 0, "pv": 0, "sn": sn, "msg": {}}, "\r\n"),
        ("cmd0 info, term \\n", {"cmd": 0, "pv": 0, "sn": sn, "msg": {}}, "\n"),
        ("cmd0 info, sin term", {"cmd": 0, "pv": 0, "sn": sn, "msg": {}}, ""),
        ("cmd2 query attr[0]", {"cmd": 2, "pv": 0, "sn": sn, "msg": {"attr": [0]}}, "\r\n"),
        ("cmd2 query attr[1]", {"cmd": 2, "pv": 0, "sn": sn, "msg": {"attr": [1]}}, "\r\n"),
        ("cmd3 set vacio", {"cmd": 3, "pv": 0, "sn": sn, "msg": {"attr": [], "data": {}}}, "\r\n"),
    ]

    for nombre, payload, term in pruebas:
        print(f"--- {nombre} ---")
        print(probe(ip, payload, term))
        print()


if __name__ == "__main__":
    main()
