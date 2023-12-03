.PHONY: .FORCE release install_circuitpython install_flasher install

install_circuitpython:
	./install_circuitpython.sh
install_flasher:
	./install_flasher.sh

install: install_circuitpython install_flasher
	true

release: .FORCE
	rm -rf release pico_cc_flasher.zip
	mkdir release
	./install_flasher.sh release
	cd release && zip -r ../pico_cc_flasher.zip .
	rm -rf release
