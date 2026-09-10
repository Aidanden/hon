#!/usr/bin/env python3
"""Entry point for HoN Net Guard."""

from __future__ import annotations

import signal
import sys


def main() -> int:
    from hon_net_guard.gui import App

    app = App()
    exit_code = 0

    def request_close(*_args) -> None:
        try:
            # Schedule on Tk thread; also force quit if already closing.
            if getattr(app, "_closing", False):
                try:
                    app.quit()
                except Exception:
                    pass
                return
            app.after(0, app._on_close)
        except Exception:
            try:
                app.guard.shutdown(remove_qos=True)
            except Exception:
                pass
            try:
                app.quit()
            except Exception:
                pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, request_close)
        except Exception:
            pass

    # Keep Tk responsive to Ctrl+C by pumping a no-op timer.
    def _heartbeat() -> None:
        if getattr(app, "_closing", False):
            return
        try:
            app.after(250, _heartbeat)
        except Exception:
            pass

    try:
        app.after(250, _heartbeat)
        app.mainloop()
    except KeyboardInterrupt:
        request_close()
        exit_code = 130
    finally:
        try:
            if not getattr(app, "_closing", False):
                app.guard.shutdown(remove_qos=True)
            elif getattr(app, "guard", None) is not None:
                # Ensure monitor is stopped even if close raced.
                app.guard.stop_monitor()
        except Exception:
            pass
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
