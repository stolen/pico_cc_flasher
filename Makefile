install_circuitpython:
	./install_circuitpython.sh
install_flasher:
	./install_flasher.sh

install: install_circuitpython install_flasher
	true
