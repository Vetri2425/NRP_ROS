#!/usr/bin/env python3
"""
LED Testing Script for Mission State Feedback.

This script allows testing all available LED colors and effects.
Shows all available options with unique IDs, allows navigation through them,
and applies the selected effect to the LED controller.

Usage:
    python3 led_test_script.py

Controls:
    - Press ENTER: Move to next effect/color combination
    - Type 's' or 'select': Confirm the current selection
    - Type 'q' or 'quit': Exit the test
    - Type 'list': Show all available colors and effects
"""

import os
import sys
import time
import threading

# Add Backend to path for importing LED controller
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'Backend'))

# Try to import the LED controller
try:
    from Backend.led_controller import LEDController, ANIMATION_MAP, SPI_AVAILABLE
    LED_CONTROLLER_AVAILABLE = True
except ImportError:
    LED_CONTROLLER_AVAILABLE = False
    print("Warning: Could not import LED controller. Running in simulation mode.")

# ============================================================================
# AVAILABLE COLORS WITH UNIQUE IDS
# ============================================================================
# Format: (id, name, rgb_tuple, description)
COLORS = [
    (1, "Blue", (0, 0, 255), "Pure blue color"),
    (2, "Green", (0, 255, 0), "Pure green color"),
    (3, "Red", (255, 0, 0), "Pure red color"),
    (4, "Yellow", (255, 200, 0), "Yellow color (RGB)"),
    (5, "Orange", (255, 128, 0), "Orange/Amber color"),
    (6, "Cyan", (0, 255, 255), "Cyan/Turquoise color"),
    (7, "Magenta", (255, 0, 255), "Magenta/Pink color"),
    (8, "White", (255, 255, 255), "Pure white color"),
    (9, "Purple", (128, 0, 128), "Purple/Violet color"),
    (10, "Pink", (255, 105, 180), "Hot pink color"),
    (11, "Light Blue", (173, 216, 230), "Light blue/Azure"),
    (12, "Lime", (0, 255, 128), "Lime green color"),
]

# ============================================================================
# AVAILABLE EFFECTS WITH UNIQUE IDS
# ============================================================================
# Format: (id, name, effect_type, description)
EFFECTS = [
    (101, "Solid", "solid", "Solid color (no animation)"),
    (102, "Blink", "blink", "Blinking on/off"),
    (103, "Chase", "chase", "Comet chase effect (one LED moving)"),
    (104, "Strobe", "strobe", "Fast strobe (one LED at a time)"),
]

# ============================================================================
# COMBINED LIGHTING OPTIONS (Color + Effect combinations)
# ============================================================================
# Format: (unique_id, color_id, effect_id, color_name, effect_name, description)
LIGHTING_OPTIONS = []

# Generate all combinations
option_id = 1000
for color in COLORS:
    for effect in EFFECTS:
        LIGHTING_OPTIONS.append((
            option_id,
            color[0],    # color_id
            effect[0],   # effect_id
            color[1],   # color_name
            effect[1],  # effect_name
            f"{color[1]} {effect[1]}"
        ))
        option_id += 1

# ============================================================================
# STATE-BASED OPTIONS (Pre-defined mission states)
# ============================================================================
# These match the existing ANIMATION_MAP from led_controller.py
MISSION_STATES = [
    (201, "idle", "Solid Blue", "Blue solid - System idle"),
    (202, "loading", "Blue Strobe", "Blue strobe - Loading/Mission loading"),
    (203, "ready", "Yellow Strobe", "Yellow strobe - Ready to arm"),
    (204, "running", "Yellow Blink", "Yellow blink - Mission running"),
    (205, "paused", "Solid Orange", "Orange solid - Mission paused"),
    (206, "completed", "Solid Green", "Green solid - Mission completed"),
    (207, "error", "Red Blink", "Red blink - Error state"),
    (208, "stopped", "Red Strobe", "Red strobe - Mission stopped"),
]


class LEDTestController:
    """Test controller for LED patterns (works with or without actual hardware)."""
    
    def __init__(self, num_leds=None):
        self.current_option_index = 0
        self.selected_option = None
        self.led_controller = None
        self._animation_thread = None
        self._running = True
        self._current_pattern = None
        
        # Determine number of LEDs - default to 30 (strip) if not specified
        if num_leds is None:
            num_leds = 30  # Default to 30 LEDs for full strip
        self.num_leds = num_leds
        
        # Try to initialize the real LED controller
        if LED_CONTROLLER_AVAILABLE:
            try:
                # Set environment variable for 30 LEDs
                os.environ['LED_STRIP'] = 'strip'
                self.led_controller = LEDController(num_leds=num_leds)
                print(f"[LED] Real LED controller initialized ({num_leds} LEDs)")
            except Exception as e:
                print(f"[LED] Could not initialize real controller: {e}")
                print("[LED] Running in SIMULATION mode (no actual LEDs)")
        else:
            print("[LED] LED controller not available. Running in SIMULATION mode.")
    
    @property
    def current_option(self):
        """Get the current lighting option."""
        return LIGHTING_OPTIONS[self.current_option_index]
    
    def get_option_by_id(self, option_id):
        """Get lighting option by its unique ID."""
        for option in LIGHTING_OPTIONS:
            if option[0] == option_id:
                return option
        return None
    
    def next_option(self):
        """Move to the next lighting option."""
        self.current_option_index = (self.current_option_index + 1) % len(LIGHTING_OPTIONS)
        return self.current_option
    
    def previous_option(self):
        """Move to the previous lighting option."""
        self.current_option_index = (self.current_option_index - 1) % len(LIGHTING_OPTIONS)
        return self.current_option
    
    def select_current(self):
        """Select the current lighting option."""
        self.selected_option = self.current_option
        return self.selected_option
    
    def apply_option(self, option):
        """Apply a lighting option to the LEDs."""
        if self.led_controller and self.led_controller.spi:
            # Real LED controller - use the color and effect
            color_rgb = None
            for color in COLORS:
                if color[0] == option[1]:
                    color_rgb = color[2]
                    break
            
            effect_type = None
            for effect in EFFECTS:
                if effect[0] == option[2]:
                    effect_type = effect[2]
                    break
            
            if color_rgb and effect_type:
                # Use the new set_custom method
                self.led_controller.set_custom(color_rgb, effect_type)
                print(f"[LED] Applied: {option[5]} ({effect_type} {color_rgb})")
        else:
            # Simulation mode - just print what would happen
            color_rgb = None
            for color in COLORS:
                if color[0] == option[1]:
                    color_rgb = color[2]
                    break
            effect_type = None
            for effect in EFFECTS:
                if effect[0] == option[2]:
                    effect_type = effect[2]
                    break
            print(f"\n[SIMULATION] Would apply: {option[5]}")
            print(f"  - Color RGB: {color_rgb}")
            print(f"  - Effect: {effect_type}")
    
    def apply_state(self, state_name):
        """Apply a mission state to the LEDs."""
        if self.led_controller and self.led_controller.spi:
            self.led_controller.update_state(state_name)
            print(f"[LED] Applied state: {state_name}")
        else:
            print(f"[SIMULATION] Would apply state: {state_name}")
    
    def _apply_effect(self, effect_type, color_rgb):
        """Apply an effect directly to the LED controller."""
        # This would require extending the LED controller to support arbitrary colors/effects
        # For now, we'll simulate
        print(f"[LED] Applying effect: {effect_type} with color {color_rgb}")
    
    def shutdown(self):
        """Shutdown the LED controller."""
        self._running = False
        if self.led_controller:
            self.led_controller.shutdown()


def print_header():
    """Print the header with all available options."""
    print("\n" + "=" * 70)
    print("LED TESTING SCRIPT - Available Colors and Effects")
    print("=" * 70)
    
    print("\n--- AVAILABLE COLORS ---")
    print(f"{'ID':<5} {'Name':<15} {'RGB':<20} Description")
    print("-" * 60)
    for color in COLORS:
        print(f"{color[0]:<5} {color[1]:<15} {str(color[2]):<20} {color[3]}")
    
    print("\n--- AVAILABLE EFFECTS ---")
    print(f"{'ID':<5} {'Name':<15} {'Type':<10} Description")
    print("-" * 60)
    for effect in EFFECTS:
        print(f"{effect[0]:<5} {effect[1]:<15} {effect[2]:<10} {effect[3]}")
    
    print("\n--- COMBINED LIGHTING OPTIONS (Color + Effect) ---")
    print(f"{'Unique ID':<10} {'Color ID':<10} {'Effect ID':<10} Description")
    print("-" * 60)
    # Show first 10 and last 5 as examples
    for i, option in enumerate(LIGHTING_OPTIONS[:10]):
        print(f"{option[0]:<10} {option[1]:<10} {option[2]:<10} {option[5]}")
    print("  ... (showing first 10 of {} total)".format(len(LIGHTING_OPTIONS)))
    for option in LIGHTING_OPTIONS[-5:]:
        print(f"{option[0]:<10} {option[1]:<10} {option[2]:<10} {option[5]}")
    
    print("\n--- MISSION STATE PRESETS ---")
    print(f"{'State ID':<10} {'State Name':<15} {'Display':<20} Description")
    print("-" * 60)
    for state in MISSION_STATES:
        print(f"{state[0]:<10} {state[1]:<15} {state[2]:<20} {state[3]}")
    
    print("\n" + "=" * 70)


def print_current_option(controller):
    """Print the current option in a clear format."""
    option = controller.current_option
    print("\n" + "-" * 50)
    print(f"CURRENT SELECTION:")
    print(f"  Unique ID:     {option[0]}")
    print(f"  Color ID:      {option[1]} ({option[3]})")
    print(f"  Effect ID:     {option[2]} ({option[4]})")
    print(f"  Description:   {option[5]}")
    print(f"  RGB Color:     {COLORS[option[1]-1][2]}")
    print(f"  Effect Type:   {EFFECTS[option[2]-101][2]}")
    print("-" * 50)


def main():
    """Main function to run the LED testing script."""
    print("\n" + "=" * 70)
    print("       LED TESTING SCRIPT FOR MISSION STATE FEEDBACK")
    print("=" * 70)
    print("\nThis script allows you to:")
    print("  1. View all available LED colors and effects")
    print("  2. Navigate through different lighting combinations")
    print("  3. Select the desired lighting effect")
    print("  4. Apply the selected effect to the LED controller")
    
    # Print all available options
    print_header()
    
    # Create the test controller
    controller = LEDTestController()
    
    # Show initial state
    print_current_option(controller)
    
    # Apply initial option
    controller.apply_option(controller.current_option)
    
    print("\n" + "=" * 70)
    print("CONTROLS:")
    print("  ENTER (or any key + Enter):  Next lighting effect")
    print("  'p' + Enter:                 Previous lighting effect")
    print("  's' + Enter (select):        Confirm current selection")
    print("  'l' + Enter (list):         Show all available options")
    print("  'm' + Enter (mission):      Show mission state presets")
    print("  'a' + Enter (apply):         Apply a specific option by ID")
    print("  'q' + Enter (quit):          Exit the test")
    print("=" * 70)
    
    print("\n>>> Press ENTER to cycle through effects, or select one...")
    
    # Main interaction loop
    while True:
        try:
            user_input = input("\nCommand [Enter=snext, s=select, q=quit]: ").strip().lower()
            
            if user_input == 'q' or user_input == 'quit':
                print("\nExiting LED test. Thank you!")
                break
            
            elif user_input == 'l' or user_input == 'list':
                print_header()
                print_current_option(controller)
            
            elif user_input == 'm' or user_input == 'mission':
                print("\n--- MISSION STATE PRESETS ---")
                print(f"{'ID':<8} {'State':<12} {'Display':<20}")
                print("-" * 45)
                for state in MISSION_STATES:
                    print(f"{state[0]:<8} {state[1]:<12} {state[2]:<20}")
                
                state_input = input("\nEnter state ID to apply (or press Enter to cancel): ").strip()
                if state_input.isdigit():
                    state_id = int(state_input)
                    for state in MISSION_STATES:
                        if state[0] == state_id:
                            controller.apply_state(state[1])
                            print(f"Applied mission state: {state[1]} ({state[2]})")
                            break
                continue
            
            elif user_input == 'a' or user_input == 'apply':
                id_input = input("Enter unique lighting option ID: ").strip()
                if id_input.isdigit():
                    option_id = int(id_input)
                    option = controller.get_option_by_id(option_id)
                    if option:
                        controller.current_option_index = LIGHTING_OPTIONS.index(option)
                        print_current_option(controller)
                        controller.apply_option(option)
                        print(f"\n✓ Applied option ID {option_id}: {option[5]}")
                    else:
                        print(f"\n✗ Invalid option ID: {option_id}")
                continue
            
            elif user_input == 'p' or user_input == 'previous':
                controller.previous_option()
                print_current_option(controller)
                controller.apply_option(controller.current_option)
            
            elif user_input == 's' or user_input == 'select':
                selected = controller.select_current()
                print(f"\n{'='*50}")
                print(f"✓ SELECTED LIGHTING EFFECT:")
                print(f"  Unique ID:     {selected[0]}")
                print(f"  Color:         {selected[3]} (ID: {selected[1]})")
                print(f"  Effect:        {selected[4]} (ID: {selected[2]})")
                print(f"  Full Name:     {selected[5]}")
                print(f"{'='*50}")
                
                # Ask to apply to controller
                confirm = input("\nApply this effect to LED controller? (y/n): ").strip().lower()
                if confirm == 'y' or confirm == 'yes':
                    controller.apply_option(selected)
                    print("\n✓ Effect applied to LED controller!")
                else:
                    print("\nEffect not applied.")
                
                # Ask to continue or exit
                continue_select = input("\nContinue testing? (y/n): ").strip().lower()
                if continue_select != 'y' and continue_select != 'yes':
                    print("\nExiting LED test. Thank you!")
                    break
            
            else:
                # Any other input (including Enter) moves to next option
                controller.next_option()
                print_current_option(controller)
                controller.apply_option(controller.current_option)
        
        except KeyboardInterrupt:
            print("\n\nInterrupted by user. Exiting...")
            break
        except EOFError:
            break
    
    # Cleanup
    controller.shutdown()
    print("\n[LED] Test complete.")


if __name__ == "__main__":
    main()
