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
    codes = btn_codes if k == "tablet_buttons" else pen_codes
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
pressed_prev = None
# Infinite loop
while True:
    try:
        data = dev.read(ep.bEndpointAddress, ep.wMaxPacketSize)
        if(DEBUG) : print(data) # shows button pressed array
        
        #When it only works on 3x6" Android Active area
        #array('B', [5, 128, 161, 13, 2, 9, 0, 0])

        
        #When it works on full 10x6" full area 
        #(Top-left point, just under VirtualMediaShortcut keys)
        #array('B', [6, 0, 0, 0, 0, 5, 37, 6, 46, 2, 5, 255, 51, 0, 0, 0, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        #(bottom-right corner)
        #array('B', [6, 15, 255, 15, 255, 6, 192, 6, 46, 2, 5, 255, 51, 15, 255, 0, 255, 255, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        
        if data[5] in [3,4,5,6]: #[192, 193]: # Pen actions
            pen_x = abs(max_x - (data[x1] * 255 + data[x2]))
            pen_y = abs(max_y - (data[y1] * 255 + data[y2]))
            #
            pen_reads_x[pen_reads_i] = pen_x
            pen_reads_y[pen_reads_i] = pen_y
            pen_reads_i += 1
            pen_reads_i %= pen_reads_len
            pen_x = int( sum(pen_reads_x) / pen_reads_len )
            pen_y = int( sum(pen_reads_y) / pen_reads_len )
            #
            pen_pressure = pressure_max - ( data[5] * 255 + data[6])
            if(DEBUG) : print("pen_x , pen_y : " , pen_x ,"-", pen_y , " --- pen_pressure :" , pen_pressure )
            if pen_pressure >= pressure_contact_threshold : # when Pen touches tablet surface detection value
                if(DEBUG) : print("tablet tapped")
                vpen.write(ecodes.EV_KEY, ecodes.BTN_TOOL_PEN, 1 )
                #vpen.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1 ) #ecodes.BTN_TOUCH not executed ever since src code mods from original driver.py
                vpen.write(ecodes.EV_KEY, ecodes.BTN_MOUSE, 1 ) # ecodes.BTN_MOUSE works, while ecodes.BTN_TOUCH does not execute
            else:
                vpen.write(ecodes.EV_KEY, ecodes.BTN_MOUSE, 0 ) # BTN_MOUSE up event
            vpen.syn()
            vpen.write(ecodes.EV_ABS, ecodes.ABS_X, pen_x)
            vpen.write(ecodes.EV_ABS, ecodes.ABS_Y, pen_y)
            vpen.write(ecodes.EV_ABS, ecodes.ABS_PRESSURE, pen_pressure)
        
        key_pressed = ( data[11] , data[12] )
        if(DEBUG) : print("--- key_pressed : " , key_pressed )
        pressed = None

        if key_pressed == (255,49): # 1st button (from top left - labelled "E")
            pressed = 0
        if key_pressed == (255,35): # 2nd button (labelled "B")
            pressed = 1
        if key_pressed == (127,51): # 3rd button (labelled "CTRL-")
            pressed = 2
        if key_pressed == (255,50): # 4th button (labelled "CTRL+")
            pressed = 3
        if key_pressed == (191,51): # 5th button (labelled "[") #TODO
            pressed = 4
        if key_pressed == (255,19): # 6th button (labelled "]") #TODO
            pressed = 5
        if key_pressed == (223,51): # 7th button (labelled "MouseSymbol_arrowUP")
            pressed = 6
        if key_pressed == (254,51): # 8th button (labelled "TAB")
            pressed = 7
        if key_pressed == (239,51): # 9th button (labelled "MouseSymbol_arrowDown")
            pressed = 8
        if key_pressed == (253,51): # 10th button (labelled "SPACE")
            pressed = 9
        if key_pressed == (247,51): # 11th button (labelled "CTRL")
            pressed = 10
        if key_pressed == (251,51): # 12th button (labelled "ALT")
            pressed = 11
                                                                                                       
        # press types: 0 - up; 1 - down; 2 - hold
        press_type = 0
        if key_pressed != (255,51) : # Key_code tuple when no keys pressed
            press_type = 1
            #if pressed_prev == pressed :   #2-hold is not working nicely
            #    press_type = 2
            pressed_prev = pressed
        
        if pressed_prev is not None:
            if(DEBUG) : 
                print("Key_pressed detected : ", pressed_prev , " :: ", config["actions"]["tablet_buttons"][pressed_prev] , " -- press type ( 0-up, 1-down , 2-hold) :", press_type )
            key_codes = config["actions"]["tablet_buttons"][pressed_prev].split("+")
            for key in key_codes:
                act = ecodes.ecodes[key]
                vbtn.write(ecodes.EV_KEY, act, press_type)
        
        pen_button = data[9] 
        if(DEBUG) : print("--- pen_button_pressed : " , pen_button )
        pen_button_pressed = None
        if pen_button == 4: # lower pen button (one closer to pen tip)
            pen_button_pressed = 0
        if pen_button == 6: # upper pen button (one further from pen tip)
            pen_button_pressed = 1

        # press types: 0 - up; 1 - down; 2 - hold
        press_type = 0
        if pen_button != 2 : # Default value when no pen button pressed 
            press_type = 1   # press_type=2 (hold status) is not working nicely, so skip implementation

        if pen_button != 2 : #
            if(DEBUG) : print("pen_button_pressed detected : ", pen_button_pressed , " :: ", config["actions"]["pen_buttons"][pen_button_pressed], " -- press type ( 0-up, 1-down , 2-hold) :", press_type )
            key_codes = config["actions"]["tablet_buttons"][pen_button_pressed].split("+")
            for key in key_codes:
                act = ecodes.ecodes[key]
                vbtn.write(ecodes.EV_KEY, act, press_type)

        # Flush
        vpen.syn()
        vbtn.syn()
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
