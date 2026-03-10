Quick Fix Snippets
❌ PROBLEM CODE (Blocking Event Loop)
Location: integrated_mission_controller.py line ~1150

def upload_single_waypoint(self, waypoint: Dict[str, Any]) -> bool:
    """Upload waypoint with HOME position"""
    try:
        # ❌ BLOCKS EVENT LOOP - Telemetry stops updating
        self.bridge.clear_waypoints()  # BLOCKING ROS CALL
        
        # ❌ BLOCKS EVENT LOOP - Telemetry stops updating
        response = self.bridge.push_waypoints([home_waypoint, mission_waypoint])  # BLOCKING
        
        # ❌ BLOCKS EVENT LOOP
        response = self.bridge.set_current_waypoint(1)  # BLOCKING
        
        return True
    except Exception as e:
        return False

Copy
Why it crashes: These blocking calls freeze the asyncio event loop → telemetry callbacks stop → maintain_mavros_connection() detects false disconnect → os._exit(1)

✅ SOLUTION (Non-Blocking with run_in_executor)
Step 1: Make upload_single_waypoint async

async def upload_single_waypoint(self, waypoint: Dict[str, Any]) -> bool:
    """Upload waypoint with HOME position - ASYNC VERSION"""
    try:
        loop = asyncio.get_event_loop()
        
        # ✅ NON-BLOCKING - Runs in thread pool
        await loop.run_in_executor(None, self.bridge.clear_waypoints)
        
        # ✅ NON-BLOCKING - Runs in thread pool
        response = await loop.run_in_executor(
            None, 
            self.bridge.push_waypoints, 
            [home_waypoint, mission_waypoint]
        )
        
        # ✅ NON-BLOCKING - Runs in thread pool
        response = await loop.run_in_executor(
            None,
            self.bridge.set_current_waypoint,
            1
        )
        
        return True
    except Exception as e:
        return False

Copy
python
Step 2: Make execute_current_waypoint async

async def execute_current_waypoint(self):
    """Execute the current waypoint - ASYNC VERSION"""
    waypoint = self.waypoints[self.current_waypoint_index]
    
    try:
        # Upload waypoint (now async)
        if await self.upload_single_waypoint(mavros_waypoint):
            
            # ✅ Make arm check async
            if not await self.ensure_pixhawk_armed_async():
                self.log("⚠ Warning: Could not arm", "warning")
            
            # ✅ Make mode change async
            await self.set_pixhawk_mode_async("AUTO")
            
            self.waiting_for_waypoint_reach = True
            
    except Exception as e:
        self.log(f"Failed: {e}", "error")

Copy
python
Step 3: Make helper methods async

async def ensure_pixhawk_armed_async(self) -> bool:
    """Async version of arm check"""
    loop = asyncio.get_event_loop()
    
    # ✅ NON-BLOCKING arm command
    arm_response = await loop.run_in_executor(
        None,
        self.bridge.set_armed,
        True
    )
    
    if arm_response.get('success', False):
        return True
    
    # Wait for telemetry confirmation
    await asyncio.sleep(0.2)
    return self.pixhawk_state.get('armed', False) if self.pixhawk_state else False


async def set_pixhawk_mode_async(self, mode: str):
    """Async version of mode change"""
    loop = asyncio.get_event_loop()
    
    # ✅ NON-BLOCKING mode change
    response = await loop.run_in_executor(
        None,
        self.bridge.set_mode,
        mode
    )
    
    if response.get('mode_sent', False):
        self.log(f"✅ Mode changed to: {mode}")


Copy
python
Step 4: Update start_mission to call async method

def start_mission(self) -> Dict[str, Any]:
    """Start mission execution"""
    with self.lock:
        # ... validation code ...
        
        self.mission_state = MissionState.RUNNING
        
        # ✅ Schedule async execution (don't block)
        asyncio.create_task(self.execute_current_waypoint())
        
        return {'success': True, 'message': 'Mission started'}

Copy
python
📦 MINIMAL CHANGES NEEDED
Files to modify:

integrated_mission_controller.py - Add async/await to 3 methods

Add import asyncio at top

Methods to convert:

upload_single_waypoint() → async

execute_current_waypoint() → async

ensure_pixhawk_armed() → async

set_pixhawk_mode() → async

Time to implement: ~15 minutes

Result: Event loop stays responsive → telemetry continues → no false disconnect → no crash


