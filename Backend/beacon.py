import socket
import threading
import time
import json
import logging
import os
import subprocess

logger = logging.getLogger("beacon")


class RoverBeacon:
    def __init__(self, rover_id: str, rover_name: str, port: int = 5001, beacon_port: int = 5002, interval: float = 2.0):
        self.rover_id = rover_id or os.environ.get('ROVER_ID', socket.gethostname())
        self.rover_name = rover_name or os.environ.get('ROVER_NAME', self.rover_id)
        self.port = port
        self.beacon_port = beacon_port
        self.interval = interval
        self._running = False
        self._thread = None
        self._socket = None
        self._start_time = time.time()

    def start(self):
        """Start the beacon broadcasting in a daemon thread."""
        if self._running:
            return
        
        self._running = True
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()
        logger.info(f"Beacon started: {self.rover_name} ({self.rover_id}) broadcasting on UDP {self.beacon_port}")

    def stop(self):
        """Stop the beacon broadcasting."""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
        logger.info("Beacon stopped")

    def _get_local_ip(self) -> str:
        """Get local IP without requiring internet access."""
        try:
            # Create a UDP socket and connect to a broadcast address
            # This doesn't send any data, just determines the outgoing interface
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0)
            s.connect(('10.254.254.254', 1))  # Doesn't need to be reachable
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            pass

        # Fallback: parse hostname resolution
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if not ip.startswith('127.'):
                return ip
        except Exception:
            pass

        # Last resort: scan interfaces
        try:
            result = subprocess.run(
                ['hostname', '-I'], capture_output=True, text=True, timeout=2
            )
            ips = result.stdout.strip().split()
            for ip in ips:
                if not ip.startswith('127.') and ':' not in ip:
                    return ip
        except Exception:
            pass

        return '127.0.0.1'

    def _broadcast_loop(self):
        """Main broadcast loop running in daemon thread."""
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception as e:
            logger.error(f"Failed to create broadcast socket: {e}")
            return

        while self._running:
            try:
                # Get current IP (re-fetch each time in case it changes)
                current_ip = self._get_local_ip()
                
                # Build beacon payload
                payload = {
                    "type": "rover_beacon",
                    "rover_id": self.rover_id,
                    "rover_name": self.rover_name,
                    "ip": current_ip,
                    "port": self.port,
                    "version": "1.0",
                    "uptime": int(time.time() - self._start_time),
                    "timestamp": time.time()
                }

                # Send beacon
                message = json.dumps(payload).encode('utf-8')
                self._socket.sendto(message, ('255.255.255.255', self.beacon_port))
                
                logger.debug(f"Beacon sent: {self.rover_name} at {current_ip}:{self.port}")

            except Exception as e:
                logger.error(f"Beacon broadcast error: {e}")

            # Sleep for interval
            time.sleep(self.interval)

        # Clean up socket
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None