#!/usr/bin/python3.12

# Proper test driver for the 10moons graphics tablet

import os
import sys

# Specification of the device https://python-evdev.readthedocs.io/en/latest/
from evdev import UInput, ecodes, AbsInfo
# Establish usb communication with device
import usb
import yaml

DEBUG = False	# = True --> Useful when inspecting tablet behaviour and pen interactions
#DEBUG = True

path = os.path.join(os.path.dirname(__file__), "config-vin1060plus.yaml")
# Loading tablet configuration
with open(path, "r") as f:
    config = yaml.load(f, Loader=yaml.FullLoader)


# Get the required ecodes from configuration
pen_codes = []
btn_codes = []
for k, v in config["actions"].items():
    #codes = btn_codes if k == "tablet_buttons" else pen_codes
    codes = btn_codes if k in ["tablet_buttons", "pen_buttons"] else pen_codes
    if isinstance(v, list):
        codes.extend(v)
    else:
        codes.append(v)

if(DEBUG) : print("codes", codes)
if(DEBUG) : print("pen_codes", pen_codes)
if(DEBUG) : print("btn_codes", btn_codes)

temp = []
for c in pen_codes:
    temp.extend([ecodes.ecodes[x] for x in c.split("+")])
pen_codes = temp

temp = []
for c in btn_codes:
    temp.extend([ecodes.ecodes[x] for x in c.split("+")])
btn_codes = temp

pen_events = {
    ecodes.EV_KEY: pen_codes,
    ecodes.EV_ABS: [
        #AbsInfo input: value, min, max, fuzz, flat
        (ecodes.ABS_X, AbsInfo(0, 0, config["pen"]["max_x"], 0, 0, config["pen"]["resolution_x"])),         
        (ecodes.ABS_Y, AbsInfo(0, 0, config["pen"]["max_y"], 0, 0, config["pen"]["resolution_y"])),
        #dont calculate absolute x-max/x-min or y-max/y-min values when multiple displays used
        #rather use xrandr and xinput together to configure which display handles the virtual pen ID
        #eg. xinput map-to-output 17 DisplayPort-1
        (ecodes.ABS_PRESSURE, AbsInfo(0, 0, config["pen"]["max_pressure"], 0, 0, 1))
    ],
}

btn_events = {ecodes.EV_KEY: btn_codes}
if(DEBUG) : print("pen_events :: ", pen_events)
if(DEBUG) : print("btn_events :: ", btn_events)

# Find the device
dev = usb.core.find(idVendor=config["vendor_id"], idProduct=config["product_id"])
# Select end point for reading second interface [2] for actual data
# Interface[0] associated Internal USB storage (labelled as CDROM drive)
# Interface[1] useful to map 'Full Tablet Active Area' -- outputs 64 bytes of xinput events
# Interface[2] maps to the 'AndroidActive Area' --- outputs 8 bytes of xinput events ( but only before  ./10moons-probe is executed)
if(DEBUG) : print(dev)
if(DEBUG) : print("--------------------------------")
ep = dev[0].interfaces()[1].endpoints()[0]
# Reset the device (don't know why, but till it works don't touch it)
dev.reset()  

# Drop default kernel driver from all devices
for j in [0, 1, 2]:
    if dev.is_kernel_driver_active(j):
        dev.detach_kernel_driver(j)

# Set new configuration
dev.set_configuration()

vpen = UInput(events=pen_events, name=config["xinput_name"], version=0x3)
if(DEBUG) : print(vpen.capabilities(verbose=True).keys() )
if(DEBUG) : print(vpen.capabilities(verbose=True) )
vbtn = UInput(events=btn_events, name=config["xinput_name"] + "_buttons", version=0x3)  

#compare with xinput list
if(DEBUG) : print(vbtn.capabilities(verbose=True).keys() )
if(DEBUG) : print(vbtn.capabilities(verbose=True) )
if(DEBUG) : print(vpen)
if(DEBUG) : print(vbtn)

pressed = -1

# Direction and axis configuration
max_x = config["pen"]["max_x"] * config["settings"]["swap_direction_x"]
max_y = config["pen"]["max_y"] * config["settings"]["swap_direction_y"]
if config["settings"]["swap_axis"]:
    y1, y2, x1, x2 = (1, 2, 3, 4) 
else:
    x1, x2, y1, y2 = (1, 2, 3, 4)
    
#Pen pressure thresholds:
pressure_max = config["pen"]["max_pressure"]
pressure_min = config["pen"]["pressure_min"]
pressure_contact_threshold = config["pen"]["pressure_contact_threshold"]
#Unfortunately vin1060plus does not show 8192 pressure resolution.  #TODO: need to review pressure parameters

try:
    smooth_seq_len = config["pen"]["smooth_seq_len"]
except:
    smooth_seq_len = 1
pen_reads_x = [ int(max_x/2) for _ in range(smooth_seq_len) ]
pen_reads_y = [ int(max_y/2) for _ in range(smooth_seq_len) ]
pen_reads_len = smooth_seq_len
pen_reads_i = 0
#
pen_touch_prev = True
keys_prev = [0] * len(config["actions"]["tablet_buttons"])
penbuttons_prev = [0] * len(config["actions"]["pen_buttons"])
is_rotated = False
num_errors = 0
#
# Infinite loop
while True:
    try:
        if num_errors > 50:
            raise Exception("too many subsequent errors detected. bailing out...")

        data = dev.read(ep.bEndpointAddress, ep.wMaxPacketSize)
        if(DEBUG) : print(data) # shows button pressed array
        
        #When it only works on 3x6" Android Active area
        #array('B', [5, 128, 161, 13, 2, 9, 0, 0])

        
        #When it works on full 10x6" full area 
        #(Top-left point, just under VirtualMediaShortcut keys)
        #array('B', [6, 0, 0, 0, 0, 5, 37, 6, 46, 2, 5, 255, 51, 0, 0, 0, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        #(bottom-right corner)
        #array('B', [6, 15, 255, 15, 255, 6, 192, 6, 46, 2, 5, 255, 51, 15, 255, 0, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        
        # data[5]: MSB pressure level 6,5,4,3
        if data[0] != 6:
            print(f"wrong reportID[{data[0]}]", flush=True)
            x += 1
            continue
        if len(data) < 13:
            print(f"wrong report len[{len(data)}]", flush=True)
            for i in range(len(data)): print(f"{data[i]:02x}", end=" ", flush=True)
            print("")
            x += 1
            continue
        if data[5] not in [2,3,4,5,6,7]:
            print(f"*pressureMSB:{data[5]:02x}*", end="", flush=True)
            x += 1
            continue

        num_errors = 0

        # xy: data[1,2,3,4]
        pen_reads_x[pen_reads_i] = abs(max_x - (data[x1] * 255 + data[x2]))
        pen_reads_y[pen_reads_i] = abs(max_y - (data[y1] * 255 + data[y2]))
        pen_reads_i = (pen_reads_i+1) % pen_reads_len
        pen_x = int( sum(pen_reads_x) / pen_reads_len )
        pen_y = int( sum(pen_reads_y) / pen_reads_len )

        # pressure: data[5,6]
        pen_pressure = pressure_max - ( (data[5] & 31) * 255 + data[6]) # 8192 levels -> 13bits -> 5bits from data5 + 8bits from data6
        pen_touch = (pen_pressure >= pressure_contact_threshold) # when Pen touches tablet surface detection value

        # keys: data11, data12
        keys = [0] * len(keys_prev)
        if (~data[11] & 128): keys[2]=1     # C-
        if (~data[11] & 64): keys[4]=1      # [
        if (~data[11] & 32): keys[6]=1      # clk+
        if (~data[11] & 16): keys[8]=1      # clk-
        if (~data[11] & 8): keys[10]=1      # CTRL
        if (~data[11] & 4): keys[11]=1      # ALT
        if (~data[11] & 2): keys[9]=1       # SPACE
        if (~data[11] & 1): keys[7]=1       # TAB
        #
        if (~data[12] & 32): keys[5]=1      # ]
        if (~data[12] & 16): keys[1]=1      # B
        if (~data[12] & 2): keys[0]=1       # E
        if (~data[12] & 1): keys[3]=1       # C+

        # pen buttons: data9: b1=4, b2=6, no_buttons=2
        penbuttons = [0] * len(penbuttons_prev)
        if (data[9] == 4): penbuttons[0] = 1
        if (data[9] == 6): penbuttons[1] = 1



        if keys == config["settings"]["rotate_shortcut"]:
            # rotate axes + invert Y
            keys = [0] * len(keys)
            x1, x2, y1, y2 = (y1, y2, x1, x2)
            config["settings"]["swap_direction_y"] = 1 - config["settings"]["swap_direction_y"]
            if is_rotated:
                max_x = config["pen"]["max_x"] * config["settings"]["swap_direction_x"]
                max_y = config["pen"]["max_y"] * config["settings"]["swap_direction_y"]
            else:
                max_y = max_x
                max_x = config["pen"]["max_y"] * config["settings"]["swap_direction_y"]
            is_rotated = not is_rotated
            print(f"tablet axes rotated: {is_rotated}")
            continue

        vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, int(pen_touch) )
        if pen_touch:
            vpen.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, int(pen_touch) )
        if pen_touch or pen_touch_prev:
            vpen.write(ecodes.EV_KEY, ecodes.BTN_MOUSE, int(pen_touch) )
        pen_touch_prev = pen_touch
        vpen.write(ecodes.EV_ABS, ecodes.ABS_X, pen_x)
        vpen.write(ecodes.EV_ABS, ecodes.ABS_Y, pen_y)
        vpen.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pen_pressure)
        #
        vpen.syn()
        
        for i in range(len(keys)):
            if keys[i] != keys_prev[i]:
                key_codes = config["actions"]["tablet_buttons"][i].split("+")
                for key in key_codes:
                    act = ecodes.ecodes[key]
                    vbtn.write(ecodes.EV_KEY, act, keys[i])
                    # print(f"keys[{i}] : {keys[i]}")
        keys_prev = keys
        #
        for i in range(len(penbuttons)):
            if penbuttons[i] != penbuttons_prev[i]:
                key_codes = config["actions"]["pen_buttons"][i].split("+")
                for key in key_codes:
                    act = ecodes.ecodes[key]
                    vbtn.write(ecodes.EV_KEY, act, penbuttons[i])
                    # print(f"penbutton[{i}] : {penbuttons[i]}")
        penbuttons_prev = penbuttons
        #
        vbtn.syn()



        # Flush
        vpen.syn()
    except usb.core.USBError as e:
        if e.args[0] == 19:
            vpen.close()
            raise Exception("Device has been disconnected")
    except KeyboardInterrupt:
        vpen.close()
        vbtn.close()
        sys.exit("\nDriver terminated successfully.")
    except Exception as e:
        print(e)
