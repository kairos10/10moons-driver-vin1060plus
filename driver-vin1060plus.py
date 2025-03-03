#!/usr/bin/python3.12
"""
Test driver for 10moons graphics tablet
Handles pen input, tablet buttons, and multimedia controls
"""

import os
from dataclasses import dataclass
from typing import List, Tuple
import usb
import yaml
from evdev import UInput, ecodes, AbsInfo
import time

# Constants
DEBUG = False
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config-vin1060plus.yaml")

# Data packet index constants for USB reports
DATA_REPORT_ID    = 0   # Report identifier (expected value: 6)
DATA_X_MSB        = 1   # High byte of X coordinate (normal orientation)
DATA_X_LSB        = 2   # Low byte of X coordinate
DATA_Y_MSB        = 3   # High byte of Y coordinate
DATA_Y_LSB        = 4   # Low byte of Y coordinate
DATA_PRESSURE_MSB = 5   # Most significant byte of pressure
DATA_PRESSURE_LSB = 6   # Least significant byte of pressure
DATA_UNUSED_7     = 7
DATA_UNUSED_8     = 8
DATA_BTN_PEN      = 9   # Pen button state (4: button 1, 6: button 2)
DATA_UNUSED_10    = 10
DATA_BTN_TABLET_1 = 11  # First byte of tablet button states
DATA_BTN_TABLET_2 = 12  # Second byte of tablet button states
DATA_TILT_X       = 13  # X-axis tilt value (signed byte)
DATA_TILT_Y       = 14  # Y-axis tilt value (signed byte)

# the tablet reports fixed RawX values when the MM area is touched
MM_RAWX2KEY = {
    0x00c8: 0, 0x025f: 1, 0x03f7: 2, 0x058e: 3, 0x0725: 4, 0x08bd: 5, 0x0a54: 6, 0x0bec: 7, 0x0d83: 8, 0x0f1a: 9
}
MM_RAWY = 0xf000 # value reported on Y when the MM area is touched


@dataclass
class TabletConfig:
    """Stores tablet configuration data"""
    vendor_id: int
    product_id: int
    xinput_name: str
    pen: dict
    actions: dict
    settings: dict

class TabletDriver:
    """Main class for handling graphics tablet functionality"""
    
    def __init__(self):
        # Load configuration from YAML file
        with open(CONFIG_PATH, "r") as f:
            config_data = yaml.load(f, Loader=yaml.FullLoader)
        self.config = TabletConfig(**config_data)

        # Parse action codes from config into pen and button codes
        self.pen_codes, self.btn_codes = [], []
        for key, value in self.config.actions.items():
            target = self.btn_codes if key in ["tablet_buttons", "pen_buttons", "multimedia_buttons"] else self.pen_codes
            if isinstance(value, list):
                target.extend([ecodes.ecodes[x] for item in value for x in item.split("+")])
            else:
                target.append(ecodes.ecodes[value])

        self.vpen, self.vbtn = self._initialize_virtual_devices()
        self.device, self.ep = self._setup_usb_device()
        
        # Initialize {pen,button} state variables
        smooth_seq_len = self.config.pen.get("smooth_seq_len", 1)
        max_x = self.config.pen["max_x"] * self.config.settings["swap_direction_x"]
        max_y = self.config.pen["max_y"] * self.config.settings["swap_direction_y"]
        self.pen_state = {
            "reads_x": [int(max_x/2)] * smooth_seq_len,
            "reads_y": [int(max_y/2)] * smooth_seq_len,
            "reads_i": 0,
            "touch_prev": False
        }
        
        self.btns_keys, self.btns_pen, self.btns_mm = None, None, None
        self.btns_keys_prev = [0] * len(self.config.actions["tablet_buttons"])
        self.btns_pen_prev = [0] * len(self.config.actions["pen_buttons"])
        self.btns_mm_prev = [0] * len(self.config.actions["multimedia_buttons"])

        self.tablet_is_rotated = False

    def _initialize_virtual_devices(self) -> Tuple[UInput, UInput]:
        """Initialize virtual input devices"""
        pen_events = {
            ecodes.EV_KEY: self.pen_codes,
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(0, 0, self.config.pen["max_x"], 0, 0, self.config.pen["resolution_x"])),
                (ecodes.ABS_Y, AbsInfo(0, 0, self.config.pen["max_y"], 0, 0, self.config.pen["resolution_y"])),
                (ecodes.ABS_PRESSURE, AbsInfo(0, 0, self.config.pen["max_pressure"], 0, 0, 1)),
                (ecodes.ABS_TILT_X, AbsInfo(0, -127, 127, 0, 0, 128)),
                (ecodes.ABS_TILT_Y, AbsInfo(0, -127, 127, 0, 0, 128)),
            ],
        }
        btn_events = {ecodes.EV_KEY: self.btn_codes}
        
        vpen = UInput(events=pen_events, name=self.config.xinput_name, version=0x3)
        vpen.syn()
        vbtn = UInput(events=btn_events, name=f"{self.config.xinput_name}_buttons", version=0x3)
        return vpen, vbtn

    def _setup_usb_device(self) -> Tuple[usb.core.Device, usb.core.Endpoint]:
        """Configure USB device connection"""
        dev = usb.core.find(idVendor=self.config.vendor_id, idProduct=self.config.product_id)
        if not dev:
            raise Exception("Device not found")
            
        ep = dev[0].interfaces()[1].endpoints()[0]
        dev.reset()
        time.sleep(.3)
        
        # Detach kernel drivers
        for i in range(3):
            if dev.is_kernel_driver_active(i):
                dev.detach_kernel_driver(i)
                
        dev.set_configuration()
        self._send_initialization_reports(dev)
        return dev, ep



    def _send_initialization_reports(self, dev: usb.core.Device):
        reports = [
            # [ReportID, Command (mode selection), Mode (likely full tablet area), Enable, X/Y bounds, FeatureSetID, Checksum]
            [0x08, 0x04, 0x1d, 0x01, 0xff, 0xff, 0x06, 0x2e],
            
            # Report ID (Feature Report 8), Command (set coordinate range)
            # Flag (standard range, no offset)
            # X-axis maximum (65280)
            # Reserved or delimiter byte
            # Y-axis maximum (65280)
            [0x08, 0x03, 0x00, 0xff, 0xf0, 0x00, 0xff, 0xf0],
            
            # Activate tablet features
            # [ReportID, Command (feature activation), Enable, Padding x5]
            [0x08, 0x06, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00],
            
            # repeat of second report
            [0x08, 0x03, 0x00, 0xff, 0xf0, 0x00, 0xff, 0xf0]
        ]
        
        for report in reports:
            # 0x21[REQUEST_TYPE_CLASS|RECIPIENT_INTERFACE|ENDPOINT_OUT] 9[SET_REPORT] 3[FEATURE_REPORT] 8[reportId] 2[ifIndex] 8[len]
            dev.ctrl_transfer(0x21, 9, 0x0308, 2, report)


    def process_input(self, data: bytes) -> bool:
        """Process raw input data from tablet and update virtual devices"""
        # Validate input data
        if data[DATA_REPORT_ID] != 6:
            print(f"wrong reportID[{data[DATA_REPORT_ID]}]", flush=True)
            return False
        if len(data) < 13:
            print(f"wrong report len[{len(data)}]", flush=True)
            print(" ".join(f"{x:02x}" for x in data), flush=True)
            return False
        if data[DATA_PRESSURE_MSB] not in [2, 3, 4, 5, 6, 7]:
            print(f"*pressureMSB:{data[DATA_PRESSURE_MSB]:02x}*", end="", flush=True)
            return False

        # Determine coordinate axes based on rotation state
        x1, x2, y1, y2 = (DATA_X_MSB, DATA_X_LSB, DATA_Y_MSB, DATA_Y_LSB) if not self.tablet_is_rotated else (DATA_Y_MSB, DATA_Y_LSB, DATA_X_MSB, DATA_X_LSB)

        raw_x = data[x1] * 255 + data[x2]
        raw_y = data[y1] * 255 + data[y2]
        
        # Check if pen is in multimedia row
        mm_key = None
        if raw_y & MM_RAWY != 0:
            raw_y = 0
            mm_key = MM_RAWX2KEY.get(raw_x)

        # Update pen position with smoothing
        smooth_seq_len = len(self.pen_state["reads_x"])
        max_x = self.config.pen["max_x"] * self.config.settings["swap_direction_x"]
        max_y = self.config.pen["max_y"] * self.config.settings["swap_direction_y"]
        self.pen_state["reads_x"][self.pen_state["reads_i"]] = abs(max_x - raw_x)
        self.pen_state["reads_y"][self.pen_state["reads_i"]] = abs(max_y - raw_y)
        self.pen_state["reads_i"] = (self.pen_state["reads_i"] + 1) % smooth_seq_len
        
        pen_x = int(sum(self.pen_state["reads_x"]) / smooth_seq_len)
        pen_y = int(sum(self.pen_state["reads_y"]) / smooth_seq_len)

        # Process pressure
        pressure_min_histerezis = self.config.pen.get("pressure_min_histerezis", 0)
        pen_pressure = self.config.pen["max_pressure"] - ((data[DATA_PRESSURE_MSB] & 31) * 255 + data[DATA_PRESSURE_LSB])
        pen_touch = pen_pressure >= ( self.config.pen["pressure_contact_threshold"] - self.pen_state["touch_prev"] * pressure_min_histerezis )
        
        # Handle multimedia keys
        self.btns_mm = [0] * len(self.btns_mm_prev)
        if pen_touch and mm_key is not None:
            self.btns_mm[mm_key] = 1
            pen_touch = False

        # Parse tablet button states from raw data
        self.btns_keys = [0] * len(self.btns_keys_prev)
        if not (data[DATA_BTN_TABLET_1] & 128): self.btns_keys[2] = 1   # C-
        if not (data[DATA_BTN_TABLET_1] & 64):  self.btns_keys[4] = 1   # [
        if not (data[DATA_BTN_TABLET_1] & 32):  self.btns_keys[6] = 1   # clk+
        if not (data[DATA_BTN_TABLET_1] & 16):  self.btns_keys[8] = 1   # clk-
        if not (data[DATA_BTN_TABLET_1] & 8):   self.btns_keys[10] = 1  # CTRL
        if not (data[DATA_BTN_TABLET_1] & 4):   self.btns_keys[11] = 1  # ALT
        if not (data[DATA_BTN_TABLET_1] & 2):   self.btns_keys[9] = 1   # SPACE
        if not (data[DATA_BTN_TABLET_1] & 1):   self.btns_keys[7] = 1   # TAB
        if not (data[DATA_BTN_TABLET_2] & 32):  self.btns_keys[5] = 1   # ]
        if not (data[DATA_BTN_TABLET_2] & 16):  self.btns_keys[1] = 1   # B
        if not (data[DATA_BTN_TABLET_2] & 2):   self.btns_keys[0] = 1   # E
        if not (data[DATA_BTN_TABLET_2] & 1):   self.btns_keys[3] = 1   # C+
        if self.btns_keys == self.config.settings["rotate_shortcut"]:
            self._handle_rotation()
            return True

        # Parse pen button states from raw data"""
        self.btns_pen = [0] * len(self.btns_pen_prev)
        if data[DATA_BTN_PEN] == 4: self.btns_pen[0] = 1
        if data[DATA_BTN_PEN] == 6: self.btns_pen[1] = 1

        # Process tilt
        tilt_x = int.from_bytes([data[DATA_TILT_X]], signed=True)
        tilt_y = int.from_bytes([data[DATA_TILT_Y]], signed=True)

        # Update virtual devices
        self._update_pen_device(pen_touch, pen_x, pen_y, pen_pressure, tilt_x, tilt_y)
        self._update_buttons()
        
        return True

    def _handle_rotation(self):
        """Handle tablet rotation shortcut"""
        self.tablet_is_rotated = not self.tablet_is_rotated
        if self.tablet_is_rotated:
            max_x = self.config.pen["max_y"] * self.config.settings["swap_direction_y"]
            max_y = self.config.pen["max_x"] * self.config.settings["swap_direction_x"]
        else:
            max_x = self.config.pen["max_x"] * self.config.settings["swap_direction_x"]
            max_y = self.config.pen["max_y"] * self.config.settings["swap_direction_y"]
        
        smooth_seq_len = len(self.pen_state["reads_x"])
        self.pen_state["reads_x"] = [int(max_x/2)] * smooth_seq_len
        self.pen_state["reads_y"] = [int(max_y/2)] * smooth_seq_len
        print(f"tablet axes rotated: {self.tablet_is_rotated}")

    def _update_pen_device(self, pen_touch: bool, pen_x: int, pen_y: int, pen_pressure: int, tilt_x: int, tilt_y: int):
        if pen_touch != self.pen_state["touch_prev"]:
            self.vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, int(pen_touch))
            if pen_touch:
                self.vpen.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, int(pen_touch))
                # self.vpen.write(ecodes.EV_KEY, ecodes.BTN_TOOL_RUBBER, int(pen_touch))
                # self.vpen.write(ecodes.EV_KEY, ecodes.BTN_MOUSE, int(pen_touch))
            else:
                self.vpen.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, 0)
        if pen_touch:
            self.vpen.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pen_pressure)
            self.vpen.write(ecodes.EV_ABS, ecodes.ABS_TILT_X, tilt_x)
            self.vpen.write(ecodes.EV_ABS, ecodes.ABS_TILT_Y, tilt_y)

        self.vpen.write(ecodes.EV_ABS, ecodes.ABS_X, pen_x)
        self.vpen.write(ecodes.EV_ABS, ecodes.ABS_Y, pen_y)

        self.vpen.syn()
        self.pen_state["touch_prev"] = pen_touch

    def _update_buttons(self):
        """Update virtual button device with current button states"""
        for crts,prevs, acts in [
            (self.btns_keys, self.btns_keys_prev, self.config.actions["tablet_buttons"]),
            (self.btns_pen, self.btns_pen_prev, self.config.actions["pen_buttons"]),
            (self.btns_mm, self.btns_mm_prev, self.config.actions["multimedia_buttons"]),
            ]:
            for (crt, prev, act) in zip(crts, prevs, acts):
                if crt != prev:
                    key_codes = act.split("+")
                    for key in key_codes:
                        self.vbtn.write(ecodes.EV_KEY, ecodes.ecodes[key], crt)

        self.btns_keys_prev = self.btns_keys
        self.btns_pen_prev = self.btns_pen
        self.btns_mm_prev = self.btns_mm
        self.vbtn.syn()

    def run(self):
        """Main driver loop"""
        num_errors = 0
        skip_num = 5
        
        while True:
            try:
                if num_errors > 50:
                    raise Exception("Too many subsequent errors detected")
                    
                data = self.device.read(self.ep.bEndpointAddress, self.ep.wMaxPacketSize)
                if skip_num > 0:
                    skip_num -= 1
                    continue
                    
                if self.process_input(data):
                    num_errors = 0
                else:
                    num_errors += 1
                    
            except usb.core.USBError as e:
                if e.args[0] == 19:
                    raise Exception("Device disconnected")
            except KeyboardInterrupt:
                print("\nDriver terminated successfully.")
                break
            except Exception as e:
                print(e)
                break
        self.cleanup()

    def cleanup(self):
        self.vpen.close()
        self.vbtn.close()
        usb.util.release_interface(self.device, 0)

def main():
    driver = TabletDriver()
    driver.run()

if __name__ == "__main__":
    main()
