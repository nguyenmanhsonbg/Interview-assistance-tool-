from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import urllib.request


def main() -> None:
    root = pathlib.Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))

    from app.application import create_application
    from app.config import AppConfig
    from app.server import create_server

    with tempfile.TemporaryDirectory() as temporary:
        config = AppConfig(
            port=0,
            data_directory=pathlib.Path(temporary),
            web_directory=root / "web",
        )
        application = create_application(config, initial_pin="246810")
        server = create_server(
            config,
            router=application.router,
            security=application.security,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        application.start()
        thread.start()
        try:
            address = f"http://127.0.0.1:{server.server_address[1]}"
            with urllib.request.urlopen(address + "/api/v1/health", timeout=3) as response:
                body = json.loads(response.read())
            assert body["success"] and body["data"]["status"] == "ok"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
            application.stop()
    print("packaged HTTP smoke: OK")


if __name__ == "__main__":
    main()
