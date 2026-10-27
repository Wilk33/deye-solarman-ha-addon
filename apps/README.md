# Applications in SolarMan Diagnostics 2.0.8

Repozytorium zawiera trzy kanoniczne źródła aplikacji:

- `apps/deye-solarman/src/deye_solarman_diagnostics` - SolarMan Diagnostics 2.0.8 i oba adaptery transportu;
- `apps/haos-alarm/src/haos_alarm` - Alarm 1.0.2;
- `apps/continuous-noise/src/continuous_noise` - Continuous Noise 1.0.0.

Wspólny kod audio, MQTT i Supervisor nowych dodatków znajduje się w `packages/ha_audio_common`.

Instalowalne katalogi Home Assistant OS znajdują się w katalogu głównym:

- `deye-solarman-diagnostics`;
- `haos-alarm`;
- `continuous-noise`.

`tools/package_addon.py` generuje runtime SolarMan Diagnostics. `tools/package_audio_addons.py` generuje runtime Alarm i Continuous Noise. Nie należy edytować wygenerowanych kopii pod `rootfs/usr/src/app`.
