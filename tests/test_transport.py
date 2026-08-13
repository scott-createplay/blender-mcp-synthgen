"""Tests for MCP transport — reconnection, error handling, TransportError."""

import json
import socket
import threading
import pytest

from synthgen.mcp.transport import SocketTransport, TransportError


class TestTransportError:
    def test_connection_refused(self):
        transport = SocketTransport(host="localhost", port=19999, connect_timeout=1.0)
        with pytest.raises(TransportError, match="Blender"):
            transport._connect()

    def test_connection_timeout(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("localhost", 0))
        _, port = srv.getsockname()
        # listen backlog 0 + don't accept -> connection will hang
        srv.listen(0)

        # Fill the backlog so the next connect times out
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.connect(("localhost", port))

        transport = SocketTransport(host="localhost", port=port, connect_timeout=0.5)
        try:
            with pytest.raises(TransportError, match="timed out"):
                transport._connect()
        finally:
            blocker.close()
            srv.close()

    def test_error_message_includes_port(self):
        transport = SocketTransport(host="localhost", port=19998, connect_timeout=0.5)
        with pytest.raises(TransportError) as exc_info:
            transport._connect()
        assert "19998" in str(exc_info.value)


class TestSocketReconnect:
    """Test that SocketTransport reconnects after the socket dies."""

    @pytest.fixture()
    def echo_server(self):
        """A tiny TCP server that echoes back a fixed JSON response."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("localhost", 0))
        srv.listen(1)
        _, port = srv.getsockname()
        stop = threading.Event()
        conns = []

        def serve():
            srv.settimeout(0.5)
            while not stop.is_set():
                try:
                    conn, _ = srv.accept()
                except (socket.timeout, OSError):
                    continue
                conns.append(conn)
                threading.Thread(target=handle, args=(conn,), daemon=True).start()

        def handle(conn):
            try:
                while not stop.is_set():
                    data = conn.recv(4096)
                    if not data:
                        break
                    resp = {"status": "ok", "result": {"output": "hello"}}
                    conn.sendall(json.dumps(resp).encode())
            except OSError:
                pass

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        yield port, stop, conns
        stop.set()
        for c in conns:
            try:
                c.close()
            except OSError:
                pass
        srv.close()
        t.join(timeout=2)

    def test_reconnects_after_server_drops(self, echo_server):
        port, stop, conns = echo_server
        transport = SocketTransport(host="localhost", port=port, connect_timeout=2.0)

        result = transport.execute_python("print('hi')")
        assert result == {"output": "hello"}

        # Kill the accepted connection server-side
        for c in conns:
            c.close()
        conns.clear()
        transport._close_socket()

        result2 = transport.execute_python("print('hi again')")
        assert result2 == {"output": "hello"}

    def test_close_socket_clears_state(self):
        transport = SocketTransport(host="localhost", port=19997, connect_timeout=0.5)
        transport._sock = socket.socket()
        transport._close_socket()
        assert transport._sock is None
