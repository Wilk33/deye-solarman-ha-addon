from deye_inverter_core.main import main
from .rs485 import ModbusRtuTransport
from .solarman import SolarmanClient


if __name__ == "__main__":
	main(SolarmanClient,ModbusRtuTransport)
