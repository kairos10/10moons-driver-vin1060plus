# Installation

1. the required python packages should be available in the context of the *tablet-vinsa1060* service. On Fedora it is enough to install `python3-evdev`, `python3-pyusb` and `python3-pyyaml`
1. ```sudo make install```

# Troubleshooting
* `journalctl -u tablet-vinsa1060.service --follow`
* `systemctl restart tablet-vinsa1060.service`
* `udevadm trigger`
