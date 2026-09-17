from deye_inverter_core.main import main
from .solarman import SolarmanClient


if __name__ == "__main__":
	main(SolarmanClient,source="solarman_tcp",source_name="SolarMan Diagnostics")
