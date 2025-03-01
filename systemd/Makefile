INST_DIR = /usr/local/tablet_vinsa1060/
INST_OPTS = -o root -g root --backup=none --compare

all: help

help:
	@echo -e 'Nothing to do. Install the driver with:\n\n\tsudo make install\n'

install:
	install $(INST_OPTS) -d $(INST_DIR)
	install $(INST_OPTS) t501_setup.sh $(INST_DIR)
	install $(INST_OPTS) ../driver-vin1060plus.py $(INST_DIR)
	install $(INST_OPTS) --mode=644 ../config-vin1060plus.yaml $(INST_DIR)
	install $(INST_OPTS) --mode=644 tablet-vinsa1060.service /etc/systemd/system/
	install $(INST_OPTS) --mode=644 01-drawing-tablet-pen.rules /etc/udev/rules.d/
	systemctl daemon-reload
	udevadm control --reload
