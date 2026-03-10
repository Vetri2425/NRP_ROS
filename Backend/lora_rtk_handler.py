"""
LoRa RTK Handler - Manages LoRa receiver connection and RTCM data injection
Integrates LoRa-received RTCM corrections with existing RTK injection system
"""

import threading
import time
import sys
from datetime import datetime
from typing import Optional, Callable
import logging

try:
    from .lora_receiver_usb import LoRaUSBReceiver
except ImportError:
    from lora_receiver_usb import LoRaUSBReceiver

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [LoRa RTK] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class LoRaRTKHandler:
    """
    Handles LoRa receiver connection and RTCM data injection
    Runs in background thread, feeds data to RTK injection function
    """
    
    def __init__(self, rtk_inject_callback: Callable[[bytes], bool]):
        """
        Initialize LoRa RTK handler
        
        Args:
            rtk_inject_callback: Function to call with received RTCM bytes
                                Should return True if injection successful
        """
        self.receiver = None
        self.rtk_inject_callback = rtk_inject_callback
        self.running = False
        self.receiver_thread = None
        self.is_connected = False
        self.bytes_received = 0
        self.messages_received = 0
        self.error_count = 0
        self.status_message = "Idle"
        self.status_callback = None
        self.connection_time = None
    
    def set_status_callback(self, callback: Callable[[str, dict], None]) -> None:
        """
        Set callback for status updates
        
        Args:
            callback: Function(status_type: str, data: dict)
                     status_type: 'connected', 'disconnected', 'error', 'status'
        """
        self.status_callback = callback
    
    def _emit_status(self, status_type: str, **kwargs) -> None:
        """Emit status update via callback"""
        if self.status_callback:
            try:
                self.status_callback(status_type, kwargs)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    def connect(self) -> bool:
        """
        Connect to LoRa receiver USB device
        
        Returns:
            bool: True if connected successfully
        """
        try:
            logger.info("Attempting to connect to LoRa receiver...")
            self.status_message = "Connecting..."
            self._emit_status('status', message=self.status_message)
            
            self.receiver = LoRaUSBReceiver()
            
            if not self.receiver.connect():
                logger.error("Failed to connect to LoRa receiver")
                self.status_message = "Connection failed"
                self._emit_status('error', message="Failed to connect to LoRa receiver")
                return False
            
            self.is_connected = True
            self.connection_time = datetime.now()
            self.status_message = "Connected"
            self.bytes_received = 0
            self.messages_received = 0
            self.error_count = 0
            
            logger.info("✓ LoRa receiver connected successfully")
            self._emit_status('connected', 
                            device="CH340 USB",
                            connection_time=self.connection_time.isoformat()
            )
            return True
        
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.status_message = f"Connection error: {str(e)}"
            self._emit_status('error', message=str(e))
            return False
    
    def disconnect(self) -> None:
        """Disconnect from LoRa receiver"""
        try:
            if self.receiver:
                self.receiver.close()
                self.receiver = None
            
            self.is_connected = False
            self.status_message = "Disconnected"
            
            logger.info("LoRa receiver disconnected")
            self._emit_status('disconnected')
        
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
    
    def _rtk_data_callback(self, raw_bytes: bytes) -> None:
        """
        Callback for each received LoRa message
        
        Args:
            raw_bytes: Raw data received from LoRa transmitter
        """
        try:
            self.messages_received += 1
            self.bytes_received += len(raw_bytes)
            
            # Attempt to inject into RTK system
            try:
                success = self.rtk_inject_callback(raw_bytes)
                if not success:
                    self.error_count += 1
                    logger.warning(f"RTK injection failed for message #{self.messages_received}")
            
            except Exception as e:
                self.error_count += 1
                logger.error(f"RTK injection error: {e}")
            
            # Log every 10 messages
            if self.messages_received % 10 == 0:
                logger.info(f"LoRa RTK: {self.messages_received} messages, "
                           f"{self.bytes_received} bytes, "
                           f"{self.error_count} errors")
                self._emit_status('status',
                                messages_received=self.messages_received,
                                bytes_received=self.bytes_received,
                                error_count=self.error_count
                )
        
        except Exception as e:
            logger.error(f"Callback processing error: {e}")
    
    def start_stream(self) -> bool:
        """
        Start receiving LoRa RTK corrections in background thread
        
        Returns:
            bool: True if stream started successfully
        """
        if self.running:
            logger.warning("Stream already running")
            return False
        
        if not self.is_connected:
            logger.error("Not connected to receiver")
            self.status_message = "Not connected"
            self._emit_status('error', message="Not connected to receiver")
            return False
        
        try:
            self.running = True
            self.receiver_thread = threading.Thread(
                target=self._receiver_worker,
                daemon=True,
                name="LoRa-RTK-Stream"
            )
            self.receiver_thread.start()
            
            self.status_message = "Streaming"
            logger.info("✓ LoRa RTK stream started")
            self._emit_status('streaming', started_at=datetime.now().isoformat())
            return True
        
        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            self.running = False
            self.status_message = f"Stream start error: {str(e)}"
            self._emit_status('error', message=f"Failed to start stream: {str(e)}")
            return False
    
    def stop_stream(self) -> None:
        """Stop receiving LoRa RTK corrections"""
        if not self.running:
            logger.warning("Stream not running")
            return
        
        try:
            # Signal worker to stop
            self.running = False

            # Close the receiver so the blocking listen() exits
            try:
                if self.receiver:
                    self.receiver.close()
            except Exception as e:
                logger.debug(f"Error closing receiver: {e}")

            # Wait for thread to finish (timeout after 3 seconds)
            if self.receiver_thread and self.receiver_thread.is_alive():
                self.receiver_thread.join(timeout=3.0)
            
            self.status_message = "Stopped"
            logger.info("✓ LoRa RTK stream stopped")
            logger.info(f"Summary: {self.messages_received} messages, "
                       f"{self.bytes_received} bytes, "
                       f"{self.error_count} errors")
            
            self._emit_status('streaming_stopped',
                            total_messages=self.messages_received,
                            total_bytes=self.bytes_received,
                            total_errors=self.error_count
            )
        
        except Exception as e:
            logger.error(f"Error stopping stream: {e}")
    
    def _receiver_worker(self) -> None:
        """Background thread worker for receiving LoRa data"""
        try:
            logger.info("LoRa receiver worker started")
            
            # Use the receiver's listen method with our callback
            self.receiver.listen(
                duration=None,  # Run indefinitely
                callback=self._rtk_data_callback
            )
        
        except Exception as e:
            logger.error(f"Receiver worker error: {e}")
            self.error_count += 1
            self.status_message = f"Worker error: {str(e)}"
            self._emit_status('error', message=f"Receiver worker error: {str(e)}")
        
        finally:
            self.running = False
            logger.info("LoRa receiver worker stopped")
    
    def get_status(self) -> dict:
        """
        Get current handler status
        
        Returns:
            dict: Status information
        """
        return {
            'is_connected': self.is_connected,
            'is_running': self.running,
            'status_message': self.status_message,
            'messages_received': self.messages_received,
            'bytes_received': self.bytes_received,
            'error_count': self.error_count,
            'connection_time': self.connection_time.isoformat() if self.connection_time else None,
            'uptime_seconds': (datetime.now() - self.connection_time).total_seconds() if self.connection_time else 0
        }
    
    def __del__(self):
        """Cleanup on destruction"""
        try:
            if self.running:
                self.stop_stream()
            if self.is_connected:
                self.disconnect()
        except:
            pass


# Global handler instance
_lora_rtk_handler: Optional[LoRaRTKHandler] = None


def create_lora_rtk_handler(rtk_inject_callback: Callable[[bytes], bool]) -> LoRaRTKHandler:
    """
    Create and return global LoRa RTK handler instance
    
    Args:
        rtk_inject_callback: Function to call with received RTCM bytes
    
    Returns:
        LoRaRTKHandler: Handler instance
    """
    global _lora_rtk_handler
    
    if _lora_rtk_handler is None:
        _lora_rtk_handler = LoRaRTKHandler(rtk_inject_callback)
    
    return _lora_rtk_handler


def get_lora_rtk_handler() -> Optional[LoRaRTKHandler]:
    """Get existing handler instance"""
    return _lora_rtk_handler
