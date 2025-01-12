#!/bin/bash

t501_setup() {
	#local T501_RESET="/usr/local/tablet_vinsa1060/10moons-probe"
	local T501_VDEV="/usr/local/tablet_vinsa1060/driver-vin1060plus.py"

	local _info=$( lsusb | grep T501 | grep -oE 'Bus [0-9]+ Device [0-9]+' )
	if [ -z "$_info" ]; then
		echo "tablet not found"
		return 1
	else
		echo "tablet found on ${_info}"
		_info=( $_info )
		echo "kill all previous driver instances..."
		killall `basename "$T501_VDEV"`
		#echo "resetting tablet..."
		#eval "$T501_RESET" ${_info[1]} ${_info[3]}
		echo "running driver..."
		eval nice -n -5 "$T501_VDEV"
	fi
}

t501_setup
