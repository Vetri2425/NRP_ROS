#!/usr/bin/env python3
"""
LoRa Receiver - Direct USB Communication
Bypasses serial driver issues by using PyUSB
Listens for messages from transmitter and provides RTCM binary data
"""

import usb.core
import usb.util
import time
import sys
from datetime import datetime
from typing import Optional, Callable, List


class LoRaUSBReceiver:
    """Communicate with CH340-based LoRa receiver via USB"""
    
    def __init__(self, vendor_id=0x1a86, product_id=0x7523):
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.dev = None
        self.endpoint_out = None
        self.endpoint_in = None
        self.message_count = 0
        self.is_connected = False
        
    def connect(self) -> bool:
        """Find and connect to CH340 device"""
        print(f"Searching for CH340 device (ID: {hex(self.vendor_id)}:{hex(self.product_id)})...")
        
        # Find device
        self.dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if not self.dev:
            print("✗ Device not found!")
            return False
        
        print(f"✓ Device found: {self.dev}")
        
        try:
            # Set configuration
            self.dev.set_configuration()
            print("✓ Configuration set")
        except Exception as e:
            print(f"✗ Could not set configuration: {e}")
            return False
        
        # Get endpoints
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]
        
        # Find all endpoints
        all_endpoints_in = []
        all_endpoints_out = []
        
        for ep in intf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                all_endpoints_in.append(ep)
            else:
                all_endpoints_out.append(ep)
        
        print(f"Found {len(all_endpoints_in)} IN endpoints and {len(all_endpoints_out)} OUT endpoints")
        
        # Use the first bulk endpoints (usually 0x82 and 0x02)
        if len(all_endpoints_in) > 0:
            self.endpoint_in = all_endpoints_in[0]
            print(f"Using IN endpoint: {hex(self.endpoint_in.bEndpointAddress)}")
        
        if len(all_endpoints_out) > 0:
            self.endpoint_out = all_endpoints_out[0]
            print(f"Using OUT endpoint: {hex(self.endpoint_out.bEndpointAddress)}")
        
        if not self.endpoint_out or not self.endpoint_in:
            print("✗ Could not find USB endpoints")
            return False
        
        self.is_connected = True
        print(f"✓ Endpoints configured - Ready to receive!")
        return True
    
    def send_command(self, cmd: str) -> bool:
        """Send AT command to receiver"""
        try:
            if isinstance(cmd, str):
                cmd = f"{cmd}\r\n".encode()
            self.endpoint_out.write(cmd)
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False
    
    def read_response(self, timeout_ms: int = 1000) -> str:
        """Read response from device"""
        try:
            data = self.endpoint_in.read(1024, timeout=timeout_ms)
            return data.tobytes().decode('utf-8', errors='ignore')
        except usb.core.USBTimeoutError:
            return ""
        except Exception as e:
            print(f"Error reading: {e}")
            return ""
    
    def get_receiver_info(self) -> None:
        """Query receiver configuration"""
        print("\n" + "=" * 60)
        print("RECEIVER CONFIGURATION")
        print("=" * 60)
        
        commands = [
            ("AT", "Test connection"),
            ("AT+ADDRESS?", "Receiver address"),
            ("AT+BAND?", "Frequency band"),
            ("AT+PARAMETER?", "LoRa parameters"),
            ("AT+NETWORKID?", "Network ID"),
            ("AT+MODE?", "Operating mode"),
        ]
        
        for cmd, desc in commands:
            print(f"\n{desc}:")
            print(f"  Command: {cmd}")
            
            # Clear buffer
            try:
                while True:
                    self.endpoint_in.read(1024, timeout=100)
            except:
                pass
            
            # Send command
            self.send_command(cmd)
            
            # Read response
            response = self.read_response(500)
            if response:
                print(f"  Response: {response.strip()}")
            else:
                print(f"  Response: (no response)")
        
        print("\n" + "=" * 60)
    
    def read_message_data(self, timeout_ms: int = 100) -> Optional[bytes]:
        """
        Read raw message data from LoRa receiver.
        Used for RTK correction injection.
        
        Returns:
            bytes: Raw RTCM correction data, or None if timeout
        """
        try:
            data = self.endpoint_in.read(256, timeout=timeout_ms)
            if data:
                return data.tobytes()
            return None
        except usb.core.USBTimeoutError:
            return None
        except Exception as e:
            print(f"Error reading LoRa data: {e}")
            return None
    
    def listen(self, duration: Optional[int] = None, callback: Optional[Callable[[bytes], None]] = None) -> None:
        """
        Listen for incoming messages from transmitter
        
        Args:
            duration: Listen duration in seconds (None = infinite)
            callback: Optional callback function for each message received
        """
        print("\n" + "=" * 60)
        print("LISTENING FOR MESSAGES")
        print("=" * 60)
        print(f"Start time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Device: USB 1a86:7523")
        print("-" * 60)
        print("Waiting for incoming LoRa messages from transmitter...")
        print("(Press Ctrl+C to stop)\n")
        sys.stdout.flush()
        
        start_time = time.time()
        buffer = ""
        last_msg_time = time.time()
        poll_count = 0
        
        try:
            # Exit the listen loop when the device is closed via `close()`
            while self.is_connected:
                if duration and (time.time() - start_time) > duration:
                    print(f"\nTimeout reached ({duration}s)")
                    break
                
                try:
                    # Try to read data
                    data = None
                    try:
                        data = self.endpoint_in.read(256, timeout=100)
                    except usb.core.USBTimeoutError:
                        pass
                    except:
                        pass
                    
                    if data:
                        raw_bytes = data.tobytes()
                        
                        # Try to decode as text for display
                        text = raw_bytes.decode('utf-8', errors='ignore')
                        if text:
                            buffer += text
                            last_msg_time = time.time()
                            
                            # Invoke callback with raw bytes
                            if callback:
                                try:
                                    callback(raw_bytes)
                                except Exception as e:
                                    print(f"Callback error: {e}")
                        
                        # Process complete lines
                        while '\n' in buffer or '\r' in buffer:
                            if '\r\n' in buffer:
                                line, buffer = buffer.split('\r\n', 1)
                            elif '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                            elif '\r' in buffer:
                                line, buffer = buffer.split('\r', 1)
                            else:
                                break
                            
                            line = line.strip()
                            if line and len(line) > 2:  # Filter out empty/short lines
                                self.message_count += 1
                                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                                
                                # Handle both +RCV= format and plain text format
                                if "+RCV=" in line:
                                    # Parse LoRa message: +RCV=<Address>,<Length>,<Data>,<RSSI>,<SNR>
                                    print(f"\n{'='*60}")
                                    print(f"[{timestamp}] LoRa Message #{self.message_count}:")
                                    print(f"  Raw: {line}")
                                    
                                    try:
                                        # Split by +RCV= and then parse
                                        rcv_data = line.split('+RCV=')[1]
                                        parts = rcv_data.split(',', 4)  # Split into max 5 parts
                                        
                                        if len(parts) >= 3:
                                            from_addr = parts[0].strip()
                                            length = parts[1].strip()
                                            msg_data = parts[2].strip()
                                            
                                            print(f"  ✓ From Address: {from_addr}")
                                            print(f"  ✓ Payload Length: {length} bytes")
                                            print(f"  ✓ Data: {msg_data}")
                                            
                                            if len(parts) >= 4:
                                                rssi = parts[3].strip() if len(parts) > 3 else "N/A"
                                                print(f"  ✓ RSSI: {rssi} dBm")
                                            
                                            if len(parts) >= 5:
                                                snr = parts[4].strip() if len(parts) > 4 else "N/A"
                                                print(f"  ✓ SNR: {snr} dB")
                                    
                                    except Exception as e:
                                        print(f"  Note: {e}")
                                    
                                    print(f"{'='*60}\n")
                                    sys.stdout.flush()
                                
                                else:
                                    # Plain text message
                                    print(f"\n{'='*60}")
                                    print(f"[{timestamp}] LoRa Message #{self.message_count}:")
                                    print(f"  ✓ Data: {line}")
                                    print(f"{'='*60}\n")
                                    sys.stdout.flush()
                    else:
                        # No data, keep polling
                        poll_count += 1
                        if poll_count % 50 == 0:  # Print status every 5 seconds
                            elapsed = time.time() - last_msg_time
                            if elapsed > 10:
                                print(f"[{datetime.now().strftime('%H:%M:%S')}] Waiting... (no messages in {int(elapsed)}s)", flush=True)
                
                except usb.core.USBTimeoutError:
                    pass
                except Exception as e:
                    print(f"Error reading: {e}", flush=True)
                
                time.sleep(0.05)  # Small delay to reduce CPU usage
        
        except KeyboardInterrupt:
            print("\n\nStopped by user")
        finally:
            # Ensure we mark connection state false when listen ends
            self.is_connected = False
        
        elapsed = time.time() - start_time
        print("-" * 60)
        print(f"Stop time: {datetime.now().strftime('%H:%M:%S')}")
        print(f"Duration: {elapsed:.1f} seconds")
        print(f"Messages received: {self.message_count}")
        print("=" * 60)
        sys.stdout.flush()
    
    def close(self) -> None:
        """Close connection"""
        print("Closing connection...")
        # Mark as disconnected which will cause any running listen() loop to exit
        self.is_connected = False


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="LoRa USB Receiver - Listen for transmitter messages")
    parser.add_argument("--duration", type=int, help="Listen duration in seconds")
    parser.add_argument("--info", action="store_true", help="Show receiver info only")
    
    args = parser.parse_args()
    
    receiver = LoRaUSBReceiver()
    
    if not receiver.connect():
        sys.exit(1)
    
    try:
        receiver.get_receiver_info()
        
        if not args.info:
            receiver.listen(args.duration)
    
    except KeyboardInterrupt:
        print("\n\nInterrupted")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        receiver.close()


if __name__ == "__main__":
    main()
