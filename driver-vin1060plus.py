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
    codes = btn_codes if k in ["tablet_buttons", "pen_buttons", "multimedia_buttons"] else pen_codes
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
        #AbsInfo input: value, min, max, fuzz, flat, resolution
        (ecodes.ABS_X, AbsInfo(0, 0, config["pen"]["max_x"], 0, 0, config["pen"]["resolution_x"])),         
        (ecodes.ABS_Y, AbsInfo(0, 0, config["pen"]["max_y"], 0, 0, config["pen"]["resolution_y"])),
        #dont calculate absolute x-max/x-min or y-max/y-min values when multiple displays used
        #rather use xrandr and xinput together to configure which display handles the virtual pen ID
        #eg. xinput map-to-output 17 DisplayPort-1
        (ecodes.ABS_PRESSURE, AbsInfo(0, 0, config["pen"]["max_pressure"], 0, 0, 1)),
        (ecodes.ABS_TILT_X, AbsInfo(0, -127, 127, 0, 0, 128)),
        (ecodes.ABS_TILT_Y, AbsInfo(0, -127, 127, 0, 0, 128)),
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

############## configure the interface -- 0x21[REQUEST_TYPE_CLASS|RECIPIENT_INTERFACE|ENDPOINT_OUT] 9[SET_REPORT] 3[FEATURE_REPORT] 8[reportId] 2[ifIndex] 8[len]
report = [ 0x08, 0x04, 0x1d, 0x01, 0xff, 0xff, 0x06, 0x2e ]
dev.ctrl_transfer(0x21, 9, 0x0308, 2, report)
report = [ 0x08, 0x03, 0x00, 0xff, 0xf0, 0x00, 0xff, 0xf0 ]
dev.ctrl_transfer(0x21, 9, 0x0308, 2, report)
report = [ 0x08, 0x06, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00 ]
dev.ctrl_transfer(0x21, 9, 0x0308, 2, report)
report = [ 0x08, 0x03, 0x00, 0xff, 0xf0, 0x00, 0xff, 0xf0 ]
dev.ctrl_transfer(0x21, 9, 0x0308, 2, report)
##############

vpen = UInput(events=pen_events, name=config["xinput_name"], version=0x3)
if(DEBUG) : print(vpen.capabilities(verbose=True).keys() )
if(DEBUG) : print(vpen.capabilities(verbose=True) )
vbtn = UInput(events=btn_events, name=config["xinput_name"] + "_buttons", version=0x3)  

#compare with xinput list
if(DEBUG) : print(vbtn.capabilities(verbose=True).keys() )
if(DEBUG) : print(vbtn.capabilities(verbose=True) )
if(DEBUG) : print(vpen)
if(DEBUG) : print(vbtn)

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
pen_touch_prev = False
mm_pressed_prev = False
keys_prev = [0] * len(config["actions"]["tablet_buttons"])
penbuttons_prev = [0] * len(config["actions"]["pen_buttons"])
is_rotated = False
num_errors = 0
skip_num = 5 # the info from the 1st packets seem strange -- discard it
mm_x2key = { 0x00c8:1, 0x025f:2, 0x03f7:3, 0x058e:4, 0x0725:5, 0x08bd:6, 0x0a54:7, 0x0bec:8, 0x0d83:9, 0x0f1a:10 }
#
# Infinite loop
while True:
    try:
        if num_errors > 50:
            raise Exception("too many subsequent errors detected. bailing out...")

        data = dev.read(ep.bEndpointAddress, ep.wMaxPacketSize)
        if(DEBUG) : print(data) # shows button pressed array

        if skip_num > 0:
            skip_num -= 1
        
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
            num_errors += 1
            continue
        if len(data) < 13:
            print(f"wrong report len[{len(data)}]", flush=True)
            for i in range(len(data)): print(f"{data[i]:02x}", end=" ", flush=True)
            print("")
            num_errors += 1
            continue
        if data[5] not in [2,3,4,5,6,7]:
            print(f"*pressureMSB:{data[5]:02x}*", end="", flush=True)
            num_errors += 1
            continue

        num_errors = 0


        # xy: data[1,2,3,4]
        raw_x = data[x1] * 255 + data[x2]
        raw_y = data[y1] * 255 + data[y2]
        if raw_y&0xf000 > 0:
            # pen is on the multimedia row
            raw_y = 0
            try:
                mm_key = mm_x2key[raw_x]
            except:
                mm_key = 0
        else:
            mm_key = None
        pen_reads_x[pen_reads_i] = abs(max_x - raw_x)
        pen_reads_y[pen_reads_i] = abs(max_y - raw_y)
        pen_reads_i = (pen_reads_i+1) % pen_reads_len
        #
        pen_x = int( sum(pen_reads_x) / pen_reads_len )
        pen_y = int( sum(pen_reads_y) / pen_reads_len )

        # pressure: data[5,6]
        pen_pressure = pressure_max - ( (data[5] & 31) * 255 + data[6]) # 8192 levels -> 13bits -> 5bits from data5 + 8bits from data6
        pen_touch = (pen_pressure >= pressure_contact_threshold) # when Pen touches tablet surface detection value

        mm_pressed = pen_touch and mm_key!=None
        if mm_pressed:
            pen_touch = False

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

        tilt_x = int.from_bytes([data[13]], signed=True)
        tilt_y = int.from_bytes([data[14]], signed=True)
        #print(f"{tilt_x:3d}", end=" ", flush=True)



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

        if mm_key and mm_pressed!=mm_pressed_prev:
            key_codes = config["actions"]["multimedia_buttons"][mm_key-1].split("+")
            for key in key_codes:
                act = ecodes.ecodes[key]
                vbtn.write(ecodes.EV_KEY, act, int(mm_pressed))
            vbtn.syn()
        mm_pressed_prev = mm_pressed

        vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, int(pen_touch) )
        if pen_touch:
            vpen.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, int(pen_touch) )
        if pen_touch or pen_touch_prev:
            vpen.write(ecodes.EV_KEY, ecodes.BTN_MOUSE, int(pen_touch) )
        pen_touch_prev = pen_touch
        vpen.write(ecodes.EV_ABS, ecodes.ABS_X, pen_x)
        vpen.write(ecodes.EV_ABS, ecodes.ABS_Y, pen_y)
        vpen.write(ecodes.EV_ABS, ecodes.ABS_TILT_X, tilt_x)
        vpen.write(ecodes.EV_ABS, ecodes.ABS_TILT_Y, tilt_y)
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
        print("\nDriver terminated successfully.")
        break
    except Exception as e:
        print(e)
        break

vpen.close()
vbtn.close()
usb.util.release_interface(dev, 0)

sys.exit(0)
