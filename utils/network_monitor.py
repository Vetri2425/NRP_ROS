"""
Network monitoring utility for WiFi signal strength and LoRa connection status.

Provides cached network telemetry data for Socket.IO rover_data emissions.
Designed for Jetson Nano/Ubuntu systems with minimal performance impact.
"""

import subprocess
import re
import time
import os
import threading
from typing import Dict, Optional


class NetworkMonitor:
    """Monitor WiFi signal strength and LoRa connection status with caching.

    IMPORTANT: get_network_data() is called from the roslibpy WebSocket
    callback thread (via schedule_fast_emit → get_rover_data).  It must
    NEVER run subprocesses inline — that would block ALL telemetry.
    Instead, a background thread refreshes the cache every cache_duration
    seconds, and get_network_data() always returns the cache instantly.
    """

    def __init__(self, interface: str = "wlan0", cache_duration: float = 3.0):
        """
        Initialize network monitor with caching.

        Args:
            interface: WiFi interface name (wlan0, wlp2s0, etc.)
            cache_duration: Seconds to cache network data (reduces overhead)
        """
        self.interface = interface
        self.cache_duration = cache_duration
        self.last_check_time = 0.0
        self._lock = threading.Lock()
        self.cached_data = {
            "connection_type": "none",
            "wifi_signal_strength": 0,
            "wifi_rssi": -100,
            "interface": interface,
            "lora_connected": False,
            "wifi_connected": False
        }

        # Auto-detect WiFi interface on first run
        self._auto_detect_interface()

        # Start background refresh thread so get_network_data() never blocks
        self._bg_thread = threading.Thread(
            target=self._background_refresh_loop, daemon=True
        )
        self._bg_thread.start()
    
    def _auto_detect_interface(self) -> None:
        """Auto-detect active WiFi interface if default fails"""
        try:
            # Try default interface first
            result = subprocess.run(
                ['iwconfig', self.interface],
                capture_output=True,
                text=True,
                timeout=1
            )
            
            if result.returncode == 0 and 'IEEE 802.11' in result.stdout:
                print(f"[NetworkMonitor] Using WiFi interface: {self.interface}")
                return
            
            # If default fails, try to find any WiFi interface
            result = subprocess.run(
                ['iwconfig'],
                capture_output=True,
                text=True,
                timeout=1
            )
            
            # Parse output for wireless interfaces
            for line in result.stdout.split('\n'):
                if 'IEEE 802.11' in line:
                    match = re.match(r'^(\S+)', line)
                    if match:
                        detected_interface = match.group(1)
                        print(f"[NetworkMonitor] Auto-detected WiFi interface: {detected_interface}")
                        self.interface = detected_interface
                        self.cached_data['interface'] = detected_interface
                        return
            
            print(f"[NetworkMonitor] Warning: No WiFi interface detected, using default: {self.interface}")
            
        except Exception as e:
            print(f"[NetworkMonitor] Interface detection error: {e}")
    
    def get_wifi_signal_strength(self, rssi_dbm: int) -> int:
        """
        Convert RSSI (dBm) to 0-4 signal strength scale.
        
        Scale matches typical WiFi quality metrics:
        - 4: Excellent (-50 dBm or better)
        - 3: Good (-60 to -50 dBm)
        - 2: Fair (-70 to -60 dBm)
        - 1: Weak (-80 to -70 dBm)
        - 0: No signal (worse than -80 dBm)
        
        Args:
            rssi_dbm: Signal strength in dBm (typically -30 to -100)
            
        Returns:
            Signal strength on 0-4 scale
        """
        if rssi_dbm >= -50:
            return 4  # Excellent
        elif rssi_dbm >= -60:
            return 3  # Good
        elif rssi_dbm >= -70:
            return 2  # Fair
        elif rssi_dbm >= -80:
            return 1  # Weak
        else:
            return 0  # No signal / Disconnected
    
    def get_wifi_info(self) -> Dict:
        """
        Read WiFi signal strength using iwconfig command.
        
        Returns dict with signal strength, RSSI, and connection status.
        Safe to call frequently - returns default values on any error.
        
        Returns:
            {
                "wifi_signal_strength": 0-4,
                "wifi_rssi": -100 to -30,
                "interface": "wlan0",
                "wifi_connected": bool
            }
        """
        try:
            result = subprocess.check_output(
                ['iwconfig', self.interface],
                stderr=subprocess.DEVNULL,
                universal_newlines=True,
                timeout=2
            )
            
            # Check if interface is connected (has ESSID)
            wifi_connected = 'ESSID:off/any' not in result and 'ESSID:"' in result
            
            # Parse signal level: "Signal level=-45 dBm" or "Link Quality=70/70  Signal level=-45 dBm"
            rssi_match = re.search(r'Signal level=(-?\d+)', result)
            
            if rssi_match and wifi_connected:
                rssi = int(rssi_match.group(1))
                signal_strength = self.get_wifi_signal_strength(rssi)
                
                return {
                    "wifi_signal_strength": signal_strength,
                    "wifi_rssi": rssi,
                    "interface": self.interface,
                    "wifi_connected": True
                }
            else:
                # Interface exists but not connected
                return {
                    "wifi_signal_strength": 0,
                    "wifi_rssi": -100,
                    "interface": self.interface,
                    "wifi_connected": False
                }
                
        except subprocess.TimeoutExpired:
            print(f"[NetworkMonitor] WiFi check timeout for {self.interface}")
        except subprocess.CalledProcessError as e:
            print(f"[NetworkMonitor] iwconfig error for {self.interface}: {e}")
        except FileNotFoundError:
            print("[NetworkMonitor] iwconfig not found - install wireless-tools package")
        except Exception as e:
            print(f"[NetworkMonitor] Unexpected WiFi error: {e}")
        
        # Return disconnected state on any error
        return {
            "wifi_signal_strength": 0,
            "wifi_rssi": -100,
            "interface": self.interface,
            "wifi_connected": False
        }
    
    def get_connection_type(self) -> str:
        """
        Detect active connection type: wifi, ethernet, or none.
        
        Checks for active network connections and determines the type.
        Priority: WiFi > Ethernet > None
        
        Returns:
            'wifi' | 'ethernet' | 'none'
        """
        try:
            # Method 1: Check IP route to see default gateway interface
            result = subprocess.run(
                ['ip', 'route', 'show', 'default'],
                capture_output=True,
                text=True,
                timeout=1
            )
            
            if result.returncode == 0 and result.stdout:
                # Parse: "default via 192.168.1.1 dev eth0"
                match = re.search(r'dev\s+(\S+)', result.stdout)
                if match:
                    default_interface = match.group(1)
                    
                    # Check if it's a wireless interface
                    if any(prefix in default_interface.lower() for prefix in ['wl', 'wlan', 'wifi']):
                        return 'wifi'
                    # Check if it's an ethernet interface
                    elif any(prefix in default_interface.lower() for prefix in ['eth', 'en', 'eno', 'enp']):
                        return 'ethernet'
            
            # Method 2: Fallback - check if WiFi interface has IP address
            try:
                result = subprocess.run(
                    ['ip', 'addr', 'show', self.interface],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                
                if result.returncode == 0:
                    # Check for inet (IPv4) address
                    if 'inet ' in result.stdout and 'UP' in result.stdout:
                        return 'wifi'
            except Exception:
                pass
            
            # Method 3: Check ethernet interfaces for active connection
            eth_interfaces = ['eth0', 'eno1', 'enp0s3', 'enp1s0']
            for eth_if in eth_interfaces:
                try:
                    result = subprocess.run(
                        ['ip', 'addr', 'show', eth_if],
                        capture_output=True,
                        text=True,
                        timeout=1
                    )
                    
                    if result.returncode == 0:
                        # Check for inet address and UP state
                        if 'inet ' in result.stdout and 'UP' in result.stdout:
                            return 'ethernet'
                except Exception:
                    continue
            
            return 'none'
            
        except Exception as e:
            print(f"[NetworkMonitor] Connection type detection error: {e}")
            return 'none'
    
    def get_lora_status(self) -> bool:
        """
        Check LoRa connection status.
        
        This is a placeholder implementation. Customize based on your LoRa hardware:
        
        Option 1 - Serial port check:
            return os.path.exists('/dev/ttyUSB0') or os.path.exists('/dev/ttyACM1')
        
        Option 2 - Check for LoRa process:
            result = subprocess.run(['pgrep', '-f', 'lora'], capture_output=True)
            return result.returncode == 0
        
        Option 3 - Read from LoRa status file (if your driver creates one):
            try:
                with open('/sys/class/lora/status', 'r') as f:
                    return f.read().strip() == 'connected'
            except:
                return False
        
        Option 4 - Check timestamp of last received packet:
            lora_last_rx = '/tmp/lora_last_rx'
            if os.path.exists(lora_last_rx):
                age = time.time() - os.path.getmtime(lora_last_rx)
                return age < 30  # Connected if packet within last 30 seconds
        
        Returns:
            True if LoRa is connected, False otherwise
        """
        try:
            # TODO: Replace with actual LoRa hardware check
            # Currently returns False (no LoRa)
            
            # Example: Check if LoRa serial device exists
            lora_devices = ['/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyS0']
            for device in lora_devices:
                if os.path.exists(device):
                    # Device exists, but you might want to do a more robust check
                    # like reading device info or checking for recent activity
                    return True
            
            return False
            
        except Exception as e:
            print(f"[NetworkMonitor] LoRa status check error: {e}")
            return False
    
    def _background_refresh_loop(self) -> None:
        """Periodically refresh network data in a background thread.

        This keeps cached_data up-to-date so get_network_data() can
        return instantly without running any subprocesses.
        """
        while True:
            try:
                self._refresh_data()
            except Exception as e:
                print(f"[NetworkMonitor] Background refresh error: {e}")
            time.sleep(self.cache_duration)

    def _refresh_data(self) -> None:
        """Run the actual subprocess calls and update the cache."""
        connection_type = self.get_connection_type()
        wifi_info = self.get_wifi_info()
        lora_status = self.get_lora_status()

        # For ethernet connections, set WiFi signal to max (4) to show green status
        if connection_type == 'ethernet':
            wifi_info['wifi_signal_strength'] = 4
            wifi_info['wifi_rssi'] = -30  # Excellent signal equivalent

        new_data = {
            "connection_type": connection_type,
            **wifi_info,
            "lora_connected": lora_status
        }

        with self._lock:
            self.cached_data = new_data
            self.last_check_time = time.time()

    def get_network_data(self, force_refresh: bool = False) -> Dict:
        """
        Get network data from cache (never blocks).

        The background thread refreshes data every cache_duration seconds.
        This method always returns instantly, making it safe to call from
        the roslibpy WebSocket callback thread or any latency-sensitive path.

        Args:
            force_refresh: If True, run a synchronous refresh (only use
                from non-critical threads, e.g. CLI testing).

        Returns:
            {
                "connection_type": "wifi" | "ethernet" | "none",
                "wifi_signal_strength": 0-4,
                "wifi_rssi": -100 to -30,
                "interface": "wlan0",
                "wifi_connected": bool,
                "lora_connected": bool
            }
        """
        if force_refresh:
            self._refresh_data()

        with self._lock:
            return self.cached_data.copy()
    
    def get_signal_quality_label(self, signal_strength: int) -> str:
        """
        Convert signal strength number to human-readable label.
        
        Args:
            signal_strength: 0-4 scale value
            
        Returns:
            Quality label string
        """
        labels = {
            4: "Excellent",
            3: "Good",
            2: "Fair",
            1: "Weak",
            0: "Disconnected"
        }
        return labels.get(signal_strength, "Unknown")


# Convenience function for one-off checks
def get_current_network_status(interface: str = "wlan0") -> Dict:
    """
    Get current network status without caching (one-time check).
    
    Useful for debugging or one-off status checks.
    
    Args:
        interface: WiFi interface name
        
    Returns:
        Network status dictionary
    """
    monitor = NetworkMonitor(interface=interface, cache_duration=0)
    return monitor.get_network_data(force_refresh=True)


if __name__ == "__main__":
    """Test the network monitor"""
    print("Testing Network Monitor...")
    print("-" * 50)
    
    monitor = NetworkMonitor()
    data = monitor.get_network_data(force_refresh=True)
    
    print(f"Connection Type: {data['connection_type'].upper()}")
    print(f"Interface: {data['interface']}")
    print(f"WiFi Connected: {data['wifi_connected']}")
    print(f"WiFi Signal Strength: {data['wifi_signal_strength']}/4 ({monitor.get_signal_quality_label(data['wifi_signal_strength'])})")
    print(f"WiFi RSSI: {data['wifi_rssi']} dBm")
    print(f"LoRa Connected: {data['lora_connected']}")
    print("-" * 50)
    
    # Test caching
    print("\nTesting cache (should be instant)...")
    start = time.time()
    cached_data = monitor.get_network_data()
    print(f"Cache retrieval took: {(time.time() - start)*1000:.2f}ms")
    
    print("\nTest complete!")
